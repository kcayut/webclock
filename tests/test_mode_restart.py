"""Cold owner selection and per-owner feed caches must not cross account scopes."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import g

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.storage import save_json


PASSWORD = 'original administrator password'
PROJECT = Path(__file__).resolve().parents[1]


class ModeRestartTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.auth = AuthService(self.root / 'auth.json')
        self.a = self.auth.setup('A', PASSWORD, enable_managed=True)['owner_id']
        self.b = self.auth.create_account('B', 'another account password')['owner_id']
        save_json(self.root / 'settings.json', dict(clock.DEFAULT_SETTINGS, brightness=11))
        save_json(self.root / 'manual_notes.json', [])
        save_json(self.root / 'owners' / self.b / 'settings.json', dict(clock.DEFAULT_SETTINGS, brightness=88))

    def test_restart_with_member_primary_keeps_original_owner_settings_separate(self):
        self.auth.switch_mode('self', self.b, admin_owner_id=self.a, password=PASSWORD,
                              expected_generation=self.auth.state()['generation'], confirm_shared=True)
        code = '''
import json
import app as clock
service = clock.auth_service()
state = service.state()
primary_before = clock.app.test_client().get('/api/control').json['settings']['brightness']
service.switch_mode('managed', state['owner_id'], admin_owner_id=state['administrator_id'],
                    password='original administrator password', expected_generation=state['generation'])
client = clock.app.test_client()
csrf = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
login = client.post('/login', base_url='https://localhost',
    json={'username': 'A', 'password': 'original administrator password'}, headers={'X-CSRF-Token': csrf})
assert login.status_code == 200, login.text
original = client.get('/api/control', base_url='https://localhost').json['settings']['brightness']
print(json.dumps({'primary': primary_before, 'original': original}))
'''
        environment = dict(os.environ, WEBCLOCK_STATE_DIR=str(self.root),
                           NOTES_FILE=str(self.root / 'manual_notes.json'), ICAL_URL='', WEBCLOCK_HA_APP='0')
        result = subprocess.run([sys.executable, '-c', code], cwd=PROJECT, env=environment,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'primary': 88, 'original': 11})

    def test_alternating_owners_preserve_other_owner_feed_cache(self):
        for owner, directory, source in ((self.a, self.root, 'a'),
                                        (self.b, self.root / 'owners' / self.b, 'b')):
            save_json(directory / 'calendar.json', {'local_display_enabled': False, 'sources': [{
                'id': source, 'name': source, 'provider': 'ics', 'url': 'https://example.invalid/' + source,
                'display_enabled': True}]})
        payload = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        with patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')), \
                patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')), \
                patch.dict(clock.calendar_feed_cache, {}, clear=True), \
                patch.object(clock.requests, 'get', return_value=SimpleNamespace(
                    content=payload, raise_for_status=lambda: None)) as fetch:
            for owner, source in ((self.a, 'a'), (self.b, 'b'), (self.a, 'a'), (self.b, 'b')):
                with clock.app.test_request_context('/'):
                    g.owner_id = owner
                    self.assertEqual(clock.get_calendar_events(now, now + timedelta(days=1), [source]), [])
            self.assertEqual(fetch.call_count, 2, 'Each owner should retain its feed until the normal TTL expires')
            self.assertEqual({key[0] for key in clock.calendar_feed_cache},
                             {str(self.root), str(self.root / 'owners' / self.b)})

    def test_nonroot_device_never_uses_another_primary_owners_cached_settings(self):
        third = self.auth.create_account('C', 'third account password')['owner_id']
        save_json(self.root / 'owners' / third / 'settings.json', dict(clock.DEFAULT_SETTINGS, brightness=33))
        with patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')), \
                patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')), \
                patch.object(clock, 'ICAL_URL', ''), \
                patch.dict(clock.display_settings, dict(clock.DEFAULT_SETTINGS, brightness=11), clear=True):
            with clock.app.test_request_context('/'):
                g.owner_id = self.b
                access = clock.group_service(read_only=True)
                group = access.create_group(self.b, {'name': 'B device'})
                invitation = access.create_invite(self.b, group['id'])
                prepared = access.prepare(self.b, 'browser')
                access.join(self.b, prepared['token'], prepared['attempt_id'], invitation['code'], 'browser')
            for mode in ('self', 'managed'):
                self.auth.switch_mode(mode, third, admin_owner_id=self.a, password=PASSWORD,
                    expected_generation=self.auth.state()['generation'], confirm_shared=True)
            client = clock.app.test_client()
            client.set_cookie('webclock_device', prepared['token'], path='/api/v2/device')
            response = client.get('/api/v2/device/display', base_url='https://localhost')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json['identity']['owner_id'], self.b)
            self.assertEqual(response.json['settings']['brightness'], 88)


if __name__ == '__main__':
    unittest.main()
