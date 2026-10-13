#!/usr/bin/env python3
"""Independent, fixed-installation update worker and local control socket."""

import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time

try:
    from scripts import release_versions, update_clock
except ModuleNotFoundError as error:
    if error.name != 'scripts':
        raise
    import release_versions
    import update_clock


CHECK_INTERVAL = 24 * 60 * 60
RETRY_INTERVAL = 60 * 60
STARTUP_DELAY = 60
SOCKET_PATH = Path('/run/webclock-updater/control.sock')
STATE_PATH = Path('/var/lib/webclock-updater/state.json')


class Updater:
    def __init__(self, project, state_path=STATE_PATH, *, channel='stable', auto_update=True, on_updated=None):
        self.project = Path(project).resolve(strict=True)
        self.state_path = Path(state_path)
        self.on_updated = on_updated
        self.lock = threading.RLock()
        self.worker = None
        self.stopped = threading.Event()
        self.data = {
            'supported': True, 'state': 'idle', 'channel': channel,
            'auto_update': auto_update, 'auto_update_paused': False,
            'latest_version': None, 'update_available': False,
            'release_url': '', 'release_notes': '', 'phase': '', 'error': None,
            'result': None, 'last_checked': None, 'next_check': time.time() + STARTUP_DELAY,
        }
        if self.state_path.is_symlink():
            raise RuntimeError('Updater state must not be a symlink.')
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text())
            if not isinstance(saved, dict):
                raise ValueError('Invalid updater state.')
            self.data.update({key: value for key, value in saved.items() if key in self.data})
        recorded = self._git_channel()
        if recorded in ('stable', 'beta') and recorded != self.data['channel']:
            self.data.update(channel=recorded, latest_version=None, update_available=False,
                             release_url='', release_notes='', last_checked=None)
        self._validate_settings(self.data['channel'], self.data['auto_update'])
        if self.data['state'] == 'updating':
            # Never guess whether an interrupted process reached its rollback.
            self.data.update(state='interrupted', phase='', error='update_interrupted',
                             result='manual_recovery', auto_update_paused=True)
        elif self.data['state'] == 'checking':
            self.data.update(state='idle', phase='')
        self.data['next_check'] = max(float(self.data['next_check'] or 0), time.time() + STARTUP_DELAY)
        try:
            self._save()
        except OSError:
            pass

    @staticmethod
    def _validate_settings(channel, auto_update):
        if channel not in ('stable', 'beta') or type(auto_update) is not bool:
            raise ValueError('invalid_settings')

    def _save(self):
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.state-', dir=self.state_path.parent)
        try:
            with os.fdopen(descriptor, 'w') as output:
                json.dump(self.data, output, ensure_ascii=False)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _change(self, allow_failure=False, **values):
        with self.lock:
            self.data.update(values)
            try:
                self._save()
            except OSError as error:
                if not allow_failure:
                    raise
                print('WebClock updater could not persist state: ' + type(error).__name__, flush=True)

    def status(self):
        with self.lock:
            result = dict(self.data)
            result['current_version'] = (self.project / 'VERSION').read_text().strip()
            return result

    def _busy(self):
        return self.worker is not None and self.worker.is_alive()

    def dispatch(self, request):
        if not isinstance(request, dict):
            return {'ok': False, 'error': 'invalid_request', 'status': self.status()}
        action = request.get('action')
        allowed = {
            'status': {'action'}, 'check': {'action'},
            'configure': {'action', 'channel', 'auto_update'},
            'install': {'action', 'expected_version'},
        }
        with self.lock:
            if action not in allowed or set(request) - allowed[action]:
                return {'ok': False, 'error': 'invalid_request', 'status': self.status()}
            if action == 'status':
                return {'ok': True, 'status': self.status()}
            if self._busy():
                return {'ok': False, 'error': 'update_busy', 'status': self.status()}
            if action == 'configure':
                try:
                    self._validate_settings(request.get('channel'), request.get('auto_update'))
                except ValueError:
                    return {'ok': False, 'error': 'invalid_settings', 'status': self.status()}
                changed_channel = request['channel'] != self.data['channel']
                self.data.update(channel=request['channel'], auto_update=request['auto_update'])
                if changed_channel:
                    self.data.update(latest_version=None, update_available=False,
                                     release_url='', release_notes='', last_checked=None,
                                     next_check=time.time() + STARTUP_DELAY)
                try:
                    self._save()
                except OSError:
                    return {'ok': False, 'error': 'state_save_failed', 'status': self.status()}
                if changed_channel:
                    self._sync_channel(request['channel'])
            elif action == 'check':
                try:
                    self._start(self._check, False)
                except OSError:
                    return {'ok': False, 'error': 'state_save_failed', 'status': self.status()}
            elif action == 'install':
                expected = request.get('expected_version')
                if not isinstance(expected, str) or not self.data['update_available'] or expected != self.data['latest_version']:
                    return {'ok': False, 'error': 'release_changed', 'status': self.status()}
                try:
                    self._start(self._install, expected)
                except OSError:
                    return {'ok': False, 'error': 'state_save_failed', 'status': self.status()}
            return {'ok': True, 'status': self.status()}

    def _start(self, target, *args):
        self._change(state='updating' if target == self._install else 'checking', phase='checking')
        self.worker = threading.Thread(target=target, args=args, daemon=True, name='webclock-update')
        self.worker.start()

    def _discover(self):
        return release_versions.discover_release(self.data['channel'], self.status()['current_version'])

    def _record_release(self, release):
        self._change(latest_version=release['latest_version'],
                     update_available=release['update_available'],
                     release_url=release.get('html_url') or '',
                     release_notes=(release.get('body') or '')[:16000],
                     last_checked=time.time(), next_check=time.time() + CHECK_INTERVAL)

    def _check(self, automatic=False):
        try:
            self._change(state='checking', phase='checking', error=None)
            release = self._discover()
            self._record_release(release)
            self._change(state='available' if release['update_available'] else 'idle', phase='')
            if automatic and self.data['auto_update'] and not self.data['auto_update_paused'] and release['update_available']:
                self._install(release['latest_version'])
        except Exception as error:
            # Command output may contain private URLs; web-visible status uses fixed codes.
            print('WebClock release check failed: ' + type(error).__name__, flush=True)
            try:
                self._change(state='failed', phase='', error='release_check_failed',
                             next_check=time.time() + RETRY_INTERVAL)
            except OSError:
                pass

    def _install(self, expected):
        self._change(state='updating', phase='checking', error=None, result=None)
        started = False
        try:
            release = self._discover()
            self._record_release(release)
            if not release['update_available'] or release['latest_version'] != expected:
                self._change(state='available' if release['update_available'] else 'idle',
                             phase='', error='release_changed')
                return
            started = True
            result = update_clock.update(self.project, channel=self.data['channel'],
                                        expected_version=expected,
                                        progress=lambda phase: self._change(allow_failure=True, phase=phase))
            self._change(state='idle', phase='', error=None, result=result or 'updated',
                         update_available=False, auto_update_paused=False)
            if result == 'updated' and self.on_updated is not None:
                # The project now contains the released updater; reload it instead of keeping old code.
                self.on_updated()
        except Exception as error:
            print('WebClock update failed: ' + type(error).__name__, flush=True)
            recovered = getattr(error, 'rollback_succeeded', None)
            result = 'rolled_back' if recovered is True else ('manual_recovery' if recovered is False else 'failed')
            try:
                self._change(state='failed', phase='', error='update_failed' if started else 'release_check_failed',
                             result=result, auto_update_paused=True,
                             next_check=time.time() + RETRY_INTERVAL)
            except OSError as save_error:
                print('WebClock updater could not persist state: ' + type(save_error).__name__, flush=True)

    def _git_channel(self):
        try:
            return subprocess.run(['git', '-c', 'safe.directory=' + str(self.project), '-C', str(self.project),
                                   'config', '--local', '--get', 'webclock.releaseChannel'],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                  timeout=15).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ''

    def _sync_channel(self, channel):
        """Keep the host command (update_clock.sh) on the channel chosen in the web page."""
        repository = self.project / '.git'
        try:
            if repository.is_symlink() or not repository.is_dir():
                return
            owner_uid = repository.stat().st_uid
            if os.geteuid() not in (0, owner_uid):
                return
            owner = pwd.getpwuid(owner_uid).pw_name
            prefix = []
            if os.geteuid() == 0 and owner != 'root' and shutil.which('runuser'):
                prefix = ['runuser', '-u', owner, '--']
            cmd = prefix + ['git', '-c', 'safe.directory=' + str(self.project), '-C', str(self.project),
                           'config', '--local', 'webclock.releaseChannel', channel]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.SubprocessError):
            print('WebClock could not record the release channel in Git.', flush=True)

    def scheduler(self):
        while not self.stopped.wait(1):
            with self.lock:
                if not self._busy() and time.time() >= self.data['next_check']:
                    self._start(self._check, True)


