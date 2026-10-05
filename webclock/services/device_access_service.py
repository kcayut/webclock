"""Owner-scoped display groups and invitations, without device enrollment yet.

One process owns device-access.json. B2 will commit enrollment, capacity and
credentials together in this file under the same storage lock.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import math
from pathlib import Path
import re
import secrets
import time
from uuid import uuid4

from .storage import load_json, save_json, storage_lock


CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
INVITE_SECONDS = 600
DEVICE_LIMIT = 100
GROUP_LIMIT = 100
SOURCE_LIMIT = 10
GLOBAL_LIMIT = 100
RATE_SECONDS = 60
_RATE_WINDOWS = {}
CONTENT_FIELDS = {'calendar_source_ids', 'manual_note_ids', 'schedule_ids'}


class AccessError(ValueError):
    def __init__(self, message, status=400, code='invalid_request', retry_after=None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


def _stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def _epoch(stamp):
    value = datetime.fromisoformat(stamp)
    if value.tzinfo is None:
        raise ValueError('Timestamp must include its timezone')
    return value.timestamp()


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ValueError('Name must contain 1-100 characters')
    return value.strip()


def _reference_ids(key, values):
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError('Invalid content IDs: ' + key)
    if key == 'manual_note_ids':
        invalid = any(type(value) is not int or value <= 0 for value in values)
    else:
        invalid = any(not isinstance(value, str) or not value or len(value) > 128 for value in values)
    if invalid:
        raise ValueError('Invalid content IDs: ' + key)
    return values


class DeviceAccessService:
    def __init__(self, state_path, invite_secret, validate_settings, default_settings,
                 content_catalog, clock=None):
        self.path = Path(state_path)
        self.secret = invite_secret
        self.validate_settings = validate_settings
        self.default_settings = default_settings
        self.content_catalog = content_catalog
        self.clock = clock or time.time

    def _load(self):
        try:
            data = load_json(self.path, dict(version=1, groups={}, invites={}, devices={}, attempts={}))
            if (not isinstance(data, dict) or set(data) != {'version', 'groups', 'invites', 'devices', 'attempts'}
                    or type(data.get('version')) is not int or data['version'] != 1
                    or any(not isinstance(data.get(field), dict)
                           for field in ('groups', 'invites', 'devices', 'attempts'))
                    or len(data['groups']) > GROUP_LIMIT or len(data['devices']) > DEVICE_LIMIT):
                raise ValueError('Invalid state envelope')
            group_fields = {'id', 'owner_id', 'name', 'enabled', 'display_overrides', 'content',
                            'content_version', 'created_at', 'updated_at', 'is_default'}
            default_owners = set()
            for group_id, row in data['groups'].items():
                if (not isinstance(row, dict) or set(row) != group_fields or row['id'] != group_id
                        or not isinstance(group_id, str) or not group_id or len(group_id) > 128
                        or not isinstance(row['owner_id'], str) or not row['owner_id'] or len(row['owner_id']) > 128
                        or type(row['enabled']) is not bool or type(row['is_default']) is not bool
                        or type(row['content_version']) is not int or row['content_version'] < 1
                        or not isinstance(row['content'], dict) or set(row['content']) != CONTENT_FIELDS):
                    raise ValueError('Invalid stored group')
                _name(row['name'])
                self._settings(row['display_overrides'])
                for key, values in row['content'].items():
                    _reference_ids(key, values)
                _epoch(row['created_at'])
                _epoch(row['updated_at'])
                if row['is_default']:
                    if row['owner_id'] in default_owners:
                        raise ValueError('Duplicate default group')
                    default_owners.add(row['owner_id'])
            invite_fields = {'id', 'group_id', 'owner_id', 'code_digest', 'created_at', 'expires_at',
                             'capacity', 'used', 'closed'}
            invite_ids = set()
            for group_id, row in data['invites'].items():
                if (not isinstance(row, dict) or set(row) != invite_fields or row['group_id'] != group_id
                        or group_id not in data['groups'] or row['owner_id'] != data['groups'][group_id]['owner_id']
                        or not isinstance(row['id'], str) or not row['id'] or len(row['id']) > 128
                        or row['id'] in invite_ids or row['id'] in data['groups']
                        or not isinstance(row['code_digest'], str)
                        or not re.fullmatch(r'[a-f0-9]{64}', row['code_digest'])
                        or type(row['capacity']) is not int or not 1 <= row['capacity'] <= 100
                        or type(row['used']) is not int or not 0 <= row['used'] <= row['capacity']
                        or type(row['closed']) is not bool
                        or _epoch(row['expires_at']) <= _epoch(row['created_at'])):
                    raise ValueError('Invalid stored invitation')
                invite_ids.add(row['id'])
            for field in ('devices', 'attempts'):
                if any(not isinstance(key, str) or not key or not isinstance(row, dict)
                       for key, row in data[field].items()):
                    raise ValueError('Invalid future enrollment records')
            return data
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise AccessError('Invalid stored device access data', 503, 'access_not_ready') from error

    def _owner(self, owner_id):
        if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 128:
            raise AccessError('Management identity required', 401, 'unauthorized')
        return owner_id

    def _group(self, state, owner_id, group_id):
        self._owner(owner_id)
        row = state['groups'].get(group_id)
        if not isinstance(row, dict) or row.get('owner_id') != owner_id:
            raise AccessError('Group not found', 404, 'not_found')
        return row

    def _defaults(self):
        return deepcopy(self.default_settings())

    def _settings(self, overrides):
        if not isinstance(overrides, dict):
            raise ValueError('Display overrides must be an object')
        merged = self._defaults()
        for key, value in overrides.items():
            if key == 'night':
                if not isinstance(value, dict) or not isinstance(merged.get('night'), dict):
                    raise ValueError('Invalid night overrides')
                merged[key] = dict(merged[key], **value)
            else:
                merged[key] = value
        validated = self.validate_settings(merged)
        # Store only the explicit leaves, including False and 0. An empty object
        # resets all overrides to inheritance rather than copying today's defaults.
        patch = {key: ({field: validated[key][field] for field in value}
                       if key == 'night' else validated[key])
                 for key, value in overrides.items()}
        return patch, validated

    def _content(self, value):
        if not isinstance(value, dict) or set(value) - CONTENT_FIELDS:
            raise ValueError('Invalid content selections')
        catalog = self.content_catalog()
        schedules = {row['id']: row for row in catalog.get('schedules', [])}
        available = {key: set(catalog.get(key, [])) for key in CONTENT_FIELDS}
        available['schedule_ids'] = set(schedules)
        result = {}
        for key in CONTENT_FIELDS:
            ids = _reference_ids(key, value.get(key, []))
            if set(ids) - available[key]:
                raise ValueError('Select existing content IDs: ' + key)
            result[key] = sorted(set(ids))
        for schedule_id in result['schedule_ids']:
            link = schedules[schedule_id].get('calendar_link')
            if link and set(link['source_ids']) - (available['calendar_source_ids'] | {'local'}):
                raise ValueError('Selected alarm depends on a missing calendar source')
        return result

    def _public_group(self, row):
        result = deepcopy(row)
        result['effective_settings'] = self._settings(row['display_overrides'])[1]
        return result

    def _new_id(self, existing):
        for _ in range(20):
            value = uuid4().hex
            if value not in existing:
                return value
        raise AccessError('Unable to allocate an identifier', 503, 'temporarily_unavailable')

    def _create(self, state, owner_id, data, is_default=False):
        self._owner(owner_id)
        if (not isinstance(data, dict)
                or set(data) - {'name', 'enabled', 'display_overrides', 'content'}):
            raise ValueError('Invalid group fields')
        if len(state['groups']) >= GROUP_LIMIT:
            raise ValueError('Group limit reached (100)')
        enabled = data.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError('Enabled must be a boolean')
        group_id = self._new_id(state['groups'])
        now = _stamp(self.clock())
        row = dict(id=group_id, owner_id=owner_id, name=_name(data.get('name')),
                   enabled=enabled, display_overrides=self._settings(data.get('display_overrides', {}))[0],
                   content=self._content(data.get('content', {})), content_version=1,
                   created_at=now, updated_at=now, is_default=is_default)
        state['groups'][group_id] = row
        save_json(self.path, state)
        return self._public_group(row)

    def initialize_owner(self, owner_id, name='預設群組'):
        """Explicit, idempotent migration; ordinary reads never create a group."""
        with storage_lock:
            self._owner(owner_id)
            state = self._load()
            for row in state['groups'].values():
                if row.get('owner_id') == owner_id and row.get('is_default'):
                    return self._public_group(row)
            catalog = self.content_catalog()
            content = {key: list(catalog.get(key, [])) for key in CONTENT_FIELDS}
            content['schedule_ids'] = [row['id'] for row in catalog.get('schedules', [])]
            content = catalog.get('default_content', content)
            return self._create(state, owner_id, dict(name=name, content=content), is_default=True)

    def list_groups(self, owner_id):
        with storage_lock:
            self._owner(owner_id)
            return [self._public_group(row) for row in self._load()['groups'].values()
                    if row.get('owner_id') == owner_id]

    def get_group(self, owner_id, group_id):
        with storage_lock:
            return self._public_group(self._group(self._load(), owner_id, group_id))

    def create_group(self, owner_id, data):
        with storage_lock:
            return self._create(self._load(), owner_id, data)

    def update_group(self, owner_id, group_id, data):
        with storage_lock:
            state = self._load()
            row = self._group(state, owner_id, group_id)
            if (not isinstance(data, dict) or not data
                    or set(data) - {'name', 'enabled', 'display_overrides', 'content'}):
                raise ValueError('Invalid group fields')
            updated = deepcopy(row)
            if 'name' in data:
                updated['name'] = _name(data['name'])
            if 'enabled' in data:
                if type(data['enabled']) is not bool:
                    raise ValueError('Enabled must be a boolean')
                updated['enabled'] = data['enabled']
            if 'display_overrides' in data:
                updated['display_overrides'] = self._settings(data['display_overrides'])[0]
            if 'content' in data:
                # Content PATCH preserves other lists; explicit [] revokes that list.
                if not isinstance(data['content'], dict):
                    raise ValueError('Content selections must be an object')
                updated['content'] = self._content(dict(row['content'], **data['content']))
            if updated != row:
                if (any(updated[key] != row[key] for key in ('enabled', 'content'))
                        or self._settings(updated['display_overrides'])[1]
                        != self._settings(row['display_overrides'])[1]):
                    updated['content_version'] += 1
                updated['updated_at'] = _stamp(self.clock())
                state['groups'][group_id] = updated
                save_json(self.path, state)
            return self._public_group(updated)

    def delete_group(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            self._group(state, owner_id, group_id)
            if any(row.get('group_id') == group_id for row in state['devices'].values()):
                raise AccessError('Move group members before deleting the group', 409, 'group_has_members')
            del state['groups'][group_id]
            state['invites'].pop(group_id, None)
            save_json(self.path, state)

    def _digest(self, code):
        secret = self.secret() if callable(self.secret) else self.secret
        if isinstance(secret, str):
            secret = secret.encode()
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise AccessError('Invitation secret is unavailable', 503, 'access_not_ready')
        return hmac.new(secret, code.encode('ascii'), hashlib.sha256).hexdigest()

    def _invite_metadata(self, state, row):
        group = state['groups'].get(row['group_id'], {})
        remaining = max(0, min(row['capacity'] - row['used'], DEVICE_LIMIT - len(state['devices'])))
        status = ('closed' if row['closed'] else 'disabled' if not group.get('enabled')
                  else 'expired' if self.clock() >= _epoch(row['expires_at'])
                  else 'full' if remaining == 0 else 'active')
        return {**{key: row[key] for key in ('id', 'group_id', 'created_at', 'expires_at', 'capacity', 'used')},
                'remaining': remaining, 'status': status}

    def create_invite(self, owner_id, group_id, capacity=5):
        if type(capacity) is not int or not 1 <= capacity <= 100:
            raise ValueError('Capacity must be an integer from 1 to 100')
        with storage_lock:
            state = self._load()
            group = self._group(state, owner_id, group_id)
            if not group['enabled']:
                raise AccessError('Enable the group before creating an invitation', 409, 'group_disabled')
            if len(state['devices']) >= DEVICE_LIMIT:
                raise AccessError('Device limit reached (100)', 409, 'device_limit')
            for _ in range(20):
                code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))
                digest = self._digest(code)
                if not any(hmac.compare_digest(digest, row['code_digest']) for row in state['invites'].values()):
                    break
            else:
                raise AccessError('Unable to allocate an invitation', 503, 'temporarily_unavailable')
            now = self.clock()
            row = dict(id=self._new_id(set(state['groups']) | {row['id'] for row in state['invites'].values()}),
                       group_id=group_id, owner_id=owner_id, code_digest=digest,
                       created_at=_stamp(now), expires_at=_stamp(now + INVITE_SECONDS),
                       capacity=capacity, used=0, closed=False)
            state['invites'][group_id] = row
            save_json(self.path, state)
            return dict(self._invite_metadata(state, row), code=code)

    def get_invite(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            self._group(state, owner_id, group_id)
            row = state['invites'].get(group_id)
            return self._invite_metadata(state, row) if row else None

    def close_invite(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            self._group(state, owner_id, group_id)
            row = state['invites'].get(group_id)
            if row and not row['closed']:
                row['closed'] = True
                save_json(self.path, state)
            return self._invite_metadata(state, row) if row else None

    def _limit(self, source):
        """All attempts count; a fixed window stores at most 100 source keys."""
        now = self.clock()
        key = str(self.path.resolve())
        window = _RATE_WINDOWS.get(key)
        if window is None or now >= window['reset'] or now < window['start']:
            # Services normally share one state path. Bound test/multi-app paths too.
            if len(_RATE_WINDOWS) >= 100:
                oldest = min(_RATE_WINDOWS, key=lambda item: _RATE_WINDOWS[item]['start'])
                del _RATE_WINDOWS[oldest]
            window = _RATE_WINDOWS[key] = dict(start=now, reset=now + RATE_SECONDS, total=0, sources={})
        source = source if isinstance(source, str) and len(source) <= 200 else 'unknown'
        used = window['sources'].get(source, 0)
        if window['total'] >= GLOBAL_LIMIT or used >= SOURCE_LIMIT:
            raise AccessError('Too many invitation attempts', 429, 'rate_limited',
                              max(1, math.ceil(window['reset'] - now)))
        window['total'] += 1
        window['sources'][source] = used + 1

    def check_invite(self, code, source):
        """B1 validation only; B2 must recheck and consume within its transaction.

        The caller must use the transport peer address, never untrusted forwarded
        headers. No public enrollment route is exposed in B1.
        """
        with storage_lock:
            self._limit(source)
            normalized = code.upper() if isinstance(code, str) and code.isascii() else ''
            if len(normalized) != 6 or any(char not in CODE_ALPHABET for char in normalized):
                raise AccessError('Invalid or unavailable invitation', 400, 'invalid_invitation')
            digest = self._digest(normalized)
            state = self._load()
            match = None
            for row in state['invites'].values():
                if hmac.compare_digest(row['code_digest'], digest):
                    match = row
            if match is None or self._invite_metadata(state, match)['status'] != 'active':
                raise AccessError('Invalid or unavailable invitation', 400, 'invalid_invitation')
            return dict(invite_id=match['id'], group_id=match['group_id'], owner_id=match['owner_id'])
