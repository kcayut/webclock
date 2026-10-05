import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import app as clock
import update_clock as updater

REAL_SERVICE_URL = updater.service_url
REAL_CONFIGURATION = updater.service_configuration


class HttpClientTest(unittest.TestCase):
    def test_csrf_bootstrap_failure_does_not_send_an_unprotected_write(self):
        for status in (403, 500):
            with self.subTest(status=status), patch.object(updater.urllib.request, 'build_opener') as build:
                build.return_value.open.side_effect = HTTPError(
                    'http://localhost/api/csrf', status, 'Rejected', {}, None)
                with self.assertRaises(HTTPError) as rejected:
                    updater.http_json('http://localhost/api/control', {'brightness': 40})
                self.assertEqual(rejected.exception.code, status)
                build.return_value.open.assert_called_once_with('http://localhost/api/csrf', timeout=15)


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
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = self.client.get('/api/csrf').json['csrf_token']

    def test_save_reload_and_invalid_inputs(self):
        expected = {'mode': 'black', 'brightness': 35, 'timezone_offset': 9, 'language': 'en', 'time_format': '24h'}
        self.assertEqual(self.client.post('/api/control', json=expected).status_code, 200)
        self.assertEqual(clock.load_display_settings(), expected)
        previous = self.path.read_bytes()
        for data in ({'brightness': 101}, {'brightness': True}, {'brightness': 3.5},
                     {'timezone_offset': '-13'}, {'language': 'unknown'}, {'language': 'zh-CN'},
                     {'mode': 'invalid'}, {'other': 1}, [], None):
            with self.subTest(data=data):
                response = self.client.post('/api/control', data=json.dumps(data), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(clock.display_settings, expected)
        self.assertEqual(self.client.post('/api/control', json={'brightness': '40'}).status_code, 200)
        self.assertEqual(clock.load_display_settings()['brightness'], 40)

    def test_deployment_language_validation(self):
        for language in ('zh-TW', 'en', 'ja'):
            with self.subTest(language=language), patch.dict(clock.os.environ, WEBCLOCK_LANGUAGE=language):
                self.assertEqual(clock.deployment_language(), language)
        with patch.dict(clock.os.environ, WEBCLOCK_LANGUAGE='zh-CN'):
            with self.assertRaisesRegex(ValueError, 'zh-TW, en, ja'):
                clock.deployment_language()

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


class ProtectedDataValidationTest(unittest.TestCase):
    def test_installed_validators_reject_bad_access_without_app_import_or_secret_output(self):
        from webclock.services.auth_service import AuthService
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = Path(__file__).resolve().parents[1]
            shutil.copytree(source / 'webclock', project / 'webclock',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (project / 'venv/bin').mkdir(parents=True)
            (project / 'venv/bin/python3').symlink_to(sys.executable)
            state = project / 'state'
            service = AuthService(state / 'auth.json')
            service.setup('admin', 'test-only-password-long', enable_managed_test=True)
            before = {path.name: path.read_bytes() for path in state.iterdir()}
            real_run = updater.run
            def check():
                # Reuse this test environment's installed packages, but execute
                # the copied installation's validators in a fresh subprocess.
                with patch.object(updater, 'run', side_effect=lambda args, cwd=None:
                                  real_run([sys.executable, *args[1:]], cwd=cwd)):
                    updater.verify_protected_data(project, state)
            check()
            self.assertEqual({path.name: path.read_bytes() for path in state.iterdir()}, before)
            self.assertFalse((project / 'webclock_state').exists())
            (state / 'device-access.json').write_text('{"private-secret": "invalid schema"}')
            with self.assertRaisesRegex(RuntimeError, 'cannot read protected state') as error:
                check()
            self.assertNotIn('private-secret', str(error.exception))


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
        self.configuration = {}
        for name, value in [
            ('service_url', lambda project: ('http://127.0.0.1:80', os.getuid(), os.getgid())),
            ('service_configuration', lambda project: self.configuration),
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

    def test_success_preserves_time_format(self):
        self.settings['time_format'] = '12h'
        self.test_success_preserves_settings_and_data()

    def test_saved_time_format_default_and_invalid_values(self):
        state = self.project / 'webclock_state'
        state.mkdir()
        settings = state / 'settings.json'
        settings.write_text(json.dumps(self.settings))
        layout = state, self.project / 'manual_notes.json'
        before = settings.read_bytes()
        updater.check_saved_data(layout, layout, dict(self.settings, time_format='24h'))
        self.assertEqual(settings.read_bytes(), before)
        for value in ('12h', 'invalid', None):
            with self.assertRaises(RuntimeError):
                updater.check_saved_data(layout, layout, dict(self.settings, time_format=value))
        with patch.object(updater, 'http_json', return_value={'settings': dict(self.settings, time_format='24h'), 'events': []}), \
             patch.object(updater, 'service_property', side_effect=lambda key: '123' if key == 'MainPID' else 'active'), \
             patch.object(updater.time, 'sleep'):
            updater.wait_healthy('http://localhost', self.settings)

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

    def modular_target(self):
        (self.remote / 'webclock').mkdir(exist_ok=True)
        (self.remote / 'webclock/app.py').write_text('modular server placeholder')
        self.commit('new module layout')

    def test_external_state_and_notes_restore_after_failed_new_service(self):
        self.modular_target()
        state = self.root / 'external-state'
        state.mkdir()
        settings = state / 'settings.json'
        settings.write_text(json.dumps(self.settings))
        schedules = state / 'schedules.json'
        schedules.write_text('[{"id":"preserve-schedule"}]')
        notes = self.root / 'external-notes.json'
        notes.write_text('[{"id":4,"text":"external reminder"}]')
        notes.chmod(0o640)
        self.configuration.update(WEBCLOCK_STATE_DIR=str(state), NOTES_FILE=str(notes))
        originals = {path: path.read_bytes() for path in (settings, schedules, notes, self.project / '.env')}
        mode = notes.stat().st_mode

        def fail_after_start(*args):
            for path in originals:
                path.write_text('changed by the failed new service')
            (state / 'new-device.json').write_text('{}')
            raise RuntimeError('new API failed')

        with patch.object(updater, 'wait_healthy'), patch.object(updater, 'verify_server', side_effect=fail_after_start):
            with self.assertRaisesRegex(RuntimeError, 'new API failed'):
                updater.update(self.project)
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        self.assertEqual(notes.stat().st_mode, mode)
        self.assertFalse((state / 'new-device.json').exists())
        self.assertEqual((self.project / 'venv/package').read_text(), 'old package')
        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), self.old_head)
        backup = next(self.project.glob('.webclock-update-*'))
        manifest = json.loads((backup / 'manifest.json').read_text())
        entry = next(item for item in manifest['data'] if item['path'] == str(state))
        self.assertEqual((backup / entry['backup'] / 'schedules.json').read_bytes(), originals[schedules])
        self.assertTrue(any((directory / 'new-device.json').exists() for directory in (backup / 'failed-data').iterdir()))

    def test_failed_upgrade_removes_new_state_and_preserves_original_notes(self):
        self.modular_target()
        state = self.root / 'new-state'
        self.configuration['WEBCLOCK_STATE_DIR'] = str(state)
        original = (self.project / 'manual_notes.json').read_bytes()
        with patch.object(updater, 'wait_healthy'), patch.object(updater, 'verify_server', side_effect=RuntimeError('bad API')):
            with self.assertRaisesRegex(RuntimeError, 'bad API'):
                updater.update(self.project)
        self.assertFalse(state.exists())
        self.assertFalse((self.project / 'webclock_state').exists())
        self.assertEqual((self.project / 'manual_notes.json').read_bytes(), original)

    def test_backup_failure_does_not_touch_uncaptured_data(self):
        original = (self.project / 'manual_notes.json').read_bytes()
        original_run = self.fake_run

        def fail_copy(args, cwd=None):
            if args[:2] == ['cp', '-a'] and args[2] == str(self.project / 'manual_notes.json'):
                raise OSError('backup disk full')
            return original_run(args, cwd)

        with patch.object(updater, 'run', side_effect=fail_copy), patch.object(updater, 'wait_healthy'):
            with self.assertRaisesRegex(OSError, 'backup disk full'):
                updater.update(self.project)
        self.assertEqual((self.project / 'manual_notes.json').read_bytes(), original)
        self.assertEqual((self.project / 'app.py').read_text(), 'old source\n')
        self.assertEqual(self.state, 'active')
        backup = next(self.project.glob('.webclock-update-*'))
        self.assertFalse((backup / 'failed-data').exists())

    def test_conflicting_migration_files_fail_before_stopping_service(self):
        self.modular_target()
        state = self.project / 'webclock_state'
        state.mkdir()
        (state / 'manual_notes.json').write_text('[{"id":9,"text":"different"}]')
        with self.assertRaisesRegex(RuntimeError, 'reminder files differ'):
            updater.update(self.project)
        self.assertFalse(any(args[0] == 'systemctl' for args in self.calls))
        self.assert_data_preserved()

    def test_incoming_tracked_custom_data_is_rejected(self):
        self.configuration['NOTES_FILE'] = 'private/notes.json'
        (self.remote / 'private').mkdir()
        (self.remote / 'private/notes.json').write_text('[]')
        self.commit('unsafe custom data')
        with self.assertRaisesRegex(RuntimeError, 'tracks installation data'):
            updater.update(self.project)
        self.assertFalse(any(args[0] == 'systemctl' for args in self.calls))

    def test_unsafe_data_paths_and_lock_symlink_are_rejected(self):
        for state, notes in ((self.project, self.root / 'notes.json'),
                             (self.project / 'venv/state', self.root / 'notes.json'),
                             (self.root / 'state', self.root / 'state/settings.json')):
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                updater.protected_paths(self.project, (state, notes))
        victim = self.root / 'untouched'
        victim.write_text('preserve')
        (self.project / '.webclock-update.lock').symlink_to(victim)
        with self.assertRaises(OSError):
            updater.update(self.project)
        self.assertEqual(victim.read_text(), 'preserve')
        self.assertFalse(any(args[0] == 'systemctl' for args in self.calls))

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
        environment = b'PORT=80\0HOST=0.0.0.0\0DATA_ROOT=/from-systemd\0'
        (process / 'environ').write_bytes(environment)
        (self.project / '.env').write_text(
            'PORT=5000\nDATA_ROOT=/from-dotenv\n'
            'WEBCLOCK_STATE_DIR=${DATA_ROOT}/state\nNOTES_FILE=${DATA_ROOT}/notes.json\n')
        properties = {'WorkingDirectory': str(self.project), 'MainPID': '123'}
        def installed_python(args, cwd=None, env=None):
            # Execute the real dotenv loader using this test environment's packages.
            return self.real_run([sys.executable, *args[1:]], cwd=cwd, env=env)
        with patch.object(updater, 'service_property', side_effect=properties.__getitem__):
            with patch.object(updater, 'Path', side_effect=lambda value: fake_proc if value == '/proc' else Path(value)):
                with patch.object(updater, 'run', side_effect=installed_python):
                    with patch.object(updater, 'service_configuration', side_effect=REAL_CONFIGURATION):
                        url, uid, gid = REAL_SERVICE_URL(self.project)
                        configuration = REAL_CONFIGURATION(self.project)
                        self.assertEqual(configuration['WEBCLOCK_STATE_DIR'], '/from-systemd/state')
                        self.assertEqual(configuration['NOTES_FILE'], '/from-systemd/notes.json')
                        (process / 'environ').write_bytes(environment + b'PYTHON_DOTENV_DISABLED=1\0')
                        self.assertEqual(REAL_CONFIGURATION(self.project), {'PORT': '80', 'HOST': '0.0.0.0'})
        self.assertEqual(url, 'http://127.0.0.1:80')
        self.assertEqual((uid, gid), (os.getuid(), os.getgid()))

    def test_failed_recovery_keeps_backup_and_reports_failure(self):
        with patch.object(updater, 'wait_healthy', side_effect=RuntimeError('crash')):
            with self.assertRaisesRegex(RuntimeError, 'crash'):
                updater.update(self.project)
        backup = next(self.project.glob('.webclock-update-*'))
        self.assertTrue((backup / 'failed-venv').exists())
        manifest = json.loads((backup / 'manifest.json').read_text())
        env = next(item for item in manifest['data'] if item['path'] == str(self.project / '.env'))
        self.assertEqual((backup / env['backup']).read_bytes(), (self.project / '.env').read_bytes())
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

    def managed_installation(self, external=False, previous_support=True):
        (self.remote / 'webclock/services').mkdir(parents=True)
        (self.remote / 'webclock/app.py').write_text('# modular server')
        if previous_support:
            (self.remote / 'webclock/services/auth_service.py').write_text('AUTH_SCHEMA_VERSION = 1\n')
        self.commit('protected baseline')
        self.real_run(['git', 'fetch'], cwd=self.project)
        self.real_run(['git', 'merge', '--ff-only', 'origin/main'], cwd=self.project)
        self.old_head = self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project)
        (self.remote / 'webclock/services/auth_service.py').write_text('AUTH_SCHEMA_VERSION = 1\n# updated\n')
        self.commit('protected update')
        if external:
            self.configuration.update(WEBCLOCK_STATE_DIR=str(self.root / 'private-state'),
                                      NOTES_FILE=str(self.root / 'private-notes.json'))
        state, notes = updater.data_layout(self.project, self.configuration, True)
        state.mkdir()
        (state / 'settings.json').write_text(json.dumps(self.settings))
        notes.write_bytes((self.project / 'manual_notes.json').read_bytes())
        auth = dict(version=1, mode='managed', owner_id='owner', username='admin', password_hash='scrypt:32768:8:1$' + 's' * 16 + '$' + 'a' * 128,
                    session_secret='s' * 43, invite_secret='i' * 43, generation=1, sessions={})
        (state / 'auth.json').write_text(json.dumps(auth))
        (state / 'auth-required').write_text(json.dumps({'version': 1, 'mode': 'managed'}))
        return state, auth

    def public_health_only(self, url, data=None, headers=None):
        self.assertTrue(url.endswith('/api/health'), url)
        self.assertIsNone(data)
        return {'status': 'ok', 'auth_schema': 1, 'deployment_mode': 'managed',
                'device_schema': 2, 'managed_device_schema': 3}

    def test_managed_update_custom_paths_uses_only_public_health(self):
        state, auth = self.managed_installation(external=True)
        with patch.object(updater, 'http_json', side_effect=self.public_health_only), \
             patch.object(updater, 'service_property', side_effect=lambda key: '123' if key == 'MainPID' else 'active'), \
             patch.object(updater.time, 'sleep'):
            updater.update(self.project)
        self.assertEqual(json.loads((state / 'auth.json').read_text()), auth)
        self.assertEqual(list(self.project.glob('.webclock-update-*')), [])

    def test_managed_rollback_keeps_latest_revocations_and_never_reads_private_api(self):
        state, auth = self.managed_installation(external=True)
        def fail_after_change(*args):
            auth['generation'] += 1
            (state / 'auth.json').write_text(json.dumps(auth))
            (state / 'device-access.json').write_text(json.dumps(dict(
                version=1, groups={}, invites={}, devices={'latest': {'status': 'revoked'}}, attempts={})))
            raise RuntimeError('failed new health')
        with patch.object(updater, 'http_json', side_effect=self.public_health_only), \
             patch.object(updater, 'wait_healthy'), patch.object(updater, 'verify_server', side_effect=fail_after_change):
            with self.assertRaisesRegex(RuntimeError, 'failed new health'):
                updater.update(self.project)
        self.assertEqual(json.loads((state / 'auth.json').read_text()), auth)
        self.assertEqual(json.loads((state / 'device-access.json').read_text())['devices']['latest']['status'], 'revoked')
        self.assertEqual(self.real_run(['git', 'rev-parse', 'HEAD'], cwd=self.project), self.old_head)
        self.assertEqual(self.state, 'active')

    def test_managed_rollback_to_unsupported_code_remains_stopped(self):
        state, auth = self.managed_installation(previous_support=False)
        self.fail_pip = True
        with patch.object(updater, 'http_json', side_effect=self.public_health_only), patch.object(updater, 'wait_healthy'):
            with self.assertRaises(subprocess.CalledProcessError):
                updater.update(self.project)
        self.assertEqual(self.state, 'inactive')
        self.assertEqual(json.loads((state / 'auth.json').read_text()), auth)
        self.assertFalse(any(command[:2] == ['systemctl', 'start'] for command in self.calls))

    def test_corrupt_or_missing_protected_auth_stops_before_service_mutations(self):
        state, auth = self.managed_installation()
        for contents in ('{secret-invalid-json', '', json.dumps(dict(auth, mode='self'))):
            (state / 'auth.json').write_text(contents)
            with self.assertRaisesRegex(RuntimeError, 'authorization state') as error:
                updater.update(self.project)
            self.assertNotIn('secret-invalid-json', str(error.exception))
        (state / 'auth.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'authorization state'):
            updater.update(self.project)
        self.assertFalse(any(command[0] == 'systemctl' for command in self.calls))

    def test_mode_changed_during_stop_cannot_start_unsupported_source(self):
        from webclock.services.auth_service import AuthService
        original = self.fake_run
        switched = False
        def setup_during_stop(args, cwd=None):
            nonlocal switched
            result = original(args, cwd=cwd)
            if args[:2] == ['systemctl', 'stop'] and not switched:
                switched = True
                AuthService(self.project / 'webclock_state/auth.json').setup(
                    'admin', 'test-only-password-long', enable_managed_test=True)
            return result
        with patch.object(updater, 'run', side_effect=setup_during_stop), patch.object(updater, 'wait_healthy'):
            with self.assertRaisesRegex(RuntimeError, 'does not support protected'):
                updater.update(self.project)
        self.assertEqual(self.state, 'inactive')
        self.assertFalse(any(command[:2] == ['systemctl', 'start'] for command in self.calls))


if __name__ == '__main__':
    unittest.main()
