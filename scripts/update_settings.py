"""Host-only settings client; use the worker's persisted state, never edit it live."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time


def request(socket_path, payload, timeout=5):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(socket_path))
        connection.sendall(json.dumps(payload).encode() + b'\n')
        with connection.makefile('rb') as response:
            data = response.readline(262145)
    if len(data) > 262144 or not data.endswith(b'\n'):
        raise ValueError('Invalid worker response size.')
    reply = json.loads(data)
    if not isinstance(reply, dict) or not isinstance(reply.get('status'), dict):
        raise ValueError('Invalid worker response.')
    if not reply.get('ok'):
        raise RuntimeError(reply.get('error', 'updater_unavailable'))
    return reply['status']


def configure(kind, *, channel=None, auto_update=None, project=None):
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo on the WebClock host.')
    config_path = Path('/etc/webclock-docker-updater.json' if kind == 'docker' else '/etc/webclock-updater.json')
    info = config_path.lstat()
    if config_path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unsafe worker configuration.')
    config = json.loads(config_path.read_text())
    if config.get('kind', 'systemd') != kind:
        raise RuntimeError('Wrong worker provider.')
    if project and Path(config['project']).resolve() != Path(project).resolve():
        raise RuntimeError('Worker belongs to another installation.')
    socket_path = Path(config.get('socket_path', '/run/webclock-updater/control.sock'))
    for attempt in range(20):
        try:
            state = request(socket_path, {'action': 'status'})
            break
        except (FileNotFoundError, ConnectionRefusedError):
            if attempt == 19:
                raise
            time.sleep(0.25)
    if state.get('update_provider') != kind:
        raise RuntimeError('Wrong worker provider.')
    if channel is not None or auto_update is not None:
        state = request(socket_path, {'action': 'configure',
                        'channel': channel if channel is not None else state['channel'],
                        'auto_update': auto_update if auto_update is not None else state['auto_update']})
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['systemd', 'docker'], default='systemd')
    parser.add_argument('--project')
    parser.add_argument('--channel', choices=['stable', 'beta'])
    parser.add_argument('--auto-update', choices=['on', 'off'])
    args = parser.parse_args()
    try:
        value = None if args.auto_update is None else args.auto_update == 'on'
        print(json.dumps(configure(args.kind, channel=args.channel, auto_update=value,
                                   project=args.project), indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        print('Update settings unavailable: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
