"""Portable application data with optional encryption and recoverable restore."""
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .auth_service import AuthService
from .control_access_service import ControlAccessService
from .control_service import read_control_requests
from .device_access_service import DeviceAccessService
from .device_service import DeviceService, _identifier
from .display_settings import DEFAULT_NIGHT, validate_settings
from .event_service import read_events
from .schedule_service import read_schedules
from .storage import save_json, storage_lock


FORMAT = 'webclock-portable-backup'
MAGIC = b'WEBCLOCK\x00\x01'
PLAIN_MAGIC = b'WEBCLOCK\x00\x02'
MAX_PLAINTEXT = 20 * 1024 * 1024
MAX_FILE_SIZE = MAX_PLAINTEXT + len(MAGIC) + 16 + 12 + 16
PENDING_DIR = '.portable-restore-pending'
PREVIOUS_DIR = '.portable-restore-previous'
SCOPED_FILES = frozenset(('settings.json', 'manual_notes.json', 'calendar.json',
                          'schedules.json', 'events.json', 'control-requests.json'))
ROOT_FILES = SCOPED_FILES | {'auth.json', 'auth-required', 'device-access.json',
                             'devices.json', 'control-clients.json'}
OWNER_PATTERN = r'[A-Za-z0-9_-]{1,128}'


class BackupError(ValueError):
    def __init__(self, code='invalid_backup', status=400):
        super().__init__(code)
        self.code, self.status = code, status


class RecoveryError(RuntimeError):
    """The journal must remain in place and requests must fail closed."""


def _dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise BackupError() from exc


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError()
        result[key] = value
    return result


def _parse(raw):
    try:
        def invalid(_):
            raise BackupError()
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BackupError() from exc


def _allowed(name):
    if not isinstance(name, str):
        return False
    parts = PurePosixPath(name).parts
    return (name in ROOT_FILES or (len(parts) == 3 and parts[0] == 'owners'
            and re.fullmatch(OWNER_PATTERN, parts[1]) and parts[2] in SCOPED_FILES
            and name == '/'.join(parts)))


def _paths(state_dir, notes_file):
    state, notes = Path(state_dir), Path(notes_file)
    if state.is_symlink() or notes.is_symlink():
        raise BackupError('unsafe_data_path')
    state, notes = state.resolve(), notes.resolve()
    if (notes == state or notes in state.parents or notes == state / 'owners'
            or state / 'owners' in notes.parents or any(notes == state / name
                for name in (ROOT_FILES - {'manual_notes.json'}) | {PENDING_DIR, PREVIOUS_DIR})
            or any(state / name in notes.parents for name in (PENDING_DIR, PREVIOUS_DIR))):
        # Custom notes paths are portable, but may never alias another managed file.
        raise BackupError('unsafe_data_path')
    return state, notes


def _target(state, notes, name):
    if not _allowed(name):
        raise BackupError('invalid_backup_path')
    path = notes if name == 'manual_notes.json' else state / name
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise BackupError('unsafe_data_path')
        if parent == state or parent == notes.parent:
            break
    return path


