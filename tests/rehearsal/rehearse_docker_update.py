"""Opt-in CI rehearsal with a real Docker daemon and disposable Compose data.

Release discovery and pulling are replaced with locally built candidate images.
This checks real replacement/rollback, not public Release or HA OS delivery.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import docker_update


def run(*command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-image', required=True)
    parser.add_argument('--managed', action='store_true')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    source = json.loads(run('docker', 'image', 'inspect', args.source_image).stdout)[0]
    version = source['Config']['Labels']['org.opencontainers.image.version']
    architecture = source['Architecture']
    good, bad = '99.0.0', '99.0.1'
    tags = [docker_update.REPOSITORY + ':' + item for item in (good, bad)]
    with tempfile.TemporaryDirectory(prefix='webclock-update-') as directory:
        project = Path(directory).resolve()
        compose = (repo / 'docker-compose.yml').read_text().replace('container_name: webclock', 'container_name: webclock-update-rehearsal')
        compose = re.sub(r'(?m)^    image:.*$', '    image: ' + args.source_image, compose)
        (project / 'docker-compose.yml').write_text(compose)
        (project / '.env').write_text('WEBCLOCK_VERSION=' + version + '\nWEBCLOCK_HTTP_PORT=18501\n')
        (project / 'manual_notes.json').write_text('[]')
        for name in ('webclock_state', '.webclock-mode-backups-webclock_state', 'tls', 'webclock_updater_run'):
            (project / name).mkdir()
        if args.managed:
            run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-keyout', str(project / 'tls/key.pem'), '-out', str(project / 'tls/cert.pem'),
                '-subj', '/CN=clock.test', '-addext', 'subjectAltName=DNS:clock.test')
            with (project / '.env').open('a') as output:
                output.write('WEBCLOCK_TLS_CERT=/app/tls/cert.pem\nWEBCLOCK_TLS_KEY=/app/tls/key.pem\n'
                             'WEBCLOCK_UPDATE_HOST=clock.test\nWEBCLOCK_UPDATE_CA=/app/tls/cert.pem\n')
            run('docker', 'compose', 'run', '--rm', '-T', '--no-deps', '--no-build', 'webclock',
                'python', 'scripts/manage_auth.py', 'setup', '--username', 'admin', '--enable-managed',
                cwd=project, input='disposable-ci-password\ndisposable-ci-password\n')
        auth = project / 'webclock_state/auth.json'
        auth_before = hashlib.sha256(auth.read_bytes()).hexdigest() if args.managed else None
        sentinel = project / 'webclock_state/rehearsal.json'
        sentinel.write_text('{"private": "retained"}')
        updater = docker_update.DockerUpdater(project)
        try:
            for candidate, tag in zip((good, bad), tags):
                dockerfile = ('FROM ' + args.source_image + '\n'
                              'RUN printf "' + candidate + '\\n" > /app/VERSION\n'
                              'LABEL org.opencontainers.image.version="' + candidate + '"\n')
                if candidate == bad:
                    dockerfile += 'CMD ["python", "-c", "raise SystemExit(1)"]\n'
                (project / 'Dockerfile').write_text(dockerfile)
                run('docker', 'build', '--platform', 'linux/' + architecture, '-t', tag, str(project))
            updater.start_service()
            for _ in range(45):
                try:
                    updater.preflight()
                    break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError('Source container did not become ready')
            if args.managed:
                auth_before = hashlib.sha256(auth.read_bytes()).hexdigest()
            real_wait = updater.wait_for_health
            def wait(version, image_id, mode, **kwargs):
                return real_wait(version, image_id, mode, timeout=10 if version == bad else 45)
            def local_pull(target, arch):
                image = updater._image(docker_update.REPOSITORY + ':' + target, target)
                assert image['Architecture'] == arch
                return image['Id']
            release = {'latest_version': good, 'update_available': True, 'prerelease': False}
            with patch.object(docker_update.release_versions, 'discover_release', return_value=release), \
                 patch.object(updater, 'pull_image', side_effect=local_pull), \
                 patch.object(updater, 'wait_for_health', side_effect=wait):
                class Interrupted(BaseException):
                    pass
                write = docker_update.atomic_write
                def interrupt_cutover(path, *args, **kwargs):
                    write(path, *args, **kwargs)
                    if path == updater.compose_file:
                        raise Interrupted()
                with patch.object(docker_update, 'atomic_write', side_effect=interrupt_cutover):
                    try:
                        updater.update(expected_version=good)
                    except Interrupted:
                        pass
                    else:
                        raise AssertionError('Expected an interrupted configuration switch')
                info = updater._container(running=False)
                assert not info['State']['Running']
                assert info['HostConfig']['RestartPolicy']['Name'] == 'no'
                operation = updater.read_journal()['op_id']
                assert updater.recover('previous', operation, confirmed=True) == 'rolled_back'
                assert updater._container()['HostConfig']['RestartPolicy']['Name'] == 'always'
                assert updater.update(expected_version=good) == 'updated'
                assert updater.preflight()['source_version'] == good
                assert sentinel.read_text() == '{"private": "retained"}'
                if args.managed:
                    assert updater.preflight()['deployment_mode'] == 'managed'
                    assert hashlib.sha256(auth.read_bytes()).hexdigest() == auth_before
                release['latest_version'] = bad
                try:
                    updater.update(expected_version=bad)
                except docker_update.DockerUpdateError as error:
                    assert error.rollback_succeeded is True, error
                else:
                    raise AssertionError('Crashing image was reported as successful')
                assert updater.preflight()['source_version'] == good
                assert updater.read_journal()['step'] == 'rolled_back'
                assert updater._container()['HostConfig']['RestartPolicy']['Name'] == 'always'
                assert sentinel.read_text() == '{"private": "retained"}'
                if args.managed:
                    assert hashlib.sha256(auth.read_bytes()).hexdigest() == auth_before
            print('Real Docker image replacement and rollback passed for ' + architecture)
        finally:
            updater._compose('down', check=False)
            run('docker', 'image', 'rm', *tags)
            # Container-created directories may be owned by root on Linux runners.
            if sys.platform.startswith('linux'):
                run('sudo', 'chown', '-R', str(os.getuid()) + ':' + str(os.getgid()), str(project))


if __name__ == '__main__':
    main()
