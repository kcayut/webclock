"""One integration path for calendar selection, browser alarms and old devices."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from threading import Barrier, Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.storage import revision


class CalendarAlarmApiTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.client = clock.app.test_client()
        self.now = datetime.fromisoformat('2026-09-30T09:00:00+08:00')
        for name, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                            ('NOTES_FILE', str(self.root / 'notes.json')),
                            ('ICAL_URL', ''), ('calendar_feed_cache', {})]:
            mock = patch.object(clock, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        for target in ('webclock.api.management.taipei_now', 'webclock.app.get_local_now'):
            mock = patch(target, return_value=self.now)
            mock.start()
            self.addCleanup(mock.stop)
        payload = '''BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:meeting
DTSTART:20260930T023045Z
DTEND:20260930T030000Z
SUMMARY:Team meeting
END:VEVENT
END:VCALENDAR
'''.replace('\n', '\r\n').encode()
        mock = patch.object(clock.requests, 'get', return_value=SimpleNamespace(
            content=payload, raise_for_status=lambda: None))
        self.download = mock.start()
        self.addCleanup(mock.stop)
        response = self.client.post('/api/calendar', json={
            'sources': [dict(id='work', name='工作', provider='google',
                             url='https://calendar.example/private-token.ics', display_enabled=True)],
            'local_display_enabled': True})
        self.assertEqual(response.status_code, 200, response.json)

    def add_alarm(self, identifier, **fields):
        data = dict(id=identifier, name=identifier, time='09:10', **fields)
        response = self.client.post('/api/v1/schedules', json=data)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def test_visibility_is_independent_from_alarm_link_and_private_urls_stay_private(self):
        self.add_alarm('event', calendar_link=dict(mode='event', source_ids=['work'], offset_minutes=30))
        self.add_alarm('day', calendar_link=dict(mode='day', source_ids=['work'], offset_minutes=0))
        self.add_alarm('regular')
        expected = {'event': '2026-09-30T10:00:45+08:00', 'day': '2026-09-30T09:10:00+08:00',
                    'regular': '2026-09-30T09:10:00+08:00'}
        response = self.client.get('/api/v1/schedules')
        self.assertEqual({row['id']: row['next_occurrence'] for row in response.json['schedules']}, expected)
        self.assertEqual({row['id'] for row in response.json['calendar_sources']}, {'local', 'work'})
        preview = self.client.post('/api/v1/schedules/preview', json={'id': 'event'})
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertEqual(preview.json['next_occurrence'], expected['event'])
        self.assertNotIn('private-token', preview.text)
        self.assertTrue(self.client.get('/api/status').json['events'])
        response = self.client.patch('/api/calendar', json={
            'sources': [{'id': 'work', 'display_enabled': False}], 'local_display_enabled': False})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.client.get('/api/status').json['events'], [])
        alarms = self.client.get('/api/v1/browser-alarms').json['alarms']
        self.assertEqual({row['id']: row['starts_at'] for row in alarms}, {
            key: int(datetime.fromisoformat(value).timestamp() * 1000) for key, value in expected.items()})
        for route in ('/api/status', '/api/v1/browser-alarms', '/api/v1/schedules',
                      '/api/v1/device/config', '/api/v1/device/schedules', '/api/backup', '/', '/schedules'):
            self.assertNotIn('private-token', self.client.get(route).text, route)
        device = self.client.get('/api/v1/device/schedules').json
        self.assertEqual([row['id'] for row in device['schedules']], ['regular'])
        self.assertEqual(device['revision'], revision(device['schedules']))
        self.assertEqual(self.client.get('/api/v1/device/config').json['schedule_revision'], device['revision'])
        skipped = self.client.post('/api/v1/schedules/event/skip-next')
        self.assertEqual(skipped.status_code, 200, skipped.json)
        self.assertEqual(skipped.json['skipped']['datetime'], expected['event'])
        self.assertIsNone(skipped.json['next_event'])

    def test_local_source_and_missing_external_source_never_fall_back_to_daily_alarm(self):
        (self.root / 'notes.json').write_text(json.dumps([
            dict(id=1, text='本地會議', due_date='2026-09-30 11:30', enabled=True)]))
        self.add_alarm('local', calendar_link=dict(mode='event', source_ids=['local'], offset_minutes=15))
        self.add_alarm('external', calendar_link=dict(mode='day', source_ids=['work'], offset_minutes=0))
        self.client.patch('/api/calendar', json={'local_display_enabled': False})
        rows = self.client.get('/api/v1/schedules').json['schedules']
        self.assertEqual(rows[0]['next_occurrence'], '2026-09-30T11:15:00+08:00')
        self.client.post('/api/calendar', json={'sources': [], 'local_display_enabled': False})
        rows = self.client.get('/api/v1/schedules').json['schedules']
        self.assertIsNone(rows[1]['next_occurrence'])
        invalid = self.client.post('/api/v1/schedules', json=dict(name='missing', time='09:00',
            calendar_link=dict(mode='day', source_ids=['removed'], offset_minutes=0)))
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.put('/api/v1/schedules/external', json={'enabled': False}).status_code, 200)

    def test_browser_response_keeps_two_linked_events_in_the_same_minute(self):
        self.add_alarm('seconds', calendar_link=dict(mode='event', source_ids=['work'], offset_minutes=30))
        now = datetime.fromisoformat('2026-09-30T10:00:50+08:00')
        events = []
        for second in (45, 55):
            stamp = int(now.replace(minute=30, second=second).timestamp() * 1000)
            events.append(dict(source_id='work', uid='event-' + str(second), all_day=False,
                               starts_at=stamp, ends_at=stamp))
        with patch('webclock.api.management.taipei_now', return_value=now), \
             patch.object(clock, 'get_calendar_events', return_value=events) as lookup:
            alarms = self.client.get('/api/v1/browser-alarms').json['alarms']
        self.assertEqual([row['starts_at'] for row in alarms], [
            int(now.replace(second=second).timestamp() * 1000) for second in (45, 55)])
        self.assertEqual(lookup.call_count, 2)  # One feed warm-up and one shared occurrence window.

    def test_separately_linked_sources_download_together_on_cold_requests(self):
        sources = [dict(id='source-' + str(i), name='Calendar ' + str(i), provider='ics',
                        url='https://calendar.example/feed-' + str(i), display_enabled=False) for i in range(3)]
        response = self.client.post('/api/calendar', json=dict(sources=sources, local_display_enabled=False))
        self.assertEqual(response.status_code, 200, response.json)
        for source in sources:
            self.add_alarm(source['id'], calendar_link=dict(mode='event', source_ids=[source['id']], offset_minutes=0))
        payload = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:parallel\r\nDTSTART:20260930T023000Z\r\nSUMMARY:Parallel\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        for route in ('/api/v1/browser-alarms', '/api/v1/schedules', '/api/status'):
            with self.subTest(route=route):
                clock.calendar_feed_cache.clear()
                gate, lock = Barrier(3), Lock()
                fetched = []

                def download(url, **kwargs):
                    gate.wait(timeout=2)  # Sequential per-alarm fetches break this barrier.
                    with lock:
                        fetched.append(url)
                    return SimpleNamespace(content=payload, raise_for_status=lambda: None)

                with patch.object(clock.requests, 'get', side_effect=download):
                    response = self.client.get(route)
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(set(fetched), {source['url'] for source in sources})
                self.assertEqual(len(fetched), 3, 'Each source is fetched once per cold request')
                if route.endswith('browser-alarms'):
                    self.assertEqual(len(response.json['alarms']), 3)
                elif route.endswith('schedules'):
                    self.assertTrue(all(row['next_occurrence'] for row in response.json['schedules']))
                else:
                    self.assertIsNotNone(response.json['next_event'])

    def test_calendar_download_time_does_not_make_the_browser_clock_run_late(self):
        self.add_alarm('event', calendar_link=dict(mode='event', source_ids=['work'], offset_minutes=30))
        response_time = self.now + timedelta(seconds=5)
        with patch('webclock.api.management.taipei_now', side_effect=[self.now, response_time]):
            response = self.client.get('/api/v1/browser-alarms')
        self.assertEqual(response.json['server_timestamp'], int(response_time.timestamp() * 1000))

    def test_event_catalog_selects_sources_and_exposes_only_event_fields(self):
        (self.root / 'notes.json').write_text(json.dumps([
            dict(id=1, text='本地會議', due_date='2026-09-30 11:30', enabled=True)]))
        response = self.client.get('/api/v1/calendar-events?source_id=work')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(response.json['events']), 1)
        event = response.json['events'][0]
        self.assertEqual(set(event), {'source_id', 'uid', 'text', 'starts_at', 'ends_at',
                                      'all_day', 'recurring', 'recurrence_id'})
        self.assertEqual((event['source_id'], event['uid'], event['recurring'], event['recurrence_id']),
                         ('work', 'meeting', False, ''))
        self.assertEqual(response.json['server_time'], self.now.isoformat())
        self.assertNotIn('private-token', response.text)
        response = self.client.get('/api/v1/calendar-events?source_id=local&source_id=work')
        self.assertEqual({event['source_id'] for event in response.json['events']}, {'local', 'work'})
        for query in ('', '?source_id=', '?source_id=missing', '?source_id=work&url=private',
                      '?source_id=work&source_id=missing'):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/v1/calendar-events' + query).status_code, 400)

    def test_selected_occurrence_and_series_follow_reschedule_and_cancellation(self):
        master = '''BEGIN:VEVENT
UID:weekly
DTSTART:20260930T023000Z
DTEND:20260930T030000Z
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Weekly meeting
END:VEVENT
'''
        other = '''BEGIN:VEVENT
UID:other
DTSTART:20260930T013000Z
SUMMARY:Other meeting
END:VEVENT
'''

        def feed(events):
            self.download.return_value.content = ('BEGIN:VCALENDAR\nVERSION:2.0\n' + events
                + 'END:VCALENDAR\n').replace('\n', '\r\n').encode()
            clock.calendar_feed_cache.clear()

        def expected(once, series):
            rows = self.client.get('/api/v1/schedules').json['schedules']
            self.assertEqual({row['id']: row['next_occurrence'] for row in rows},
                             {'once': once, 'series': series})
            self.assertEqual(self.client.post('/api/v1/schedules/preview', json={'id': 'once'}
                ).json['next_occurrence'], once)
            alarms = self.client.get('/api/v1/browser-alarms').json['alarms']
            self.assertEqual({row['id']: row['starts_at'] for row in alarms}, {
                key: int(datetime.fromisoformat(value).timestamp() * 1000)
                for key, value in [('once', once), ('series', series)] if value})

        feed(master + other)
        events = self.client.get('/api/v1/calendar-events?source_id=work').json['events']
        occurrence = next(event for event in events if event['uid'] == 'weekly')
        self.assertTrue(occurrence['recurring'])
        self.assertTrue(occurrence['recurrence_id'])
        for identifier, scope in [('once', 'occurrence'), ('series', 'series')]:
            self.add_alarm(identifier, calendar_link=dict(mode='event', source_ids=['work'], offset_minutes=10,
                target=dict(source_id='work', uid='weekly', scope=scope,
                            recurrence_id=occurrence['recurrence_id'] if scope == 'occurrence' else '')))
        expected('2026-09-30T10:20:00+08:00', '2026-09-30T10:20:00+08:00')

        moved = '''BEGIN:VEVENT
UID:weekly
RECURRENCE-ID:20260930T023000Z
DTSTART:20261001T033000Z
DTEND:20261001T040000Z
SUMMARY:Moved weekly meeting
END:VEVENT
'''
        feed(master + moved + other)
        expected('2026-10-01T11:20:00+08:00', '2026-10-01T11:20:00+08:00')
        events = self.client.get('/api/v1/calendar-events?source_id=work').json['events']
        updated = next(event for event in events if event['uid'] == 'weekly')
        self.assertEqual(updated['recurrence_id'], occurrence['recurrence_id'])
        self.assertNotEqual(updated['starts_at'], occurrence['starts_at'])

        cancelled = '''BEGIN:VEVENT
UID:weekly
RECURRENCE-ID:20260930T023000Z
STATUS:CANCELLED
END:VEVENT
'''
        feed(master + cancelled + other)
        expected(None, '2026-10-07T10:20:00+08:00')
        events = self.client.get('/api/v1/calendar-events?source_id=work').json['events']
        self.assertFalse(any(event['uid'] == 'weekly' and event['recurrence_id'] == occurrence['recurrence_id']
                             for event in events))

        feed(master.replace('SUMMARY:Weekly meeting', 'STATUS:CANCELLED\nSUMMARY:Weekly meeting') + other)
        expected(None, None)


if __name__ == '__main__':
    unittest.main()
