"""A/B round trips exercise real HTTP scopes, cold backups and device credentials."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.storage import save_json, load_json
from webclock.services.device_access_service import _RATE_WINDOWS


PASSWORD = 'administrator test password'
MEMBER_PASSWORD = 'member private password'


class ModeSpacesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.root = self.folder / 'state'
        self.auth = AuthService(self.root / 'auth.json')
        self.auth.setup('admin', PASSWORD, enable_managed=True)
        self.a = self.auth.owner_id()
        self.b = self.auth.create_account('member', MEMBER_PASSWORD)['owner_id']
        for change in [patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                       patch.object(clock, 'ROOT', self.folder),
                       patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')),
                       patch.object(clock, 'ICAL_URL', ''),
                       patch.dict(clock.display_settings, clock.DEFAULT_SETTINGS, clear=True),
                       patch.dict(clock.app.config, SECRET_KEY=self.auth.session_secret()),
                       patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected private polling'))]:
            change.start()
            self.addCleanup(change.stop)
        _RATE_WINDOWS.clear()
        self.clients = [clock.app.test_client() for _ in range(3)]
        self.admin, self.member, self.anonymous = self.clients
        self.login(self.admin, 'admin', PASSWORD)
        self.login(self.member, 'member', MEMBER_PASSWORD)

    def call(self, client, path, method='GET', data=None, **kwargs):
        headers = kwargs.pop('headers', {})
        if method not in ('GET', 'HEAD'):
            csrf = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
            headers = dict(headers, **{'X-CSRF-Token': csrf})
        return client.open(path, method=method, base_url='https://localhost', json=data, headers=headers, **kwargs)

    def login(self, client, username, password):
        result = self.call(client, '/login', 'POST', dict(username=username, password=password))
        self.assertEqual(result.status_code, 200, result.text)

    def preview(self, client, owner, mode='self'):
        result = self.call(client, '/api/mode/preview', 'POST',
                           dict(mode=mode, primary_owner_id=owner, username='admin', password=PASSWORD))
        self.assertEqual(result.status_code, 200, result.text)
        return result.json

    def switch(self, client, owner, mode='self', preview=None):
        preview = preview or self.preview(client, owner, mode)
        data = dict(mode=mode, primary_owner_id=owner, username='admin', password=PASSWORD,
                    revision=preview['revision'], generation=preview['generation'], confirm_shared=True)
        return self.call(client, '/api/mode/switch', 'POST', data)

    def group_device(self, client):
        group = self.call(client, '/api/v1/groups/initialize', 'POST', {})
        self.assertEqual(group.status_code, 200, group.text)
        invite = self.call(client, '/api/v1/groups/' + group.json['id'] + '/invite', 'POST', {})
        device = clock.app.test_client()
        prepared = self.call(device, '/api/v2/device/join/prepare', 'POST', {})
        joined = self.call(device, '/api/v2/device/join', 'POST',
                           dict(attempt_id=prepared.json['attempt_id'], code=invite.json['code']))
        self.assertEqual(joined.status_code, 201, joined.text)
        return device, joined.json['identity']

    def note(self, client, text):
        data = dict(version=1, settings=dict(clock.DEFAULT_SETTINGS, brightness=0, time_format='12h'),
                    notes=[dict(id=7, text=text, due_date='', enabled=True)])
        result = self.call(client, '/api/backup', 'POST', data)
        self.assertEqual(result.status_code, 200, result.text)

    def test_round_trip_retains_ids_preferences_and_dormant_device_owner(self):
        self.note(self.admin, 'A private')
        self.note(self.member, 'B private')
        ad, ai = self.group_device(self.admin)
        bd, bi = self.group_device(self.member)
        self.assertEqual(ai['owner_id'], self.a)
        self.assertEqual(bi['owner_id'], self.b)
        for device, label in ((ad, 'A private'), (bd, 'B private')):
            result = self.call(device, '/api/v2/device/display')
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([row['text'] for row in result.json['events']], [label])
        b_bytes = (self.root / 'owners' / self.b / 'manual_notes.json').read_bytes()
        old_csrf = self.member.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        preview = self.preview(self.admin, self.a)
        self.assertEqual({row['owner_id']: row['active'] for row in preview['spaces']}, {self.a: True, self.b: False})
        self.assertEqual(preview['public_content'], [])
        result = self.switch(self.admin, self.a, preview=preview)
        self.assertEqual(result.status_code, 200, result.text)
        backup = self.folder / '.webclock-mode-backups-state' / result.json['backup_id']
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertTrue((backup / 'data/state/owners' / self.b / 'manual_notes.json').exists())
        self.assertEqual(self.call(bd, '/api/v2/device/display').status_code, 403)
        self.assertEqual(self.call(ad, '/api/v2/device/display').status_code, 200)
        exported = self.call(self.anonymous, '/api/backup')
        self.assertIn('A private', exported.text)
        self.assertNotIn('B private', exported.text)
        stale = self.member.post('/api/control', base_url='https://localhost', json={'brightness': 99},
                                 headers={'X-CSRF-Token': old_csrf})
        self.assertEqual(stale.status_code, 403)
        self.note(self.anonymous, 'A edited in self')
        result = self.switch(self.anonymous, self.a, 'managed')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.call(self.member, '/api/backup').status_code, 401)
        self.login(self.member, 'member', MEMBER_PASSWORD)
        self.login(self.admin, 'admin', PASSWORD)
        self.assertIn('A edited in self', self.call(self.admin, '/api/backup').text)
        self.assertIn('B private', self.call(self.member, '/api/backup').text)
        self.assertEqual((self.root / 'owners' / self.b / 'manual_notes.json').read_bytes(), b_bytes)
        self.assertEqual(self.call(bd, '/api/v2/device/identity').json['identity']['device_id'], bi['device_id'])
        self.assertEqual(self.call(bd, '/api/v2/device/display').json['settings']['brightness'], 0)
        self.assertEqual(self.call(self.member, '/api/control').json['settings']['time_format'], '12h')

    def test_select_member_as_primary_does_not_change_role_or_merge_spaces(self):
        self.note(self.admin, 'A secret')
        self.note(self.member, 'B content')
        self.assertEqual(self.switch(self.admin, self.b).status_code, 200)
        self.assertIn('B content', self.call(self.anonymous, '/api/backup').text)
        self.assertNotIn('A secret', self.call(self.anonymous, '/api/backup').text)
        self.note(self.anonymous, 'B self edit')
        self.assertEqual(self.switch(self.anonymous, self.b, 'managed').status_code, 200)
        self.login(self.member, 'member', MEMBER_PASSWORD)
        self.assertIn('B self edit', self.call(self.member, '/api/backup').text)
        self.assertEqual(self.auth.state()['accounts'][self.b]['role'], 'member')
        self.assertEqual(self.call(self.member, '/api/accounts').status_code, 403)
        self.assertEqual(self.call(self.member, '/mode').status_code, 403)

    def test_web_setup_requires_host_code_https_and_single_use(self):
        path = self.folder / 'fresh' / 'settings.json'
        with patch.object(clock, 'SETTINGS_FILE', str(path)), patch.object(clock, 'NOTES_FILE', str(path.with_name('manual_notes.json'))):
            fresh = clock.auth_service()
            browser = clock.app.test_client()
            self.assertEqual(self.call(browser, '/setup').status_code, 200)
            csrf = browser.get('/api/csrf').json['csrf_token']
            self.assertEqual(browser.post('/setup', json={'code': 'wrong'}, headers={'X-CSRF-Token': csrf}).status_code, 403)
            issued = fresh.issue_setup_code()
            data = dict(code=issued['code'], username='first', password=PASSWORD)
            self.assertEqual(self.call(browser, '/setup', 'POST', dict(data, code='wrong')).status_code, 403)
            result = self.call(browser, '/setup', 'POST', data)
            self.assertEqual(result.status_code, 201, result.text)
            self.assertEqual(self.call(browser, '/setup', 'POST', data).status_code, 409)
            self.assertEqual(fresh.mode(), 'managed')
            self.assertNotIn(issued['code'], fresh.path.read_text())

    def test_resume_does_not_replay_current_minute_alarm(self):
        from datetime import datetime
        from webclock.services.display_service import browser_alarm_payload
        from webclock.services.schedule_service import TAIPEI, validate_schedule
        now = datetime(2026, 10, 8, 8, 30, 30, tzinfo=TAIPEI)
        row = validate_schedule({'name': 'Missed', 'time': '08:30'})
        before = browser_alarm_payload([row], clock.holiday_service, now)
        self.assertTrue(before['alarms'])
        after = browser_alarm_payload([row], clock.holiday_service, now, not_before=int(now.timestamp() * 1000))
        self.assertEqual(after['alarms'], [])

    def test_old_pending_can_prepare_again_under_new_primary(self):
        device = clock.app.test_client()
        old = self.call(device, '/api/v2/device/join/prepare', 'POST', {})
        self.assertEqual(old.status_code, 201)
        self.assertEqual(self.switch(self.admin, self.b).status_code, 200)
        self.assertIn(self.call(device, '/api/v2/device/identity').status_code, (401, 403))
        fresh = self.call(device, '/api/v2/device/join/prepare', 'POST', {})
        self.assertEqual(fresh.status_code, 201, fresh.text)
        self.assertNotEqual(old.json['attempt_id'], fresh.json['attempt_id'])
        self.assertEqual(self.call(device, '/api/v2/device/identity').json['status'], 'pending')

    def test_preview_counts_legacy_source_without_publishing_its_url(self):
        with patch.object(clock, 'ICAL_URL', 'https://private.invalid/secret-feed'):
            preview = self.preview(self.admin, self.a)
        a = next(row for row in preview['spaces'] if row['owner_id'] == self.a)
        b = next(row for row in preview['spaces'] if row['owner_id'] == self.b)
        self.assertEqual((a['sources'], a['private_urls']), (1, 1))
        self.assertEqual((b['sources'], b['private_urls']), (0, 0))
        self.assertNotIn('secret-feed', str(preview))

    def test_stale_preview_and_backup_failure_do_not_switch(self):
        preview = self.preview(self.admin, self.a)
        self.note(self.member, 'Concurrent change')
        self.assertEqual(self.switch(self.admin, self.a, preview=preview).status_code, 409)
        before = self.auth.path.read_bytes()
        with patch('scripts.backup_clock.create_backup', side_effect=OSError('disk full')):
            self.assertEqual(self.switch(self.admin, self.a).status_code, 500)
        self.assertEqual(self.auth.path.read_bytes(), before)
        self.assertEqual(self.auth.mode(), 'managed')

    def test_member_crud_and_partial_import_stay_inside_space(self):
        self.note(self.admin, 'A hidden')
        self.note(self.member, 'B hidden')
        archive = self.call(self.member, '/api/backup').json
        self.assertEqual(archive['owner_id'], self.b)
        self.assertEqual(self.call(self.admin, '/api/backup', 'POST', archive).status_code, 400)
        self.assertIn('A hidden', self.call(self.admin, '/api/backup').text)
        self.assertEqual(self.call(self.member, '/api/backup', 'POST', archive).status_code, 200)
        a_group = self.call(self.admin, '/api/v1/groups', 'POST', {'name': 'A group'}).json
        self.assertEqual(self.call(self.member, '/api/v1/groups/' + a_group['id']).status_code, 404)
        self.assertNotIn('A hidden', self.call(self.member, '/admin').text)
        created = self.call(self.member, '/api/v1/schedules', 'POST', {'name': 'B alarm', 'time': '08:00'})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.call(self.admin, '/api/v1/schedules').json['schedules'], [])
        self.assertEqual(self.call(self.member, '/api/mode/preview', 'POST',
            dict(mode='self', primary_owner_id=self.b, password=MEMBER_PASSWORD)).status_code, 403)
        self.assertEqual(self.auth.mode(), 'managed')


if __name__ == '__main__':
    unittest.main()
