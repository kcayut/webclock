"""Explicit host CLI migration preserves self-mode data and requires real enrollment."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from scripts import manage_auth
from webclock.services.auth_service import AuthService
from webclock.services.device_access_service import _RATE_WINDOWS
from webclock.services.device_service import DeviceService
from webclock.services.schedule_service import validate_schedule
from webclock.services.storage import load_json, save_json


PASSWORD = 'synthetic migration password'


class ManageAuthTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.service = AuthService(self.root / 'auth.json')

    def setup_cli(self, flag='--enable-managed'):
        output = StringIO()
        with patch.object(manage_auth, 'load_dotenv'), patch.object(manage_auth.getpass, 'getpass', return_value=PASSWORD), \
                redirect_stdout(output), redirect_stderr(output):
            result = manage_auth.main(['--state-dir', str(self.root), 'setup', '--username', 'owner', flag])
        self.assertNotIn(PASSWORD, output.getvalue())
        return result

    def test_cli_requires_opt_in_before_password_and_keeps_old_flag_compatible(self):
        with patch.object(manage_auth, 'load_dotenv'), patch.object(manage_auth.getpass, 'getpass') as password, \
                redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            manage_auth.main(['--state-dir', str(self.root), 'setup', '--username', 'owner'])
        self.assertEqual(error.exception.code, 2)
        password.assert_not_called()
        self.assertFalse(self.service.path.exists())
        self.assertEqual(self.setup_cli('--enable-managed-test'), 0)
        self.assertEqual(self.service.mode(), 'managed')
        before = self.service.path.read_bytes()
        self.assertEqual(self.setup_cli(), 1)
        self.assertEqual(self.service.path.read_bytes(), before)

    def test_self_migration_keeps_data_identity_and_requires_six_character_join(self):
        settings = dict(clock.DEFAULT_SETTINGS, night=dict(clock.DEFAULT_NIGHT))
        fixtures = {
            'settings.json': settings,
            'manual_notes.json': [{'id': 1, 'text': 'Private migrated note', 'due_date': ''}],
            'schedules.json': [validate_schedule({'id': 'alarm', 'name': 'Migrated alarm', 'time': '07:30',
                'calendar_link': {'mode': 'day', 'source_ids': ['work']}})],
            'calendar.json': {'sources': [{'id': 'work', 'name': 'Private source', 'provider': 'ics',
                'url': 'https://calendar.invalid/private.ics', 'display_enabled': False}], 'local_display_enabled': True},
        }
        for name, value in fixtures.items():
            save_json(self.root / name, value)
        devices = DeviceService(self.root / 'devices.json')
        devices.register({'id': 'old-observation', 'name': 'Reported name'})
        devices.rename('old-observation', {'name': 'Desk clock'})
        command = devices.command('old-observation', 'sync')
        devices.report({'id': 'old-observation', 'device_type': 'browser',
            'capabilities': {'display': True, 'audio': False}, 'acknowledged_commands': [command['id']]})
        for item in [patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                     patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')),
                     patch.object(clock, 'ICAL_URL', ''), patch.dict(clock.display_settings, settings, clear=True),
                     patch.dict(clock.app.config, SECRET_KEY=self.service.session_secret()),
                     patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network'))]:
            item.start()
            self.addCleanup(item.stop)
        _RATE_WINDOWS.clear()
        client = clock.app.test_client()
        base = 'https://localhost'
        csrf = client.get('/api/csrf', base_url=base).json['csrf_token']
        group = client.post('/api/v1/groups/initialize', base_url=base, json={}, headers={'X-CSRF-Token': csrf}).json
        self.assertEqual(group['content']['manual_note_ids'], [1])
        before_auth = self.service.state()
        before = {path.name: path.read_bytes() for path in self.root.iterdir() if path.name != 'auth.json'}
        self.assertEqual(self.setup_cli(), 0)
        after = self.service.state()
        for key in ('owner_id', 'invite_secret'):
            self.assertEqual(after[key], before_auth[key])
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content, name)
        self.assertEqual(load_json(self.root / 'device-access.json', {})['devices'], {})
        self.assertEqual(devices.list()[0]['name'], 'Desk clock')
        self.assertEqual(devices.list()[0]['sync_status']['state'], 'confirmed')
        # Simulate the documented service restart with the new session secret.
        clock.app.config['SECRET_KEY'] = AuthService(self.service.path).session_secret()
        client = clock.app.test_client()
        self.assertEqual(client.get('/api/v1/devices', base_url=base).status_code, 401)
        for endpoint in ('config', 'schedules', 'holidays'):
            denied = client.get('/api/v1/device/' + endpoint, base_url=base,
                                headers={'Authorization': 'Bearer old-shared-token'})
            self.assertEqual(denied.status_code, 403)
            self.assertNotIn('Private', denied.text)
        self.assertEqual(client.get('/api/status', base_url=base).json['events'], [])
        csrf = client.get('/api/csrf', base_url=base).json['csrf_token']
        login = client.post('/login', base_url=base, json={'username': 'owner', 'password': PASSWORD},
                            headers={'X-CSRF-Token': csrf})
        self.assertEqual(login.status_code, 200)
        invitation = client.post('/api/v1/groups/' + group['id'] + '/invite', base_url=base,
            json={'capacity': 1}, headers={'X-CSRF-Token': login.json['csrf_token']}).json
        self.assertEqual(len(invitation['code']), 6)
        display = clock.app.test_client()
        self.assertEqual(display.get('/api/v2/device/identity', base_url=base).status_code, 401)
        csrf = display.get('/api/csrf', base_url=base).json['csrf_token']
        headers = {'X-CSRF-Token': csrf}
        attempt = display.post('/api/v2/device/join/prepare', base_url=base, json={}, headers=headers)
        self.assertEqual(attempt.status_code, 201)
        self.assertTrue(display.get_cookie('webclock_device', path='/api/v2/device').secure)
        joined = display.post('/api/v2/device/join', base_url=base,
            json={'attempt_id': attempt.json['attempt_id'], 'code': invitation['code']}, headers=headers)
        self.assertEqual(joined.status_code, 201)
        identity = joined.json['identity']
        self.assertNotEqual(identity['device_id'], 'old-observation')
        self.assertEqual(identity['owner_id'], before_auth['owner_id'])
        self.assertEqual(identity['group_id'], group['id'])
        self.assertEqual(display.get('/api/v2/device/identity', base_url=base).json['identity'], identity)
        self.assertEqual((self.root / 'devices.json').read_bytes(), before['devices.json'])
        self.assertEqual((self.root / 'calendar.json').read_bytes(), before['calendar.json'])
        self.assertEqual((self.root / 'schedules.json').read_bytes(), before['schedules.json'])


if __name__ == '__main__':
    unittest.main()
