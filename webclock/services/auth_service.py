"""Persisted accounts, host-authorized setup and atomic data-space mode selection."""
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
AUTH_MULTI_OWNER_VERSION = 1
SESSION_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 100
LOGIN_WINDOW_SECONDS = 60
LOGIN_SOURCE_LIMIT = 5
LOGIN_GLOBAL_LIMIT = 50
MAX_LOGIN_SOURCES = 256
PASSWORD_METHOD = 'scrypt:32768:8:1'
PASSWORD_PATTERN = r'scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[0-9a-f]{128}'
SETUP_CODE_SECONDS = 600
MAX_ACCOUNTS = 100


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
                'data_owner_id': 'local-owner', 'administrator_id': None, 'accounts': {},
                'username': None, 'password_hash': None,
                'session_secret': self._temporary_secret,
                'invite_secret': self._temporary_invite_secret,
                'generation': 1, 'sessions': {}}

    @staticmethod
    def _validate(data):
        valid = (isinstance(data, dict) and type(data.get('version')) is int
                 and data['version'] == AUTH_SCHEMA_VERSION and data.get('mode') in ('self', 'managed')
                 and isinstance(data.get('owner_id'), str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', data['owner_id'])
                 and type(data.get('generation')) is int and data['generation'] >= 1
                 and isinstance(data.get('sessions'), dict) and len(data['sessions']) <= MAX_SESSIONS)
        if not valid:
            raise AuthStateError('Invalid authorization state; host recovery is required.')
        data = copy.deepcopy(data)
        for field in ('session_secret', 'invite_secret'):
            if not isinstance(data.get(field), str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', data[field]):
                raise AuthStateError('Invalid authorization secret; host recovery is required.')
        if data['session_secret'] == data['invite_secret']:
            raise AuthStateError('Authorization secrets must be independent.')
        # Older single-account files are normalized on read, without changing disk.
        if 'accounts' not in data:
            data['accounts'] = {}
            data['administrator_id'] = None
            if data['mode'] == 'managed':
                data['accounts'][data['owner_id']] = {
                    'owner_id': data['owner_id'], 'username': data.get('username'),
                    'password_hash': data.get('password_hash'), 'role': 'admin',
                    'enabled': True, 'created_at': 0}
                data['administrator_id'] = data['owner_id']
            data['data_owner_id'] = data['owner_id']
        if (not isinstance(data['accounts'], dict) or len(data['accounts']) > MAX_ACCOUNTS
                or not isinstance(data.get('data_owner_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', data['data_owner_id'])
                or (data.get('administrator_id') is not None and not isinstance(data['administrator_id'], str))):
            raise AuthStateError('Invalid account collection; host recovery is required.')
        usernames = set()
        for owner, account in data['accounts'].items():
            if (not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', owner)
                    or not isinstance(account, dict) or account.get('owner_id') != owner
                    or not isinstance(account.get('username'), str)
                    or not 1 <= len(account['username'].strip()) <= 128
                    or account['username'] != account['username'].strip()
                    or any(ord(char) < 32 for char in account['username'])
                    or account['username'] in usernames
                    or not isinstance(account.get('password_hash'), str)
                    or not re.fullmatch(PASSWORD_PATTERN, account['password_hash'])
                    or account.get('role') not in ('admin', 'member')
                    or type(account.get('enabled')) is not bool
                    or type(account.get('created_at')) not in (int, float)
                    or not math.isfinite(account['created_at']) or account['created_at'] < 0):
                raise AuthStateError('Invalid account identity; host recovery is required.')
            usernames.add(account['username'])
            if 'deleted_at' in account and (account['enabled']
                    or type(account['deleted_at']) not in (int, float)
                    or not math.isfinite(account['deleted_at']) or account['deleted_at'] < 0):
                raise AuthStateError('Invalid deleted account state; host recovery is required.')
        if data['accounts']:
            primary = data['accounts'].get(data['owner_id'])
            admin = data['accounts'].get(data.get('administrator_id'))
            if (data['data_owner_id'] not in data['accounts']
                    or not primary or not primary['enabled'] or not admin or not admin['enabled']
                    or admin['role'] != 'admin' or data.get('username') != admin['username']
                    or data.get('password_hash') != admin['password_hash']):
                raise AuthStateError('Invalid primary or administrator identity; host recovery is required.')
            if data['mode'] == 'self' and (type(data.get('explicit_self_generation')) is not int
                                          or data['explicit_self_generation'] != data['generation']
                                          or data['sessions']):
                raise AuthStateError('Self mode requires an explicit protected transition.')
        elif (data['mode'] == 'managed' or data.get('username') is not None
              or data.get('password_hash') is not None or data['sessions']
              or data.get('administrator_id') is not None):
            raise AuthStateError('Invalid administrator identity; host recovery is required.')
        if 'scope_changed_at' in data and (type(data['scope_changed_at']) is not int
                                           or data['scope_changed_at'] < 0):
            raise AuthStateError('Invalid authorization transition timestamp.')
        setup = data.get('setup_code')
        if setup is not None and (data['accounts'] or not isinstance(setup, dict)
                or not isinstance(setup.get('digest'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', setup['digest'])
                or type(setup.get('expires_at')) not in (int, float)
                or not math.isfinite(setup['expires_at'])):
            raise AuthStateError('Invalid initial setup state; host recovery is required.')
        for digest, record in data['sessions'].items():
            if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                    or not isinstance(record, dict) or not isinstance(record.get('owner_id'), str)
                    or record['owner_id'] not in data['accounts']
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
            if required and data['mode'] != 'managed' and not data['accounts']:
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
                data['data_owner_id'] = data['owner_id']
                save_json(self.path, data)
            return copy.deepcopy(data)

    @staticmethod
    def _password(password):
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise AuthError('invalid_password', 'Password must contain 12 to 1024 characters.')
        return generate_password_hash(password, method=PASSWORD_METHOD, salt_length=16)

    @staticmethod
    def _username(username):
        if (not isinstance(username, str) or not 1 <= len(username.strip()) <= 128
                or any(ord(char) < 32 for char in username)):
            raise AuthError('invalid_username', 'Invalid account username.')
        return username.strip()

    @staticmethod
    def _public_account(account):
        return {key: value for key, value in account.items() if key != 'password_hash'}

    @staticmethod
    def _rotate(data, *, devices=False):
        data.update(session_secret=secrets.token_urlsafe(32),
                    generation=data['generation'] + 1, sessions={})
        if devices:
            data['invite_secret'] = secrets.token_urlsafe(32)
        if data['mode'] == 'self' and data['accounts']:
            data['explicit_self_generation'] = data['generation']
        else:
            data.pop('explicit_self_generation', None)

    def setup(self, username, password, *, enable_managed=False, enable_managed_test=False):
        """Explicit host-only migration; keep the earlier test keyword compatible."""
        if enable_managed is not True and enable_managed_test is not True:
            raise AuthError('managed_opt_in_required', 'Explicit managed-mode enablement is required.', 409)
        username = self._username(username)
        password_hash = self._password(password)
        with storage_lock:
            data = self.state()
            if data['accounts']:
                raise AuthError('already_initialized', 'Administrator already exists; use host password recovery.', 409)
            if not self.path.exists():
                data['owner_id'] = str(uuid4())
                data['data_owner_id'] = data['owner_id']
            owner = data['owner_id']
            data['accounts'][owner] = {'owner_id': owner, 'username': username,
                'password_hash': password_hash, 'role': 'admin', 'enabled': True,
                'created_at': self.now()}
            data.update(mode='managed', username=username, password_hash=password_hash,
                        administrator_id=owner, setup_code=None)
            self._rotate(data)
            # Commit protection first. Interrupted initialization remains closed.
            save_json(self.required_path, {'version': AUTH_SCHEMA_VERSION, 'mode': 'managed'})
            save_json(self.path, data)
            return {'mode': data['mode'], 'owner_id': owner, 'username': username}

    def issue_setup_code(self, ttl_seconds=SETUP_CODE_SECONDS):
        """Host CLI only: return a high-entropy, single-use code once."""
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise AuthError('invalid_setup_expiry', 'Setup code lifetime must be 1 to 3600 seconds.')
        with storage_lock:
            data = self.ensure_initialized()
            if data['accounts']:
                raise AuthError('already_initialized', 'Administrator already exists; use host password recovery.', 409)
            code = secrets.token_urlsafe(24)
            expires_at = self.now() + ttl_seconds
            data['setup_code'] = {'digest': hashlib.sha256(code.encode()).hexdigest(), 'expires_at': expires_at}
            save_json(self.path, data)
            return {'code': code, 'expires_at': expires_at}

    def complete_setup(self, code, username, password, source='unknown'):
        with storage_lock:
            data = self.state()
            if data['accounts']:
                raise AuthError('already_initialized', 'Administrator already exists; use host password recovery.', 409)
            self._rate_limit(source, self.now())
            setup = data.get('setup_code')
            digest = hashlib.sha256(code.encode()).hexdigest() if isinstance(code, str) and len(code) <= 128 else ''
            if (not setup or setup['expires_at'] <= self.now()
                    or not secrets.compare_digest(digest, setup['digest'])):
                raise AuthError('invalid_setup_code', 'Invalid or expired setup code.', 403)
            # setup removes the code in the same atomic commit as the administrator.
            return self.setup(username, password, enable_managed=True)

    def reset_password(self, password, username=None):
        """Host recovery retains account identity and works during explicit self mode."""
        password_hash = self._password(password)
        with storage_lock:
            data = self.state()
            owner = data['administrator_id']
            if username is not None:
                owner = next((key for key, value in data['accounts'].items()
                              if value['username'] == username and value['role'] == 'admin'), None)
            if owner is None:
                raise AuthError('not_initialized', 'No matching administrator exists.', 409)
            data['accounts'][owner]['password_hash'] = password_hash
            if owner == data['administrator_id']:
                data['password_hash'] = password_hash
            self._rotate(data)
            save_json(self.required_path, {'version': AUTH_SCHEMA_VERSION, 'mode': 'managed'})
            save_json(self.path, data)
            return {'mode': data['mode'], 'owner_id': owner, 'username': data['accounts'][owner]['username']}

    def owner_active(self, owner_id):
        data = self.state()
        if not data['accounts']:
            return owner_id == data['owner_id']
        account = data['accounts'].get(owner_id)
        return bool(account and account['enabled'] and
                    (data['mode'] == 'managed' or owner_id == data['owner_id']))

    def is_admin(self, owner_id):
        account = self.state()['accounts'].get(owner_id)
        return bool(account and account['enabled'] and account['role'] == 'admin')

    def list_accounts(self):
        return [self._public_account(account) for account in self.state()['accounts'].values()
                if 'deleted_at' not in account]

    @staticmethod
    def _require_managed(data):
        if data['mode'] != 'managed':
            raise AuthError('managed_required', 'Account management requires managed mode.', 409)

    def create_account(self, username, password, role='member'):
        username = self._username(username)
        if role not in ('admin', 'member'):
            raise AuthError('invalid_role', 'Invalid account role.')
        password_hash = self._password(password)
        with storage_lock:
            data = self.state()
            self._require_managed(data)
            if any(account['username'] == username for account in data['accounts'].values()):
                raise AuthError('username_exists', 'Account username already exists.', 409)
            if len(data['accounts']) >= MAX_ACCOUNTS:
                raise AuthError('account_limit', 'Account limit reached.', 409)
            owner = str(uuid4())
            account = {'owner_id': owner, 'username': username, 'password_hash': password_hash,
                       'role': role, 'enabled': True, 'created_at': self.now()}
            data['accounts'][owner] = account
            save_json(self.path, data)
            return self._public_account(account)

    def update_account(self, owner_id, *, enabled=None, role=None, password=None):
        if enabled is not None and type(enabled) is not bool:
            raise AuthError('invalid_enabled', 'Enabled must be a boolean.')
        if role is not None and role not in ('admin', 'member'):
            raise AuthError('invalid_role', 'Invalid account role.')
        password_hash = self._password(password) if password is not None else None
        with storage_lock:
            data = self.state()
            self._require_managed(data)
            account = data['accounts'].get(owner_id)
            if not account or 'deleted_at' in account:
                raise AuthError('account_not_found', 'Account not found.', 404)
            if ((owner_id in (data['owner_id'], data['administrator_id']) and enabled is False)
                    or (owner_id == data['administrator_id'] and role == 'member')):
                raise AuthError('primary_account_protected', 'The primary or recovery administrator must remain available.', 409)
            if enabled is not None:
                account['enabled'] = enabled
            if role is not None:
                account['role'] = role
            if password_hash:
                account['password_hash'] = password_hash
                if owner_id == data['administrator_id']:
                    data['password_hash'] = password_hash
            self._rotate(data)
            save_json(self.path, data)
            return self._public_account(account)

    def delete_account(self, owner_id):
        with storage_lock:
            data = self.state()
            self._require_managed(data)
            if owner_id not in data['accounts'] or 'deleted_at' in data['accounts'][owner_id]:
                raise AuthError('account_not_found', 'Account not found.', 404)
            if owner_id in (data['owner_id'], data['administrator_id'], data['data_owner_id']):
                raise AuthError('primary_account_protected', 'Select an alternative primary data space before deletion.', 409)
            # Retain the data-space identity for complete backup/recovery.
            data['accounts'][owner_id].update(enabled=False, deleted_at=self.now())
            self._rotate(data)
            save_json(self.path, data)

    def _credentials(self, data, username, password, source):
        self._rate_limit(source, self.now())
        valid_input = (isinstance(username, str) and len(username) <= 128
                       and isinstance(password, str) and len(password) <= 1024)
        account = next((account for account in data['accounts'].values()
                        if valid_input and secrets.compare_digest(username.encode(), account['username'].encode())), None)
        candidate = account or data['accounts'].get(data['administrator_id'])
        valid_password = bool(candidate and check_password_hash(candidate['password_hash'], password if valid_input else ''))
        if not valid_input or not account or not account['enabled'] or not valid_password:
            raise AuthError('invalid_credentials', 'Invalid username or password.', 401)
        return account

    def verify_admin(self, username, password, source='unknown'):
        with storage_lock:
            account = self._credentials(self.state(), username, password, source)
            if account['role'] != 'admin':
                raise AuthError('admin_required', 'Administrator authorization is required.', 403)
            # Failed reauthentication is throttled; successful previews/switches do
            # not consume the attempt budget for the next half of a round trip.
            key = str(source or 'unknown')[:128]
            self._login_sources[key].pop()
            if not self._login_sources[key]:
                del self._login_sources[key]
            self._login_global.pop()
            return account['owner_id']

    def switch_mode(self, mode, primary_owner_id, *, admin_owner_id, password,
                    expected_generation, confirm_shared=False, source='unknown'):
        with storage_lock:
            data = self.state()
            if mode not in ('self', 'managed'):
                raise AuthError('invalid_mode', 'Mode must be self or managed.')
            if type(expected_generation) is not int or expected_generation != data['generation']:
                raise AuthError('generation_conflict', 'Authorization changed; refresh the preview.', 409)
            admin = data['accounts'].get(admin_owner_id) if isinstance(admin_owner_id, str) else None
            if not admin or admin['role'] != 'admin' or not admin['enabled']:
                raise AuthError('admin_required', 'Administrator authorization is required.', 403)
            self.verify_admin(admin['username'], password, source)
            primary = data['accounts'].get(primary_owner_id) if isinstance(primary_owner_id, str) else None
            if not primary or not primary['enabled']:
                raise AuthError('invalid_primary_owner', 'Select an enabled primary account.', 409)
            if mode == 'self' and confirm_shared is not True:
                raise AuthError('sharing_confirmation_required', 'Confirm that the selected data space will be managed by reachable network users.', 409)
            if data['mode'] == mode and data['owner_id'] == primary_owner_id:
                raise AuthError('mode_unchanged', 'The selected mode and primary account are already active.', 409)
            data.update(mode=mode, owner_id=primary_owner_id, scope_changed_at=int(self.now() * 1000))
            self._rotate(data, devices=True)
            save_json(self.path, data)
            return {'mode': mode, 'owner_id': primary_owner_id, 'generation': data['generation'],
                    'scope_changed_at': data['scope_changed_at']}

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
            account = self._credentials(data, username, password, source)
            data['sessions'] = {digest: record for digest, record in data['sessions'].items()
                                if record['expires_at'] > now}
            if len(data['sessions']) >= MAX_SESSIONS:
                oldest = min(data['sessions'], key=lambda digest: data['sessions'][digest]['expires_at'])
                del data['sessions'][oldest]
            token = secrets.token_urlsafe(32)
            record = {'owner_id': account['owner_id'], 'expires_at': now + SESSION_SECONDS,
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
            if (record is None or record['expires_at'] <= self.now()
                    or not data['accounts'][record['owner_id']]['enabled']):
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