class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        try:
            line = self.rfile.readline(4097)
            if len(line) > 4096 or not line.endswith(b'\n'):
                raise ValueError('invalid_request')
            request = json.loads(line)
            result = self.server.updater.dispatch(request)
        except (ValueError, UnicodeError):
            result = {'ok': False, 'error': 'invalid_request'}
        except Exception:
            result = {'ok': False, 'error': 'updater_unavailable'}
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode() + b'\n')


class ControlServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/webclock-updater.json')
    args = parser.parse_args()
    config_path = Path(args.config)
    info = config_path.lstat()
    if config_path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Updater configuration must be owned and writable only by root.')
    config = json.loads(config_path.read_text())
    restart = threading.Event()
    server = None

    def reload_after_update():
        # serve_forever() returns and systemd restarts this unit from the updated project.
        restart.set()
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    updater = Updater(config['project'], channel=config.get('channel', 'stable'),
                      auto_update=config.get('auto_update', True), on_updated=reload_after_update)
    os.umask(0o077)
    SOCKET_PATH.parent.mkdir(mode=0o700, exist_ok=True)
    SOCKET_PATH.unlink(missing_ok=True)
    with ControlServer(str(SOCKET_PATH), ControlHandler) as server:
        server.updater = updater
        scheduler = threading.Thread(target=updater.scheduler, daemon=True)
        scheduler.start()
        try:
            server.serve_forever()
        finally:
            updater.stopped.set()
            SOCKET_PATH.unlink(missing_ok=True)
    if restart.is_set():
        print('WebClock updater reloading the released updater code.', flush=True)


if __name__ == '__main__':
    main()
