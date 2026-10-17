"""Validate release versions and package committed, public distribution files."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts.release_versions import release_version


SERVER_FILES = frozenset((
    'VERSION', '.env.example', '.dockerignore', '.gitignore', 'Dockerfile', 'docker-compose.yml', 'requirements.txt',
    'app.py', 'index.html', 'sw.js', 'setup.sh', 'install.sh', 'update_clock.py',
    'update_clock.sh', 'docker_update.sh', 'README.md', 'README_en.md',
    'README_jp.md', 'CHANGELOG.md', 'repository.yaml', 'hacs.json',
    'homeassistant/README.md', 'homeassistant/prepare_local_app.sh',
))
SERVER_DIRS = ('webclock/', 'templates/', 'static/', 'scripts/', 'doc/',
               'custom_components/webclock/', 'homeassistant/addon/')
CLOCK_FILES = frozenset((
    'index.html', 'sw.js', 'static/clock.css', 'static/clock.js', 'static/offline.js',
    'static/time-format.js', 'static/time-inputs.js', 'static/time-inputs.css',
))
PRIVATE_NAMES = frozenset(('manual_notes.json', 'auth.json', 'auth-required',
                           'device-access.json', 'webclock_state', 'tls', 'venv',
                           '__pycache__', '.git'))


def check_versions(read_text, tag=None):
    version = read_text('VERSION').strip()
    release_version(version)
    if tag is not None and tag != 'v' + version:
        raise ValueError('Release tag must match VERSION: v' + version)
    if json.loads(read_text('custom_components/webclock/manifest.json'))['version'] != version:
        raise ValueError('Integration manifest version must match VERSION')
    checks = {
        'custom_components/webclock/const.py': r'^VERSION = "' + re.escape(version) + r'"$',
        'custom_components/webclock/www/webclock-cards.js': r"^  const VERSION = '" + re.escape(version) + r"';$",
        'homeassistant/addon/config.yaml': r'^version: ["\x27]?' + re.escape(version) + r'["\x27]?$',
        'docker-compose.yml': r'ghcr\.io/kcayut/webclock:\$\{WEBCLOCK_VERSION:-' + re.escape(version) + r'\}',
    }
    for name, pattern in checks.items():
        if not re.search(pattern, read_text(name), re.M):
            raise ValueError(name + ' must match VERSION')
    if not re.search(r'^image: ghcr\.io/kcayut/webclock-addon$', read_text('homeassistant/addon/config.yaml'), re.M):
        raise ValueError('Unexpected Home Assistant image registry')
    for name in ('Dockerfile', 'homeassistant/addon/Dockerfile'):
        if 'org.opencontainers.image.version="${BUILD_VERSION}"' not in read_text(name):
            raise ValueError(name + ' must label its build version')
    return version


def is_public(path):
    return all(part not in PRIVATE_NAMES and part != 'webclock_updater_run'
               and not part.startswith(('.webclock-', '.docker-update', '.docker-migration'))
               and (not part.startswith('.env') or part == '.env.example')
               and not part.endswith(('.pyc', '.pyo', '.pem', '.key'))
               for part in PurePosixPath(path).parts)


def build_release(output, version=None, root=ROOT):
    # git archive reads committed blobs, never local .env files or modified state.
    archive = subprocess.check_output(['git', 'archive', '--format=tar', 'HEAD'], cwd=root)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            name = member.name
            if not is_public(name) or not (name in SERVER_FILES or name.startswith(SERVER_DIRS)):
                continue
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError('Release files must be regular files: ' + name)
            member.mode = 0o755 if member.mode & 0o111 else 0o644
            files[name] = (member, source.extractfile(member).read())
    # Keep published archive paths while maintaining portable scripts in one place.
    for name in ('portable_update_clock.sh', 'portable_docker_update.sh'):
        source_name = 'scripts/update/' + name
        if source_name not in files:
            raise ValueError('Missing release file: ' + source_name)
        files[name] = files[source_name]
    actual = check_versions(lambda name: files[name][1].decode(), 'v' + version if version else None)
    for required in ('install.sh', 'setup.sh', 'scripts/setup.sh', 'app.py', 'webclock/app.py',
                     'homeassistant/prepare_local_app.sh',
                     'scripts/update/update_clock.sh', 'scripts/update/docker_update.sh',
                     'portable_docker_update.sh', 'docker_update.sh', 'scripts/docker_update.py',
                     'scripts/docker_update_install.py', 'scripts/docker_update_migrate.py',
                     'scripts/update_settings.py', *CLOCK_FILES):
        if required not in files:
            raise ValueError('Missing release file: ' + required)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = int(subprocess.check_output(['git', 'show', '-s', '--format=%ct', 'HEAD'], cwd=root))
    server_path = output / ('webclock-' + actual + '.tar.gz')
    with server_path.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=stamp) as compressed:
        with tarfile.open(mode='w', fileobj=compressed) as server:
            for name, (member, data) in sorted(files.items()):
                entry = tarfile.TarInfo('webclock-' + actual + '/' + name)
                entry.size, entry.mode, entry.mtime = len(data), member.mode, stamp
                server.addfile(entry, io.BytesIO(data))
    clock_path = output / ('webclock-clock-' + actual + '.zip')
    with zipfile.ZipFile(clock_path, 'w', compression=zipfile.ZIP_DEFLATED) as clock:
        for name, (member, data) in sorted(files.items()):
            if name in CLOCK_FILES or name.startswith('static/brand/'):
                entry = zipfile.ZipInfo('webclock-clock-' + actual + '/' + name, time.gmtime(stamp)[:6])
                entry.external_attr = member.mode << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                clock.writestr(entry, data)
    installer = output / 'install.sh'
    installer_source, replacements = re.subn(
        rb'^RELEASE_VERSION=""$', ('RELEASE_VERSION="' + actual + '"').encode(),
        files['install.sh'][1], flags=re.M)
    if replacements != 1:
        raise ValueError('install.sh must have exactly one empty RELEASE_VERSION assignment')
    installer.write_bytes(installer_source)
    installer.chmod(0o755)
    docker_bootstrap = output / 'portable_docker_update.sh'
    bootstrap_source, replacements = re.subn(
        rb'^RELEASE_VERSION=""$', ('RELEASE_VERSION="' + actual + '"').encode(),
        files['portable_docker_update.sh'][1], flags=re.M)
    if replacements != 1:
        raise ValueError('portable_docker_update.sh must declare RELEASE_VERSION exactly once')
    docker_bootstrap.write_bytes(bootstrap_source)
    docker_bootstrap.chmod(0o755)
    artifacts = (installer, docker_bootstrap, server_path, clock_path)
    (output / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in artifacts))
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='check the current checkout without creating assets')
    parser.add_argument('--tag', help='expected Git tag, for example v1.1.0')
    parser.add_argument('--version', help='expected package version, for example 1.1.0')
    parser.add_argument('--output', type=Path, help='directory for release assets built from Git HEAD')
    args = parser.parse_args()
    if args.check:
        print(check_versions(lambda name: (ROOT / name).read_text(), args.tag))
    elif args.output:
        print(build_release(args.output, args.version or (args.tag.removeprefix('v') if args.tag else None)))
    else:
        parser.error('specify --check or --output')


if __name__ == '__main__':
    main()
