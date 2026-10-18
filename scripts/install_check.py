"""Checks shared by fresh systemd and Compose installs; never initialize application data."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time

from dotenv import dotenv_values

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.update_clock import authorization_state, check_public_health, protected_paths, update_tls_handler


MARKER = '.webclock-install.json'


def configuration(project, docker=False):
    values = dotenv_values(project / '.env')
    port = int((values.get('WEBCLOCK_HTTP_PORT') or '80') if docker else (values.get('PORT') or '5000'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT / WEBCLOCK_HTTP_PORT must be between 1 and 65535.')
    host = '0.0.0.0' if docker else (values.get('HOST') or '0.0.0.0')
    state = project / ('webclock_state' if docker else (values.get('WEBCLOCK_STATE_DIR') or 'webclock_state'))
    if docker and values.get('WEBCLOCK_STATE_DIR') not in (None, '', '/app/webclock_state'):
        raise ValueError('Docker installs require WEBCLOCK_STATE_DIR=/app/webclock_state and its existing Compose mount.')
    result = {'port': port, 'host': host, 'state': str(state.absolute())}
    notes = state / 'manual_notes.json' if docker else project / (values.get('NOTES_FILE') or str(state / 'manual_notes.json'))
    result['notes'] = str(notes.absolute())
    for key in ('WEBCLOCK_TLS_CERT', 'WEBCLOCK_TLS_KEY', 'WEBCLOCK_UPDATE_HOST', 'WEBCLOCK_UPDATE_CA'):
        value = values.get(key)
        if value:
            if key != 'WEBCLOCK_UPDATE_HOST':
                if docker:
                    if not value.startswith('/app/tls/') or '..' in Path(value).parts:
                        raise ValueError(key + ' must be inside /app/tls for Docker.')
                    value = str(project / 'tls' / value[len('/app/tls/'):])
                else:
                    value = str((project / value).absolute())
            result[key] = value
    return result


def validate_tls(config, managed):
    cert, key = config.get('WEBCLOCK_TLS_CERT'), config.get('WEBCLOCK_TLS_KEY')
    if bool(cert) != bool(key) or (managed and not cert):
        raise ValueError('Managed setup needs valid HTTPS first: --tls-cert FILE --tls-key FILE --tls-host NAME [--tls-ca FILE].')
    if not cert:
        return
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    client = ssl.create_default_context(cafile=config.get('WEBCLOCK_UPDATE_CA'))
    name = config.get('WEBCLOCK_UPDATE_HOST') or local_host(config['host'])
    # Verify the pair, trust chain, expiry and hostname before creating credentials.
    client_in, client_out, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
    endpoints = (client.wrap_bio(client_in, client_out, server_hostname=name),
                 server.wrap_bio(server_in, server_out, server_side=True))
    completed = set()
    for _ in range(10):
        for index, endpoint in enumerate(endpoints):
            try:
                endpoint.do_handshake()
                completed.add(index)
            except ssl.SSLWantReadError:
                pass
        server_in.write(client_out.read())
        client_in.write(server_out.read())
        if len(completed) == 2:
            return
    raise ValueError('TLS certificate validation did not complete.')


def local_host(host):
    return {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)


def prepare(project, kind, mode, project_id, existing, guard_only=False):
    marker = project / MARKER
    config = configuration(project, kind == 'docker')
    state = Path(config['state'])
    if state.is_symlink() or state.resolve() != state.absolute() or state == project or state in project.parents:
        raise ValueError('State directory must not be a symlink or overlap the project root.')
    for reserved in (project / '.git', project / 'venv', project / 'scripts'):
        if state == reserved or reserved in state.parents:
            raise ValueError('State directory overlaps installed program files.')
    if state.exists() and not state.is_dir():
        raise ValueError('State directory must be a directory.')
    try:
        protected_paths(project, (state, Path(config['notes'])))
    except RuntimeError as error:
        raise ValueError(str(error)) from error
    expected = {'version': 1, 'kind': kind, 'mode': mode, 'project': project_id, 'config': config}
    if marker.is_symlink():
        raise ValueError('Install marker must not be a symlink.')
    if marker.exists():
        saved = json.loads(marker.read_text())
        if (not isinstance(saved, dict)
                or any(saved.get(key) != expected[key] for key in ('version', 'kind', 'mode', 'project'))
                or not isinstance(saved.get('config'), dict)
                or any(saved['config'].get(key) != config[key] for key in ('state', 'notes'))):
            raise ValueError('Unfinished install identity or state directory differs. Restore its options and .env before retrying.')
        auth = authorization_state(state)
        if auth and auth['mode'] == 'managed' and mode != 'managed':
            raise ValueError('Protected data cannot be installed in self mode.')
    else:
        if existing or (state.exists() and any(state.iterdir())):
            raise ValueError('Existing installation/data found. Use the updater or documented mode-change procedure.')
        for notes in (project / 'manual_notes.json', Path(config['notes'])):
            if notes.is_symlink() or (notes.exists() and (not notes.is_file() or json.loads(notes.read_text()) != [])):
                raise ValueError('Existing reminder data found; back it up and use the documented migration procedure.')
    if guard_only:
        return
    validate_tls(config, mode == 'managed')
    if not existing and kind == 'systemd':
        family = socket.AF_INET6 if ':' in config['host'] else socket.AF_INET
        with socket.socket(family) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind((config['host'], config['port']))
            except OSError as exc:
                raise ValueError(f"Port {config['port']} is unavailable. Stop the conflicting service or change PORT in .env: {exc}") from exc
    if not marker.exists() or saved != expected:
        # Port/TLS corrections may resume an incomplete install; identity and data stay fixed.
        with tempfile.NamedTemporaryFile(mode='w', dir=project, prefix=MARKER + '.', delete=False) as stream:
            json.dump(expected, stream)
        Path(stream.name).replace(marker)
    print(config['state'])


def wait_ready(project, record, timeout=60):
    config = record['config']
    version = (project / 'VERSION').read_text().strip()
    host = 'host.docker.internal' if record['kind'] == 'docker' else local_host(config['host'])
    if ':' in host:
        host = '[' + host + ']'
    url = '{}://{}:{}'.format('https' if config.get('WEBCLOCK_TLS_CERT') else 'http', host, config['port'])
    tls = update_tls_handler(project, config)
    deadline, last_error = time.monotonic() + timeout, 'No response'
    while time.monotonic() < deadline:
        try:
            health = check_public_health(url, deployment_mode=record['mode'], tls_handler=tls)
            if health.get('version') != version:
                raise RuntimeError('Running version does not match the installed release.')
            return
        except (OSError, ValueError, RuntimeError) as error:
            last_error = str(error)
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError('HTTP(S) /api/health did not become ready: ' + last_error)


def print_urls(record):
    config = record['config']
    tls = bool(config.get('WEBCLOCK_TLS_CERT'))
    hosts = [config.get('WEBCLOCK_UPDATE_HOST')] if tls else []
    if not hosts or not hosts[0]:
        host = config['host']
        if host not in ('0.0.0.0', '::'):
            hosts = [host]
        elif record['kind'] == 'docker':
            # The helper runs in a container; only the caller can identify the host.
            hosts = [os.environ.get('WEBCLOCK_INSTALL_HOST') or 'localhost']
        else:
            try:
                hosts = sorted({entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None)
                                if not entry[4][0].startswith(('127.', '::1'))})
            except socket.gaierror:
                hosts = []
            if not hosts:
                hosts = [socket.gethostname()]
    for host in hosts:
        if ':' in host:
            host = '[' + host + ']'
        base = '{}://{}:{}'.format('https' if tls else 'http', host, config['port'])
        print('Clock: ' + base + '/')
        print('Management: ' + base + '/admin')
    if record['kind'] == 'docker' and hosts == ['localhost']:
        print('Other devices: replace localhost with this Docker host\'s LAN IP address.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('guard', 'prepare', 'auth-needed', 'wait', 'complete', 'port', 'tls-files'))
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--kind', choices=('docker', 'systemd'), default='systemd')
    parser.add_argument('--mode', choices=('self', 'managed'), default='self')
    parser.add_argument('--project-id')
    parser.add_argument('--existing', action='store_true')
    args = parser.parse_args()
    project = args.project.resolve()
    if args.action in ('guard', 'prepare'):
        prepare(project, args.kind, args.mode, args.project_id or str(project), args.existing, args.action == 'guard')
        return
    record = json.loads((project / MARKER).read_text())
    if args.action == 'port':
        print(record['config']['port'])
    elif args.action == 'tls-files':
        for key in ('WEBCLOCK_TLS_CERT', 'WEBCLOCK_TLS_KEY'):
            if record['config'].get(key):
                print(record['config'][key])
    elif args.action == 'auth-needed':
        auth = authorization_state(Path(record['config']['state']))
        if auth and auth['mode'] == 'managed':
            if record['mode'] != 'managed':
                raise ValueError('Protected data cannot be installed in self mode.')
            print('no')
        else:
            print('yes')
    elif args.action == 'wait':
        wait_ready(project, record)
    else:
        print_urls(record)
        (project / MARKER).unlink()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit('Install check failed: ' + str(error))
