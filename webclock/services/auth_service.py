"""Single-process, host-initialized administrator identity and revocable sessions."""
from collections import deque
import copy
import hashlib
import math
from pathlib import Path
import re
import secrets
import time
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash

from webclock.services.storage import load_json, save_json, storage_lock


AUTH_SCHEMA_VERSION = 1
SESSION_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 100
LOGIN_WINDOW_SECONDS = 60
LOGIN_SOURCE_LIMIT = 5
LOGIN_GLOBAL_LIMIT = 50
MAX_LOGIN_SOURCES = 256
PASSWORD_METHOD = 'scrypt:32768:8:1'


class AuthStateError(RuntimeError):
    """An existing protected installation must not fall back to anonymous access."""


class AuthError(ValueError):
    def __init__(self, code, message, status=400, retry_after=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


class AuthService:
    def __init__(self, path, now=None):
        self.path = Path(path)
        self.required_path = self.path.with_name('auth-required')
        self.now = now or time.time
        self._temporary_secret = secrets.token_urlsafe(32)
        self._temporary_invite_secret = secrets.token_urlsafe(32)
        self._login_sources = {}
        self._login_global = deque()

    def _empty(self):
        return {'version': AUTH_SCHEMA_VERSION, 'mode': 'self', 'owner_id': 'local-owner',
                'username': None, 'password_hash': None,
                'session_secret': self._temporary_secret,
                'invite_secret': self._temporary_invite_secret,
                'generation': 1, 'sessions': {}}

    @staticmethod
    def _validate(data):
        valid = (isinstance(data, dict) and type(data.get('version')) is int
                 and data['version'] == AUTH_SCHEMA_VERSION and data.get('mode') in ('self', 'managed')
                 and isinstance(data.get('owner_id'), str) and 1 <= len(data['owner_id']) <= 128
                 and type(data.get('generation')) is int and data['generation'] >= 1
                 and isinstance(data.get('sessions'), dict) and len(data['sessions']) <= MAX_SESSIONS)
        if not valid:
            raise AuthStateError('Invalid authorization state; host recovery is required.')
        for field in ('session_secret', 'invite_secret'):
            if not isinstance(data.get(field), str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', data[field]):
                raise AuthStateError('Invalid authorization secret; host recovery is required.')
        if data['session_secret'] == data['invite_secret']:
            raise AuthStateError('Authorization secrets must be independent.')
        if data['mode'] == 'managed':
            if (not isinstance(data.get('username'), str) or not 1 <= len(data['username']) <= 128
                    or not isinstance(data.get('password_hash'), str)
                    or not re.fullmatch(r'scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[0-9a-f]{128}', data['password_hash'])):
                raise AuthStateError('Invalid administrator identity; host recovery is required.')
        elif data.get('username') is not None or data.get('password_hash') is not None or data['sessions']:
            raise AuthStateError('Unexpected administrator data in self mode.')
        for digest, record in data['sessions'].items():
            if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                    or not isinstance(record, dict) or record.get('owner_id') != data['owner_id']
                    or type(record.get('generation')) is not int
                    or record['generation'] != data['generation']
                    or type(record.get('expires_at')) not in (int, float)
                    or not math.isfinite(record['expires_at'])):
                raise AuthStateError('Invalid session state; host recovery is required.')
        return data

    def state(self):
        """Return internal state, including secrets; never serialize this into an API."""
        with storage_lock:
            required = self.required_path.exists()
            try:
                data = load_json(self.path, None)
            except (OSError, ValueError, TypeError) as exc:
                raise AuthStateError('Unreadable authorization state; host recovery is required.') from exc
            if data is None:
                if required or self.path.exists():
                    raise AuthStateError('Missing authorization state; host recovery is required.')
                return self._empty()
            data = self._validate(data)
            if required and data['mode'] != 'managed':
                raise AuthStateError('Protected installation cannot fall back to self mode.')
            return copy.deepcopy(data)

    def mode(self):
        return self.state()['mode']

    def owner_id(self):
        return self.state()['owner_id']

    def session_secret(self):
        return self.state()['session_secret']

    def invite_secret(self):
        return self.state()['invite_secret']

    def ensure_initialized(self):
        with storage_lock:
            data = self.state()
            if not self.path.exists():
                data['owner_id'] = str(uuid4())
                save_json(self.path, data)
            return copy.deepcopy(data)

    @staticmethod
    def _password(password):
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise AuthError('invalid_password', 'Password must contain 12 to 1024 characters.')
        return generate_password_hash(password, method=PASSWORD_METHOD, salt_length=16)

    def setup(self, username, password, *, enable_managed=False, enable_managed_test=False):
        """Explicit host-only migration; keep the earlier test keyword compatible."""
        if enable_managed is not True and enable_managed_test is not True:
            raise AuthError('managed_opt_in_required', 'Explicit managed-mode enablement is required.', 409)
        if (not isinstance(username, str) or not 1 <= len(username.strip()) <= 128
                or any(ord(char) < 32 for char in username)):
            raise AuthError('invalid_username', 'Invalid administrator username.')
        password_hash = self._password(password)
        with storage_lock:
            data = self.state()
            if data['mode'] == 'managed':
                raise AuthError('already_initialized', 'Administrator already exists; use host password recovery.', 409)
            if not self.path.exists():
                data['owner_id'] = str(uuid4())
            data.update(mode='managed', username=username.strip(), password_hash=password_hash,
                        session_secret=secrets.token_urlsafe(32), generation=data['generation'] + 1, sessions={})
            # Commit protection first. Interrupted initialization remains closed.
            save_json(self.required_path, {'version': AUTH_SCHEMA_VERSION, 'mode': 'managed'})
            save_json(self.path, data)
            return {'mode': data['mode'], 'owner_id': data['owner_id'], 'username': data['username']}

    def reset_password(self, password):
        password_hash = self._password(password)
        with storage_lock:
            data = self.state()
            if data['mode'] != 'managed':
                raise AuthError('not_initialized', 'No administrator exists.', 409)
            data.update(password_hash=password_hash, session_secret=secrets.token_urlsafe(32),
                        generation=data['generation'] + 1, sessions={})
            save_json(self.required_path, {'version': AUTH_SCHEMA_VERSION, 'mode': 'managed'})
            save_json(self.path, data)
            return {'mode': data['mode'], 'owner_id': data['owner_id'], 'username': data['username']}

    def _rate_limit(self, source, now):
        cutoff = now - LOGIN_WINDOW_SECONDS
        while self._login_global and self._login_global[0] <= cutoff:
            self._login_global.popleft()
        for key in list(self._login_sources):
            timestamps = self._login_sources[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                del self._login_sources[key]
        source = str(source or 'unknown')[:128]
        timestamps = self._login_sources.get(source, deque())
        blocked = (timestamps if len(timestamps) >= LOGIN_SOURCE_LIMIT else
                   self._login_global if len(self._login_global) >= LOGIN_GLOBAL_LIMIT else None)
        if blocked:
            retry = max(1, math.ceil(blocked[0] + LOGIN_WINDOW_SECONDS - now))
            raise AuthError('rate_limited', 'Too many login attempts; try again later.', 429, retry)
        if source not in self._login_sources and len(self._login_sources) >= MAX_LOGIN_SOURCES:
            raise AuthError('rate_limited', 'Too many login attempts; try again later.', 429,
                            LOGIN_WINDOW_SECONDS)
        timestamps.append(now)
        self._login_sources[source] = timestamps
        self._login_global.append(now)

    def login(self, username, password, source='unknown'):
        with storage_lock:
            data = self.state()
            if data['mode'] != 'managed':
                raise AuthError('not_initialized', 'Administrator login is not enabled.', 409)
            now = self.now()
            self._rate_limit(source, now)
            valid_input = (isinstance(username, str) and len(username) <= 128
                           and isinstance(password, str) and len(password) <= 1024)
            try:
                # A wrong username still performs the same password KDF.
                valid_password = check_password_hash(data['password_hash'], password if valid_input else '')
            except (ValueError, TypeError) as exc:
                raise AuthStateError('Invalid password hash; host recovery is required.') from exc
            if not valid_input or not secrets.compare_digest(username.encode(), data['username'].encode()) or not valid_password:
                raise AuthError('invalid_credentials', 'Invalid username or password.', 401)
            data['sessions'] = {digest: record for digest, record in data['sessions'].items()
                                if record['expires_at'] > now}
            if len(data['sessions']) >= MAX_SESSIONS:
                oldest = min(data['sessions'], key=lambda digest: data['sessions'][digest]['expires_at'])
                del data['sessions'][oldest]
            token = secrets.token_urlsafe(32)
            record = {'owner_id': data['owner_id'], 'expires_at': now + SESSION_SECONDS,
                      'generation': data['generation']}
            data['sessions'][hashlib.sha256(token.encode()).hexdigest()] = record
            save_json(self.path, data)
            return dict(record, token=token)

    def authenticate(self, token):
        with storage_lock:
            data = self.state()
            if data['mode'] != 'managed' or not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                return None
            record = data['sessions'].get(hashlib.sha256(token.encode()).hexdigest())
            if record is None or record['expires_at'] <= self.now():
                return None
            return record['owner_id']

    def logout(self, token):
        with storage_lock:
            data = self.state()
            if data['mode'] != 'managed' or not isinstance(token, str):
                return
            digest = hashlib.sha256(token.encode()).hexdigest()
            if digest in data['sessions']:
                del data['sessions'][digest]
                save_json(self.path, data)
