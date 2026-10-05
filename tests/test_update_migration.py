"""Exercise a real legacy server through Git update and HTTP data migration.

Run with a checkout containing the legacy revision and its ``holidays`` package.
Only systemd, Linux ownership lookup and pip are replaced; application startup,
Git, HTTP, health checks, file persistence and migration remain real.
"""
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import update_clock as updater


ROOT = Path(__file__).resolve().parents[1]
# Pin the last single-file server, so this still tests migration after a commit.
LEGACY_REVISION = '49969dcc16fe5d8d48cb73bfd5241df766f93174'
SERVER = '''
import sys
import app
from werkzeug.serving import make_server
server = make_server('127.0.0.1', int(sys.argv[1]), app.app)
print(server.server_port, flush=True)
server.serve_forever()
'''


@unittest.skipUnless(importlib.util.find_spec('holidays'), 'Legacy server requires holidays')
class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.real_run = updater.run
        try:
            legacy = self.real_run(['git', 'show', LEGACY_REVISION + ':app.py'], cwd=ROOT)
        except subprocess.CalledProcessError:
            self.skipTest('Legacy revision is unavailable; fetch full Git history')
        self.assertIn('app = Flask(__name__)', legacy)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.remote = self.root / 'remote'
        self.project = self.root / 'installed'
        self.remote.mkdir()
        self.real_run(['git', 'init', '-b', 'main', str(self.remote)])
        self.real_run(['git', 'config', 'user.name', 'Migration test'], cwd=self.remote)
        self.real_run(['git', 'config', 'user.email', 'migration@example.invalid'], cwd=self.remote)
        (self.remote / 'app.py').write_text(legacy, encoding='utf-8')
        shutil.copy2(ROOT / '.gitignore', self.remote / '.gitignore')
        self.commit('Legacy single-file server')
        self.real_run(['git', 'clone', str(self.remote), str(self.project)])
        self.old_head = self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project)
        for name in ('app.py', 'requirements.txt', 'sw.js', 'update_clock.py', 'update_clock.sh'):
            shutil.copy2(ROOT / name, self.remote / name)
        for name in ('webclock', 'templates', 'static', 'scripts'):
            shutil.copytree(ROOT / name, self.remote / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.commit('Modular management server')
        self.new_head = self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.remote)

        (self.project / 'venv/bin').mkdir(parents=True)
        (self.project / 'venv/bin/python3').symlink_to(sys.executable)
        (self.project / 'venv/package-marker').write_text('old packages')
        (self.project / '.env').write_text('ICAL_URL=\n')
        self.configuration = {}
        self.process = None
        self.port = 0
        self.server_log = (self.root / 'server.log').open('w+')
        self.addCleanup(self.server_log.close)
        self.addCleanup(self.stop_service)
        self.start_service()
        self.settings = {
            'mode': 'black', 'brightness': 35, 'timezone_offset': 9, 'language': 'ja',
            'night': {'enabled': True, 'start': '21:30', 'end': '06:45',
                      'brightness': 12, 'black': False},
        }
        self.notes = [
            {'id': 1, 'text': '保留舊提醒', 'due_date': '', 'display_start': '',
             'display_end': '', 'display_mode': 'range', 'weekdays': [], 'enabled': True},
            {'id': 2, 'text': '已暫停的每週提醒', 'due_date': '', 'display_start': '08:00',
             'display_end': '09:00', 'display_mode': 'daily', 'weekdays': [0, 2], 'enabled': False},
        ]
        self.assertEqual(updater.http_json(self.url + '/api/backup', {
            'version': 1, 'settings': self.settings, 'notes': self.notes,
        }), {'status': 'ok'})
        self.before = {name: (self.project / name).read_bytes() for name in (
            '.env', 'manual_notes.json', 'webclock_state/settings.json',
            'webclock_state/before-import.json',
        )}
        for name, value in (
            ('run', self.platform_run),
            ('service_url', lambda project: (self.url, os.getuid(), os.getgid())),
            ('service_configuration', lambda project: dict(self.configuration)),
            ('service_property', self.service_property),
        ):
            mocked = patch.object(updater, name, side_effect=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        owner = patch.object(updater.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='root'))
        owner.start()
        self.addCleanup(owner.stop)

    def commit(self, message):
        self.real_run(['git', 'add', '.'], cwd=self.remote)
        self.real_run(['git', '-c', 'commit.gpgsign=false', 'commit', '-m', message], cwd=self.remote)

    def start_service(self):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH='', ICAL_URL='')
        for key in ('WEBCLOCK_STATE_DIR', 'NOTES_FILE', 'DEVICE_API_TOKEN'):
            environment.pop(key, None)
        self.process = subprocess.Popen(
            [sys.executable, '-u', '-B', '-c', SERVER, str(self.port)],
            cwd=self.project, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=self.server_log,
        )
        ready, _, _ = select.select([self.process.stdout], [], [], 10)
        line = self.process.stdout.readline().strip() if ready else ''
        if not line.isdigit():
            self.server_log.flush()
            self.fail('Server failed to start: ' + (self.root / 'server.log').read_text())
        self.port = int(line)
        self.url = 'http://127.0.0.1:' + str(self.port)

    def stop_service(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
            self.process.stdout.close()
            self.process = None

    def service_property(self, name):
        running = self.process is not None and self.process.poll() is None
        return {'MainPID': str(self.process.pid) if running else '0',
                'ActiveState': 'active' if running else 'inactive'}[name]

    def platform_run(self, args, cwd=None):
        if args[0] == 'systemctl':
            self.assertEqual(args[2], 'webclock')
            {'start': self.start_service, 'stop': self.stop_service}[args[1]]()
            return ''
        if args[:3] == [str(self.project / 'venv/bin/python3'), '-m', 'pip']:
            (self.project / 'venv/package-marker').write_text('new packages')
            return ''
        if args[:2] == [str(self.project / 'venv/bin/python3'), '-c']:
            # Execute installed read-only validators with the test environment's
            # real packages; the fixture does not install a separate virtualenv.
            return self.real_run([sys.executable, *args[1:]], cwd=cwd)
        return self.real_run(args, cwd=cwd)

    def test_real_managed_server_update_uses_public_health_and_preserves_identity(self):
        with patch.object(updater.time, 'sleep'):
            updater.update(self.project)
        self.stop_service()
        self.real_run([sys.executable, '-B', '-c', '''
from webclock.services.auth_service import AuthService
AuthService('webclock_state/auth.json').setup('admin', 'test-only-password-long', enable_managed_test=True)
'''], cwd=self.project)
        auth_path = self.project / 'webclock_state/auth.json'
        original_auth = auth_path.read_bytes()
        with (self.remote / 'app.py').open('a') as stream:
            stream.write('\n# Next protected release\n')
        self.commit('Next protected release')
        expected_head = self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.remote)
        self.start_service()
        with self.assertRaises(HTTPError) as private:
            updater.http_json(self.url + '/api/v1/devices')
        self.assertEqual(private.exception.code, 401)
        private.exception.close()
        original_http = updater.http_json
        def public_only(url, data=None, headers=None):
            self.assertTrue(url.endswith('/api/health'), url)
            self.assertIsNone(data)
            return original_http(url, data, headers)
        with patch.object(updater, 'http_json', side_effect=public_only), patch.object(updater.time, 'sleep'):
            updater.update(self.project)
        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), expected_head)
        self.assertEqual(auth_path.read_bytes(), original_auth)
        self.assertEqual(original_http(self.url + '/api/health')['deployment_mode'], 'managed')
        self.assertEqual(list(self.project.glob('.webclock-update-*')), [])

    def test_real_legacy_server_upgrades_with_settings_notes_and_management_api(self):
        with self.assertRaises(HTTPError) as missing:
            updater.http_json(self.url + '/api/v1/schedules')
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()
        with patch.object(updater.time, 'sleep'):
            updater.update(self.project)

        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), self.new_head)
        for name, content in self.before.items():
            self.assertEqual((self.project / name).read_bytes(), content, name)
        self.assertEqual(json.loads((self.project / 'webclock_state/manual_notes.json').read_text()), self.notes)
        self.assertEqual(updater.http_json(self.url + '/api/status')['settings'], dict(self.settings, time_format='24h'))
        self.assertEqual(updater.http_json(self.url + '/api/backup')['notes'], self.notes)
        self.assertEqual(updater.http_json(self.url + '/api/v1/schedules')['schedules'], [])
        schedule = updater.http_json(self.url + '/api/v1/schedules', {
            'name': '升級後建立排程', 'time': '08:30', 'rule': {'weekdays': [1, 2, 3, 4, 5]},
        })
        self.assertEqual(schedule['name'], '升級後建立排程')
        self.assertEqual(updater.http_json(self.url + '/api/v1/device/schedules')['schedules'], [schedule])
        self.assertEqual(updater.http_json(self.url + '/api/v1/device/config')['schema_version'], 2)
        self.assertEqual(list(self.project.glob('.webclock-update-*')), [])
        self.assertEqual((self.project / 'venv/package-marker').read_text(), 'new packages')

    def test_failed_upgrade_restores_legacy_server_after_new_api_writes(self):
        real_verify = updater.verify_server

        def fail_after_writing(project, url, layout, expected_notes, configuration):
            real_verify(project, url, layout, expected_notes, configuration)
            changed_settings = dict(self.settings, brightness=72, time_format='12h')
            changed_notes = [dict(self.notes[0], text='新版已改寫提醒')]
            self.assertEqual(updater.http_json(url + '/api/backup', {
                'version': 1, 'settings': changed_settings, 'notes': changed_notes,
            }), {'status': 'ok'})
            updater.http_json(url + '/api/v1/schedules', {'name': '新版排程', 'time': '09:00'})
            self.assertEqual(updater.http_json(url + '/api/status')['settings'], changed_settings)
            self.assertEqual(updater.http_json(url + '/api/backup')['notes'], changed_notes)
            self.assertTrue((project / 'webclock_state/schedules.json').exists())
            raise RuntimeError('Failure after real API writes')

        with patch.object(updater, 'verify_server', side_effect=fail_after_writing):
            with patch.object(updater.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'Failure after real API writes'):
                    updater.update(self.project)

        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), self.old_head)
        self.assertEqual((self.project / 'venv/package-marker').read_text(), 'old packages')
        for name, content in self.before.items():
            self.assertEqual((self.project / name).read_bytes(), content, name)
        self.assertFalse((self.project / 'webclock_state/manual_notes.json').exists())
        self.assertFalse((self.project / 'webclock_state/schedules.json').exists())
        self.assertEqual(updater.http_json(self.url + '/api/status')['settings'], self.settings)
        self.assertEqual(updater.http_json(self.url + '/api/backup')['notes'], self.notes)
        with self.assertRaises(HTTPError) as missing:
            updater.http_json(self.url + '/api/v1/schedules')
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()
        backup, = self.project.glob('.webclock-update-*')
        self.assertEqual((backup / 'failed-venv/package-marker').read_text(), 'new packages')
        self.assertTrue((backup / 'manifest.json').is_file())
        self.assertTrue((backup / 'failed-data').is_dir())

    def test_legacy_upgrade_respects_external_state_and_notes_paths(self):
        self.stop_service()
        external = self.root / 'outside'
        external.mkdir()
        state = external / 'state'
        notes = external / 'reminders.json'
        notes.write_bytes(self.before['manual_notes.json'])
        self.configuration = {'WEBCLOCK_STATE_DIR': str(state), 'NOTES_FILE': str(notes)}
        (self.project / '.env').write_text(
            'ICAL_URL=\n' + ''.join(key + '=' + value + '\n'
                                    for key, value in self.configuration.items()),
        )
        self.before['.env'] = (self.project / '.env').read_bytes()
        self.start_service()
        self.assertFalse(state.exists())
        self.assertEqual(updater.http_json(self.url + '/api/backup')['notes'], self.notes)
        with patch.object(updater.time, 'sleep'):
            updater.update(self.project)

        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), self.new_head)
        for name, content in self.before.items():
            self.assertEqual((self.project / name).read_bytes(), content, name)
        self.assertEqual(notes.read_bytes(), self.before['manual_notes.json'])
        self.assertEqual(json.loads((state / 'settings.json').read_text()), self.settings)
        self.assertEqual(updater.http_json(self.url + '/api/status')['settings'], dict(self.settings, time_format='24h'))
        self.assertEqual(updater.http_json(self.url + '/api/backup')['notes'], self.notes)
        schedule = updater.http_json(self.url + '/api/v1/schedules', {
            'name': '外部資料目錄排程', 'time': '07:00',
        })
        self.assertEqual(json.loads((state / 'schedules.json').read_text()), [schedule])
        self.assertEqual(updater.http_json(self.url + '/api/v1/device/schedules')['schedules'], [schedule])
        self.assertFalse((self.project / 'webclock_state/schedules.json').exists())
        self.assertFalse((state / 'manual_notes.json').exists())
        self.assertEqual(list(self.project.glob('.webclock-update-*')), [])


if __name__ == '__main__':
    unittest.main()
