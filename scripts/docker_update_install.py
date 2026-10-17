"""Explicit opt-in installation of the root-owned Docker update worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

try:
    from scripts import docker_update, update_settings
except ModuleNotFoundError as error:
    if error.name != 'scripts':
        raise
    import docker_update
    import update_settings

RUNTIME = Path('/usr/local/lib/webclock-docker-updater')
CONFIG = Path('/etc/webclock-docker-updater.json')
UNIT = Path('/etc/systemd/system/webclock-docker-updater.service')


def wait_until_ready(socket_path, project, version):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            state = update_settings.request(socket_path, {'action': 'status'}, timeout=0.25)
        except (OSError, ValueError, RuntimeError):
            time.sleep(0.25)
            continue
        if (state.get('update_provider') != 'docker' or state.get('worker_version') != version
                or state.get('project_path') != str(project) or not state.get('supported')):
            raise RuntimeError('Worker identity does not match this installation.')
        return
    raise RuntimeError('Worker control socket did not become ready within 10 seconds.')


def enable(project, source=None):
    if os.geteuid() != 0:
        raise RuntimeError('Run this command as root on the Docker host.')
    project = Path(project).resolve(strict=True)
    source = Path(source).resolve(strict=True) if source else project
    version = (source / 'VERSION').read_text().strip()
    docker_update.release_versions.release_version(version)
    payload = {'VERSION': (version + '\n').encode()}
    for name in ('updater_service.py', 'docker_update.py', 'release_versions.py', 'update_clock.py', 'update_settings.py'):
        path = source / 'scripts' / name
        docker_update.regular_path(path)
        payload[name] = path.read_bytes()
    docker_update.root_owned(project)
    for name in ('docker-compose.yml', '.env'):
        docker_update.root_owned(project / name)
    if any(char.isspace() or char in '%\\"' for char in str(project)):
        raise RuntimeError('Unsupported installation path.')
    for target in (RUNTIME, CONFIG, UNIT):
        docker_update.regular_path(target)
        docker_update.root_owned(target if target.exists() else target.parent)
    previous = json.loads(CONFIG.read_text()) if CONFIG.exists() else None
    if previous and (previous.get('project') != str(project) or previous.get('kind') != 'docker'):
        raise RuntimeError('Another Docker installation is already registered.')
    updater = docker_update.DockerUpdater(project)
    journal = updater.read_journal()
    if journal and journal['step'] not in docker_update.TERMINAL_STEPS:
        raise RuntimeError('Resolve the interrupted transaction before enabling updates.')
    updater.lock()
    was_active = False
    service_changed = False
    previous_files = {}
    previous_metadata = {}
    try:
        pre = updater.preflight()
        if pre['source_version'] != version:
            raise RuntimeError('Worker release must match the running image. Upgrade the application first.')
        if previous and subprocess.run(['systemctl', 'is-active', '--quiet', 'webclock-docker-updater'],
                                       check=False).returncode == 0:
            # The transaction lock proves no image update is in progress before stopping the old worker.
            subprocess.run(['systemctl', 'stop', 'webclock-docker-updater'], check=True)
            was_active = True
        socket_dir = project / docker_update.SOCKET_DIR
        docker_update.regular_path(socket_dir)
        if socket_dir.exists():
            docker_update.root_owned(socket_dir)
        socket_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(socket_dir, 0o700)
        for path in (CONFIG, UNIT, socket_dir / 'configured'):
            docker_update.regular_path(path)
            previous_metadata[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        original = updater.compose_file.read_bytes()
        if '/run/webclock-updater' not in original.decode():
            marker = '    volumes:\n'
            if original.decode().count(marker) != 1:
                raise RuntimeError('Cannot safely add control mount to this Compose layout.')
            updated = original.decode().replace(marker, marker + '      - ./webclock_updater_run:/run/webclock-updater:ro\n')
            docker_update.atomic_write(updater.compose_file, updated.encode())
            updater.expected_config_hash = updater._config_hash()
            try:
                updater.start_service()
                updater.wait_for_health(pre['source_version'], pre['source_image_id'], pre['deployment_mode'])
            except Exception:
                docker_update.atomic_write(updater.compose_file, original)
                updater.expected_config_hash = updater._config_hash()
                updater.start_service()
                updater.wait_for_health(pre['source_version'], pre['source_image_id'], pre['deployment_mode'])
                raise
        RUNTIME.mkdir(mode=0o755, exist_ok=True)
        for name in payload:
            path = RUNTIME / name
            docker_update.regular_path(path)
            previous_files[name] = path.read_bytes() if path.exists() else None
        saved = RUNTIME / 'previous'
        docker_update.regular_path(saved)
        saved.mkdir(mode=0o700, exist_ok=True)
        # Keep one complete prior worker; a failed refresh restores it before restarting.
        for name, content in previous_files.items():
            if content is not None:
                docker_update.atomic_write(saved / name, content, 0o600)
        for name, content in payload.items():
            docker_update.atomic_write(RUNTIME / name, content, 0o644)
        config = previous or {'project': str(project), 'kind': 'docker', 'channel': 'stable', 'auto_update': False}
        config.update(socket_path=str(socket_dir / 'control.sock'),
                      state_path='/var/lib/webclock-docker-updater/state.json')
        docker_update.atomic_write(CONFIG, (json.dumps(config) + '\n').encode(), 0o600)
        unit = '''[Unit]
Description=WebClock Docker release updater
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
User=root
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/bin/python3 -E -s /usr/local/lib/webclock-docker-updater/updater_service.py --config /etc/webclock-docker-updater.json
Restart=always
RestartSec=3
StateDirectory=webclock-docker-updater
StateDirectoryMode=0700
UMask=0077

[Install]
WantedBy=multi-user.target
'''
        docker_update.atomic_write(UNIT, unit.encode(), 0o644)
        docker_update.atomic_write(socket_dir / 'configured', b'docker\n', 0o600)
        service_changed = True
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'webclock-docker-updater'], check=True)
        subprocess.run(['systemctl', 'restart', 'webclock-docker-updater'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'webclock-docker-updater'], check=True)
        wait_until_ready(socket_dir / 'control.sock', project, version)
    except Exception:
        if service_changed:
            subprocess.run(['systemctl', 'stop', 'webclock-docker-updater'], check=True)
            if previous is None:
                subprocess.run(['systemctl', 'disable', 'webclock-docker-updater'], check=False)
        for name, content in previous_files.items():
            if content is None:
                (RUNTIME / name).unlink(missing_ok=True)
            else:
                docker_update.atomic_write(RUNTIME / name, content, 0o644)
        for path, snapshot in previous_metadata.items():
            if snapshot is None:
                path.unlink(missing_ok=True)
            else:
                docker_update.atomic_write(path, snapshot[0], snapshot[1])
        if service_changed:
            subprocess.run(['systemctl', 'daemon-reload'], check=True)
        if was_active:
            subprocess.run(['systemctl', 'restart', 'webclock-docker-updater'], check=True)
        raise
    finally:
        updater.unlock()
    print('Docker update worker enabled. Automatic installation is off by default; existing preferences are retained.')


if __name__ == '__main__':
    try:
        enable(sys.argv[1], source=Path(__file__).resolve().parents[1])
    except Exception as error:
        detail = str(error) if type(error) is RuntimeError else getattr(error, 'code', type(error).__name__)
        print('Could not enable Docker updates: ' + detail, file=sys.stderr)
        sys.exit(1)
