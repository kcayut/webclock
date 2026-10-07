"""Cold data backups for a stopped WebClock installation (Linux/macOS)."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import secrets
import stat
import sys
import tempfile

from dotenv import load_dotenv, set_key

if __package__:
    from . import update_clock as updater
else:
    import update_clock as updater
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# These modules only validate/read state; importing the app would migrate data.
from webclock.services.device_access_service import DeviceAccessService
from webclock.services.display_settings import DEFAULT_NIGHT, validate_settings


FORMAT = 'webclock-host-backup'
ROLES = {'env', 'legacy_notes', 'default_state', 'state', 'notes'}


def configuration(project, state_dir=None, notes_file=None):
    # Match server dotenv precedence without importing app (which migrates data).
    environment = os.environ.copy()
    try:
        load_dotenv(project / '.env')
        values = dict(os.environ)
    finally:
        os.environ.clear()
        os.environ.update(environment)
    if state_dir is not None:
        values['WEBCLOCK_STATE_DIR'] = str(state_dir)
    if notes_file is not None:
        values['NOTES_FILE'] = str(notes_file)
    return values


def data_roots(project, values):
    state, notes = updater.data_layout(project, values, modular=True)
    paths = updater.protected_paths(project, (state, notes))
    candidates = [('env', project / '.env'), ('legacy_notes', project / 'manual_notes.json'),
                  ('default_state', project / 'webclock_state'), ('state', state), ('notes', notes)]
    roots = {}
    for role, path in candidates:
        if path in paths and path not in roots.values():
            roots[role] = path
    if len(roots) != len(paths):
        raise ValueError('Unsupported overlapping data paths.')
    reserved = [project / name for name in (
        'webclock', 'scripts', 'static', 'templates', 'tests', 'doc', 'docs', 'firmware', '.agents', '.codex', '.venv',
        'app.py', 'index.html', 'sw.js', 'setup.sh', 'update_clock.py', 'update_clock.sh', 'requirements.txt',
        'Dockerfile', 'docker-compose.yml', '.gitignore', '.dockerignore', 'TODO.md',
        'README.md', 'README_en.md', 'README_jp.md')]
    if (project / '.git').exists():
        reserved.extend(project / name for name in updater.run(['git', 'ls-files', '-z'], cwd=project).split('\0') if name)
    if any(path == source or source in path.parents or path in source.parents for path in roots.values() for source in reserved):
        raise ValueError('Data paths overlap application source or tracked files.')
    return roots


def inventory(path):
    """Hash bytes and record empty directories; never follow links/special files."""
    if path.is_symlink():
        raise ValueError('Symlinks are not supported in backups or data.')
    if not path.exists():
        return None
    result = {}
    pending = [path]
    while pending:
        item = pending.pop()
        mode = item.lstat().st_mode
        relative = item.relative_to(path).as_posix()
        if stat.S_ISDIR(mode):
            result[relative] = {'type': 'directory'}
            pending.extend(item.iterdir())
        elif stat.S_ISREG(mode):
            digest = hashlib.sha256()
            with item.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            result[relative] = {'type': 'file', 'size': item.stat().st_size, 'sha256': digest.hexdigest()}
        else:
            raise ValueError('Symlinks and special files are not supported.')
    return result


def separate(directory, paths):
    if directory.is_symlink():
        raise ValueError('Backup directory must not be a symlink.')
    directory = directory.resolve()
    if any(directory == path or path in directory.parents or directory in path.parents for path in paths):
        raise ValueError('Backup and data paths must not overlap.')
    return directory


def copy_data(source, target):
    # cp -a also preserves ownership when an administrator runs this command.
    updater.run(['cp', '-a', str(source), str(target)])


def layout_signature(roots, layout):
    result = {}
    for name, path in zip(('state', 'notes'), layout):
        for role, root in roots.items():
            if path == root or root in path.parents:
                result[name] = {'root': role, 'relative': path.relative_to(root).as_posix()}
                break
        else:
            raise ValueError('Data layout is outside the backup roots.')
    return result


def create_backup(directory, roots, layout):
    directory = separate(directory, roots.values())
    before = {role: inventory(path) for role, path in roots.items()}
    directory.mkdir(mode=0o700)  # Never reuse or overwrite an existing backup.
    try:
        (directory / 'data').mkdir(mode=0o700)
        for role, path in roots.items():
            if before[role] is not None:
                copy_data(path, directory / 'data' / role)
        copied = {role: inventory(directory / 'data' / role) for role in roots}
        if before != copied or before != {role: inventory(path) for role, path in roots.items()}:
            raise ValueError('Data changed during backup; stop all writers and retry.')
        manifest = dict(format=FORMAT, version=1, created_at=datetime.now(timezone.utc).isoformat(),
                        layout=layout_signature(roots, layout), data=copied)
        with (directory / 'manifest.json').open('x', encoding='utf-8') as stream:
            os.chmod(stream.fileno(), 0o600)
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        verify_backup(directory)
    except BaseException:
        shutil.rmtree(directory)
        raise
    return directory


def verify_backup(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Expected a real backup directory.')
    if directory.stat().st_mode & 0o077:
        raise ValueError('Backup directory must be private (chmod 700).')
    if {item.name for item in directory.iterdir()} != {'manifest.json', 'data'}:
        raise ValueError('Unexpected backup contents.')
    manifest_path, data_path = directory / 'manifest.json', directory / 'data'
    if (manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024
            or data_path.is_symlink() or not data_path.is_dir()):
        raise ValueError('Invalid backup manifest or data directory.')
    with manifest_path.open(encoding='utf-8') as stream:
        manifest = json.load(stream)
    if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT
            or type(manifest.get('version')) is not int or manifest['version'] != 1):
        raise ValueError('Unsupported backup format/version.')
    entries = manifest.get('data')
    if (not isinstance(entries, dict) or not {'env', 'legacy_notes', 'default_state'} <= entries.keys()
            or not entries.keys() <= ROLES):
        raise ValueError('Invalid backup roles.')
    layout = manifest.get('layout')
    if not isinstance(layout, dict) or set(layout) != {'state', 'notes'}:
        raise ValueError('Invalid backup layout.')
    for location in layout.values():
        if (not isinstance(location, dict) or set(location) != {'root', 'relative'}
                or location['root'] not in entries or not isinstance(location['relative'], str)
                or not location['relative'] or Path(location['relative']).is_absolute()
                or '..' in Path(location['relative']).parts):
            raise ValueError('Invalid backup layout path.')
    if {item.name for item in data_path.iterdir()} != {role for role, value in entries.items() if value is not None}:
        raise ValueError('Missing or unexpected backup data.')
    for role, expected in entries.items():
        actual = inventory(data_path / role)
        if actual != expected:
            raise ValueError('Backup integrity check failed: ' + role)
        if actual is not None and actual['.']['type'] != ('directory' if role in {'state', 'default_state'} else 'file'):
            raise ValueError('Invalid backup data type: ' + role)
    return manifest


def remove_data(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def revoke_restored_access(state):
    """Only schema-1 credential records can be safely retained and invalidated."""
    path = state / 'device-access.json'
    if not path.exists():
        return
    try:
        service = DeviceAccessService(path, lambda: '', validate_settings,
            lambda: {'night': dict(DEFAULT_NIGHT)}, lambda: {})
        data = service._load()
        for invite in data['invites'].values():
            if not isinstance(invite, dict) or type(invite.get('closed')) is not bool:
                raise ValueError()
            invite['closed'] = True
        keys = {'id', 'owner_id', 'group_id', 'enabled', 'status', 'credential_digest',
                'credential_generation', 'created_at', 'assignment_revision', 'rejoin_required'}
        for identity, device in data['devices'].items():
            if (not isinstance(device, dict) or not keys <= set(device)
                    or set(device) - (keys | {'display_overrides', 'content_overrides'}) or device.get('id') != identity
                    or type(device.get('credential_generation')) is not int or device['credential_generation'] < 1
                    or type(device.get('assignment_revision')) is not int or device['assignment_revision'] < 1
                    or type(device.get('enabled')) is not bool or type(device.get('rejoin_required')) is not bool
                    or device.get('status') not in ('active', 'disabled', 'revoked')
                    or any(not isinstance(device.get(key), str) or not device[key]
                           for key in ('owner_id', 'group_id', 'created_at'))
                    or (device['credential_digest'] is not None and not isinstance(device['credential_digest'], str))):
                raise ValueError()
            device.update(enabled=False, status='revoked', credential_digest=None,
                          credential_generation=device['credential_generation'] + 1, rejoin_required=True)
        data['attempts'] = {}
    except (ValueError, KeyError, TypeError, OSError):
        raise ValueError('Unsupported or invalid device authorization state. Keep the service stopped.') from None
    write_private_json(path, data)


def write_private_json(path, value):
    with path.open('w', encoding='utf-8') as stream:
        os.chmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())


def invalidate_restored_authorization(state, target_auth):
    auth = updater.authorization_state(state, required=bool(target_auth and target_auth['mode'] == 'managed'))
    if auth is None:
        # Legacy backups have no authorization contract; reject orphaned access data.
        if (state / 'device-access.json').exists():
            raise ValueError('Device authorization state is missing its owner authorization data.')
        return
    auth['session_secret'] = secrets.token_urlsafe(32)
    auth['invite_secret'] = secrets.token_urlsafe(32)
    auth['generation'] = max(auth['generation'], (target_auth or {}).get('generation', 0)) + 1
    auth['sessions'] = {}
    revoke_restored_access(state)
    if auth['mode'] == 'managed':
        marker = state / 'auth-required'
        write_private_json(marker, {'version': 1, 'mode': 'managed'})
        if os.geteuid() == 0:
            owner = (state / 'auth.json').stat()
            os.chown(marker, owner.st_uid, owner.st_gid)
    write_private_json(state / 'auth.json', auth)


def restore_backup(directory, roots, rollback_directory, project, values):
    directory = separate(directory, roots.values())
    manifest = verify_backup(directory)
    layout = updater.data_layout(project, values, modular=True)
    if set(manifest['data']) != set(roots) or manifest['layout'] != layout_signature(roots, layout):
        raise ValueError('Data layout differs; use --state-dir / --notes-file with the same nesting and relative filenames.')
    source_location = manifest['layout']['state']
    # A custom state layout also archives the dormant default directory. Invalidate
    # both so changing the state path later cannot revive historical credentials.
    locations = {(source_location['root'], source_location['relative']), ('default_state', '.')}
    floors = {}
    for role, relative in locations:
        target_auth = updater.authorization_state(roots[role] / relative)
        source_auth = updater.authorization_state(directory / 'data' / role / relative,
            required=bool(target_auth and target_auth['mode'] == 'managed'))
        if source_auth and source_auth['mode'] == 'managed' and not updater.supports_authorization(project):
            raise ValueError('Target code cannot enforce restored authorization. Keep the service stopped.')
        floors[role, relative] = target_auth
    rollback_directory = separate(rollback_directory, [*roots.values(), directory])
    # ponytail: cold restore only; stop every writer. Multi-file live transactions need a shared server lock.
    staged = {}
    changed = []
    recovery_failed = False
    try:
        for target in roots.values():
            inventory(target)
        for role, target in roots.items():
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            stage = Path(tempfile.mkdtemp(prefix='.webclock-restore-', dir=target.parent))
            staged[role] = stage
            if manifest['data'][role] is not None:
                copy_data(directory / 'data' / role, stage / 'incoming')
                if inventory(stage / 'incoming') != manifest['data'][role]:
                    raise ValueError('Staged data failed verification.')
        # On another host, keep all private .env settings but use the chosen target paths.
        env = staged['env'] / 'incoming'
        if env.exists():
            environment = os.environ.copy()
            try:
                os.environ.clear()
                load_dotenv(env)
                archived_layout = updater.data_layout(project, dict(os.environ), modular=True)
            finally:
                os.environ.clear()
                os.environ.update(environment)
            target_layout = updater.data_layout(project, values, modular=True)
            if archived_layout != target_layout:
                for key, path in zip(('WEBCLOCK_STATE_DIR', 'NOTES_FILE'), target_layout):
                    set_key(str(env), key, str(path))
                original = (directory / 'data' / 'env').stat()
                os.chmod(env, stat.S_IMODE(original.st_mode))
                if os.geteuid() == 0:
                    os.chown(env, original.st_uid, original.st_gid)
        for (role, relative), target_auth in floors.items():
            invalidate_restored_authorization(staged[role] / 'incoming' / relative, target_auth)
        create_backup(rollback_directory, roots, layout)
        print('Pre-restore backup: ' + str(rollback_directory), flush=True)
        for role, target in roots.items():
            if target.exists():
                os.replace(target, staged[role] / 'previous')
            changed.append(role)
            if (staged[role] / 'incoming').exists():
                os.replace(staged[role] / 'incoming', target)
    except BaseException:
        try:
            for role in reversed(staged):
                target = roots[role]
                # If moving the old target failed, it is still in place.
                if (staged[role] / 'previous').exists():
                    remove_data(target)
                    os.replace(staged[role] / 'previous', target)
                elif role in changed and not (staged[role] / 'incoming').exists():
                    remove_data(target)
        except BaseException:
            recovery_failed = True
            print('Recovery incomplete. Keep the service stopped. Pre-restore backup: ' + str(rollback_directory), file=sys.stderr)
        raise
    finally:
        if not recovery_failed:
            for stage in staged.values():
                shutil.rmtree(stage)


@contextmanager
def installation_lock(project):
    fd = os.open(project / '.webclock-update.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('create', 'verify', 'restore'))
    parser.add_argument('directory', type=Path, help='New backup directory, or existing backup to verify/restore')
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--state-dir', type=Path, help='Effective state path on this host')
    parser.add_argument('--notes-file', type=Path, help='Effective reminder path on this host')
    parser.add_argument('--stopped', action='store_true', help='Confirm all servers/containers and other writers are stopped')
    parser.add_argument('--yes', action='store_true', help='Confirm replacing all target data (restore only)')
    parser.add_argument('--rollback-dir', type=Path, help='New directory for the retained pre-restore backup')
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Backup operation interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.operation == 'verify':
            verify_backup(args.directory)
        else:
            if not args.stopped:
                parser.error('Stop all writers first, then pass --stopped. This command does not stop services.')
            if args.operation == 'restore' and (not args.yes or args.rollback_dir is None):
                parser.error('Restore requires --yes and a new --rollback-dir.')
            project = args.project.resolve()
            if not (project / 'webclock/app.py').is_file():
                raise ValueError('Use a current WebClock installation as --project; source and dependencies are not in the backup.')
            values = configuration(project, args.state_dir, args.notes_file)
            roots = data_roots(project, values)
            for role, path in roots.items():
                print(role + ': ' + str(path), flush=True)
            with installation_lock(project):
                if args.operation == 'create':
                    create_backup(args.directory, roots, updater.data_layout(project, values, modular=True))
                else:
                    restore_backup(args.directory, roots, args.rollback_dir, project, values)
        print(args.operation.capitalize() + ' complete. Backup data is private; no service was started.')
    except (Exception, KeyboardInterrupt) as error:
        # Do not print subprocess output or parsed values: either can contain secrets.
        print('Backup operation failed (' + type(error).__name__ + '). ' +
              (str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Keep the service stopped and check paths, permissions and available space.'), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
