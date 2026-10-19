#!/usr/bin/env python3
"""Update one local, official Compose installation without restoring live data."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

try:
    from scripts import release_versions, update_clock
except ModuleNotFoundError as error:
    if error.name != 'scripts':
        raise
    import release_versions
    import update_clock

REPOSITORY = 'ghcr.io/kcayut/webclock'
IMAGE_ID = re.compile(r'sha256:[a-f0-9]{64}')
TERMINAL_STEPS = {'completed', 'rolled_back', 'failed_before_stop'}
MOUNTS = {
    '/app/manual_notes.json': ('manual_notes.json', False),
    '/app/webclock_state': ('webclock_state', True),
    '/app/.webclock-mode-backups-webclock_state': ('.webclock-mode-backups-webclock_state', True),
    '/app/tls': ('tls', False),
}
SOCKET_DIR = 'webclock_updater_run'


class DockerUpdateError(RuntimeError):
    def __init__(self, message, *, code='update_failed', rollback_succeeded=None):
        super().__init__(message)
        self.code = code
        self.rollback_succeeded = rollback_succeeded


def regular_path(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise DockerUpdateError('Symlink in updater path.', code='unsafe_path')
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise DockerUpdateError('Unsupported file type.', code='unsafe_path')


def root_owned(path):
    regular_path(path)
    for part in (path, *path.parents):
        info = part.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise DockerUpdateError('Background updates require root-owned installation parents.', code='unsafe_owner')


def atomic_write(path, content, mode=None):
    regular_path(path)
    old = path.stat() if path.exists() else None
    fd, name = tempfile.mkstemp(prefix='.docker-update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), mode if mode is not None else (stat.S_IMODE(old.st_mode) if old else 0o600))
            if old and os.geteuid() == 0:
                os.fchown(output.fileno(), old.st_uid, old.st_gid)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def parse_env_file(path):
    regular_path(path)
    lines = path.read_text().splitlines() if path.exists() else []
    values = {}
    for line in lines:
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$', line)
        if match:
            values[match[1]] = match[2]
    return lines, values


def versioned_env(content, version):
    release_versions.release_version(version)
    lines = content.decode().splitlines()
    found = False
    for index, line in enumerate(lines):
        match = re.match(r'^(\s*(?:export\s+)?WEBCLOCK_VERSION\s*=\s*)(.*?)(\s+#.*)?$', line)
        if match:
            lines[index] = match[1] + version + (match[3] or '')
            found = True
    if not found:
        lines.append('WEBCLOCK_VERSION=' + version)
    return ('\n'.join(lines) + '\n').encode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Health checks must not redirect.')


class DockerUpdater:
    def __init__(self, project_dir, *, runner=None):
        self.project = Path(project_dir).resolve(strict=True)
        self.compose_file = self.project / 'docker-compose.yml'
        self.env_file = self.project / '.env'
        self.lock_file = self.project / '.docker-update.lock'
        self.journal_file = self.project / '.docker-update-journal.json'
        self.backup_dir = self.project / '.docker-update-backups'
        self.runner = runner or self._default_runner
        self._lock_fd = None
        self.compose_name = None
        self.endpoint = None
        self.health_url = None
        self.tls_handler = None
        self.expected_config_hash = None

    @staticmethod
    def _default_runner(cmd, **kwargs):
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              timeout=300, **kwargs)

    def _run(self, args, *, check=True):
        # Do not let a shell or .env select another Docker context/project.
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('COMPOSE_', 'DOCKER_'))}
        _, variables = parse_env_file(self.env_file)
        for key in variables:
            environment.pop(key, None)
        prefix = ['docker'] + (['--host', self.endpoint] if self.endpoint else [])
        return self.runner(prefix + list(args), cwd=self.project, env=environment, check=check)

    def _compose(self, *args, check=True):
        if args and args[0] in ('stop', 'up'):
            self._assert_config()
        fixed = ['compose', '--project-directory', str(self.project), '--env-file', str(self.env_file),
                 '-f', str(self.compose_file)]
        if self.compose_name:
            fixed += ['--project-name', self.compose_name]
        return self._run(fixed + list(args), check=check)

    def lock(self):
        regular_path(self.lock_file)
        self._lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise DockerUpdateError('Another update is active.', code='update_busy') from error

    def unlock(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def read_journal(self):
        regular_path(self.journal_file)
        if not self.journal_file.exists():
            return None
        try:
            data = json.loads(self.journal_file.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('step'), str):
                raise ValueError()
            return data
        except (OSError, ValueError) as error:
            raise DockerUpdateError('Unreadable journal; inspect before retrying.', code='manual_recovery',
                                    rollback_succeeded=False) from error

    def write_journal(self, data):
        atomic_write(self.journal_file, (json.dumps(data, indent=2) + '\n').encode(), 0o600)
        operation = data.get('op_id', '')
        if data.get('step') in ('completed', 'rolled_back') and re.fullmatch(r'up-[a-f0-9]{32}', operation):
            backup = self.backup_dir / operation
            regular_path(backup)
            if backup.is_dir():
                try:
                    atomic_write(backup / 'transaction.json', (json.dumps(data) + '\n').encode(), 0o600)
                except OSError:
                    pass  # No cleanup marker means this backup stays retained.

    def _container(self, running=True, allow_missing=False):
        ids = self._compose('ps', '--all', '--quiet', 'webclock').stdout.split()
        if not ids and allow_missing:
            return None
        if len(ids) != 1:
            raise DockerUpdateError('Expected exactly one Compose container.', code='invalid_service')
        info = json.loads(self._run(['inspect', ids[0]]).stdout)[0]
        labels = info.get('Config', {}).get('Labels') or {}
        if (labels.get('com.docker.compose.project') != self.compose_name
                or labels.get('com.docker.compose.service') != 'webclock'
                or labels.get('com.docker.compose.project.working_dir') != str(self.project)
                or labels.get('com.docker.compose.project.config_files') != str(self.compose_file)):
            raise DockerUpdateError('Container belongs to another installation.', code='wrong_installation')
        state = info.get('State', {})
        if running and (not state.get('Running') or state.get('Restarting')):
            raise DockerUpdateError('Service is not running normally.', code='container_stopped')
        return info

    def _image(self, reference, version):
        image = json.loads(self._run(['image', 'inspect', reference]).stdout)[0]
        labels = image.get('Config', {}).get('Labels') or {}
        if (not IMAGE_ID.fullmatch(image.get('Id', '')) or image.get('Os') != 'linux'
                or image.get('Architecture') not in ('amd64', 'arm64')
                or labels.get('org.opencontainers.image.version') != version
                or labels.get('org.opencontainers.image.source') != 'https://github.com/kcayut/webclock'):
            raise DockerUpdateError('Image identity/version/architecture mismatch.', code='invalid_image')
        return image

    def _validate_mounts(self, mounts):
        expected = {target: (str(self.project / name), writable) for target, (name, writable) in MOUNTS.items()}
        if '/run/webclock-updater' in {item.get('Destination') for item in mounts}:
            expected['/run/webclock-updater'] = (str(self.project / SOCKET_DIR), False)
        actual = {item['Destination']: (item.get('Source'), item.get('RW')) for item in mounts
                  if item.get('Type') == 'bind'}
        if actual != expected or len(mounts) != len(expected):
            raise DockerUpdateError('Unsupported persistent mounts.', code='unsupported_mounts')
        for source, _ in expected.values():
            regular_path(Path(source))
            if not Path(source).exists():
                raise DockerUpdateError('Missing mounted file/directory.', code='missing_mount')

    def _only_writer(self, container_id):
        ids = self._run(['ps', '--all', '--quiet']).stdout.split()
        if not ids:
            return
        for info in json.loads(self._run(['inspect', *ids]).stdout):
            if info['Id'] == container_id:
                continue
            for mount in info.get('Mounts', []):
                if not mount.get('RW') or mount.get('Type') != 'bind':
                    continue
                source = Path(mount['Source']).resolve()
                for name, writable in MOUNTS.values():
                    data = self.project / name
                    if writable and (source == data or source in data.parents or data in source.parents):
                        raise DockerUpdateError('Another container can write WebClock data.', code='shared_data')

    def preflight(self, recovery=None):
        migration = self.project / '.docker-migration.json'
        regular_path(migration)
        if migration.exists() and json.loads(migration.read_text()).get('step') != 'rolled_back':
            raise DockerUpdateError('Use the migrated installation or review migration recovery.', code='migration_pending')
        for path in (self.compose_file, self.env_file, self.backup_dir, self.journal_file):
            regular_path(path)
        if not self.compose_file.is_file() or not self.env_file.is_file():
            raise DockerUpdateError('Missing Compose or .env file.', code='invalid_compose')
        for name in ('compose.yml', 'compose.yaml', 'compose.override.yml', 'compose.override.yaml',
                     'docker-compose.override.yml', 'docker-compose.override.yaml'):
            if (self.project / name).exists():
                raise DockerUpdateError('Custom Compose overrides need manual review.', code='unsupported_compose')
        context = json.loads(self._run(['context', 'inspect', 'default']).stdout)[0]
        endpoint = context['Endpoints']['docker']['Host']
        if endpoint != 'unix:///var/run/docker.sock':
            raise DockerUpdateError('Only the local system Docker daemon is supported.', code='unsupported_daemon')
        self.endpoint = endpoint
        security = json.loads(self._run(['info', '--format', '{{json .SecurityOptions}}']).stdout)
        if any('rootless' in option or 'userns' in option for option in security or []):
            raise DockerUpdateError('Rootless/user namespace remapping is not supported.', code='unsupported_daemon')
        config = json.loads(self._compose('config', '--format', 'json').stdout)
        self.compose_name = config.get('name')
        if not isinstance(self.compose_name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', self.compose_name):
            raise DockerUpdateError('Invalid Compose project identity.', code='invalid_project')
        if set(config.get('services', {})) != {'webclock'} or set(config) - {'name', 'services', 'networks'}:
            raise DockerUpdateError('Only the official single-service Compose layout is supported.', code='unsupported_compose')
        service = config['services']['webclock']
        restart_policy = service.get('restart', 'no')
        if not isinstance(restart_policy, str) or not re.fullmatch(r'no|always|unless-stopped|on-failure(?::[1-9][0-9]*)?', restart_policy):
            raise DockerUpdateError('Unsupported restart policy.', code='unsupported_compose')
        allowed = {'image', 'build', 'container_name', 'restart', 'ports', 'volumes', 'environment', 'networks',
                   'command', 'entrypoint'}
        # Compose renders absent image-command overrides as explicit JSON nulls.
        if set(service) - allowed or any(service.get(key) is not None for key in ('command', 'entrypoint')):
            raise DockerUpdateError('Custom commands or privileges are unsupported.', code='unsupported_compose')
        reference = service.get('image', '')
        if not (reference.startswith(REPOSITORY + ':') or reference.startswith(REPOSITORY + '@sha256:')
                or IMAGE_ID.fullmatch(reference)):
            raise DockerUpdateError('Not an official WebClock image.', code='invalid_image')
        if service.get('networks', {}) not in ({}, {'default': None}, {'default': {}}):
            raise DockerUpdateError('Custom networks are unsupported.', code='unsupported_compose')
        info = self._container(running=not recovery, allow_missing=bool(recovery))
        if info:
            self._validate_mounts(info.get('Mounts', []))
        self._validate_mounts([{'Type': item.get('type'), 'Source': item.get('source'),
                               'Destination': item.get('target'), 'RW': not item.get('read_only', False)}
                              for item in service.get('volumes', [])])
        configured_env = service.get('environment', {})
        actual_env = (configured_env if recovery else
                      dict(entry.split('=', 1) for entry in info['Config'].get('Env', []) if '=' in entry))
        if not recovery and any(actual_env.get(key) != value for key, value in configured_env.items()):
            raise DockerUpdateError('Compose environment differs from running service.', code='configuration_changed')
        if (configured_env.get('WEBCLOCK_STATE_DIR', 'webclock_state') not in ('webclock_state', '/app/webclock_state')
                or configured_env.get('NOTES_FILE') != '/app/webclock_state/manual_notes.json'):
            raise DockerUpdateError('Custom state paths are unsupported.', code='unsupported_mounts')
        bindings = info.get('NetworkSettings', {}).get('Ports', {}).get('5000/tcp') or [] if info else []
        ports = service.get('ports', [])
        if len(ports) != 1 or ports[0].get('target') != 5000 or (not recovery and not bindings):
            raise DockerUpdateError('Unsupported service port mapping.', code='unsupported_ports')
        port = str(ports[0].get('published', ''))
        if not port.isdigit() or not 0 < int(port) < 65536:
            raise DockerUpdateError('Invalid host port.', code='unsupported_ports')
        if (ports[0].get('host_ip', '0.0.0.0') not in ('0.0.0.0', '127.0.0.1', '') or
                (not recovery and not any(b.get('HostPort') == port and b.get('HostIp') in ('0.0.0.0', '127.0.0.1', '') for b in bindings))):
            raise DockerUpdateError('Health endpoint is not local.', code='unsupported_ports')
        tls = bool(actual_env.get('WEBCLOCK_TLS_CERT'))
        if tls != bool(actual_env.get('WEBCLOCK_TLS_KEY')):
            raise DockerUpdateError('Incomplete TLS configuration.', code='invalid_tls')
        tls_config = dict(actual_env)
        ca = tls_config.get('WEBCLOCK_UPDATE_CA')
        if ca:
            if not ca.startswith('/app/tls/') or '..' in Path(ca).parts:
                raise DockerUpdateError('Docker update CA must be under /app/tls.', code='invalid_tls')
            tls_config['WEBCLOCK_UPDATE_CA'] = str(self.project / 'tls' / ca.removeprefix('/app/tls/'))
            regular_path(Path(tls_config['WEBCLOCK_UPDATE_CA']))
        self.tls_handler = update_clock.update_tls_handler(self.project, tls_config)
        self.health_url = ('https' if tls else 'http') + '://127.0.0.1:' + port + '/api/health'
        if recovery:
            allowed_hashes = [recovery.get('config_hash'), recovery.get('applied_config_hash')]
            allowed_hashes.extend(recovery.get('transition_config_hashes', []))
            if self._config_hash() not in allowed_hashes:
                raise DockerUpdateError('Configuration changed since the transaction.', code='configuration_changed')
            self._only_writer(info['Id'] if info else None)
            self.expected_config_hash = self._config_hash()
            return {'reference': reference, 'container_id': info['Id'] if info else None,
                    'restart_policy': restart_policy}
        health = self._check_health()
        if not health or health.get('status') != 'ok' or health.get('deployment_mode') not in ('self', 'managed'):
            raise DockerUpdateError('Source service is not healthy.', code='unhealthy_source')
        version = health.get('version')
        release_versions.release_version(version)
        if health['deployment_mode'] == 'managed' and not tls:
            raise DockerUpdateError('Managed updates require verified HTTPS.', code='invalid_tls')
        source = self._image(info['Image'], version)
        selected = self._image(reference, version)
        if source['Id'] != selected['Id']:
            raise DockerUpdateError('Configured image is not running.', code='configuration_changed')
        self._only_writer(info['Id'])
        self.expected_config_hash = self._config_hash()
        return {'source_version': version, 'source_image_id': source['Id'], 'architecture': source['Architecture'],
                'container_id': info['Id'], 'deployment_mode': health['deployment_mode'],
                'config_hash': self._config_hash(), 'restart_policy': restart_policy}

    def _config_hash(self):
        return hashlib.sha256(self.compose_file.read_bytes() + b'\0' + self.env_file.read_bytes()).hexdigest()

    def _assert_config(self):
        if self.expected_config_hash is not None and self._config_hash() != self.expected_config_hash:
            raise DockerUpdateError('Installation configuration changed concurrently.', code='configuration_changed')

    def _check_health(self, timeout=2):
        handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
        if self.tls_handler:
            handlers.append(self.tls_handler)
        try:
            with urllib.request.build_opener(*handlers).open(self.health_url, timeout=timeout) as response:
                data = json.loads(response.read(65537))
                return data if isinstance(data, dict) and response.status == 200 else None
        except (OSError, ValueError, RuntimeError):
            return None

    def pull_image(self, version, architecture):
        self._run(['pull', '--platform', 'linux/' + architecture, REPOSITORY + ':' + version])
        image = self._image(REPOSITORY + ':' + version, version)
        if image['Architecture'] != architecture:
            raise DockerUpdateError('Target architecture differs.', code='invalid_image')
        return image['Id']

    def _data_files(self):
        for name in ('webclock_state', '.webclock-mode-backups-webclock_state', 'manual_notes.json', 'tls'):
            root = self.project / name
            regular_path(root)
            if not root.exists():
                raise DockerUpdateError('Persistent data disappeared.', code='missing_mount')
            yield root
            if root.is_dir():
                for child in root.rglob('*'):
                    regular_path(child)
                    yield child

    def data_fingerprint(self):
        entries = {}
        for path in self._data_files():
            if path.is_file():
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                entries[str(path.relative_to(self.project))] = digest.hexdigest()
            else:
                entries[str(path.relative_to(self.project)) + '/'] = ''
        return entries

    def backup(self, operation):
        self._assert_config()
        fingerprint = self.data_fingerprint()
        paths = list(self._data_files())
        size = sum(path.stat().st_size for path in paths if path.is_file())
        if shutil.disk_usage(self.project).free < size + 100 * 1024 * 1024:
            raise DockerUpdateError('Insufficient space for cold backup.', code='disk_full')
        self.backup_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.backup_dir, 0o700)
        target = self.backup_dir / operation
        target.mkdir(mode=0o700)
        for name in ('webclock_state', '.webclock-mode-backups-webclock_state', 'manual_notes.json',
                     'tls', '.env', 'docker-compose.yml'):
            source = self.project / name
            if source.is_dir():
                shutil.copytree(source, target / name)
            else:
                shutil.copy2(source, target / name)
        self._assert_config()
        copied = DockerUpdater(target)
        if (copied.data_fingerprint() != fingerprint or self.data_fingerprint() != fingerprint
                or copied._config_hash() != self._config_hash()):
            raise DockerUpdateError('Data changed or backup copy failed verification.', code='backup_mismatch')
        atomic_write(target / 'data-manifest.json', json.dumps(fingerprint, sort_keys=True).encode(), 0o600)
        for path in target.rglob('*'):
            if path.is_file():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
        for directory in sorted((path for path in target.rglob('*') if path.is_dir()),
                                key=lambda path: len(path.parts), reverse=True) + [target, self.backup_dir]:
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return target, fingerprint

    def stop_service(self):
        self._assert_config()
        info = self._container(running=False, allow_missing=True)
        if info:
            # A stopped failed image must stay stopped across daemon/host restarts.
            self._run(['update', '--restart=no', info['Id']])
        self._compose('stop', '--timeout', '30', 'webclock')
        info = self._container(running=False, allow_missing=True)
        if info and info.get('State', {}).get('Running'):
            raise DockerUpdateError('Container did not stop.', code='stop_failed')
        self._only_writer(info['Id'] if info else None)

    def image_config(self, image_id, restart_policy=None):
        self._assert_config()
        if not IMAGE_ID.fullmatch(image_id):
            raise DockerUpdateError('Invalid immutable image ID.', code='invalid_image')
        content, count = re.subn(r'(?m)^(\s+image:)\s*[^\n]+$', r'\g<1> ' + image_id,
                                 self.compose_file.read_text())
        if count != 1:
            raise DockerUpdateError('Ambiguous Compose image.', code='invalid_compose')
        if restart_policy is not None:
            if not re.fullmatch(r'no|always|unless-stopped|on-failure(?::[1-9][0-9]*)?', restart_policy):
                raise DockerUpdateError('Invalid restart policy.', code='unsupported_compose')
            content, count = re.subn(r'(?m)^(\s+restart:)\s*[^\n]+$',
                                     lambda match: match[1] + ' ' + json.dumps(restart_policy), content)
            if count > 1:
                raise DockerUpdateError('Ambiguous restart policy.', code='invalid_compose')
            if not count:
                content = re.sub(r'(?m)^( +)image:([^\n]+)$',
                                 lambda match: match[0] + '\n' + match[1] + 'restart: ' + json.dumps(restart_policy), content)
        return content.encode()

    def pin_image(self, image_id, restart_policy=None):
        atomic_write(self.compose_file, self.image_config(image_id, restart_policy))
        self.expected_config_hash = self._config_hash()

    def apply_config(self, journal, image_id, environment, restart_policy='no'):
        compose = self.image_config(image_id, restart_policy)
        old_env = self.env_file.read_bytes()
        hashes = [self._config_hash(), hashlib.sha256(compose + b'\0' + old_env).hexdigest(),
                  hashlib.sha256(compose + b'\0' + environment).hexdigest()]
        journal.update(transition_config_hashes=hashes, applied_config_hash=hashes[-1])
        # Persist every reachable intermediate state before replacing either file.
        self.write_journal(journal)
        self._assert_config()
        atomic_write(self.compose_file, compose)
        self.expected_config_hash = hashes[1]
        self._assert_config()
        atomic_write(self.env_file, environment)
        self.expected_config_hash = hashes[2]

    def restore_restart_policy(self, image_id, policy, journal=None):
        if journal is not None:
            self.apply_config(journal, image_id, self.env_file.read_bytes(), policy)
        else:
            self.pin_image(image_id, restart_policy=policy)
        info = self._container()
        self._run(['update', '--restart=' + policy, info['Id']])

    def start_service(self):
        self._compose('up', '-d', '--no-build', '--no-deps', '--pull', 'never', 'webclock')

    def wait_for_health(self, version, image_id, mode, timeout=45):
        deadline = time.monotonic() + timeout
        consecutive = 0
        while time.monotonic() < deadline:
            health = self._check_health()
            if health and health.get('status') == 'ok':
                info = self._container()
                if (health.get('version') != version or health.get('deployment_mode') != mode
                        or info.get('Image') != image_id or info.get('RestartCount', 0)):
                    raise DockerUpdateError('Running identity or health mismatch.', code='health_mismatch')
                self._validate_mounts(info.get('Mounts', []))
                consecutive += 1
                if consecutive >= 3:
                    return
            else:
                consecutive = 0
            time.sleep(1)
        raise DockerUpdateError('Health check timed out.', code='health_timeout')

    def update(self, channel='stable', expected_version=None, progress=None):
        def notify(phase):
            if progress:
                try:
                    progress(phase)
                except Exception:
                    pass  # Observers must not interrupt recovery.

        self.lock()
        journal = None
        stop_attempted = replacement_attempted = False
        fingerprint = None
        try:
            old = self.read_journal()
            if old and old['step'] not in TERMINAL_STEPS:
                raise DockerUpdateError('Previous update needs inspection; journal retained.',
                                        code='manual_recovery', rollback_succeeded=False)
            notify('checking')
            pre = self.preflight()
            release = release_versions.discover_release(channel, pre['source_version'])
            target = release.get('latest_version')
            if expected_version is not None and target != expected_version:
                raise DockerUpdateError('Release changed; check again.', code='release_changed')
            if not release.get('update_available'):
                return 'up_to_date'
            precedence = release_versions.release_version(target)
            if precedence <= release_versions.release_version(pre['source_version']):
                raise DockerUpdateError('Downgrades are unsupported.', code='invalid_version')
            if channel == 'stable' and (not precedence[3] or release.get('prerelease')):
                raise DockerUpdateError('Stable cannot install prereleases.', code='invalid_version')
            operation = 'up-' + uuid.uuid4().hex
            journal = dict(pre, op_id=operation, step='preparing', target_version=target,
                           started_at=time.time(), channel=channel)
            self.write_journal(journal)
            notify('downloading')
            target_id = self.pull_image(target, pre['architecture'])
            journal.update(target_image_id=target_id, step='prepared')
            self.write_journal(journal)
            if self._config_hash() != pre['config_hash']:
                raise DockerUpdateError('Installation changed during download.', code='configuration_changed')
            original_env = self.env_file.read_bytes()
            journal['step'] = 'stopping'
            self.write_journal(journal)
            stop_attempted = True
            self.stop_service()
            notify('backing_up')
            backup_path, fingerprint = self.backup(operation)
            journal.update(step='backed_up', backup_path=str(backup_path))
            self.write_journal(journal)
            notify('installing')
            journal['step'] = 'starting'
            self.apply_config(journal, target_id, versioned_env(original_env, target))
            replacement_attempted = True
            notify('restarting')
            self.start_service()
            notify('health_check')
            self.wait_for_health(target, target_id, pre['deployment_mode'])
            self.restore_restart_policy(target_id, pre['restart_policy'], journal)
            journal['step'] = 'completed'
            self.write_journal(journal)
            return 'updated'
        except Exception as error:
            if journal is None:
                raise
            recovered = None
            if stop_attempted:
                notify('rolling_back')
                recovered = False
                try:
                    self.stop_service()
                    # No migration contract: changed data may include new writes or revocations.
                    # Never restore old state or let an older image silently reinterpret it.
                    if replacement_attempted and (fingerprint is None or self.data_fingerprint() != fingerprint):
                        raise DockerUpdateError('New version changed data.', code='manual_recovery')
                    unchanged = not replacement_attempted and self._config_hash() == pre['config_hash']
                    if not unchanged:
                        self.apply_config(journal, pre['source_image_id'], original_env)
                    self.start_service()
                    self.wait_for_health(pre['source_version'], pre['source_image_id'], pre['deployment_mode'])
                    if not unchanged:
                        self.restore_restart_policy(pre['source_image_id'], pre['restart_policy'], journal)
                    else:
                        # Compose may only restart the existing container, retaining --restart=no.
                        self._run(['update', '--restart=' + pre['restart_policy'], self._container()['Id']])
                    recovered = True
                except Exception:
                    try:
                        self.stop_service()
                    except Exception:
                        pass
            journal.update(step='rolled_back' if recovered else ('manual_recovery' if stop_attempted else 'failed_before_stop'),
                           error=getattr(error, 'code', 'update_failed'))
            try:
                self.write_journal(journal)
            except OSError:
                pass  # Last durable non-terminal stage blocks further automatic attempts.
            raise DockerUpdateError('Update failed; ' + journal['step'] + '.', code=journal['step'],
                                    rollback_succeeded=recovered) from error
        finally:
            self.unlock()

    def diagnose(self):
        journal = self.read_journal()
        total = 0
        regular_path(self.backup_dir)
        if self.backup_dir.exists():
            for path in self.backup_dir.rglob('*'):
                regular_path(path)
                if path.is_file():
                    total += path.stat().st_size
        return {'transaction': journal, 'backup_bytes': total,
                'free_bytes': shutil.disk_usage(self.project).free,
                'recovery_command': 'Use --recover current|previous --operation OP_ID --yes; data is never restored.'}

    def recover(self, choice, operation, *, confirmed=False):
        if not confirmed or choice not in ('current', 'previous'):
            raise DockerUpdateError('Explicit recovery confirmation is required.', code='confirmation_required')
        self.lock()
        try:
            journal = self.read_journal()
            if (not journal or journal.get('op_id') != operation or
                    not re.fullmatch(r'up-[a-f0-9]{32}', operation or '') or journal['step'] in TERMINAL_STEPS):
                raise DockerUpdateError('Transaction changed or does not need recovery.', code='invalid_operation')
            observed = self.preflight(recovery=journal)
            journal.setdefault('restart_policy', observed['restart_policy'])
            original = dict(journal)
            if choice == 'previous':
                version, image_id = journal['source_version'], journal['source_image_id']
            else:
                candidates = [(journal['source_version'], journal['source_image_id'])]
                if journal.get('target_image_id'):
                    candidates.append((journal['target_version'], journal['target_image_id']))
                for version, image_id in candidates:
                    try:
                        if self._image(observed['reference'], version)['Id'] == image_id:
                            break
                    except DockerUpdateError:
                        continue
                else:
                    raise DockerUpdateError('Configured image is not part of this transaction.', code='invalid_image')
            require_unchanged = choice == 'previous' or (image_id == journal['source_image_id'] and
                journal['step'] not in ('preparing', 'prepared', 'stopping', 'backed_up'))
            if require_unchanged:
                manifest = self.backup_dir / operation / 'data-manifest.json'
                regular_path(manifest)
                fingerprint = json.loads(manifest.read_text())
                if self.data_fingerprint() != fingerprint:
                    raise DockerUpdateError('Data changed; old image recovery is unsafe.', code='manual_recovery')
            self._image(image_id, version)
            archive = self.project / '.docker-update-history'
            regular_path(archive)
            archive.mkdir(mode=0o700, exist_ok=True)
            atomic_write(archive / (operation + '.json'), (json.dumps(original) + '\n').encode(), 0o600)
            journal.update(step='recovering', recovery_version=version)
            self.write_journal(journal)
            try:
                self.stop_service()
                if require_unchanged and self.data_fingerprint() != fingerprint:
                    raise DockerUpdateError('Data changed before stop.', code='manual_recovery')
                self.apply_config(journal, image_id, versioned_env(self.env_file.read_bytes(), version))
                self.start_service()
                self.wait_for_health(version, image_id, journal['deployment_mode'])
                self.restore_restart_policy(image_id, journal['restart_policy'], journal)
            except Exception:
                self.stop_service()
                journal['step'] = 'manual_recovery'
                self.write_journal(journal)
                raise
            journal.update(step='rolled_back' if image_id == journal['source_image_id'] else 'completed',
                           recovered_at=time.time())
            self.write_journal(journal)
            return journal['step']
        finally:
            self.unlock()

    def prune_backups(self, keep, *, confirmed=False):
        if type(keep) is not int or keep < 1:
            raise DockerUpdateError('Keep at least one recovery point.', code='invalid_retention')
        self.lock()
        try:
            journal = self.read_journal()
            if journal and journal['step'] not in TERMINAL_STEPS:
                raise DockerUpdateError('Resolve the active transaction first.', code='manual_recovery')
            regular_path(self.backup_dir)
            candidates = []
            if self.backup_dir.exists():
                for path in self.backup_dir.iterdir():
                    regular_path(path)
                    if not path.is_dir() or not re.fullmatch(r'up-[a-f0-9]{32}', path.name):
                        continue
                    marker = path / 'transaction.json'
                    regular_path(marker)
                    if not marker.is_file():
                        continue  # Legacy/unresolved backups are never deleted automatically.
                    record = json.loads(marker.read_text())
                    if record.get('op_id') != path.name or record.get('step') not in ('completed', 'rolled_back'):
                        continue
                    candidates.append(path)
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            remove = [p for p in candidates[keep:] if not journal or p.name != journal.get('op_id')]
            for path in remove:
                for child in path.rglob('*'):
                    regular_path(child)
            if confirmed:
                for path in remove:
                    shutil.rmtree(path)
            return {'remove': [p.name for p in remove], 'applied': confirmed, 'keep': keep}
        finally:
            self.unlock()


def update(project, channel='stable', expected_version=None, progress=None):
    return DockerUpdater(project).update(channel, expected_version, progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='.')
    parser.add_argument('--channel', choices=['stable', 'beta'], default='stable')
    parser.add_argument('--version', help='Confirm the currently offered release; never downgrade')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true')
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--diagnose', action='store_true')
    actions.add_argument('--recover', choices=['current', 'previous'])
    actions.add_argument('--prune-backups', type=int, metavar='KEEP', help='Preview old resolved backups to remove; keep at least one')
    parser.add_argument('--operation', help='Transaction ID from --diagnose')
    parser.add_argument('--yes', action='store_true', help='Confirm recovery or backup cleanup')
    args = parser.parse_args()
    updater = DockerUpdater(args.project)
    try:
        if args.recover:
            print(updater.recover(args.recover, args.operation, confirmed=args.yes))
        elif args.prune_backups is not None:
            print(json.dumps(updater.prune_backups(args.prune_backups, confirmed=args.yes), indent=2))
        elif args.diagnose:
            print(json.dumps(updater.diagnose(), indent=2))
        elif args.status:
            print(json.dumps(updater.read_journal(), indent=2))
        elif args.check:
            pre = updater.preflight()
            print(json.dumps(release_versions.discover_release(args.channel, pre['source_version']), indent=2))
        else:
            print(updater.update(args.channel, args.version, lambda phase: print(phase, flush=True)))
    except Exception as error:
        # Docker errors can contain expanded private environment values.
        print('Update failed: ' + getattr(error, 'code', 'preflight_failed'), file=sys.stderr)
        return 3 if getattr(error, 'rollback_succeeded', None) is False else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