def _read(path, limit=MAX_PLAINTEXT):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise BackupError('invalid_data_file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise BackupError('backup_too_large', 413)
        return raw
    finally:
        os.close(fd)


def _inventory(state, notes):
    names = set(ROOT_FILES)
    owners = state / 'owners'
    if owners.is_symlink():
        raise BackupError('unsafe_data_path')
    if owners.exists():
        populated = 0
        for directory in owners.iterdir():
            if (directory.is_symlink() or not directory.is_dir()
                    or not re.fullmatch(OWNER_PATTERN, directory.name)):
                raise BackupError('invalid_owner_data')
            existing = [name for name in SCOPED_FILES
                        if (directory / name).exists() or (directory / name).is_symlink()]
            if existing:
                populated += 1
                if populated > 100:
                    raise BackupError('invalid_owner_data')
                names.update('owners/' + directory.name + '/' + name for name in existing)
    result = {}
    size = 0
    for name in sorted(names):
        raw = _read(_target(state, notes, name))
        if raw is not None:
            size += len(raw)
            if size > MAX_PLAINTEXT:
                raise BackupError('backup_too_large', 413)
            result[name] = raw
    return result


def validate(payload, validate_content=None):
    """Validate before disk mutation; content callback applies the app's note/calendar rules."""
    if (not isinstance(payload, dict) or set(payload) != {'format', 'version', 'created_at', 'files'}
            or payload['format'] != FORMAT or type(payload['version']) is not int
            or payload['version'] != 1 or not isinstance(payload['created_at'], str)
            or not isinstance(payload['files'], dict) or len(payload['files']) > 611):
        raise BackupError()
    try:
        stamp = datetime.fromisoformat(payload['created_at'])
        if stamp.utcoffset() is None:
            raise ValueError()
        files = payload['files']
        if any(not _allowed(name) for name in files) or 'auth.json' not in files:
            raise BackupError('invalid_backup_path')
        if len(_dump(payload)) > MAX_PLAINTEXT:
            raise BackupError('backup_too_large', 413)
        auth = AuthService._validate(files['auth.json'])
        protected = bool(auth['accounts']) or auth['mode'] == 'managed'
        if ('auth-required' in files and files['auth-required'] != {'version': 1, 'mode': 'managed'}) or (
                protected != ('auth-required' in files)):
            raise BackupError('invalid_authorization')
        owner_ids = set(auth['accounts']) or {auth['owner_id']}
        for name in files:
            if name.startswith('owners/') and (name.split('/')[1] not in owner_ids
                    or name.split('/')[1] == auth['data_owner_id']):
                raise BackupError('invalid_owner_data')
        # Existing validators are path-based. A private temporary tree avoids parallel schemas.
        with tempfile.TemporaryDirectory(prefix='webclock-validate-') as temporary:
            root = Path(temporary)
            for name, value in files.items():
                save_json(root / name, value)
            for directory in [root] + sorted((root / 'owners').iterdir() if (root / 'owners').exists() else []):
                owner = auth['data_owner_id'] if directory == root else directory.name
                settings = files.get((directory.relative_to(root).as_posix() + '/' if directory != root else '') + 'settings.json', {})
                validate_settings(settings)
                read_schedules(directory)
                if any(row['owner_id'] != owner for row in read_events(directory)):
                    raise BackupError('invalid_owner_data')
                if any(row['owner_id'] != owner for row in read_control_requests(directory).values()):
                    raise BackupError('invalid_owner_data')
            access = DeviceAccessService(root / 'device-access.json', lambda: '', validate_settings,
                                         lambda: {'night': dict(DEFAULT_NIGHT)}, lambda: {})._load()
            if any(row['owner_id'] not in owner_ids for field in ('groups', 'devices', 'invites', 'attempts')
                   for row in access[field].values()):
                raise BackupError('invalid_owner_data')
            if any(row['owner_id'] not in owner_ids for row in
                   ControlAccessService(root / 'control-clients.json', None)._load()['clients'].values()):
                raise BackupError('invalid_owner_data')
            observations = files.get('devices.json', {})
            if not isinstance(observations, dict) or len(observations) > 100:
                raise BackupError()
            for device_id, row in observations.items():
                _identifier(device_id)
                if not isinstance(row, dict) or row.get('id') != device_id:
                    raise BackupError()
            DeviceService(root / 'devices.json').list()
        for name, value in files.items():
            if name.endswith('manual_notes.json'):
                if (not isinstance(value, list) or len(value) > 1000 or any(not isinstance(row, dict)
                        or type(row.get('id')) is not int or row['id'] < 1 for row in value)
                        or len({row['id'] for row in value}) != len(value)):
                    raise BackupError()
            if name.endswith('calendar.json') and not isinstance(value, dict):
                raise BackupError()
        if validate_content:
            validate_content(files)
        return payload
    except BackupError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, OverflowError) as exc:
        raise BackupError() from exc


def capture(state_dir, notes_file, calendar=None, validate_content=None):
    """Host settings never enter the file; external primary notes use a logical name."""
    with storage_lock:
        state, notes = _paths(state_dir, notes_file)
        if pending(state):
            raise RecoveryError('An interrupted restore requires recovery.')
        files = {name: _parse(raw) for name, raw in _inventory(state, notes).items()}
        auth = AuthService(state / 'auth.json').state()
        files['auth.json'] = auth
        if auth['accounts'] or auth['mode'] == 'managed':
            files['auth-required'] = {'version': 1, 'mode': 'managed'}
        if calendar is not None:
            files.setdefault('calendar.json', copy.deepcopy(calendar))
        payload = dict(format=FORMAT, version=1, created_at=datetime.now(timezone.utc).isoformat(), files=files)
        return validate(payload, validate_content)


