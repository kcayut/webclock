"""Portable managed backups cross storage layouts without exposing private data."""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.storage import save_json


PASSWORD = 'administrator test password'
BACKUP_PASSWORD = 'backup test password'
BASE = '/api/backup/complete/'


class CompleteBackupApiTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / 'bare-metal'
        self.source.mkdir()
        self.auth = AuthService(self.source / 'auth.json')
        self.owner = self.auth.setup('owner', PASSWORD, enable_managed=True)['owner_id']
        self.member = self.auth.create_account('member', PASSWORD)['owner_id']
        self.notes = self.root / 'custom-reminders.json'
        save_json(self.notes, [{'id': 1, 'text': 'portable reminder', 'due_date': ''}])
        save_json(self.source / 'settings.json', dict(clock.DEFAULT_SETTINGS, brightness=37))
        save_json(self.source / 'owners' / self.member / 'calendar.json',
                  {'url': 'https://example.invalid/member-secret.ics'})
        save_json(self.source / 'owners' / self.member / 'manual_notes.json',
                  [{'id': 2, 'text': 'member private reminder', 'due_date': ''}])
        self.addCleanup(clock._auth_services.clear)

    @contextmanager
    def installation(self, path, notes=None, ha=False):
        with patch.object(clock, 'SETTINGS_FILE', str(path / 'settings.json')), \
                patch.object(clock, 'NOTES_FILE', str(notes or path / 'manual_notes.json')), \
                patch.object(clock, 'ICAL_URL', 'https://example.invalid/root-secret.ics' if path == self.source else ''), \
                patch.dict(clock.display_settings, clock.DEFAULT_SETTINGS, clear=True), \
                patch.dict(clock.app.config, SECRET_KEY=AuthService(path / 'auth.json').session_secret()), \
                patch.dict('os.environ', WEBCLOCK_HA_APP='1' if ha else '0', WEBCLOCK_INGRESS='1' if ha else '0'):
            client = clock.app.test_client()
            if ha:
                client.environ_base.update(SERVER_PORT='8099', REMOTE_ADDR='172.30.32.2',
                    HTTP_X_INGRESS_PATH='/api/hassio_ingress/test',
                    HTTP_X_FORWARDED_PROTO='https', HTTP_X_FORWARDED_HOST='localhost')
            self.client = client
            self.ha = ha
            self.csrf()
            yield client

    def request(self, method, path, **kwargs):
        if self.ha:
            kwargs['environ_overrides'] = {'SERVER_PORT': '8099', 'REMOTE_ADDR': '172.30.32.2'}
        return getattr(self.client, method)(path, base_url='https://localhost', **kwargs)

    def csrf(self):
        response = self.request('get', '/api/csrf')
        self.assertEqual(response.status_code, 200, response.text)
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = response.json['csrf_token']

    def login(self, username='owner'):
        result = self.request('post', '/login', json=dict(username=username, password=PASSWORD))
        self.assertEqual(result.status_code, 200, result.text)
        self.csrf()

    def archive(self):
        with self.installation(self.source, self.notes):
            self.login()
            result = self.request('post', BASE + 'export', json=dict(password=BACKUP_PASSWORD,
                username='owner', admin_password=PASSWORD))
            self.assertEqual(result.status_code, 200, result.data[:200])
            self.assertEqual(result.headers['Cache-Control'], 'no-store')
            self.assertNotIn(b'root-secret', result.data)
            self.assertNotIn(b'member private', result.data)
            return result.data

    def upload(self, path, raw, **extra):
        return self.request('post', BASE + path, data=dict(file=(BytesIO(raw), 'backup.webclock'),
            password=BACKUP_PASSWORD, **extra), content_type='multipart/form-data')

    def test_managed_all_owners_and_legacy_calendar_move_to_ha_data(self):
        raw = self.archive()
        target = self.root / 'ha-data'
        target.mkdir()
        save_json(target / 'options.json', {'platform': 'keep'})
        with self.installation(target, ha=True):
            preview = self.upload('preview', raw)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json['preserve_devices'])
            self.assertEqual(preview.json['summary']['accounts'], 2)
            self.assertNotIn('secret.ics', preview.text)
            self.assertFalse((target / 'auth.json').exists(), 'Preview must not import')
            restored = self.upload('restore', raw, ticket=preview.json['ticket'], confirm='yes')
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json['redirect'], '/api/hassio_ingress/test/login')
            self.assertEqual(AuthService(target / 'auth.json').mode(), 'managed')
            self.assertIn('root-secret.ics', (target / 'calendar.json').read_text())
            self.assertIn('portable reminder', (target / 'manual_notes.json').read_text())
            self.assertIn('member-secret.ics', (target / 'owners' / self.member / 'calendar.json').read_text())
            self.assertIn('keep', (target / 'options.json').read_text())
            self.csrf()
            self.login()
            self.assertEqual(self.request('get', '/api/control').json['settings']['brightness'], 37)
            self.assertIn('root-secret.ics', self.request('get', '/api/calendar').text)
            self.assertNotIn('member-secret.ics', self.request('get', '/api/calendar').text)
            self.login('member')
            self.assertIn('member-secret.ics', self.request('get', '/api/calendar').text)
            self.assertNotIn('root-secret.ics', self.request('get', '/api/calendar').text)

    def test_preview_binds_file_current_data_confirmation_and_password(self):
        raw = self.archive()
        target = self.root / 'new'
        target.mkdir()
        with self.installation(target):
            preview = self.upload('preview', raw)
            self.assertEqual(preview.status_code, 200, preview.text)
            ticket = preview.json['ticket']
            denied = self.upload('restore', raw, ticket=ticket)
            self.assertEqual(denied.status_code, 409)
            corrupted = self.upload('preview', raw[:-1] + bytes([raw[-1] ^ 1]))
            self.assertEqual(corrupted.status_code, 400)
            self.assertFalse((target / 'auth.json').exists())
            save_json(target / 'manual_notes.json', [{'id': 1, 'text': 'new draft saved', 'due_date': ''}])
            denied = self.upload('restore', raw, ticket=ticket, confirm='yes')
            self.assertEqual((denied.status_code, denied.json['code']), (409, 'preview_changed'))
            self.assertIn('new draft saved', (target / 'manual_notes.json').read_text())
            self.assertFalse((target / 'auth.json').exists())

    def test_all_account_export_requires_admin_reauthentication_and_csrf(self):
        with self.installation(self.source, self.notes):
            self.login('member')
            values = dict(password=BACKUP_PASSWORD, username='owner', admin_password=PASSWORD)
            self.assertEqual(self.request('post', BASE + 'export', json=values).status_code, 403)
            self.login()
            values['admin_password'] = 'wrong'
            response = self.request('post', BASE + 'export', json=values)
            self.assertEqual((response.status_code, response.json['code']), (401, 'invalid_credentials'))
            self.client.environ_base.pop('HTTP_X_CSRF_TOKEN')
            self.assertEqual(self.request('post', BASE + 'export', json=values).status_code, 403)

    def test_new_device_observation_invalidates_preview_before_changing_credential_policy(self):
        from webclock.services.device_service import DeviceService
        raw = self.archive()
        target = self.root / 'fresh-observation'
        target.mkdir()
        with self.installation(target, ha=True):
            preview = self.upload('preview', raw)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json['preserve_devices'])
            devices = DeviceService(target / 'devices.json')
            devices.register({'id': 'new-observation', 'name': 'Observed display'})
            before = (target / 'devices.json').read_bytes()
            restored = self.upload('restore', raw, ticket=preview.json['ticket'], confirm='yes')
            self.assertEqual((restored.status_code, restored.json['code']), (409, 'preview_changed'))
            self.assertEqual((target / 'devices.json').read_bytes(), before)
            self.assertFalse((target / 'auth.json').exists())


if __name__ == '__main__':
    unittest.main()
