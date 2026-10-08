"""Protected installs close every legacy entry while the public clock stays usable."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService


class AccessControlTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.service = AuthService(self.root / 'auth.json')
        self.service.setup('owner', 'a-long-test-password', enable_managed_test=True)
        for key, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                           ('NOTES_FILE', str(self.root / 'manual_notes.json')),
                           ('ICAL_URL', '')]:
            item = patch.object(clock, key, value)
            item.start()
            self.addCleanup(item.stop)
        for item in [patch.dict(clock.app.config, SECRET_KEY=self.service.session_secret()),
                     patch.dict(clock.display_settings, dict(clock.DEFAULT_SETTINGS, language='ja',
                                                             time_format='12h'), clear=True),
                     patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network'))]:
            item.start()
            self.addCleanup(item.stop)
        self.client = clock.app.test_client()
        self.client.environ_base['wsgi.url_scheme'] = 'https'
        clock.save_json(self.root / 'manual_notes.json', [{'id': 1, 'text': 'PRIVATE-NOTE', 'due_date': ''}])
        clock.save_json(self.root / 'calendar.json', {
            'sources': [{'id': 'private-source', 'name': 'PRIVATE-CALENDAR', 'provider': 'ics',
                         'url': 'https://example.invalid/PRIVATE-ICS', 'display_enabled': False}],
            'local_display_enabled': False})

    def request(self, path, method='GET', **kwargs):
        return self.client.open(path, method=method, base_url='https://localhost', **kwargs)

    def login(self):
        token = self.request('/api/csrf').json['csrf_token']
        response = self.request('/login', 'POST', data={
            'username': 'owner', 'password': 'a-long-test-password', 'csrf_token': token})
        self.assertIn(response.status_code, (200, 302, 303), response.text)
        return self.request('/api/csrf').json['csrf_token']

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}

    def test_all_registered_management_routes_require_identity_before_data_or_mutation(self):
        before = self.snapshot()
        public = {'index', 'status', 'public_time', 'health', 'static', 'service_worker',
                  'csrf_token', 'auth.login', 'managed_device.prepare', 'managed_device.join'}
        seen = set()
        rules = [(rule, str(rule).replace('<any(schedules,events):kind>', kind))
                 for rule in clock.app.url_map.iter_rules()
                 for kind in (('schedules', 'events') if '<any(schedules,events):kind>' in str(rule) else ('',))]
        for rule, route in rules:
            if rule.endpoint in public:
                continue
            import re
            route = re.sub(r'<int:[^>]+>', '1', route)
            route = re.sub(r'<[^>]+>', 'missing', route)
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                seen.add((route, method))
                response = self.request(route, method, json={} if method != 'GET' else None)
                with self.subTest(route=route, method=method):
                    expected = 403 if route.startswith(('/api/v1/device/', '/api/v2/device/token/')) else 401
                    if route.startswith('/api/') or method != 'GET':
                        self.assertEqual(response.status_code, expected, response.text)
                        self.assertTrue(response.is_json)
                    else:
                        self.assertEqual(response.status_code, 302)
                    self.assertNotIn('PRIVATE-', response.text)
                    self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertGreater(len(seen), 25)
        self.assertEqual(self.snapshot(), before)

    def test_public_shell_and_time_are_independent_of_admin_cookie(self):
        for authenticated in (False, True):
            if authenticated:
                self.login()
            for path in ('/', '/api/time', '/api/status', '/api/health'):
                response = self.request(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('PRIVATE-', response.text)
                self.assertNotIn('Set-Cookie', response.headers)
                self.assertNotIn('csrf_token', response.text)
            page = self.request('/').text
            self.assertIn('WebClockCore.start', page)
            self.assertIn('var currentLanguage = "zh-TW";', page)
            status = self.request('/api/status').json
            self.assertEqual(set(status), {'server_timestamp', 'events', 'next_event'})
            self.assertEqual(status['events'], [])
            self.assertIsNone(status['next_event'])
            self.assertEqual(set(self.request('/api/time').json), {'server_timestamp'})
        self.assertTrue(self.request('/api/health').json['managed_devices_ready'])

    def test_shared_token_and_admin_session_never_authorize_legacy_display(self):
        with patch.dict(os.environ, DEVICE_API_TOKEN='legacy-shared'):
            for logged in (False, True):
                if logged:
                    self.login()
                for path in ('/api/v1/device/config', '/api/v1/device/schedules', '/api/v1/device/holidays'):
                    response = self.request(path, headers={'Authorization': 'Bearer legacy-shared',
                                                          'If-None-Match': '*'})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn('ETag', response.headers)
                self.assertEqual(self.request('/api/v1/browser-alarms').status_code, 401)
        self.assertEqual(self.request('/api/v1/schedules').status_code, 200)

    def test_management_session_csrf_logout_and_origin_are_independent(self):
        token = self.login()
        self.assertEqual(self.request('/admin').status_code, 200)
        self.assertIn('action="/logout"', self.request('/admin').text)
        self.assertEqual(self.request('/api/backup').json.keys(), {'version', 'settings', 'notes'})
        for headers in ({}, {'X-CSRF-Token': 'wrong'}, {'X-CSRF-Token': token, 'Origin': 'https://evil.invalid'}):
            self.assertEqual(self.request('/api/control', 'POST', json={'brightness': 42}, headers=headers).status_code, 403)
        self.assertEqual(self.request('/api/control', 'POST', json={'brightness': 42},
                                      headers={'X-CSRF-Token': token}).status_code, 200)
        self.assertEqual(self.request('/api/calendar', headers={'Origin': 'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.request('/logout', 'POST', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.request('/api/backup').status_code, 401)
        self.assertEqual(self.request('/api/time').status_code, 200)

    def test_corrupt_or_missing_protected_state_keeps_private_endpoints_closed(self):
        self.login()
        for value in ('{broken', None):
            if value is None:
                (self.root / 'auth.json').unlink()
            else:
                (self.root / 'auth.json').write_text(value)
            self.assertEqual(self.request('/api/calendar').status_code, 503)
            self.assertEqual(self.request('/admin').status_code, 503)
            self.assertEqual(self.request('/api/health').status_code, 503)
            self.assertEqual(self.request('/').status_code, 200)
            self.assertEqual(self.request('/api/time').status_code, 200)
            self.assertNotIn('settings', self.request('/api/status').json)

    def test_group_mutations_require_management_identity_and_csrf(self):
        token = self.login()
        self.assertEqual(self.request('/api/v1/groups', 'POST', json={'name': 'Living room'}).status_code, 403)
        created = self.request('/api/v1/groups', 'POST', json={'name': 'Living room'},
                               headers={'X-CSRF-Token': token})
        self.assertEqual(created.status_code, 201, created.text)
        response = self.request('/api/v1/groups')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Living room', response.text)
        self.assertNotIn('invite_secret', response.text)
        self.assertNotIn('credential_digest', response.text)


if __name__ == '__main__':
    unittest.main()