def _key(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise BackupError('invalid_backup_password')
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768, r=8, p=1,
                          maxmem=64 * 1024 * 1024, dklen=32)


def encrypt(payload, password, validate_content=None):
    validate(payload, validate_content)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC + salt + nonce
    return header + AESGCM(_key(password, salt)).encrypt(nonce, _dump(payload), header)


def decrypt(raw, password, validate_content=None):
    if not isinstance(raw, bytes) or not len(MAGIC) + 44 <= len(raw) <= MAX_FILE_SIZE or not raw.startswith(MAGIC):
        raise BackupError('invalid_backup')
    header_size = len(MAGIC) + 28
    salt, nonce = raw[len(MAGIC):len(MAGIC) + 16], raw[len(MAGIC) + 16:header_size]
    try:
        value = AESGCM(_key(password, salt)).decrypt(nonce, raw[header_size:], raw[:header_size])
    except InvalidTag as exc:
        raise BackupError('backup_password_or_file_invalid') from exc
    return validate(_parse(value), validate_content)


def encode(payload, password=None, *, encrypted=True, validate_content=None):
    if not isinstance(encrypted, bool):
        raise BackupError()
    if encrypted:
        return encrypt(payload, password, validate_content)
    validate(payload, validate_content)
    raw = _dump(payload)
    # This checksum detects accidental damage; it does not authenticate a sender.
    return PLAIN_MAGIC + hashlib.sha256(raw).digest() + raw


def decode(raw, password=None, validate_content=None):
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE_SIZE:
        raise BackupError()
    if not raw.startswith(PLAIN_MAGIC):
        return decrypt(raw, password, validate_content)
    start = len(PLAIN_MAGIC)
    checksum, value = raw[start:start + 32], raw[start + 32:]
    if not value or not secrets.compare_digest(checksum, hashlib.sha256(value).digest()):
        raise BackupError()
    return validate(_parse(value), validate_content)


def _fresh(files):
    auth = files.get('auth.json', {})
    if auth.get('accounts') or auth.get('mode') == 'managed' or 'auth-required' in files:
        return False
    for name, value in files.items():
        if name == 'auth.json':
            continue
        if name == 'device-access.json':
            if any(value.get(key) for key in ('groups', 'devices', 'invites', 'attempts')):
                return False
        elif name == 'control-clients.json':
            if value.get('clients'):
                return False
        elif name.endswith('calendar.json'):
            if value.get('sources') or value.get('url') or value.get('calendar_targets') or value.get('local_display_enabled', True) is not True:
                return False
        elif value:
            return False
    return True


def preview(payload, state_dir, notes_file, validate_content=None, *, target_calendar=None):
    validate(payload, validate_content)
    with storage_lock:
        current = capture(state_dir, notes_file, calendar=target_calendar)
        old, auth = current['files']['auth.json'], AuthService._validate(payload['files']['auth.json'])
        if (old['accounts'] or old['mode'] == 'managed') and not (auth['accounts'] or auth['mode'] == 'managed'):
            raise BackupError('protected_restore_required', 409)
        if old['mode'] == 'managed' and auth['mode'] != 'managed':
            raise BackupError('protected_restore_required', 409)
        files = payload['files']
        access = files.get('device-access.json', {})
        return dict(mode=auth['mode'], created_at=payload['created_at'], accounts=len(auth['accounts']),
                    calendars=sum(len(value.get('sources', [])) if 'sources' in value else bool(value.get('url'))
                                  for name, value in files.items() if name.endswith('calendar.json')),
                    notes=sum(len(value) for name, value in files.items() if name.endswith('manual_notes.json')),
                    alarms=sum(len(value) for name, value in files.items() if name.endswith('schedules.json')),
                    events=sum(len(value) for name, value in files.items() if name.endswith('events.json')),
                    groups=len(access.get('groups', {})), devices=len(access.get('devices', {})),
                    preserve_devices=_fresh(current['files']),
                    program_credentials_revoked=(0 if _fresh(current['files']) else
                        len(files.get('control-clients.json', {}).get('clients', {}))))


