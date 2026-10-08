"""Explicit, revocable program credentials, separate from display-device identity."""
import copy
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import time
from uuid import uuid4

from webclock.services.storage import load_json, save_json, storage_lock


SCOPES = frozenset(('schedules:read', 'schedules:write', 'events:read',
                    'events:write', 'assignments:write'))
GRANT_FIELDS = ('group_ids', 'device_ids', 'calendar_source_ids', 'schedule_ids', 'event_ids')
MAX_CLIENTS = 100
MAX_GRANTS = 1000
DEFAULT_EXPIRY_SECONDS = 30 * 24 * 60 * 60
MAX_EXPIRY_SECONDS = 365 * 24 * 60 * 60
PUBLIC_FIELDS = ('id', 'name', 'owner_id', 'mode', 'scopes', *GRANT_FIELDS,
                 'created_at', 'expires_at')


class ControlAccessError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class ControlAccessStateError(RuntimeError):
    """Corrupt credentials require recovery; never replace them with an empty set."""


def _text(value):
    return (isinstance(value, str) and 1 <= len(value) <= 128
            and value == value.strip() and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _grants(data):
    scopes = data.get('scopes')
    if (not isinstance(scopes, list) or not scopes or len(scopes) > len(SCOPES)
            or any(not isinstance(scope, str) or scope not in SCOPES for scope in scopes)
            or len(set(scopes)) != len(scopes)):
        raise ControlAccessError('invalid_scopes', 'Select explicit supported program permissions.')
    result = {'scopes': list(scopes)}
    for field in GRANT_FIELDS:
        values = data.get(field, [])
        if (not isinstance(values, list) or len(values) > MAX_GRANTS
                or any(not _text(value) or value == '*' for value in values)
                or len(set(values)) != len(values)):
            raise ControlAccessError('invalid_grants', 'Invalid explicit resource IDs: ' + field)
        result[field] = list(values)
    return result


class ControlAccessService:
    def __init__(self, path, auth_service, now=None):
        self.path = Path(path)
        self.auth_service = auth_service
        self.now = now or time.time

    def _binding(self, owner_id, mode=None):
        auth = self.auth_service() if callable(self.auth_service) else self.auth_service
        state = auth.state()
        if not auth.owner_active(owner_id) or (mode is not None and mode != state['mode']):
            raise ControlAccessError('invalid_owner', 'Program identity does not match this installation.', 403)
        return dict(state, owner_id=owner_id)

    def _load(self):
        try:
            state = load_json(self.path, {'version': 1, 'clients': {}})
            if (not isinstance(state, dict) or set(state) != {'version', 'clients'}
                    or type(state.get('version')) is not int or state['version'] != 1
                    or not isinstance(state.get('clients'), dict) or len(state['clients']) > MAX_CLIENTS):
                raise ValueError('Invalid credentials container.')
            for client_id, row in state['clients'].items():
                if (not isinstance(row, dict) or set(row) != set(PUBLIC_FIELDS) | {'digest'}
                        or not _text(client_id) or row.get('id') != client_id
                        or not _text(row.get('name')) or not _text(row.get('owner_id'))
                        or row.get('mode') not in ('self', 'managed')
                        or not isinstance(row.get('digest'), str)
                        or not re.fullmatch(r'[0-9a-f]{64}', row['digest'])):
                    raise ValueError('Invalid credential.')
                _grants(row)
                if any(type(row[field]) not in (int, float) or not math.isfinite(row[field])
                       for field in ('created_at', 'expires_at')):
                    raise ValueError('Invalid credential time.')
                if not 60 <= row['expires_at'] - row['created_at'] <= MAX_EXPIRY_SECONDS:
                    raise ValueError('Invalid credential lifetime.')
            return state
        except (OSError, ValueError, TypeError) as exc:
            raise ControlAccessStateError('Unreadable program credentials; host recovery is required.') from exc

    @staticmethod
    def _public(row):
        return {field: copy.deepcopy(row[field]) for field in PUBLIC_FIELDS}

    @staticmethod
    def _digest(token, binding):
        message = json.dumps(['webclock-control-v1', binding['owner_id'], binding['mode'], token],
                             separators=(',', ':')).encode()
        return hmac.new(binding['invite_secret'].encode(), message, hashlib.sha256).hexdigest()

    def create(self, owner_id, mode, data):
        """The management caller must initialize AuthService and validate referenced resources."""
        allowed = {'name', 'scopes', 'expires_in', *GRANT_FIELDS}
        if not isinstance(data, dict) or set(data) - allowed or not _text(data.get('name')):
            raise ControlAccessError('invalid_client', 'Provide a name and explicit program permissions.')
        grants = _grants(data)
        lifetime = data.get('expires_in', DEFAULT_EXPIRY_SECONDS)
        if type(lifetime) is not int or not 60 <= lifetime <= MAX_EXPIRY_SECONDS:
            raise ControlAccessError('invalid_expiry', 'Credential lifetime must be 60 to 31536000 seconds.')
        with storage_lock:
            binding = self._binding(owner_id, mode)
            state = self._load()
            if len(state['clients']) >= MAX_CLIENTS:
                raise ControlAccessError('client_limit', 'Revoke an existing credential before creating another.', 409)
            token = 'wcc_' + secrets.token_urlsafe(32)
            now = self.now()
            row = dict(grants, id=str(uuid4()), name=data['name'], owner_id=owner_id, mode=mode,
                       created_at=now, expires_at=now + lifetime, digest=self._digest(token, binding))
            state['clients'][row['id']] = row
            save_json(self.path, state)
            return dict(self._public(row), token=token)

    def list(self, owner_id):
        with storage_lock:
            self._binding(owner_id)
            return [self._public(row) for row in self._load()['clients'].values()
                    if row['owner_id'] == owner_id]

    def revoke(self, owner_id, client_id):
        with storage_lock:
            self._binding(owner_id)
            state = self._load()
            row = state['clients'].get(client_id) if isinstance(client_id, str) else None
            if row is None or row['owner_id'] != owner_id:
                raise ControlAccessError('client_not_found', 'Program credential not found.', 404)
            del state['clients'][client_id]
            save_json(self.path, state)
            return self._public(row)

    def authenticate(self, token, owner_id, mode):
        with storage_lock:
            binding = self._binding(owner_id, mode)
            state = self._load()
            if not isinstance(token, str) or not re.fullmatch(r'wcc_[A-Za-z0-9_-]{43}', token):
                return None
            digest = self._digest(token, binding)
            for row in state['clients'].values():
                if (row['owner_id'] == owner_id and row['mode'] == mode
                        and row['expires_at'] > self.now()
                        and hmac.compare_digest(row['digest'], digest)):
                    return self._public(row)
            return None
