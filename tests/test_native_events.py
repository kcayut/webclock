"""Native events retain alarm time, explicit display grants and private ownership."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from types import SimpleNamespace
from threading import Event
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.device_access_service import _RATE_WINDOWS
from webclock.services.event_service import read_events, save_events, validate_event, query_events
from webclock.services.schedule_service import next_occurrence, validate_schedule
from webclock.services.storage import storage_lock


class NativeEventsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.owner = AuthService(self.root / 'auth.json').ensure_initialized()['owner_id']
        for item in (patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                     patch.object(clock, 'NOTES_FILE', str(self.root / 'notes.json')),
                     patch.object(clock, 'ICAL_URL', ''),
                     patch.object(clock, 'calendar_feed_cache', {}),
                     patch.dict(clock.display_settings, clock.DEFAULT_SETTINGS, clear=True),
                     patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network'))):
            item.start()
            self.addCleanup(item.stop)
        self.now = datetime.fromisoformat('2026-10-08T18:00:00+08:00')
        self.row = validate_event(dict(id='meeting', title='Meeting',
            start='2026-10-09T14:00:00+08:00', end='2026-10-09T15:00:00+08:00',
            owner_id=self.owner, creator_client_id='test-client',
            display_window=dict(mode='absolute', start='2026-10-08T18:00', end='2026-10-09T15:00')))
        save_events(self.root, [self.row])
        self.target = dict(source_id='webclock', uid='meeting', scope='occurrence', recurrence_id='')

    def test_time_window_and_alarm_are_independent_and_follow_edits(self):
        settings = clock.load_calendar_settings()
        with patch.object(clock, 'get_local_now', return_value=self.now):
            visible = clock.calendar_display_events(self.now, settings, [], [self.target])
        self.assertEqual([item['text'] for item in visible], ['Meeting'])
        self.assertNotIn('owner_id', visible[0])
        self.assertEqual(visible[0]['starts_at'], int(datetime.fromisoformat(self.row['start']).timestamp() * 1000))
        self.assertEqual(query_events([self.row], self.now.replace(hour=0), self.now.replace(hour=23)), [])
        alarm = validate_schedule(dict(id='alarm', name='Meeting reminder', time='09:00',
            calendar_link=dict(mode='event', source_ids=['webclock'], offset_minutes=15, target=self.target)))
        event = next_occurrence(alarm, clock.holiday_service, self.now, clock.get_calendar_events)
        self.assertEqual(event['datetime'], '2026-10-09T13:45:00+08:00')
        moved = dict(self.row, start='2026-10-09T16:00:00+08:00', end='2026-10-09T17:00:00+08:00')
        save_events(self.root, [moved])
        event = next_occurrence(alarm, clock.holiday_service, self.now, clock.get_calendar_events)
        self.assertEqual(event['datetime'], '2026-10-09T15:45:00+08:00')
        save_events(self.root, [dict(moved, enabled=False)])
        self.assertIsNone(next_occurrence(alarm, clock.holiday_service, self.now, clock.get_calendar_events))
        save_events(self.root, [])
        self.assertIsNone(next_occurrence(alarm, clock.holiday_service, self.now, clock.get_calendar_events))

    def test_no_default_display_grant_and_foreign_owner_is_hidden(self):
        save_events(self.root, [self.row, dict(self.row, id='foreign', title='Private', owner_id='other-owner')])
        with patch.object(clock, 'get_local_now', return_value=self.now):
            self.assertEqual(clock.app.test_client().get('/api/status').json['events'], [])
            self.assertEqual(clock.calendar_display_events(self.now, clock.load_calendar_settings(), [], []), [])
            self.assertEqual(clock.calendar_display_events(self.now, clock.load_calendar_settings(), ['webclock'], [],
                                                           [self.target]), [])
            visible = clock.calendar_display_events(self.now, clock.load_calendar_settings(), ['webclock'])
        self.assertEqual([event['uid'] for event in visible], ['meeting'])
        catalog = clock.group_content_catalog()
        self.assertIn('webclock', catalog['calendar_source_ids'])
        self.assertNotIn('webclock', catalog['default_content']['calendar_source_ids'])
        self.assertNotIn('webclock', [row['id'] for row in clock.load_calendar_settings()['sources']])

    def test_group_assignment_and_revision_follow_native_changes(self):
        with clock.app.test_request_context('/'):
            service = clock.group_service()
            first = service.create_group(self.owner, dict(name='A', content={'calendar_targets': [self.target]}))
            second = service.create_group(self.owner, dict(name='B', content={}))
            identity_a = dict(owner_id=self.owner, group_id=first['id'], device_id='unused')
            identity_b = dict(owner_id=self.owner, group_id=second['id'], device_id='unused')
            old_revision = clock.managed_content(dict(identity_a, device_id=None))[3]
            other_revision = clock.managed_content(dict(identity_b, device_id=None))[3]
            save_events(self.root, [dict(self.row, title='Changed')])
            self.assertNotEqual(old_revision, clock.managed_content(dict(identity_a, device_id=None))[3])
            self.assertEqual(other_revision, clock.managed_content(dict(identity_b, device_id=None))[3])

    def test_paired_devices_receive_only_assigned_events_and_detect_concurrent_edit(self):
        now = datetime.now(timezone.utc)
        row = dict(self.row, start=(now + timedelta(days=1)).isoformat(),
                   end=(now + timedelta(days=1, hours=1)).isoformat(),
                   display_window=dict(mode='relative', before_minutes=4320, end='event_end'))
        save_events(self.root, [row])
        _RATE_WINDOWS.clear()
        with clock.app.test_request_context('/'):
            service = clock.group_service()
            groups = [service.create_group(self.owner, dict(name=name, content=content)) for name, content in (
                ('A', {'calendar_targets': [self.target]}), ('B', {}))]
        clients = []
        for group in groups:
            code = service.create_invite(self.owner, group['id'], 5)['code']
            attempt = service.prepare(self.owner, group['id'])
            service.join(self.owner, attempt['token'], attempt['attempt_id'], code, group['id'])
            client = clock.app.test_client()
            client.set_cookie('webclock_device', attempt['token'], path='/api/v2/device')
            clients.append(client)
        url = '/api/v2/device/display'
        first = clients[0].get(url, base_url='https://localhost')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual([event['text'] for event in first.json['events']], ['Meeting'])
        self.assertEqual(clients[1].get(url, base_url='https://localhost').json['events'], [])
        original = clock.get_calendar_events
        def update_during_read(*args, **kwargs):
            events = original(*args, **kwargs)
            save_events(self.root, [dict(row, title='Changed')])
            return events
        with patch.object(clock, 'get_calendar_events', side_effect=update_during_read):
            changed = clients[0].get(url, base_url='https://localhost', headers={'If-None-Match': first.headers['ETag']})
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertNotIn('ETag', changed.headers)
        current = clients[0].get(url, base_url='https://localhost')
        self.assertNotEqual(first.headers['ETag'], current.headers['ETag'])
        self.assertEqual([event['text'] for event in current.json['events']], ['Changed'])

    def test_management_override_takes_priority_without_granting_other_groups(self):
        settings = clock.load_calendar_settings()
        settings['calendar_targets'] = [dict(self.target, display_window={'mode': 'day'})]
        with patch.object(clock, 'get_local_now', return_value=self.now):
            self.assertEqual(clock.calendar_display_events(self.now, settings, [], [self.target]), [])
            self.assertEqual(clock.calendar_display_events(self.now, settings, [], []), [])
        clock.save_json(self.root / 'calendar.json', settings)
        self.assertEqual(clock.load_calendar_settings()['calendar_targets'][0]['source_id'], 'webclock')
        with patch.object(clock, 'get_local_now', return_value=self.now):
            response = clock.app.test_client().get('/api/calendar/display-items')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json['items'][0]['target']['display_window'], {'mode': 'day'})
        self.assertNotIn('creator_client_id', response.text)

    def test_validation_all_day_timezone_dst_and_damaged_storage(self):
        for changes in ({'start': '2026-10-09T14:00'}, {'end': self.row['start']},
                        {'timezone': 'Invalid/Zone'}, {'owner_id': ''}, {'recurrence': 'weekly'},
                        {'display_window': None}, {'display_window': {'mode': 'relative', 'before_minutes': -1, 'end': 'event_end'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_event(dict(self.row, **changes))
        all_day = validate_event(dict(self.row, all_day=True, start='2026-10-09', end='2026-10-10'))
        events = query_events([all_day], self.now, datetime.fromisoformat('2026-10-10T12:00:00+00:00'))
        self.assertEqual(events[0]['starts_at'], int(datetime.fromisoformat('2026-10-09T00:00:00+08:00').timestamp() * 1000))
        folded = validate_event(dict(self.row, timezone='America/New_York',
                                     start='2026-11-01T01:30:00-04:00', end='2026-11-01T01:15:00-05:00'))
        self.assertEqual(folded['end'], '2026-11-01T01:15:00-05:00')
        path = self.root / 'events.json'
        path.write_text('{bad json', encoding='utf-8')
        with self.assertRaises(ValueError):
            save_events(self.root, [])
        self.assertEqual(path.read_text(encoding='utf-8'), '{bad json')

    def test_legacy_webclock_source_keeps_ics_display_and_alarm_semantics(self):
        save_events(self.root, [])
        settings = {'sources': [dict(id='webclock', name='Existing ICS', provider='ics',
                                     url='https://example.invalid/calendar.ics', display_enabled=True)],
                    'local_display_enabled': True}
        clock.save_json(self.root / 'calendar.json', settings)
        feed = ('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:meeting\n'
                'DTSTART:20261009T060000Z\nDTEND:20261009T070000Z\n'
                'SUMMARY:Subscribed\nEND:VEVENT\nEND:VCALENDAR\n').encode()
        with patch.object(clock.requests, 'get', return_value=SimpleNamespace(content=feed, raise_for_status=lambda: None)):
            self.assertEqual(clock.get_calendar_sources(), settings['sources'])
            day = self.now.replace(day=9, hour=12)
            with patch.object(clock, 'get_local_now', return_value=day):
                self.assertEqual(clock.app.test_client().get('/api/status').json['events'],
                                 [{'text': 'Subscribed', 'time': '14:00'}])
                listing = clock.app.test_client().get('/api/calendar/display-items')
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertEqual(listing.json['items'][0]['source_name'], 'Existing ICS')
            alarm = validate_schedule(dict(id='alarm', name='Subscribed reminder', time='09:00',
                calendar_link=dict(mode='event', source_ids=['webclock'], offset_minutes=15, target=self.target)))
            self.assertEqual(next_occurrence(alarm, clock.holiday_service, self.now, clock.get_calendar_events)['datetime'],
                             '2026-10-09T13:45:00+08:00')
            # Even an unsupported manual merge of state files must not replace an existing subscription.
            save_events(self.root, [self.row])
            self.assertEqual(clock.get_calendar_sources(), settings['sources'])
            self.assertEqual(clock.native_event_rows(), [])
            events = clock.get_calendar_events(day.replace(hour=0), day.replace(hour=23), ['webclock'])
            self.assertEqual([event['text'] for event in events], ['Subscribed'])

    def test_date_and_window_boundaries_reject_unprojectable_events(self):
        for changes in (
                dict(all_day=True, start='0001-01-01', end='0001-01-02', timezone='Etc/GMT-14'),
                dict(start='0001-01-01T00:00:00+00:00', end='0001-01-02T00:00:00+00:00', timezone='America/New_York'),
                dict(start='9999-12-31T00:00:00-12:00', end='9999-12-31T23:00:00-12:00', timezone='Etc/GMT-14'),
                dict(start='0002-01-01T00:00:00+14:00', end='0002-01-02T00:00:00+14:00', timezone='Etc/GMT-14',
                     display_window=dict(mode='relative', before_minutes=525600, end='event_end')),
                dict(display_window=dict(mode='absolute', start='0001-01-01T00:00', end='0001-01-02T00:00')),
                dict(display_window=dict(mode='absolute', start='9999-12-30T00:00', end='9999-12-31T00:00'))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_event(dict(self.row, **changes))
        for year in ('0002', '9998'):
            row = validate_event(dict(self.row, all_day=True, start=year + '-01-02', end=year + '-01-03',
                                      timezone='Etc/GMT-14', display_window={'mode': 'day'}))
            events = query_events([row], datetime.fromisoformat(year + '-01-01T00:00:00+00:00'),
                                  datetime.fromisoformat(year + '-01-04T00:00:00+00:00'))
            self.assertEqual(len(events), 1)

    def test_calendar_write_rejects_collision_only_when_native_events_exist(self):
        settings = {'sources': [dict(id='webclock', name='ICS', provider='ics',
                                     url='https://example.invalid/calendar.ics', display_enabled=True)]}
        client = clock.app.test_client()
        client.environ_base['HTTP_X_CSRF_TOKEN'] = client.get('/api/csrf').json['csrf_token']
        denied = client.post('/api/calendar', json=settings)
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json['code'], 'calendar_source_conflict')
        self.assertFalse((self.root / 'calendar.json').exists())
        save_events(self.root, [])
        accepted = client.post('/api/calendar', json=settings)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(clock.get_calendar_sources()[0]['provider'], 'ics')

    def test_native_snapshot_does_not_invert_storage_and_settings_lock_order(self):
        entered = Event()
        original = clock.native_event_rows
        def snapshot(*args, **kwargs):
            entered.set()
            with storage_lock:
                return original(*args, **kwargs)
        with patch.object(clock, 'native_event_rows', side_effect=snapshot), ThreadPoolExecutor(max_workers=1) as pool:
            with storage_lock:
                pending = pool.submit(clock.get_calendar_events, self.now, self.now + timedelta(days=1), ['webclock'])
                self.assertTrue(entered.wait(1))
                available = clock.settings_lock.acquire(timeout=1)
                if available:
                    clock.settings_lock.release()
            self.assertTrue(available, 'Calendar reads held settings while waiting for native storage')
            self.assertEqual(pending.result(timeout=2)[0]['uid'], 'meeting')


if __name__ == '__main__':
    unittest.main()