def pending(state_dir):
    path = Path(state_dir) / PENDING_DIR
    return path.exists() or path.is_symlink()


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, raw):
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        _sync(directory.parent)
    fd, temporary = tempfile.mkstemp(prefix='.portable-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _remove(path):
    if path.exists():
        path.unlink()
        _sync(path.parent)


def _finish(state):
    # Commit/rollback contents must be durable before the blocking journal moves.
    _sync(state / PENDING_DIR)
    previous = state / PREVIOUS_DIR
    if previous.is_symlink():
        raise RecoveryError('Unsafe recovery directory.')
    if previous.exists():
        shutil.rmtree(previous)
    os.replace(state / PENDING_DIR, previous)
    _sync(state)


def recover(state_dir, notes_file):
    """Roll back an interrupted import, or retain its committed pre-import snapshot."""
    with storage_lock:
        state, notes = _paths(state_dir, notes_file)
        if not pending(state):
            return False
        try:
            directory = state / PENDING_DIR
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError()
            journal = _parse(_read(directory / 'journal.json', MAX_PLAINTEXT * 2))
            if (not isinstance(journal, dict) or set(journal) != {'version', 'notes_file', 'files', 'committed'}
                    or journal['version'] != 1 or journal['notes_file'] != str(notes)
                    or type(journal['committed']) is not bool or not isinstance(journal['files'], dict)
                    or len(journal['files']) > 1211):
                raise ValueError()
            raw_files = {}
            for name, value in journal['files'].items():
                _target(state, notes, name)
                raw_files[name] = None if value is None else base64.b64decode(value, validate=True)
            if sum(len(value or b'') for value in raw_files.values()) > MAX_PLAINTEXT:
                raise ValueError()
            if not journal['committed']:
                for name, raw in raw_files.items():
                    path = _target(state, notes, name)
                    _remove(path) if raw is None else _write(path, raw)
            _finish(state)
            return True
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            raise RecoveryError('Restore recovery is incomplete; keep the server closed.') from exc


def restore(payload, state_dir, notes_file, validate_content=None, *, target_calendar=None):
    with storage_lock:
        summary = preview(payload, state_dir, notes_file, validate_content, target_calendar=target_calendar)
        state, notes = _paths(state_dir, notes_file)
        if (state / PREVIOUS_DIR).is_symlink():
            raise BackupError('unsafe_data_path')
        before = _inventory(state, notes)
        files = copy.deepcopy(payload['files'])
        # An absent source subscription must not activate the destination's legacy .env URL.
        files.setdefault('calendar.json', {'sources': [], 'local_display_enabled': True})
        auth = AuthService._validate(files['auth.json'])
        AuthService._rotate(auth, devices=not summary['preserve_devices'])
        auth['setup_code'] = None
        auth['scope_changed_at'] = int(datetime.now(timezone.utc).timestamp() * 1000)
        files['auth.json'] = auth
        if 'device-access.json' in files:
            access = files['device-access.json']
            access['attempts'] = {}
            for invitation in access['invites'].values():
                invitation['closed'] = True
            if not summary['preserve_devices']:
                for device in access['devices'].values():
                    device.update(enabled=False, status='revoked', credential_digest=None,
                                  credential_generation=device['credential_generation'] + 1, rejoin_required=True)
        # Fresh migration retains the program HMAC key; closed invites cannot be reused.
        # Populated restore rotates it, invalidating program digests while retaining grants.
        validate(dict(payload, files=files), validate_content)
        all_names = sorted(set(before) | set(files))
        for name in all_names:
            _target(state, notes, name)
        journal = dict(version=1, notes_file=str(notes), committed=False,
                       files={name: base64.b64encode(before[name]).decode('ascii') if name in before else None
                              for name in all_names})
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.portable-restore-stage-', dir=state))
        committed = False
        try:
            _write(stage / 'journal.json', _dump(journal))
            _sync(stage)
            os.replace(stage, state / PENDING_DIR)
            _sync(state)
            for name in all_names:
                path = _target(state, notes, name)
                _write(path, _dump(files[name])) if name in files else _remove(path)
            journal['committed'] = True
            _write(state / PENDING_DIR / 'journal.json', _dump(journal))
            committed = True
            _finish(state)
        except BaseException:
            if pending(state):
                try:
                    # replace() can succeed before fsync() raises. Read the commit
                    # decision before recovery chooses rollback versus completion.
                    committed = _parse(_read(state / PENDING_DIR / 'journal.json', MAX_PLAINTEXT * 2))['committed'] is True
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    raise RecoveryError('The restore decision is unreadable; keep the server closed.') from exc
                try:
                    recover(state, notes)
                except RecoveryError:
                    if not committed or pending(state):
                        raise
            if committed and not pending(state):
                # Data is committed, even if syncing the cleanup rename failed.
                # Report success so the caller refreshes caches and clears sessions.
                return summary
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return summary
