"""Update an existing Linux/systemd installation without replacing its data."""
import fcntl
import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
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
    environment = dict(entry.split('=', 1) for entry in
                       (proc / 'environ').read_bytes().decode().split('\0') if '=' in entry)
    # Use the installed dotenv parser, and let systemd environment override .env.
    defaults = json.loads(run([str(project / 'venv/bin/python3'), '-c',
        'import json; from dotenv import dotenv_values; d=dotenv_values(".env"); '
        'print(json.dumps({k:d[k] for k in ("HOST","PORT") if d.get(k)}))'], cwd=project))
    defaults.update(environment)
    port = int(defaults.get('PORT', 5000))
    if not 1 <= port <= 65535:
        raise RuntimeError('Invalid existing service port.')
    host = defaults.get('HOST', '0.0.0.0')
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
    if ':' in host:
        host = '[' + host + ']'
    owner = proc.stat()
    return 'http://{}:{}'.format(host, port), owner.st_uid, owner.st_gid


def http_json(url, data=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
        return json.load(response)


def wait_healthy(url, expected):
    deadline = time.monotonic() + 60
    last_pid, stable = None, 0
    while time.monotonic() < deadline:
        try:
            pid = service_property('MainPID')
            if service_property('ActiveState') != 'active' or int(pid) <= 0:
                raise RuntimeError('Service not active')
            status = http_json(url + '/api/status')
            if status.get('settings') != expected or not isinstance(status.get('events'), list):
                raise RuntimeError('Unexpected status/settings')
            stable = stable + 1 if pid == last_pid else 1
            last_pid = pid
            if stable >= 3:
                return
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
            stable = 0
        time.sleep(2)
    raise RuntimeError('Service failed its HTTP/settings health check.')


def update(project):
    project = project.resolve()
    with open(project / '.webclock-update.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        perform_update(project)


def perform_update(project):
    url, uid, gid = service_url(project)
    venv = project / 'venv'
    if venv.is_symlink() or not (venv / 'bin/python3').is_file():
        raise RuntimeError('Expected a real project-local venv directory.')
    state = project / 'webclock_state'
    settings_file = state / 'settings.json'
    if state.is_symlink() or settings_file.is_symlink():
        raise RuntimeError('Settings directory/file must not be a symlink.')
    if state.exists() and not state.is_dir():
        raise RuntimeError('webclock_state must be a directory.')
    snapshot = http_json(url + '/api/status')['settings']
    if set(snapshot) != {'mode', 'brightness', 'timezone_offset', 'language'}:
        raise RuntimeError('Could not capture current display settings.')
    if settings_file.exists() and json.loads(settings_file.read_text(encoding='utf-8')) != snapshot:
        raise RuntimeError('Saved settings differ from the running service; resolve this before updating.')

    git_prefix, old_head, target = None, None, None
    if (project / '.git').exists():
        owner = pwd.getpwuid((project / '.git').stat().st_uid).pw_name
        git_prefix = (['runuser', '-u', owner, '--'] if owner != 'root' else []) + ['git']
        # Ignore only the updater lock; all user changes must remain untouched.
        dirty = run(git_prefix + ['status', '--porcelain', '--untracked-files=normal'], cwd=project)
        if any(line != '?? .webclock-update.lock' for line in dirty.splitlines()):
            raise RuntimeError('Uncommitted/untracked files found. Commit or move them before updating.')
        old_head = run(git_prefix + ['rev-parse', 'HEAD'], cwd=project)
        run(git_prefix + ['fetch'], cwd=project)
        target = run(git_prefix + ['rev-parse', '@{upstream}'], cwd=project)
        run(git_prefix + ['merge-base', '--is-ancestor', old_head, target], cwd=project)
        for revision in (old_head, target):
            tracked = run(git_prefix + ['ls-tree', '-r', '--name-only', revision], cwd=project).splitlines()
            if any(path in ('.env', 'manual_notes.json', 'venv', 'webclock_state')
                   or path.startswith(('venv/', 'webclock_state/', '.webclock-update')) for path in tracked):
                raise RuntimeError('Git version tracks installation data; refusing to overwrite it.')
    else:
        print('No Git repository: using files already copied here; old source cannot be recovered.', flush=True)

    backup = Path(tempfile.mkdtemp(prefix='.webclock-update-', dir=project))
    print('Backup: ' + str(backup), flush=True)
    run(['cp', '-a', str(venv), str(backup / 'venv')])
    stopped = False
    try:
        snapshot = http_json(url + '/api/status')['settings']
        print('Stopping service and preserving installation data...', flush=True)
        run(['systemctl', 'stop', 'webclock'])
        stopped = True
        for name in ('.env', 'manual_notes.json'):
            if (project / name).exists():
                shutil.copy2(project / name, backup / name)
        if state.exists():
            run(['cp', '-a', str(state), str(backup / 'webclock_state')])
        state.mkdir(mode=0o700, exist_ok=True)
        os.chown(state, uid, gid)
        if settings_file.exists():
            snapshot = json.loads(settings_file.read_text(encoding='utf-8'))
        else:
            settings_file.write_text(json.dumps(snapshot), encoding='utf-8')
            settings_file.chmod(0o600)
        os.chown(settings_file, uid, gid)
        if git_prefix:
            run(git_prefix + ['merge', '--ff-only', target], cwd=project)
        print('Installing and checking Python packages...', flush=True)
        run([str(venv / 'bin/python3'), '-m', 'pip', 'install', '-r', 'requirements.txt'], cwd=project)
        run([str(venv / 'bin/python3'), '-m', 'pip', 'check'], cwd=project)
        run(['systemctl', 'start', 'webclock'])
        print('Checking service health and settings...', flush=True)
        wait_healthy(url, snapshot)
    except BaseException:
        if stopped:
            print('Update failed; restoring the previous environment/version.', flush=True)
            try:
                run(['systemctl', 'stop', 'webclock'])
                if git_prefix:
                    # --keep refuses to discard edits made after the initial clean check.
                    run(git_prefix + ['reset', '--keep', old_head], cwd=project)
                shutil.move(str(venv), str(backup / 'failed-venv'))
                shutil.move(str(backup / 'venv'), str(venv))
                run(['systemctl', 'start', 'webclock'])
                # Older releases kept settings only in memory.
                for attempt in range(15):
                    try:
                        http_json(url + '/api/control', snapshot)
                        break
                    except (OSError, ValueError):
                        time.sleep(2)
                wait_healthy(url, snapshot)
                print('Previous service restored.', flush=True)
            except Exception as rollback_error:
                print('Automatic recovery failed: ' + str(rollback_error), file=sys.stderr)
        print('Backup retained at: ' + str(backup), file=sys.stderr)
        raise
    shutil.rmtree(backup)
    print('Update Complete: service and saved settings verified.', flush=True)


if __name__ == '__main__':
    if os.geteuid() != 0:
        sys.exit('Please run: sudo bash update_clock.sh')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        update(args.project)
    except Exception as error:
        print('Update failed: ' + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout, file=sys.stderr)
            print(error.stderr, file=sys.stderr)
        sys.exit(1)
