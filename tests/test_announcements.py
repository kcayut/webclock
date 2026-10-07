"""Targeted announcements stay separate from calendars, alarms and public clocks."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.device_access_service import _RATE_WINDOWS
from webclock.services.schedule_service import validate_schedule


class AnnouncementTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth = AuthService(self.root / 'auth.json')
        self.auth.setup('owner', 'a-long-test-password', enable_managed_test=True)
        self.owner = self.auth.owner_id()
        self.instant = datetime.fromisoformat('2026-10-07T08:00:00+08:00')
        for item in (patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                     patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')),
                     patch.object(clock, 'ICAL_URL', ''),
                     patch.dict(clock.display_settings, deepcopy(clock.DEFAULT_SETTINGS), clear=True),
                     patch.dict(clock.app.config, SECRET_KEY=self.auth.session_secret()),
                     patch.object(clock, 'get_calendar_events', return_value=[]),
                     patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network'))):
            item.start()
            self.addCleanup(item.stop)
        dates = patch.object(clock, 'datetime', wraps=datetime)
        self.dates = dates.start()
        self.addCleanup(dates.stop)
        self.dates.now.side_effect = lambda zone: self.instant.astimezone(zone)
        stamps = patch.object(clock.time, 'time', side_effect=lambda: self.instant.timestamp())
        stamps.start()
        self.addCleanup(stamps.stop)
        _RATE_WINDOWS.clear()
        clock.save_json(clock.NOTES_FILE, [dict(id=1, text='Regular reminder', due_date='')])
        self.client = clock.app.test_client()
        csrf = self.call('/api/csrf').json['csrf_token']
        self.call('/login', 'POST', data=dict(username='owner', password='a-long-test-password', csrf_token=csrf))
        self.headers = {'X-CSRF-Token': self.call('/api/csrf').json['csrf_token']}
        self.group = self.service().create_group(self.owner, {'name': 'Bedroom', 'content': {'manual_note_ids': [1]}})
        self.other = self.service().create_group(self.owner, {'name': 'Office', 'content': {'manual_note_ids': [1]}})
        self.a, self.identity = self.join(self.group)
        self.b, self.other_identity = self.join(self.other)

    def call(self, path, method='GET', **kwargs):
        return self.client.open(path, method=method, base_url='https://localhost', **kwargs)

    def service(self):
        with clock.app.test_request_context('/'):
            return clock.group_service()

    def join(self, group):
        service = self.service()
        invite = service.create_invite(self.owner, group['id'])
        attempt = service.prepare(self.owner, group['id'])
        identity = service.join(self.owner, attempt['token'], attempt['attempt_id'], invite['code'], group['id'])['identity']
        client = clock.app.test_client()
        client.set_cookie('webclock_device', attempt['token'], path='/api/v2/device')
        return client, identity

    def display(self, client=None, path='display', **kwargs):
        return (client or self.a).get('/api/v2/device/' + path, base_url='https://localhost', **kwargs)

    def note(self, identifier=2, groups=None, devices=None, **fields):
        return clock.validate_note(dict(dict(id=identifier, text='Private announcement', due_date='',
            announcement_targets=dict(group_ids=groups or [], device_ids=devices or [])), **fields))

    def store(self, *announcements):
        clock.save_json(clock.NOTES_FILE, [clock.validate_note(dict(id=1, text='Regular reminder', due_date='')), *announcements])

    def test_targets_are_independent_of_stale_note_assignments_and_public_content(self):
        notice = self.note(groups=[self.group['id']], devices=[self.identity['device_id']])
        self.store(notice, self.note(3))
        a, b = self.display(), self.display(self.b)
        self.assertEqual([row['id'] for row in a.json['announcements']], [2])
        self.assertEqual(b.json['announcements'], [])
        self.assertEqual(a.json['events'], [{'text': 'Regular reminder', 'time': ''}])
        self.assertIsNone(a.json['next_event'])
        self.assertEqual(set(a.json['announcements'][0]), {'id', 'text', 'visible_until'})
        self.assertEqual(a.json['lease']['expires_at'] - a.json['server_timestamp'], 300000)
        catalog = self.call('/api/v1/groups/catalog').json
        self.assertEqual(catalog['manual_notes'], [{'id': 1, 'text': 'Regular reminder'}])
        # Converting an already-assigned reminder must not bypass the new targets.
        clock.save_json(clock.NOTES_FILE, [dict(notice, id=1)])
        self.assertEqual(self.display(self.b).json['announcements'], [])
        self.assertEqual(self.display(self.b).json['events'], [])
        with patch.object(AuthService, 'mode', return_value='self'):
            public = self.call('/api/status')
            self.assertEqual(public.json['events'], [])
            self.assertEqual(public.json['announcements'], [])
            self.assertNotIn('Private announcement', public.text)
            self.assertEqual(len(self.display().json['announcements']), 1)

    def test_form_crud_conversion_pause_and_owner_csrf_checks(self):
        data = dict(note_text='Sent notice', announcement='1', announcement_group_ids=[self.group['id']],
                    expires_at='2026-10-07T09:00')
        self.assertEqual(self.call('/add', 'POST', data=data).status_code, 403)
        self.assertEqual(clock.app.test_client().post('/add', base_url='https://localhost', data=data).status_code, 302)
        result = self.call('/add', 'POST', data=data, headers=self.headers)
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.location.endswith('#announcements-title'))
        saved = next(row for row in clock.load_notes() if row['id'] == 2)
        self.assertEqual(saved['expires_at'], '2026-10-07T09:00:00+08:00')
        self.assertEqual(self.call('/toggle/2', 'POST', headers=self.headers).status_code, 302)
        self.assertEqual(self.display().json['announcements'], [])
        # Type conversion removes the persisted marker, including on paused notes.
        self.assertEqual(self.call('/schedule/2', 'POST', data=dict(note_text='Ordinary', announcement=''), headers=self.headers).status_code, 302)
        saved = next(row for row in clock.load_notes() if row['id'] == 2)
        self.assertNotIn('announcement_targets', saved)
        self.assertNotIn('expires_at', saved)
        self.assertFalse(saved['enabled'])
        self.assertEqual(self.call('/schedule/2', 'POST', data=data, headers=self.headers).status_code, 302)
        self.assertEqual(self.call('/toggle/2', 'POST', headers=self.headers).status_code, 302)
        self.assertEqual(len(self.display().json['announcements']), 1)
        foreign = self.service().create_group('other-owner', {'name': 'Do not expose'})
        before = Path(clock.NOTES_FILE).read_bytes()
        for invalid in (dict(data, announcement_group_ids=[foreign['id']]),
                        dict(data, announcement_device_ids=['missing']), dict(data, expires_at='invalid'),
                        dict(data, expires_at='2026-10-07T09:00+08:00')):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.call('/schedule/2', 'POST', data=invalid, headers=self.headers).status_code, 400)
                self.assertEqual(Path(clock.NOTES_FILE).read_bytes(), before)
        self.assertNotIn('Do not expose', self.call('/admin').text)
        self.assertEqual(self.call('/delete/2', 'POST', headers=self.headers).status_code, 302)
        self.assertEqual(self.display().json['announcements'], [])

    def test_invalid_announcement_in_fresh_self_mode_does_not_initialize_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(clock, 'SETTINGS_FILE', str(root / 'settings.json')), \
                    patch.object(clock, 'NOTES_FILE', str(root / 'notes.json')):
                client = clock.app.test_client()
                csrf = client.get('/api/csrf').json['csrf_token']
                response = client.post('/add', data=dict(csrf_token=csrf, note_text='Invalid target',
                    announcement='1', announcement_group_ids=['missing']))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(list(root.iterdir()), [])

    def test_visibility_deadlines_cover_absolute_daily_weekday_and_due_date_boundaries(self):
        cases = [
            ('2026-10-07T08:00:00+08:00', {'expires_at': '2026-10-07T00:02:00+00:00'}, '2026-10-07T08:02:00+08:00'),
            ('2026-10-07T08:00:00+08:00', {'display_start': '2026-10-07T07:00', 'display_end': '2026-10-07T08:01'}, '2026-10-07T08:01:00+08:00'),
            ('2026-10-08T05:59:00+08:00', {'display_mode': 'daily', 'display_start': '22:00', 'display_end': '06:00', 'weekdays': [2]}, '2026-10-08T06:00:00+08:00'),
            ('2026-10-07T23:59:00+08:00', {'display_mode': 'daily', 'weekdays': [2]}, '2026-10-08T00:00:00+08:00'),
            ('2026-10-07T23:59:00+08:00', {'due_date': '2026-10-07'}, '2026-10-08T00:00:00+08:00'),
        ]
        for instant, fields, deadline in cases:
            with self.subTest(fields=fields):
                self.instant = datetime.fromisoformat(instant)
                notice = self.note(groups=[self.group['id']], **fields)
                self.store(notice)
                response = self.display()
                self.assertEqual(response.json['announcements'][0]['visible_until'], int(datetime.fromisoformat(deadline).timestamp() * 1000))
                self.instant = datetime.fromisoformat(deadline)
                self.assertEqual(self.display().json['announcements'], [])
        self.instant = datetime.fromisoformat('2026-10-07T08:00:00+08:00')
        self.store(self.note(groups=[self.group['id']]))
        first = self.display()
        self.instant += timedelta(seconds=30)
        renewed = self.display(headers={'If-None-Match': first.headers['ETag']})
        self.assertEqual(renewed.status_code, 200)
        self.assertGreater(renewed.json['announcements'][0]['visible_until'], first.json['announcements'][0]['visible_until'])

    def test_announcements_never_become_local_calendar_or_linked_alarms(self):
        self.store(self.note(groups=[self.group['id']], due_date='2026-10-07 09:00',
                             display_start='2026-10-07T07:00', display_end='2026-10-07T10:00'))
        linked = validate_schedule(dict(id='linked', name='Local linked alarm', type='alarm', time='07:30',
            rule={}, enabled=True, skip_holidays=False,
            calendar_link={'source_ids': ['local'], 'mode': 'event', 'offset_minutes': 0}))
        clock.save_json(self.root / 'schedules.json', [linked])
        self.service().update_group(self.owner, self.group['id'], {'content': {'schedule_ids': ['linked']}})
        self.assertEqual(clock.local_calendar_events(self.instant, self.instant + timedelta(days=2)), [])
        self.assertEqual(self.display(path='browser-alarms').json['alarms'], [])
        self.assertNotIn('announcements', self.display(path='browser-alarms').json)
        self.assertIsNone(self.display().json['next_event'])
        self.assertEqual(len(self.display().json['announcements']), 1)

    def test_move_revoke_and_inflight_edits_cannot_return_prior_target_content(self):
        self.store(self.note(groups=[self.group['id']]))
        first = self.display()
        self.service().update_device(self.owner, self.identity['device_id'], {'group_id': self.other['id']})
        moved = self.display(headers={'If-None-Match': first.headers['ETag']})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json['announcements'], [])
        self.store(self.note(devices=[self.identity['device_id']]))
        self.assertEqual(len(self.display().json['announcements']), 1)
        respond = clock.managed_response
        def remove_targets(*args, **kwargs):
            self.store(self.note())
            return respond(*args, **kwargs)
        with patch.object(clock, 'managed_response', side_effect=remove_targets):
            denied = self.display()
        self.assertEqual(denied.status_code, 409)
        self.assertNotIn('Private announcement', denied.text)
        self.assertNotIn('ETag', denied.headers)
        self.store(self.note(devices=[self.identity['device_id']]))
        self.service().revoke(self.owner, self.identity['device_id'])
        self.assertEqual(self.display().status_code, 401)

    def test_backup_preserves_missing_targets_and_rejects_foreign_or_malformed_targets(self):
        self.store(self.note(groups=[self.group['id']], expires_at='2026-10-08T00:00:00+08:00'))
        archive = self.call('/api/backup').json
        self.assertEqual(self.call('/api/backup', 'POST', json=archive, headers=self.headers).status_code, 200)
        self.assertEqual(self.call('/api/backup').json, archive)
        incoming = deepcopy(archive)
        incoming['notes'][1]['announcement_targets'] = dict(group_ids=['removed-group'], device_ids=['removed-device'])
        self.assertEqual(self.call('/api/backup', 'POST', json=incoming, headers=self.headers).status_code, 200)
        self.assertEqual(self.call('/api/backup').json['notes'], incoming['notes'])
        self.assertEqual(self.display().json['announcements'], [])
        foreign = self.service().create_group('other-owner', {'name': 'Foreign'})
        before = Path(clock.NOTES_FILE).read_bytes()
        for targets in ({'group_ids': [foreign['id']], 'device_ids': []}, {'group_ids': [], 'device_ids': [True]},
                        {'group_ids': [], 'device_ids': [], 'all': True}, None):
            broken = deepcopy(incoming)
            broken['notes'][1]['announcement_targets'] = targets
            self.assertEqual(self.call('/api/backup', 'POST', json=broken, headers=self.headers).status_code, 400)
            self.assertEqual(Path(clock.NOTES_FILE).read_bytes(), before)
        broken = deepcopy(incoming)
        broken['notes'][1]['expires_at'] = '2026-10-08T00:00'
        self.assertEqual(self.call('/api/backup', 'POST', json=broken, headers=self.headers).status_code, 400)
        self.assertEqual(Path(clock.NOTES_FILE).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
