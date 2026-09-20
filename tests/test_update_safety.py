import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as clock
import update_clock as updater

REAL_SERVICE_URL = updater.service_url


class SettingsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'state/settings.json'
        settings_patch = patch.object(clock, 'SETTINGS_FILE', str(self.path))
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        state_patch = patch.dict(clock.display_settings, clock.DEFAULT_SETTINGS, clear=True)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.client = clock.app.test_client()

    def test_save_reload_and_invalid_inputs(self):
        expected = {'mode': 'black', 'brightness': 35, 'timezone_offset': 9, 'language': 'en'}
        self.assertEqual(self.client.post('/api/control', json=expected).status_code, 200)
        self.assertEqual(clock.load_display_settings(), expected)
        previous = self.path.read_bytes()
        for data in ({'brightness': 101}, {'brightness': True}, {'brightness': 3.5},
                     {'timezone_offset': '-13'}, {'language': 'unknown'},
                     {'mode': 'invalid'}, {'other': 1}, [], None):
            with self.subTest(data=data):
                response = self.client.post('/api/control', data=json.dumps(data), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(clock.display_settings, expected)
        self.assertEqual(self.client.post('/api/control', json={'brightness': '40'}).status_code, 200)
        self.assertEqual(clock.load_display_settings()['brightness'], 40)

    def test_write_failure_keeps_previous_settings_and_corrupt_file_is_not_overwritten(self):
        self.client.post('/api/control', json={'brightness': 40})
        previous = self.path.read_bytes()
        with patch.object(clock.os, 'replace', side_effect=OSError('disk full')):
            with self.assertLogs(clock.app.logger, level='ERROR'):
                self.assertEqual(self.client.post('/api/control', json={'brightness': 50}).status_code, 500)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(clock.display_settings['brightness'], 40)
        self.assertEqual(list(self.path.parent.glob('.settings-*')), [])
        self.path.write_text('broken')
        with self.assertRaises(ValueError):
            clock.load_display_settings()
        self.assertEqual(self.path.read_text(), 'broken')


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.remote = self.root / 'remote'
        self.project = self.root / 'installed'
        self.remote.mkdir()
        self.real_run = updater.run
        self.real_run(['git', 'init', '-b', 'main', str(self.remote)])
        self.real_run(['git', 'config', 'user.name', 'Test'], cwd=self.remote)
        self.real_run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=self.remote)
        (self.remote / 'app.py').write_text('old source\n')
        (self.remote / '.gitignore').write_text('venv/\n.env\nmanual_notes.json\nwebclock_state/\n.webclock-update*\n')
        self.commit('old')
        self.real_run(['git', 'clone', str(self.remote), str(self.project)])
        self.old_head = self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project)
        (self.remote / 'app.py').write_text('new source\n')
        self.commit('new')
        (self.project / 'venv/bin').mkdir(parents=True)
        (self.project / 'venv/bin/python3').write_text('placeholder')
        (self.project / 'venv/package').write_text('old package')
        (self.project / '.env').write_text('PORT=80\n')
        (self.project / 'manual_notes.json').write_text('[{"id":1,"text":"keep"}]')
        self.settings = {'mode': 'black', 'brightness': 35, 'timezone_offset': 9, 'language': 'en'}
        self.calls = []
        self.fail_pip = False
        self.state = 'active'
        for name, value in [
            ('service_url', lambda project: ('http://127.0.0.1:80', os.getuid(), os.getgid())),
            ('http_json', lambda url, data=None: {'settings': self.settings, 'events': []}),
            ('run', self.fake_run),
        ]:
            mocked = patch.object(updater, name, side_effect=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        owner = patch.object(updater.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='root'))
        owner.start()
        self.addCleanup(owner.stop)

    def commit(self, message):
        self.real_run(['git', 'add', '.'], cwd=self.remote)
        self.real_run(['git', '-c', 'commit.gpgsign=false', 'commit', '-m', message], cwd=self.remote)

    def fake_run(self, args, cwd=None):
        self.calls.append(args)
        if args[0] == 'systemctl':
            if args[1] == 'stop':
                self.state = 'inactive'
            elif args[1] == 'start':
                self.state = 'active'
            return ''
        if args[0] == str(self.project / 'venv/bin/python3'):
            (self.project / 'venv/package').write_text('new package')
            if self.fail_pip:
                raise subprocess.CalledProcessError(1, args, stderr='simulated package failure')
            return ''
        return self.real_run(args, cwd=cwd)

    def assert_data_preserved(self):
        self.assertEqual((self.project / '.env').read_text(), 'PORT=80\n')
        self.assertEqual(json.loads((self.project / 'manual_notes.json').read_text())[0]['text'], 'keep')

    def test_success_preserves_settings_and_data(self):
        with patch.object(updater, 'wait_healthy') as health:
            updater.update(self.project)
        health.assert_called_once_with('http://127.0.0.1:80', self.settings)
        self.assertEqual((self.project / 'app.py').read_text(), 'new source\n')
        self.assertEqual(json.loads((self.project / 'webclock_state/settings.json').read_text()), self.settings)
        self.assert_data_preserved()
        self.assertEqual(list(self.project.glob('.webclock-update-*')), [])

    def test_package_failure_restores_git_and_venv(self):
        self.fail_pip = True
        with patch.object(updater, 'wait_healthy'):
            with self.assertRaises(subprocess.CalledProcessError):
                updater.update(self.project)
        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), self.old_head)
        self.assertEqual((self.project / 'venv/package').read_text(), 'old package')
        self.assertEqual(self.state, 'active')
        self.assert_data_preserved()
        self.assertEqual(len(list(self.project.glob('.webclock-update-*'))), 1)

    def test_success_preserves_night_schedule(self):
        self.settings['night'] = dict(clock.DEFAULT_NIGHT, enabled=True)
        self.test_success_preserves_settings_and_data()

    def test_unhealthy_service_rolls_back(self):
        with patch.object(updater, 'wait_healthy', side_effect=[RuntimeError('crash'), None]):
            with self.assertRaisesRegex(RuntimeError, 'crash'):
                updater.update(self.project)
        self.assertEqual((self.project / 'app.py').read_text(), 'old source\n')
        self.assertEqual((self.project / 'venv/package').read_text(), 'old package')
        self.assertEqual(self.state, 'active')

    def test_dirty_install_stops_before_service_changes(self):
        (self.project / 'app.py').write_text('user edits')
        with self.assertRaisesRegex(RuntimeError, 'Uncommitted'):
            updater.update(self.project)
        self.assertFalse(any(args[0] == 'systemctl' for args in self.calls))
        self.assertEqual((self.project / 'app.py').read_text(), 'user edits')

    def test_incoming_tracked_data_is_rejected(self):
        self.real_run(['git', 'add', '-f', '.gitignore'], cwd=self.remote)
        (self.remote / '.env').write_text('bad replacement')
        self.real_run(['git', 'add', '-f', '.env'], cwd=self.remote)
        self.commit('unsafe data')
        with self.assertRaisesRegex(RuntimeError, 'tracks installation data'):
            updater.update(self.project)
        self.assertFalse(any(args[0] == 'systemctl' for args in self.calls))
        self.assert_data_preserved()

    def test_corrupt_saved_settings_stops_before_mutation(self):
        (self.project / 'webclock_state').mkdir()
        (self.project / 'webclock_state/settings.json').write_text('{broken')
        with self.assertRaises(ValueError):
            updater.update(self.project)
        self.assertFalse(any(args[0] == 'systemctl' for args in self.calls))

    def test_non_git_install_preserves_files(self):
        import shutil
        shutil.rmtree(self.project / '.git')
        with patch.object(updater, 'wait_healthy'):
            updater.update(self.project)
        self.assertEqual((self.project / 'app.py').read_text(), 'old source\n')
        self.assert_data_preserved()

    def test_different_service_directory_is_rejected(self):
        with patch.object(updater, 'service_property', return_value='/different/install'):
            # Exercise the real preflight instead of this class's service mock.
            with self.assertRaisesRegex(RuntimeError, 'WorkingDirectory'):
                REAL_SERVICE_URL(self.project)

    def test_existing_systemd_port_overrides_dotenv(self):
        fake_proc = self.root / 'proc'
        process = fake_proc / '123'
        process.mkdir(parents=True)
        (process / 'cwd').symlink_to(self.project)
        (process / 'cmdline').write_bytes((str(self.project / 'venv/bin/python3') + '\0app.py\0').encode())
        (process / 'environ').write_bytes(b'PORT=80\0HOST=0.0.0.0\0')
        properties = {'WorkingDirectory': str(self.project), 'MainPID': '123'}
        with patch.object(updater, 'service_property', side_effect=properties.__getitem__):
            with patch.object(updater, 'Path', side_effect=lambda value: fake_proc if value == '/proc' else Path(value)):
                with patch.object(updater, 'run', return_value='{"PORT":"5000"}'):
                    url, uid, gid = REAL_SERVICE_URL(self.project)
        self.assertEqual(url, 'http://127.0.0.1:80')
        self.assertEqual((uid, gid), (os.getuid(), os.getgid()))

    def test_failed_recovery_keeps_backup_and_reports_failure(self):
        with patch.object(updater, 'wait_healthy', side_effect=RuntimeError('crash')):
            with self.assertRaisesRegex(RuntimeError, 'crash'):
                updater.update(self.project)
        backup = next(self.project.glob('.webclock-update-*'))
        self.assertTrue((backup / 'failed-venv').exists())
        self.assertTrue((backup / '.env').exists())
        self.assert_data_preserved()

    def test_health_check_rejects_crash_loop_and_accepts_stable_service(self):
        with patch.object(updater, 'service_property', side_effect=lambda key: '123' if key == 'MainPID' else 'active'):
            with patch.object(updater.time, 'sleep'):
                updater.wait_healthy('http://localhost', self.settings)
        with patch.object(updater, 'service_property', return_value='0'):
            with patch.object(updater.time, 'monotonic', side_effect=[0, 0, 61]):
                with patch.object(updater.time, 'sleep'):
                    with self.assertRaisesRegex(RuntimeError, 'health check'):
                        updater.wait_healthy('http://localhost', self.settings)


if __name__ == '__main__':
    unittest.main()
