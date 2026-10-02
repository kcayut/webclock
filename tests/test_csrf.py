"""Management requests need a token bound to their browser's anonymous session."""
import copy
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import app as clock


class CsrfTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                            ('NOTES_FILE', str(self.root / 'notes.json')),
                            ('ICAL_URL', ''), ('calendar_feed_cache', {})]:
            item = patch.object(clock, name, value)
            item.start()
            self.addCleanup(item.stop)
        for item in (patch.dict(clock.display_settings, copy.deepcopy(clock.DEFAULT_SETTINGS), clear=True),
                     patch.dict(os.environ, DEVICE_API_TOKEN=''),
                     patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network request'))):
            item.start()
            self.addCleanup(item.stop)
        self.client = clock.app.test_client()
        self.token = self.client.get('/api/csrf').json['csrf_token']
        self.headers = {'X-CSRF-Token': self.token}
        self.assertEqual(self.client.post('/add', data={'note_text': 'Keep'}, headers=self.headers).status_code, 302)
        self.assertEqual(self.client.post('/api/control', json={'brightness': 60}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/api/calendar', json={'url': ''}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/api/v1/schedules', json={'id': 'wake', 'name': 'Wake', 'time': '07:30'},
                                          headers=self.headers).status_code, 201)
        self.assertEqual(self.client.post('/api/v1/device/register', json={'id': 'one', 'name': 'One'}).status_code, 201)

    def snapshot(self):
        return ({path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()},
                copy.deepcopy(clock.display_settings))

    def test_every_management_mutation_rejects_missing_and_wrong_tokens_without_writes(self):
        routes = [
            ('POST', '/add', {'data': {'note_text': 'Injected'}}),
            ('POST', '/schedule/1', {'data': {'note_text': 'Changed'}}),
            ('POST', '/toggle/1', {}),
            ('POST', '/delete/1', {}),
            ('POST', '/api/control', {'json': {'brightness': 40}}),
            ('POST', '/api/backup', {'json': self.client.get('/api/backup').json}),
            ('POST', '/api/calendar', {'json': {'url': 'https://calendar.example/new.ics'}}),
            ('PATCH', '/api/calendar', {'json': {'local_display_enabled': False}}),
            ('POST', '/api/v1/schedules', {'json': {'id': 'new', 'name': 'New', 'time': '08:00'}}),
            ('POST', '/api/v1/schedules/preview', {'json': {'id': 'wake'}}),
            ('PUT', '/api/v1/schedules/wake', {'json': {'name': 'Changed'}}),
            ('DELETE', '/api/v1/schedules/wake', {}),
            ('POST', '/api/v1/schedules/wake/skip-next', {}),
            ('POST', '/api/v1/devices/one/commands', {'json': {'action': 'sync'}}),
        ]
        before = self.snapshot()
        for method, route, arguments in routes:
            for headers in ({}, {'X-CSRF-Token': 'wrong'}):
                with self.subTest(method=method, route=route, headers=headers):
                    response = self.client.open(route, method=method, headers=headers, **arguments)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json, {'code': 'csrf_failed',
                        'error': 'CSRF validation failed; reload the management page.'})
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                    self.assertEqual(self.snapshot(), before)

    def test_token_requires_matching_cookie_and_cannot_come_from_query(self):
        other = clock.app.test_client()
        self.assertNotEqual(other.get('/api/csrf').json['csrf_token'], self.token)
        no_cookie = clock.app.test_client(use_cookies=False)
        tampered = clock.app.test_client()
        tampered.set_cookie('webclock_csrf', self.client.get_cookie('webclock_csrf').value + 'tampered')
        before = self.snapshot()
        for client, route, headers in [
            (other, '/api/control', self.headers),
            (no_cookie, '/api/control', self.headers),
            (tampered, '/api/control', self.headers),
            (self.client, '/api/control?csrf_token=' + self.token, {}),
            (self.client, '/api/control', {'X-CSRF-Token': '非ASCII'}),
        ]:
            with self.subTest(route=route, headers=headers):
                response = client.post(route, json={'brightness': 40}, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json['code'], 'csrf_failed')
                self.assertEqual(self.snapshot(), before)
        response = no_cookie.post('/add', data={'note_text': 'Forged', 'csrf_token': self.token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_cross_origin_metadata_is_rejected_even_with_a_valid_token(self):
        before = self.snapshot()
        for metadata in [
            {'Origin': 'https://evil.invalid'}, {'Origin': 'null'},
            {'Referer': 'https://evil.invalid/form'}, {'Referer': 'not a URL'},
            {'Origin': 'http://localhost', 'Referer': 'https://evil.invalid/form'},
            {'Sec-Fetch-Site': 'cross-site'},
        ]:
            with self.subTest(metadata=metadata):
                response = self.client.post('/api/control', json={'brightness': 40},
                                            headers=dict(self.headers, **metadata))
                self.assertEqual(response.status_code, 403)
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                self.assertEqual(self.snapshot(), before)
        for metadata in ({}, {'Origin': 'http://localhost'},
                         {'Referer': 'http://localhost/admin'}, {'Sec-Fetch-Site': 'same-origin'}):
            response = self.client.post('/api/control', json={'brightness': 40},
                                        headers=dict(self.headers, **metadata))
            self.assertEqual(response.status_code, 200)

    def test_native_forms_accept_hidden_tokens_and_keep_validation_errors_private(self):
        for content_type in ('application/x-www-form-urlencoded', 'multipart/form-data'):
            with self.subTest(content_type=content_type):
                response = self.client.post('/add', data={'note_text': 'Form', 'csrf_token': self.token},
                                            content_type=content_type)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                before = self.snapshot()
                response = self.client.post('/add', data={'note_text': 'Draft', 'csrf_token': self.token,
                    'display_start': '2026-10-03T09:00', 'display_end': ''}, content_type=content_type)
                self.assertEqual(response.status_code, 400)
                self.assertIn('value="Draft"', response.text)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                self.assertEqual(self.snapshot(), before)
                response = self.client.post('/delete/1', data={'csrf_token': 'wrong'}, content_type=content_type)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.snapshot(), before)

    def test_delete_requires_post_and_valid_token(self):
        before = self.snapshot()
        raw = clock.app.test_client()
        for method in ('GET', 'HEAD'):
            response = raw.open('/delete/1', method=method)
            self.assertEqual(response.status_code, 405)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.post('/delete/1', data={'csrf_token': self.token}).status_code, 302)
        self.assertEqual(clock.load_notes(), [])

    def test_management_tokens_are_private_and_stable_per_browser(self):
        for route in ('/api/csrf', '/admin', '/schedules', '/api/control', '/api/backup', '/api/calendar',
                      '/api/v1/schedules', '/api/v1/devices'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual(self.client.get('/api/csrf').json['csrf_token'], self.token)
        page = self.client.get('/admin').text
        forms = re.findall(r'<form\b[^>]*method="[Pp][Oo][Ss][Tt]".*?</form>', page, re.DOTALL)
        self.assertTrue(forms)
        for form in forms:
            self.assertIn('name="csrf_token"', form)
            self.assertIn(self.token, form)
        self.assertNotIn('href="/delete/', page)
        fresh = clock.app.test_client()
        response = fresh.get('/api/csrf')
        cookie = response.headers['Set-Cookie']
        self.assertIn('webclock_csrf=', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        self.assertEqual(fresh.get('/api/csrf', headers={'Origin': 'https://evil.invalid'}).status_code, 403)

    def test_public_clock_and_status_do_not_create_or_expose_tokens(self):
        raw = clock.app.test_client()
        for client in (raw, self.client):
            for route in ('/', '/api/status'):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('Set-Cookie', response.headers)
                self.assertNotIn('csrf_token', response.text)
                self.assertNotIn(self.token, response.text)
        response = raw.get('/api/status', headers={'Origin': 'https://public.example'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
        self.assertEqual(set(response.headers['Access-Control-Allow-Methods'].split(', ')), {'GET', 'HEAD', 'OPTIONS'})

    def test_device_posts_keep_bearer_authentication_without_csrf(self):
        raw = clock.app.test_client()
        for token in ('', 'device-test-token'):
            with self.subTest(token=token), patch.dict(os.environ, DEVICE_API_TOKEN=token):
                headers = {'Authorization': 'Bearer ' + token} if token else {}
                for route, payload, expected in [
                    ('register', {'id': 'device', 'name': 'Device'}, 201),
                    ('status', {'id': 'device'}, 200),
                ]:
                    if token:
                        before = self.snapshot()
                        self.assertEqual(raw.post('/api/v1/device/' + route, json=payload).status_code, 401)
                        self.assertEqual(self.snapshot(), before)
                    response = raw.post('/api/v1/device/' + route, json=payload, headers=headers)
                    self.assertEqual(response.status_code, expected)
                    self.assertNotIn('Set-Cookie', response.headers)
                before = self.snapshot()
                self.assertEqual(raw.post('/api/control', json={'brightness': 40}, headers=headers).status_code, 403)
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
