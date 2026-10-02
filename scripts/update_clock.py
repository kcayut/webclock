"""Update an existing Linux/systemd installation without replacing its data."""
import fcntl
import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit


def run(args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def service_property(name):
    return run(['systemctl', 'show', 'webclock', '--property=' + name, '--value'])


def service_url(project):
    if Path(service_property('WorkingDirectory')).resolve() != project:
        raise RuntimeError('Service WorkingDirectory does not match this folder; nothing updated.')
    pid = int(service_property('MainPID'))
    if pid <= 0:
        raise RuntimeError('Start the existing service before updating so its settings can be preserved.')
    proc = Path('/proc') / str(pid)
    if (proc / 'cwd').resolve() != project:
        raise RuntimeError('Running service uses a different folder.')
    args = (proc / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    if (Path(args[0]).parent != project / 'venv' / 'bin'
            or not any((project / arg).resolve() == project / 'app.py' for arg in args[1:])):
        raise RuntimeError('Expected the existing project-local venv and app.py service.')
    defaults = service_configuration(project)
    port = int(defaults.get('PORT', 5000))
    if not 1 <= port <= 65535:
        raise RuntimeError('Invalid existing service port.')
    host = defaults.get('HOST', '0.0.0.0')
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
    if ':' in host:
        host = '[' + host + ']'
    owner = proc.stat()
    return 'http://{}:{}'.format(host, port), owner.st_uid, owner.st_gid


def service_configuration(project):
    """Read only relevant settings, with the running service environment taking precedence."""
    keys = ('HOST', 'PORT', 'WEBCLOCK_STATE_DIR', 'NOTES_FILE', 'DEVICE_API_TOKEN')
    pid = int(service_property('MainPID'))
    environment = dict(entry.split('=', 1) for entry in
                       (Path('/proc') / str(pid) / 'environ').read_bytes().decode().split('\0') if '=' in entry)
    return json.loads(run([str(project / 'venv/bin/python3'), '-c',
        'import json, os; from dotenv import load_dotenv; load_dotenv(".env"); '
        'print(json.dumps({k:os.environ[k] for k in ' + repr(keys) + ' if k in os.environ}))'],
        cwd=project, env=environment))


def http_json(url, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    headers = {'Content-Type': 'application/json', **(headers or {})}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
    if data is not None:
        parsed = urlsplit(url)
        csrf_url = urlunsplit((parsed.scheme, parsed.netloc, '/api/csrf', '', ''))
        try:
            with opener.open(csrf_url, timeout=15) as response:
                headers['X-CSRF-Token'] = json.load(response)['csrf_token']
        except HTTPError as error:
            # Old servers have no CSRF endpoint; other failures must not downgrade.
            if error.code != 404:
                raise
            error.close()
    request = urllib.request.Request(url, data=body, headers=headers)
    with opener.open(request, timeout=15) as response:
        return json.load(response)


def settings_match(saved, expected):
    # Older releases omit the 24-hour display default; leave their files intact.
    return (isinstance(saved, dict) and isinstance(expected, dict)
            and {'time_format': '24h', **saved} == {'time_format': '24h', **expected})


def wait_healthy(url, expected):
    deadline = time.monotonic() + 60
    last_pid, stable = None, 0
    while time.monotonic() < deadline:
        try:
            pid = service_property('MainPID')
            if service_property('ActiveState') != 'active' or int(pid) <= 0:
                raise RuntimeError('Service not active')
            status = http_json(url + '/api/status')
            if not settings_match(status.get('settings'), expected) or not isinstance(status.get('events'), list):
                raise RuntimeError('Unexpected status/settings')
            stable = stable + 1 if pid == last_pid else 1
            last_pid = pid
            if stable >= 3:
                return
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
            stable = 0
        time.sleep(2)
    raise RuntimeError('Service failed its HTTP/settings health check.')


def data_layout(project, configuration, modular):
    def path(value):
        if not value:
            raise RuntimeError('Empty data paths are not supported.')
        candidate = project / value
        if candidate.is_symlink():
            raise RuntimeError('Data directory/file must not be a symlink: ' + str(candidate))
        return candidate.resolve()

    state = path(configuration.get('WEBCLOCK_STATE_DIR', 'webclock_state') if modular else 'webclock_state')
    notes = path(configuration.get('NOTES_FILE', str(state / 'manual_notes.json') if modular else 'manual_notes.json'))
    return state, notes


def protected_paths(project, *layouts):
    candidates = {project / '.env': 'file', project / 'manual_notes.json': 'file',
                  project / 'webclock_state': 'directory'}
    for state, notes in layouts:
        if notes in (state, state / 'settings.json') or notes in state.parents:
            raise RuntimeError('Settings directory and notes file overlap.')
        candidates[state] = 'directory'
        candidates[notes] = 'file'
    for path, kind in candidates.items():
        if any(parent in candidates and candidates[parent] == 'file' for parent in path.parents):
            raise RuntimeError('Data file and directory paths overlap.')
        if path == project or path in project.parents or any(
                reserved == path or reserved in path.parents
                for reserved in (project / 'venv', project / '.git')):
            raise RuntimeError('Data paths overlap the installation: ' + str(path))
        if path.is_symlink() or (path.exists() and not (path.is_dir() if kind == 'directory' else path.is_file())):
            raise RuntimeError('Unexpected data path type: ' + str(path))
        if project in path.parents and any(part.startswith('.webclock-update') for part in path.relative_to(project).parts):
            raise RuntimeError('Data paths overlap updater backups.')
    # Back up an enclosing directory only once, including notes stored inside it.
    return [path for path in sorted(candidates, key=lambda p: len(p.parts))
            if not any(parent in candidates and candidates[parent] == 'directory' for parent in path.parents)]


def read_json(path, default):
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return default
    return json.loads(text) if text.strip() else default


def check_saved_data(current, target, snapshot):
    required = {'mode', 'brightness', 'timezone_offset', 'language'}
    if (not isinstance(snapshot, dict) or not required <= set(snapshot)
            or set(snapshot) - (required | {'night', 'time_format'})
            or snapshot.get('time_format', '24h') not in ('24h', '12h')):
        raise RuntimeError('Could not capture current display settings.')
    for state in {current[0], target[0]}:
        settings = state / 'settings.json'
        if settings.is_symlink():
            raise RuntimeError('Settings file must not be a symlink.')
        if settings.exists() and not settings_match(read_json(settings, None), snapshot):
            raise RuntimeError('Saved settings differ from the running service; resolve this before updating.')
    notes = read_json(current[1], [])
    if not isinstance(notes, list):
        raise RuntimeError('Invalid stored reminders.')
    if current[1] != target[1] and target[1].exists() and read_json(target[1], []) != notes:
        raise RuntimeError('Old and new reminder files differ; resolve this before updating.')
    return notes


def snapshot_data(paths, backup, old_head):
    entries = []
    directory = backup / 'data'
    directory.mkdir()
    for index, path in enumerate(paths):
        saved = 'data/' + str(index)
        entry = dict(path=str(path), backup=saved, existed=path.exists())
        if entry['existed']:
            run(['cp', '-a', str(path), str(backup / saved)])
        entries.append(entry)
    manifest = dict(old_head=old_head, data=entries)
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return entries


def restore_data(entries, backup):
    failed = backup / 'failed-data'
    failed.mkdir()
    for index, entry in enumerate(entries):
        path = Path(entry['path'])
        if path.exists() or path.is_symlink():
            shutil.move(str(path), str(failed / str(index)))
        if entry['existed']:
            path.parent.mkdir(parents=True, exist_ok=True)
            run(['cp', '-a', str(backup / entry['backup']), str(path)])


def prepare_data(layout, snapshot, notes, uid, gid):
    state, notes_file = layout
    for directory in {state, notes_file.parent}:
        if not directory.exists():
            directory.mkdir(parents=True, mode=0o700)
            os.chown(directory, uid, gid)
    for path, value in ((state / 'settings.json', snapshot), (notes_file, notes)):
        if not path.exists():
            with path.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o600)
            os.chown(path, uid, gid)


def verify_server(project, url, layout, expected_notes, configuration):
    if read_json(layout[1], []) != expected_notes:
        raise RuntimeError('Reminder migration did not preserve the original data.')
    if (project / 'webclock/api/device.py').is_file():
        schedules = http_json(url + '/api/v1/schedules')
        devices = http_json(url + '/api/v1/devices')
        token = configuration.get('DEVICE_API_TOKEN')
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        config = http_json(url + '/api/v1/device/config', headers=headers)
        if (not isinstance(schedules.get('schedules'), list) or not isinstance(devices.get('devices'), list)
                or config.get('schema_version') != 2 or config.get('timezone') != 'Asia/Taipei'):
            raise RuntimeError('Management/device API health check failed.')


def update(project):
    project = project.resolve()
    fd = os.open(project / '.webclock-update.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        perform_update(project)


def perform_update(project):
    url, uid, gid = service_url(project)
    configuration = service_configuration(project)
    venv = project / 'venv'
    if venv.is_symlink() or not (venv / 'bin/python3').is_file():
        raise RuntimeError('Expected a real project-local venv directory.')
    current = data_layout(project, configuration, (project / 'webclock/app.py').is_file())
    target_layout = current
    git_prefix, old_head, target, revisions = None, None, None, []
    if (project / '.git').exists():
        owner = pwd.getpwuid((project / '.git').stat().st_uid).pw_name
        git_prefix = (['runuser', '-u', owner, '--'] if owner != 'root' else []) + ['git']
        dirty = run(git_prefix + ['status', '--porcelain', '--untracked-files=normal'], cwd=project)
        if any(line != '?? .webclock-update.lock' for line in dirty.splitlines()):
            raise RuntimeError('Uncommitted/untracked files found. Commit or move them before updating.')
        old_head = run(git_prefix + ['rev-parse', 'HEAD'], cwd=project)
        run(git_prefix + ['fetch'], cwd=project)
        target = run(git_prefix + ['rev-parse', '@{upstream}'], cwd=project)
        run(git_prefix + ['merge-base', '--is-ancestor', old_head, target], cwd=project)
        revisions = [run(git_prefix + ['ls-tree', '-r', '--name-only', ref], cwd=project).splitlines()
                     for ref in (old_head, target)]
        target_layout = data_layout(project, configuration, 'webclock/app.py' in revisions[1])
    else:
        print('No Git repository: using files already copied here; old source cannot be recovered.', flush=True)

    paths = protected_paths(project, current, target_layout)
    for tracked in revisions:
        for name in tracked:
            path = project / name
            if (name.startswith(('.webclock-update', 'venv/')) or name == 'venv'
                    or any(path == data or data in path.parents or path in data.parents for data in paths)):
                raise RuntimeError('Git version tracks installation data; refusing to overwrite it.')
    snapshot = http_json(url + '/api/status')['settings']
    check_saved_data(current, target_layout, snapshot)
    backup = Path(tempfile.mkdtemp(prefix='.webclock-update-', dir=project))
    print('Backup: ' + str(backup), flush=True)
    stopped = changed = packages_changed = False
    entries = []
    try:
        run(['cp', '-a', str(venv), str(backup / 'venv')])
        snapshot = http_json(url + '/api/status')['settings']
        print('Stopping service and preserving installation data...', flush=True)
        stopped = True
        run(['systemctl', 'stop', 'webclock'])
        # Read the final persisted settings after stop, so a last-minute edit is retained.
        snapshot = read_json(current[0] / 'settings.json', snapshot)
        notes = check_saved_data(current, target_layout, snapshot)
        entries = snapshot_data(paths, backup, old_head)
        changed = True
        if git_prefix:
            run(git_prefix + ['merge', '--ff-only', target], cwd=project)
        prepare_data(target_layout, snapshot, notes, uid, gid)
        print('Installing and checking Python packages...', flush=True)
        packages_changed = True
        run([str(venv / 'bin/python3'), '-m', 'pip', 'install', '-r', 'requirements.txt'], cwd=project)
        run([str(venv / 'bin/python3'), '-m', 'pip', 'check'], cwd=project)
        run(['systemctl', 'start', 'webclock'])
        print('Checking service health, reminders and management APIs...', flush=True)
        wait_healthy(url, snapshot)
        verify_server(project, url, target_layout, notes, configuration)
    except BaseException:
        if stopped:
            print('Update failed; restoring the previous source, environment and data.', flush=True)
            try:
                run(['systemctl', 'stop', 'webclock'])
                if changed:
                    if git_prefix:
                        run(git_prefix + ['reset', '--keep', old_head], cwd=project)
                    if packages_changed:
                        shutil.move(str(venv), str(backup / 'failed-venv'))
                        run(['cp', '-a', str(backup / 'venv'), str(venv)])
                    restore_data(entries, backup)
                run(['systemctl', 'start', 'webclock'])
                # Older releases kept settings only in memory. Avoid rewriting saved files otherwise.
                for attempt in range(15):
                    try:
                        if not settings_match(http_json(url + '/api/status')['settings'], snapshot):
                            http_json(url + '/api/control', snapshot)
                        break
                    except (OSError, ValueError):
                        time.sleep(2)
                wait_healthy(url, snapshot)
                print('Previous service and data restored.', flush=True)
            except Exception as rollback_error:
                print('Automatic recovery failed: ' + str(rollback_error), file=sys.stderr)
        print('Backup retained at: ' + str(backup), file=sys.stderr)
        raise
    shutil.rmtree(backup)
    print('Update Complete: service, settings, reminders and APIs verified.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    if os.geteuid() != 0:
        sys.exit('Please run: sudo bash update_clock.sh')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Update interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        update(args.project)
    except (Exception, KeyboardInterrupt) as error:
        print('Update failed: ' + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout, file=sys.stderr)
            print(error.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
