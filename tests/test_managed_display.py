"""Two authenticated browsers must never share private display data or ETags."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.device_access_service import _RATE_WINDOWS


class ManagedDisplayTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.auth = AuthService(self.root / 'auth.json')
        self.auth.setup('owner', 'a-long-test-password', enable_managed_test=True)
        self.owner = self.auth.owner_id()
        for item in [patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                     patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')),
                     patch.object(clock, 'ICAL_URL', ''),
                     patch.dict(clock.display_settings, clock.DEFAULT_SETTINGS, clear=True),
                     patch.dict(clock.app.config, SECRET_KEY=self.auth.session_secret()),
                     patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network'))]:
            item.start()
            self.addCleanup(item.stop)
        _RATE_WINDOWS.clear()
        clock.save_json(self.root / 'calendar.json', {'local_display_enabled': True, 'sources': [
            dict(id=key, name=key, provider='ics', url='https://example.invalid/PRIVATE-' + key, display_enabled=True)
            for key in ('a', 'b')]})
        clock.save_json(self.root / 'manual_notes.json', [
            dict(id=1, text='note-a', due_date=''), dict(id=2, text='note-b', due_date='')])
        self.schedules = [dict(id=key, name='alarm-' + key, type='alarm', time='07:30', rule={},
                              enabled=True, skipped_occurrences=[], browser_sound='silent',
                              browser_volume=0, skip_holidays=False) for key in ('a', 'b')]
        clock.save_json(self.root / 'schedules.json', self.schedules)
        self.instant = datetime.fromisoformat('2026-10-05T06:00:00+08:00')
        dates = patch.object(clock, 'datetime', wraps=datetime)
        self.dates = dates.start()
        self.addCleanup(dates.stop)
        self.dates.now.side_effect = lambda zone: self.instant.astimezone(zone)

    def service(self):
        with clock.app.test_request_context('/'):
            return clock.group_service()

    def group(self, name, **extra):
        return self.service().create_group(self.owner, dict(name=name, **extra))

    def device(self, group):
        service = self.service()
        code = service.create_invite(self.owner, group['id'], 5)['code']
        attempt = service.prepare(self.owner, 'test-' + group['id'])
        joined = service.join(self.owner, attempt['token'], attempt['attempt_id'], code, 'test-' + group['id'])
        client = clock.app.test_client()
        client.set_cookie('webclock_device', attempt['token'], path='/api/v2/device')
        return client, joined['identity']

    def get(self, client, path='display', **kwargs):
        return client.get('/api/v2/device/' + path, base_url='https://localhost', **kwargs)

    def test_global_windows_use_management_zone_without_widening_group_grants(self):
        settings = clock.load_calendar_settings()
        rule = dict(source_id='a', uid='wanted', scope='occurrence', recurrence_id='',
                    display_window=dict(mode='absolute', start='2026-10-05T09:00', end='2026-10-05T10:00'))
        settings['calendar_targets'] = [rule]
        clock.save_json(self.root / 'calendar.json', settings)
        first = self.group('A', display_overrides={'timezone_offset': -5}, content={'calendar_targets': [
            {key: value for key, value in rule.items() if key != 'display_window'}]})
        second = self.group('B', content={'calendar_targets': [dict(source_id='a', uid='other', scope='series')]})
        a, _ = self.device(first)
        b, _ = self.device(second)
        event = dict(source_id='a', uid='wanted', recurrence_id='', text='Authorized', all_day=False,
                     starts_at=int(self.instant.replace(day=9, hour=9).timestamp() * 1000),
                     ends_at=int(self.instant.replace(day=9, hour=10).timestamp() * 1000))
        self.instant = self.instant.replace(hour=9, minute=30)
        with patch.object(clock, 'get_calendar_events', return_value=[]), \
                patch.object(clock, 'calendar_selected_occurrence', return_value=[event]):
            self.assertEqual([item['text'] for item in self.get(a).json['events']], ['Authorized'])
            self.assertEqual(self.get(b).json['events'], [])
            self.instant = self.instant.replace(hour=10, minute=0)
            self.assertEqual(self.get(a).json['events'], [])

    def test_display_rule_change_during_io_rejects_payload_and_etag(self):
        settings = clock.load_calendar_settings()
        settings['calendar_targets'] = [dict(source_id='a', uid='event', scope='series', display_window={'mode': 'day'})]
        clock.save_json(self.root / 'calendar.json', settings)
        group = self.group('A', content={'calendar_source_ids': ['a']})
        client, _ = self.device(group)
        def change(**kwargs):
            settings['calendar_targets'][0]['display_window'] = dict(mode='relative', before_minutes=60, end='day_end')
            clock.save_json(self.root / 'calendar.json', settings)
            return []
        with patch.object(clock, 'get_calendar_events', side_effect=change):
            response = self.get(client, headers={'If-None-Match': 'old-private-data'})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('ETag', response.headers)

    def test_item_assignment_requires_management_identity_csrf_and_owner_scope(self):
        group = self.group('Own')
        foreign = self.service().create_group('another-owner', {'name': 'Private foreign group'})
        url = '/api/v1/groups/assignments'
        body = {'item': {'kind': 'manual_note', 'id': 1}, 'group_ids': [group['id']]}
        client = clock.app.test_client()
        self.assertEqual(client.put(url, base_url='https://localhost', json=body).status_code, 401)
        token = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        client.post('/login', base_url='https://localhost', data={
            'username': 'owner', 'password': 'a-long-test-password', 'csrf_token': token})
        token = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        before = (self.root / 'device-access.json').read_bytes()
        self.assertEqual(client.put(url, base_url='https://localhost', json=body).status_code, 403)
        self.assertEqual(client.put(url, base_url='https://localhost', json=body,
                                   headers={'X-CSRF-Token': token, 'Origin': 'https://other.invalid'}).status_code, 403)
        self.assertEqual(client.put(url, base_url='https://localhost', json=dict(body, group_ids=[foreign['id']]),
                                   headers={'X-CSRF-Token': token}).status_code, 404)
        self.assertEqual((self.root / 'device-access.json').read_bytes(), before)
        result = client.put(url, base_url='https://localhost', json=body, headers={'X-CSRF-Token': token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json['assignment']['group_ids'], [group['id']])
        self.assertNotIn(foreign['id'], client.get(url, base_url='https://localhost').text)

    def test_calendar_assignment_rechecks_etag_scope_without_changing_linked_alarms(self):
        from webclock.services.schedule_service import validate_schedule
        linked = validate_schedule(dict(self.schedules[0], calendar_link={'source_ids': ['a'], 'mode': 'event', 'offset_minutes': 0}))
        clock.save_json(self.root / 'schedules.json', [linked])
        group = self.group('A', content={'calendar_source_ids': ['a'], 'schedule_ids': ['a']})
        other = self.group('B', content={'calendar_source_ids': ['a']})
        client, _ = self.device(group)
        target = dict(source_id='a', uid='weekly', scope='occurrence', recurrence_id='original')
        stamp = int(self.instant.replace(hour=9).timestamp() * 1000)
        events = [dict(source_id='a', uid=uid, recurrence_id='original', text=uid, time='09:00',
                       starts_at=stamp + offset, ends_at=stamp + offset + 60000, all_day=False, recurring=True)
                  for uid, offset in [('weekly', 0), ('unrelated', 3600000)]]
        with patch.object(clock, 'get_calendar_events', return_value=events):
            initial = self.get(client)
            self.assertEqual(len(initial.json['events']), 2)
            self.service().set_assignments(self.owner, {'item': {'kind': 'calendar', 'target': target}, 'group_ids': [other['id']]})
            changed = self.get(client, headers={'If-None-Match': initial.headers['ETag']})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual([row['text'] for row in changed.json['events']], ['unrelated'])
            self.assertNotEqual(changed.headers['ETag'], initial.headers['ETag'])
            self.assertEqual(self.get(client, 'browser-alarms').json['alarms'][0]['starts_at'], stamp)
        def revoke_during_io(**kwargs):
            self.service().set_assignments(self.owner, {'item': {'kind': 'calendar', 'target': dict(target, uid='unrelated')},
                                                       'group_ids': [other['id']]})
            return events
        with patch.object(clock, 'get_calendar_events', side_effect=revoke_during_io):
            denied = self.get(client, headers={'If-None-Match': changed.headers['ETag']})
        self.assertEqual(denied.status_code, 409)
        self.assertNotIn('ETag', denied.headers)
        self.assertNotIn('unrelated', denied.text)

    def test_two_groups_filter_on_server_and_empty_means_empty(self):
        first = self.group('A', display_overrides={'brightness': 0, 'language': 'ja'},
                           content={'calendar_source_ids': ['a'], 'manual_note_ids': [1], 'schedule_ids': ['a']})
        second = self.group('B', content={'calendar_source_ids': ['b'], 'manual_note_ids': [2], 'schedule_ids': ['b']})
        a, identity = self.device(first)
        b, _ = self.device(second)
        queries = []

        def events(start, end, source_ids):
            queries.append(source_ids)
            return [dict(source_id=key, uid=key, text='calendar-' + key, time='09:00', starts_at=0) for key in source_ids]

        with patch.object(clock, 'get_calendar_events', side_effect=events):
            for client, suffix in ((a, 'a'), (b, 'b')):
                response = self.get(client)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual({row['text'] for row in response.json['events']}, {'calendar-' + suffix, 'note-' + suffix})
                self.assertEqual(self.get(client, 'browser-alarms').json['enabled_ids'], [suffix])
                self.assertNotIn('PRIVATE-', response.text)
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
            self.assertEqual(queries, [['a'], ['b']])
            self.assertEqual(self.get(a).json['settings']['brightness'], 0)
            self.assertEqual(self.get(a).json['identity'], identity)
            self.service().update_group(self.owner, first['id'], {'content': {
                'calendar_source_ids': [], 'manual_note_ids': [], 'schedule_ids': []}})
            queries.clear()
            payload = self.get(a).json
            self.assertEqual(payload['events'], [])
            self.assertIsNone(payload['next_event'])
            self.assertEqual(self.get(a, 'browser-alarms').json['alarms'], [])
            self.assertEqual(queries, [])

    def test_etags_cover_identity_effective_settings_and_content_not_heartbeats(self):
        group = self.group('A', content={'manual_note_ids': [1]})
        a, identity = self.device(group)
        b, _ = self.device(group)
        first = self.get(a)
        etag = first.headers['ETag']
        cached = self.get(a, headers={'If-None-Match': etag})
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.headers['X-WebClock-Identity-Revision'], identity['identity_revision'])
        self.assertEqual(int(cached.headers['X-WebClock-Lease-Expires-At']) - int(cached.headers['X-WebClock-Server-Timestamp']), 300000)
        self.assertEqual(self.get(b, headers={'If-None-Match': etag}).status_code, 200)
        self.service().update_group(self.owner, group['id'], {'name': 'Renamed'})
        self.assertEqual(self.get(a).headers['ETag'], etag)
        clock.device_service().register({'id': identity['device_id'], 'name': 'Observed name'})
        self.assertEqual(self.get(a).headers['ETag'], etag)
        clock.display_settings['brightness'] = 31
        changed = self.get(a)
        self.assertNotEqual(changed.json['config_revision'], first.json['config_revision'])
        clock.save_json(self.root / 'manual_notes.json', [dict(id=1, text='changed', due_date='')])
        self.assertNotEqual(self.get(a).json['schedule_revision'], first.json['schedule_revision'])
        self.service().update_group(self.owner, group['id'], {'enabled': False})
        denied = self.get(a, headers={'If-None-Match': etag})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn('ETag', denied.headers)

    def test_linked_alarm_dependency_is_independent_from_display_selection(self):
        linked = dict(self.schedules[0], calendar_link={'source_ids': ['a'], 'mode': 'event', 'offset_minutes': 0})
        from webclock.services.schedule_service import validate_schedule
        linked = validate_schedule(linked)
        clock.save_json(self.root / 'schedules.json', [linked])
        group = self.group('A', content={'schedule_ids': ['a'], 'calendar_targets': [
            dict(source_id='a', uid='display-only', scope='occurrence', recurrence_id='')]})
        client, _ = self.device(group)
        stamp = int(self.instant.replace(hour=9).timestamp() * 1000)

        def events(start, end, source_ids):
            self.assertEqual(source_ids, ['a'])
            return [dict(source_id='a', uid='event', text='Private linked event', starts_at=stamp,
                         ends_at=stamp, all_day=False, recurring=False, recurrence_id='')]

        with patch.object(clock, 'get_calendar_events', side_effect=events):
            payload = self.get(client).json
            self.assertEqual(payload['events'], [])
            self.assertEqual(len(self.get(client, 'browser-alarms').json['alarms']), 1)
            clock.save_json(self.root / 'calendar.json', {'sources': [], 'local_display_enabled': True})
            self.assertEqual(self.get(client, 'browser-alarms').json['alarms'], [])
            self.assertIsNone(self.get(client).json['next_event'])

    def test_display_timezone_does_not_change_alarm_timezone(self):
        self.schedules[0]['calendar_link'] = None
        clock.save_json(self.root / 'schedules.json', self.schedules)
        group = self.group('A', display_overrides={'timezone_offset': -5}, content={'schedule_ids': ['a']})
        client, _ = self.device(group)
        payload = self.get(client, 'browser-alarms').json
        self.assertEqual(payload['alarms'][0]['starts_at'], int(self.instant.replace(hour=7, minute=30).timestamp() * 1000))
        self.assertEqual(self.get(client).json['settings']['timezone_offset'], -5)

    def test_scope_change_during_calendar_io_rejects_old_result(self):
        group = self.group('A', content={'calendar_source_ids': ['a']})
        client, _ = self.device(group)

        def change(**kwargs):
            self.service().update_group(self.owner, group['id'], {'content': {'calendar_source_ids': []}})
            return [dict(text='must not escape', time='', starts_at=0)]

        with patch.object(clock, 'get_calendar_events', side_effect=change):
            response = self.get(client)
            self.assertEqual(response.status_code, 409)
            self.assertNotIn('must not escape', response.text)

    def test_calendar_target_filter_uses_source_uid_and_recurrence_not_labels(self):
        once = dict(source_id='a', uid='weekly', scope='occurrence', recurrence_id='original-slot', title='Old title')
        group = self.group('Selective', content={'calendar_targets': [once]})
        client, _ = self.device(group)
        def event(source, uid, slot, text, hour):
            return dict(source_id=source, uid=uid, recurrence_id=slot, text=text, time=str(hour) + ':00',
                        starts_at=int(self.instant.replace(hour=hour).timestamp() * 1000))
        rows = [event('a', 'other', '', 'Old title', 7), event('b', 'weekly', 'original-slot', 'Other source', 8),
                event('a', 'weekly', 'original-slot', 'Moved and renamed', 11),
                event('a', 'weekly', 'next-slot', 'Next weekly', 12)]
        with patch.object(clock, 'get_calendar_events', return_value=rows) as lookup:
            first = self.get(client)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual([row['text'] for row in first.json['events']], ['Moved and renamed'])
            self.assertEqual(first.json['next_event']['text'], 'Moved and renamed')
            self.assertNotIn('Other source', first.text)
            self.assertNotIn('Old title', first.text)
            self.assertEqual(lookup.call_args.kwargs['source_ids'], ['a'])
            self.service().update_group(self.owner, group['id'], {'content': {'calendar_targets': [dict(once, scope='series')]}})
            series = self.get(client, headers={'If-None-Match': first.headers['ETag']})
            self.assertEqual(series.status_code, 200)
            self.assertEqual([row['text'] for row in series.json['events']], ['Moved and renamed', 'Next weekly'])
            self.assertNotEqual(series.headers['ETag'], first.headers['ETag'])
            self.service().update_group(self.owner, group['id'], {'content': {
                'calendar_source_ids': ['b'], 'calendar_targets': [once]}})
            union = self.get(client)
            self.assertEqual({row['text'] for row in union.json['events']}, {'Other source', 'Moved and renamed'})
            self.assertEqual(lookup.call_args.kwargs['source_ids'], ['a', 'b'])
        # A cancelled/missing target never falls back to another event with the same label.
        with patch.object(clock, 'get_calendar_events', return_value=rows[:1]):
            payload = self.get(client).json
            self.assertEqual(payload['events'], [])
            self.assertIsNone(payload['next_event'])

    def test_real_feed_target_survives_move_and_rename_then_cancellation_hides_it(self):
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, zone=None):
                return cls(2026, 10, 5, 6, tzinfo=clock.TAIPEI).astimezone(zone)
        target = dict(source_id='a', uid='weekly', scope='occurrence',
                      recurrence_id='2026-10-05T02:00:00+00:00', title='Same label')
        group = self.group('Real feed', content={'calendar_targets': [target]})
        client, _ = self.device(group)
        master = 'BEGIN:VEVENT\nUID:weekly\nDTSTART:20261005T020000Z\nRRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:Same label\nEND:VEVENT\n'
        other = 'BEGIN:VEVENT\nUID:other\nDTSTART:20261005T010000Z\nSUMMARY:Same label\nEND:VEVENT\n'
        moved = 'BEGIN:VEVENT\nUID:weekly\nRECURRENCE-ID:20261005T020000Z\nDTSTART:20261005T030000Z\nSUMMARY:Moved title\nEND:VEVENT\n'
        cancelled = 'BEGIN:VEVENT\nUID:weekly\nRECURRENCE-ID:20261005T020000Z\nSTATUS:CANCELLED\nEND:VEVENT\n'
        for override, expected in ((moved, ['Moved title']), (cancelled, [])):
            content = ('BEGIN:VCALENDAR\nVERSION:2.0\n' + master + other + override + 'END:VCALENDAR\n').replace('\n', '\r\n').encode()
            with patch.object(clock, 'datetime', FrozenDateTime), patch.object(clock, 'calendar_feed_cache', {}), \
                    patch.object(clock.requests, 'get', return_value=SimpleNamespace(content=content, raise_for_status=lambda: None)):
                response = self.get(client)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([row['text'] for row in response.json['events']], expected)
            if not expected:
                self.assertIsNone(response.json['next_event'])

    def test_target_source_deletion_during_io_rejects_old_etag_and_payload(self):
        target = dict(source_id='a', uid='weekly', scope='series')
        group = self.group('A', content={'calendar_targets': [target]})
        client, _ = self.device(group)
        row = dict(source_id='a', uid='weekly', text='private old event', time='', starts_at=0)
        with patch.object(clock, 'get_calendar_events', return_value=[row]):
            first = self.get(client)
        def remove(**kwargs):
            clock.save_json(self.root / 'calendar.json', {'sources': [], 'local_display_enabled': False})
            return [row]
        with patch.object(clock, 'get_calendar_events', side_effect=remove):
            response = self.get(client, headers={'If-None-Match': first.headers['ETag']})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('ETag', response.headers)
        self.assertNotIn(row['text'], response.text)

    def test_management_language_changes_session_only(self):
        client = clock.app.test_client()
        token = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        client.post('/login', base_url='https://localhost', data={
            'username': 'owner', 'password': 'a-long-test-password', 'csrf_token': token})
        token = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        before = dict(clock.display_settings)
        result = client.post('/api/management/language', base_url='https://localhost', json={'language': 'ja'},
                             headers={'X-CSRF-Token': token})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(clock.display_settings, before)
        for invalid in ([], {}, None, True, 'zh-CN'):
            response = client.post('/api/management/language', base_url='https://localhost', json={'language': invalid},
                                   headers={'X-CSRF-Token': token})
            self.assertEqual(response.status_code, 400)
        self.assertIn('lang="ja"', client.get('/schedules', base_url='https://localhost').text)
        self.assertIn('var currentLanguage = "zh-TW";', client.get('/', base_url='https://localhost').text)

    def test_source_removed_during_io_cannot_return_old_events_or_304(self):
        group = self.group('A', content={'calendar_source_ids': ['a']})
        client, _ = self.device(group)
        event = dict(text='old source', time='', starts_at=0)
        with patch.object(clock, 'get_calendar_events', return_value=[event]):
            etag = self.get(client).headers['ETag']

        def remove(**kwargs):
            clock.save_json(self.root / 'calendar.json', {'sources': [], 'local_display_enabled': True})
            return [event]

        with patch.object(clock, 'get_calendar_events', side_effect=remove):
            response = self.get(client, headers={'If-None-Match': etag})
            self.assertEqual(response.status_code, 409)
            self.assertNotIn('ETag', response.headers)
            self.assertNotIn('old source', response.text)


if __name__ == '__main__':
    unittest.main()
