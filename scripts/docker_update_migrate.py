"""Move a stopped official Compose installation into a protected host directory."""
import json
import os
from pathlib import Path
import shutil
import sys

try:
    from scripts import docker_update as updates
except ModuleNotFoundError as error:
    if error.name != 'scripts':
        raise
    import docker_update as updates


def migrate(project, destination, source):
    if os.geteuid() != 0:
        raise RuntimeError('Run migration with sudo on the Docker host.')
    project, destination, source = Path(project).resolve(strict=True), Path(destination), Path(source)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise RuntimeError('Choose a new absolute destination, for example /opt/webclock.')
    if any(char.isspace() or char in '%\\"' for char in str(destination)):
        raise RuntimeError('Unsupported installation path.')
    updates.root_owned(destination.parent)
    if project == destination or project in destination.parents or destination in project.parents:
        raise RuntimeError('Source and destination must not overlap.')
    if Path('/etc/webclock-docker-updater.json').exists():
        raise RuntimeError('A Docker worker is already registered. Resolve its configuration before migration.')
    marker = project / '.docker-migration.json'
    updates.regular_path(marker)
    if marker.exists() and json.loads(marker.read_text()).get('step') != 'rolled_back':
        raise RuntimeError('An earlier migration requires review; keep both directories.')
    old, new = updates.DockerUpdater(project), None
    old.lock()
    stopped = started_new = False
    record = {'destination': str(destination), 'step': 'preparing'}
    def save(step):
        record['step'] = step
        updates.atomic_write(marker, (json.dumps(record) + '\n').encode(), 0o600)
    try:
        journal = old.read_journal()
        if journal and journal['step'] not in updates.TERMINAL_STEPS:
            raise RuntimeError('Recover the interrupted update before migrating.')
        pre = old.preflight()
        record.update(source_version=pre['source_version'], source_image_id=pre['source_image_id'])
        files = list(old._data_files())
        size = sum(path.stat().st_size for path in files if path.is_file())
        if shutil.disk_usage(destination.parent).free < size + 100 * 1024 * 1024:
            raise RuntimeError('Insufficient space for a complete copy.')
        for path in (source / 'scripts').rglob('*'):
            updates.regular_path(path)
        save('stopping')
        stopped = True
        old.stop_service()
        fingerprint = old.data_fingerprint()
        destination.mkdir(mode=0o700)
        for name in ('webclock_state', '.webclock-mode-backups-webclock_state', 'manual_notes.json', 'tls', '.env', 'docker-compose.yml'):
            path = project / name
            if path.is_dir():
                shutil.copytree(path, destination / name)
            else:
                shutil.copy2(path, destination / name)
        (destination / '.env').chmod(0o600)
        (destination / 'docker-compose.yml').chmod(0o644)
        (destination / updates.SOCKET_DIR).mkdir(mode=0o700)
        shutil.copytree(source / 'scripts', destination / 'scripts')
        for name in ('docker_update.sh', 'portable_docker_update.sh'):
            entry = source / name
            if name == 'portable_docker_update.sh' and not entry.exists():
                entry = source / 'scripts/update' / name
            shutil.copy2(entry, destination / name)
        (destination / 'VERSION').write_text(pre['source_version'] + '\n')
        new = updates.DockerUpdater(destination)
        new.endpoint = old.endpoint
        new.pin_image(pre['source_image_id'], restart_policy='no')
        config = json.loads(new._compose('config', '--format', 'json').stdout)
        new._validate_mounts([{'Type': row.get('type'), 'Source': row.get('source'), 'Destination': row.get('target'),
                              'RW': not row.get('read_only', False)} for row in config['services']['webclock']['volumes']])
        if new.data_fingerprint() != fingerprint:
            raise RuntimeError('The copied data does not match the stopped installation.')
        old._assert_config()
        save('switching')
        old._run(['rm', pre['container_id']])
        new.preflight(recovery={'config_hash': new._config_hash()})
        started_new = True
        new.start_service()
        new.wait_for_health(pre['source_version'], pre['source_image_id'], pre['deployment_mode'])
        new.restore_restart_policy(pre['source_image_id'], pre['restart_policy'])
        save('migrated')
        return str(destination)
    except Exception:
        if stopped:
            try:
                if started_new:
                    new.stop_service()
                    if new.data_fingerprint() != fingerprint:
                        raise RuntimeError('New location has data changes; keep it stopped for recovery.')
                    info = new._container(running=False, allow_missing=True)
                    if info:
                        new._run(['rm', info['Id']])
                old.pin_image(pre['source_image_id'], restart_policy='no')
                old.start_service()
                old.wait_for_health(pre['source_version'], pre['source_image_id'], pre['deployment_mode'])
                old.restore_restart_policy(pre['source_image_id'], pre['restart_policy'])
                save('rolled_back')
            except Exception:
                try:
                    old.stop_service()
                except Exception:
                    pass
                save('manual_recovery')
        raise
    finally:
        old.unlock()


if __name__ == '__main__':
    try:
        print(migrate(sys.argv[1], sys.argv[2], Path(__file__).resolve().parents[1]))
    except Exception as error:
        print('Migration stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
