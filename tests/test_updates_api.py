"""Only signed-in administrators may ask the host to update."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.api import updates
from webclock.services.auth_service import AuthService


class UpdatesApiTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth = AuthService(self.root / 'auth.json')
        self.auth.setup('admin', 'administrator test password', enable_managed=True)
        self.auth.create_account('member', 'member test password')
        for change in (patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                       patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')),
                       patch.dict(clock.app.config, SECRET_KEY=self.auth.session_secret()),
                       patch.dict('os.environ', {'WEBCLOCK_HA_APP': '0'})):
            change.start()
            self.addCleanup(change.stop)
        self.admin, self.member, self.anonymous = [clock.app.test_client() for _ in range(3)]
        self.call(self.admin, '/login', 'POST', dict(username='admin', password='administrator test password'))
        self.call(self.member, '/login', 'POST', dict(username='member', password='member test password'))
        helper = patch.object(updates, 'updater_request', return_value=dict(ok=True, status=dict(
            supported=True, current_version='1.1.0', channel='stable', auto_update=True,
            state='idle', update_available=True, latest_version='1.2.0')))
        self.helper = helper.start()
        self.addCleanup(helper.stop)

    def call(self, client, path='/api/updates', method='GET', data=None, headers=None):
        headers = dict(headers or {})
        if method != 'GET':
            headers['X-CSRF-Token'] = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        return client.open(path, method=method, json=data, headers=headers, base_url='https://localhost')

    def test_admin_can_check_configure_and_install_only_fixed_fields(self):
        self.assertTrue(self.call(self.admin).json['writable'])
        for path, action, data in (
                ('check', 'check', {}),
                ('settings', 'configure', dict(channel='beta', auto_update=False)),
                ('install', 'install', dict(expected_version='1.2.0'))):
            response = self.call(self.admin, '/api/updates/' + path, 'POST', data)
            self.assertEqual(response.status_code, 200, response.text)
            self.helper.assert_called_with(action, **data)
        self.assertEqual(self.call(self.admin).headers['Cache-Control'], 'no-store')

    def test_anonymous_members_and_cross_origin_never_reach_helper(self):
        for client, expected in ((self.anonymous, 401), (self.member, 403)):
            self.assertEqual(self.call(client).status_code, expected)
            self.assertEqual(self.call(client, '/api/updates/install', 'POST',
                                       dict(expected_version='1.2.0')).status_code, expected)
        self.assertEqual(self.call(self.admin, headers={'Origin': 'https://other.invalid'}).status_code, 403)
        self.helper.assert_not_called()

    def test_csrf_and_invalid_values_never_reach_helper(self):
        self.assertEqual(self.admin.post('/api/updates/check', json={}, base_url='https://localhost').status_code, 403)
        for path, data in (
                ('check', dict(url='https://other.invalid/payload')),
                ('settings', dict(channel='main', auto_update=True)),
                ('settings', dict(channel='stable', auto_update='true')),
                ('install', dict(expected_version=['1.2.0'])),
                ('install', dict(expected_version='1.2.0', command='sudo anything'))):
            self.assertEqual(self.call(self.admin, '/api/updates/' + path, 'POST', data).status_code, 400)
        self.helper.assert_not_called()

    def test_self_mode_cannot_trigger_machine_changes(self):
        with patch.object(AuthService, 'mode', return_value='self'):
            response = self.call(self.anonymous)
            self.assertFalse(response.json['writable'])
            self.assertEqual(response.json['reason'], 'managed_required')
            self.helper.reset_mock()
            response = self.call(self.anonymous, '/api/updates/check', 'POST', {})
            self.assertEqual(response.status_code, 403)
            self.helper.assert_not_called()

    def test_ha_never_uses_bare_metal_helper(self):
        # HA App requests also require ingress; exercise the shared platform check directly.
        with patch.object(updates, 'platform_managed', return_value=True):
            response = self.call(self.admin)
            self.assertFalse(response.json['supported'])
            self.assertEqual(response.json['reason'], 'unsupported')
            self.assertEqual(self.call(self.admin, '/api/updates/check', 'POST', {}).status_code, 409)
            self.helper.assert_not_called()

    def test_missing_helper_is_an_explicit_setup_state(self):
        self.helper.side_effect = FileNotFoundError()
        with patch.object(updates, 'CONFIG_PATH', str(self.root / 'missing.json')):
            response = self.call(self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['supported'])
        self.assertEqual(response.json['reason'], 'not_configured')
        self.assertEqual(self.call(self.admin, '/api/updates/check', 'POST', {}).status_code, 503)

    def test_restarting_helper_is_temporary_not_a_setup_state(self):
        self.helper.side_effect = ConnectionRefusedError()
        (self.root / 'updater.json').write_text('{}')
        with patch.object(updates, 'CONFIG_PATH', str(self.root / 'updater.json')):
            response = self.call(self.admin)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error'], 'updater_unavailable')

    def test_busy_helper_is_a_conflict(self):
        self.helper.return_value = dict(ok=False, status={}, error='busy')
        response = self.call(self.admin, '/api/updates/install', 'POST', dict(expected_version='1.2.0'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error'], 'busy')


if __name__ == '__main__':
    unittest.main()
