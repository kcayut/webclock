import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier
from unittest.mock import patch

import app as clock


class CalendarSettingsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                            ('NOTES_FILE', str(self.root / 'notes.json')),
                            ('ICAL_URL', 'https://old.example/private.ics'),
                            ('calendar_feed_cache', {})]:
            item = patch.object(clock, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.client = clock.app.test_client()

    def test_save_reload_clear_legacy_and_private_responses(self):
        self.assertEqual(self.client.get('/api/calendar').json['url'], clock.ICAL_URL)
        url = 'webcal://p01-caldav.icloud.com/published/2/test-private-token'
        self.assertEqual(self.client.post('/api/calendar', json={'url': ' ' + url + ' '}).status_code, 200)
        saved = self.client.get('/api/calendar')
        self.assertEqual(saved.json['url'], url.replace('webcal:', 'https:'))
        self.assertEqual(saved.headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', saved.headers)
        path = self.root / 'calendar.json'
        self.assertEqual(json.loads(path.read_text()), {key: saved.json[key] for key in ('sources', 'local_display_enabled')})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for endpoint in ['/', '/admin', '/api/backup']:
            self.assertNotIn('test-private-token', self.client.get(endpoint).text)
        with patch.object(clock, 'get_calendar_events', return_value=[]):
            self.assertNotIn('test-private-token', self.client.get('/api/status').text)
        self.assertEqual(self.client.post('/api/calendar', json={'url': ''}).status_code, 200)
        self.assertEqual(clock.get_calendar_url(), '')
        with patch.object(clock.requests, 'get') as fetch:
            self.assertEqual(clock.get_calendar_events(), [])
            fetch.assert_not_called()

    def test_invalid_input_cross_origin_and_write_failure_preserve_source(self):
        self.client.post('/api/calendar', json={'url': 'https://example.com/kept.ics'})
        original = (self.root / 'calendar.json').read_bytes()
        for value in [None, [], 1, 'file:///etc/passwd', 'javascript:alert(1)', 'https://',
                      'https://user:pass@example.com/x', 'https://example.com:bad/x',
                      'https://example.com:99999/x', 'https://example.com/x\nsecret',
                      'https://example.com/x#fragment', 'https://example.com/\\x', 'x' * 4097]:
            with self.subTest(value=value):
                self.assertEqual(self.client.post('/api/calendar', json={'url': value}).status_code, 400)
        self.assertEqual(self.client.post('/api/calendar', json={}).status_code, 400)
        for method in [self.client.get, self.client.post]:
            response = method('/api/calendar', headers={'Origin': 'https://another.example'}, json={'url': ''})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        with patch.object(clock, 'save_json', side_effect=OSError('disk full')):
            cache_key = (str(self.root), 'https://example.com/kept.ics')
            clock.calendar_feed_cache[cache_key] = {'fetched_at': 1, 'calendar': None, 'queries': {}}
            self.assertEqual(self.client.post('/api/calendar', json={'url': ''}).status_code, 500)
        self.assertEqual(clock.get_calendar_url(), 'https://example.com/kept.ics')
        self.assertIn(cache_key, clock.calendar_feed_cache)
        self.assertEqual(clock.calendar_feed_cache[cache_key]['fetched_at'], 1)
        self.assertEqual((self.root / 'calendar.json').read_bytes(), original)

    def test_feed_switch_failure_midnight_and_timezone_do_not_reuse_wrong_events(self):
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        payload = (b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n'
                   b'DTSTART:20260930T020000Z\r\nSUMMARY:Meeting\r\nEND:VEVENT\r\n'
                   b'BEGIN:VEVENT\r\nSUMMARY:No start\r\nEND:VEVENT\r\n'
                   b'BEGIN:VEVENT\r\nDTSTART:20260930T020000Z\r\nSTATUS:CANCELLED\r\n'
                   b'SUMMARY:Cancelled\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
        response = SimpleNamespace(content=payload, raise_for_status=lambda: None)
        with patch.object(clock, 'get_local_now', return_value=now) as local_now, \
             patch.object(clock.requests, 'get', return_value=response) as fetch:
            self.assertEqual(clock.get_calendar_events()[0]['time'], '10:00')
            self.assertEqual(len(clock.get_calendar_events()), 1)
            self.assertEqual(fetch.call_count, 1)
            local_now.return_value = now.astimezone(timezone.utc)
            self.assertEqual(clock.get_calendar_events()[0]['time'], '02:00')
            self.assertEqual(fetch.call_count, 1)
            self.client.post('/api/calendar', json={'url': 'webcal://new.example/secret'})
            fetch.side_effect = clock.requests.RequestException('https://new.example/secret')
            with self.assertLogs(clock.app.logger, level='WARNING') as logs:
                self.assertEqual(clock.get_calendar_events(), [])
            self.assertNotIn('secret', ''.join(logs.output))
            fetch.assert_called_with('https://new.example/secret', timeout=(2, 3))
            fetch.side_effect = None
            for cached in clock.calendar_feed_cache.values():
                cached['fetched_at'] = 0
            self.assertTrue(clock.get_calendar_events())
            local_now.return_value += timedelta(days=1)
            fetch.side_effect = clock.requests.RequestException('offline')
            self.assertEqual(clock.get_calendar_events(), [])

    def test_recurring_icloud_events_exceptions_timezones_and_multiday(self):
        payload = '''BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly
DTSTART:20260923T020000Z
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Weekly
END:VEVENT
BEGIN:VEVENT
UID:excluded
DTSTART:20260923T030000Z
RRULE:FREQ=WEEKLY;COUNT=3
EXDATE:20260930T030000Z
SUMMARY:Excluded
END:VEVENT
BEGIN:VEVENT
UID:moved
DTSTART;TZID=Asia/Taipei:20260923T090000
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Original
END:VEVENT
BEGIN:VEVENT
UID:moved
RECURRENCE-ID;TZID=Asia/Taipei:20260930T090000
DTSTART;TZID=Asia/Taipei:20260930T103000
SUMMARY:Moved
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTART:20260923T040000Z
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Original cancelled
END:VEVENT
BEGIN:VEVENT
UID:cancelled
RECURRENCE-ID:20260930T040000Z
STATUS:CANCELLED
SUMMARY:Cancelled occurrence
END:VEVENT
BEGIN:VEVENT
UID:multiday
DTSTART;VALUE=DATE:20260929
DTEND;VALUE=DATE:20261002
SUMMARY:Trip
END:VEVENT
BEGIN:VEVENT
UID:floating
DTSTART:20260929T130000
RRULE:FREQ=DAILY;COUNT=2
SUMMARY:Floating
END:VEVENT
BEGIN:VEVENT
UID:extra-date
DTSTART:20260901T060000Z
RDATE:20260930T060000Z
SUMMARY:Extra date
END:VEVENT
END:VCALENDAR
'''.replace('\n', '\r\n').encode()
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock, 'get_local_now', return_value=now), \
             patch.object(clock.requests, 'get', return_value=SimpleNamespace(content=payload, raise_for_status=lambda: None)):
            events = {item['text']: item for item in clock.get_calendar_events()}
        self.assertEqual({text: event['time'] for text, event in events.items()}, {
            'Weekly': '10:00', 'Moved': '10:30', 'Trip': '', 'Floating': '13:00', 'Extra date': '14:00'})
        self.assertTrue(events['Trip']['all_day'])
        self.assertEqual(events['Trip']['start_date'], '2026-09-29')
        self.assertEqual(events['Trip']['end_date'], '2026-10-02')
        self.assertEqual(events['Moved']['starts_at'], int((now + timedelta(minutes=90)).timestamp() * 1000))
        self.assertTrue(events['Moved']['recurring'])
        self.assertEqual(events['Moved']['recurrence_id'], '2026-09-30T01:00:00+00:00')
        self.assertEqual(events['Weekly']['recurrence_id'], '2026-09-30T02:00:00+00:00')
        self.assertEqual(events['Floating']['recurrence_id'], '2026-09-30T13:00:00')
        self.assertTrue(events['Extra date']['recurring'])
        self.assertFalse(events['Trip']['recurring'])
        self.assertEqual(events['Trip']['recurrence_id'], '')

    def test_single_event_identity_survives_reschedule_and_timezone_query(self):
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        response = self.response()
        with patch.object(clock.requests, 'get', return_value=response):
            before = clock.get_calendar_events(now, now + timedelta(days=1))[0]
            response.content = response.content.replace(b'20260930T020000Z', b'20260930T040000Z')
            for cached in clock.calendar_feed_cache.values():
                cached['fetched_at'] = 0
            utc = now.astimezone(timezone.utc)
            after = clock.get_calendar_events(utc, utc + timedelta(days=1))[0]
        self.assertEqual((before['uid'], before['recurrence_id']), (after['uid'], after['recurrence_id']))
        self.assertEqual(after['recurrence_id'], '')
        self.assertFalse(after['recurring'])
        self.assertEqual(after['starts_at'] - before['starts_at'], 2 * 3600 * 1000)


    def source(self, source_id='', name='Work', url='https://calendar.example/work.ics', **values):
        return dict(id=source_id, name=name, provider='ics', url=url, **values)

    def response(self, title='Work', rule=''):
        text = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:event-1\r\n'
                'DTSTART:20260930T020000Z\r\nSUMMARY:' + title + '\r\n' + rule +
                'END:VEVENT\r\nEND:VCALENDAR\r\n')
        return SimpleNamespace(content=text.encode(), raise_for_status=lambda: None)

    def test_multiple_sources_stable_ids_defaults_and_legacy_migration(self):
        original = self.client.get('/api/calendar').json
        self.assertEqual(original['sources'][0]['id'], 'legacy')
        self.assertTrue(original['local_display_enabled'])
        (self.root / 'calendar.json').write_text(json.dumps({'url': clock.ICAL_URL}))
        self.assertEqual(clock.get_calendar_sources(), original['sources'])
        sources = original['sources'] + [self.source(name='Family', url='webcal://p01.icloud.com/private')]
        saved = self.client.post('/api/calendar', json={'sources': sources}).json
        new_id = saved['sources'][1]['id']
        self.assertTrue(new_id)
        self.assertNotEqual(new_id, 'legacy')
        self.assertTrue(all(source['display_enabled'] for source in saved['sources']))
        saved['sources'][1].update(name='Renamed', url='https://p02.icloud.com/updated')
        saved.pop('status')
        self.assertEqual(self.client.post('/api/calendar', json=saved).status_code, 200)
        self.assertEqual(clock.get_calendar_sources()[1]['id'], new_id)
        self.assertEqual(json.loads((self.root / 'calendar.json').read_text())['sources'][1]['id'], new_id)
        # Older single-source clients retain the IDs and any later subscriptions.
        self.client.post('/api/calendar', json={'url': 'https://first.example/new'})
        self.assertEqual([item['id'] for item in clock.get_calendar_sources()], ['legacy', new_id])
        self.assertEqual(self.client.post('/api/calendar', json={'sources': []}).status_code, 200)
        self.assertEqual(clock.get_calendar_sources(), [])
        self.assertEqual(clock.get_calendar_url(), '')

    def test_display_patch_preserves_urls_and_local_alarm_data(self):
        saved = self.client.post('/api/calendar', json={'sources': [self.source()]}).json
        source = saved['sources'][0]
        self.client.post('/add', data={'note_text': 'Local appointment', 'note_date': '2026-09-30', 'note_time': '11:00'})
        response = self.client.patch('/api/calendar', json={
            'sources': [{'id': source['id'], 'display_enabled': False}], 'local_display_enabled': False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['sources'][0]['url'], source['url'])
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock, 'get_local_now', return_value=now), \
             patch.object(clock.requests, 'get', return_value=self.response()) as fetch:
            self.assertEqual(clock.get_calendar_events(), [])
            fetch.assert_not_called()
            status = self.client.get('/api/status').json
            self.assertEqual(status['events'], [])
            self.assertIsNone(status['next_event'])
            events = clock.get_calendar_events(now, now + timedelta(days=1), [source['id'], 'local'])
            self.assertEqual({event['text'] for event in events}, {'Work', 'Local appointment'})
        self.assertEqual(len(clock.load_notes()), 1)
        self.assertNotIn(source['url'], json.dumps(status))

    def test_source_and_visibility_validation_preserves_saved_data(self):
        self.client.post('/api/calendar', json={'sources': [self.source('kept')]})
        original = (self.root / 'calendar.json').read_bytes()
        invalid_sources = [[self.source('local')], [self.source('bad id')], [self.source('x'), self.source('x')],
                           [self.source(name=' ')], [dict(self.source(), provider='other')],
                           [self.source(display_enabled='false')], [self.source(url='')],
                           [self.source() for _ in range(clock.MAX_CALENDAR_SOURCES + 1)]]
        for sources in invalid_sources:
            with self.subTest(sources=sources):
                self.assertEqual(self.client.post('/api/calendar', json={'sources': sources}).status_code, 400)
        for change in [{'sources': [{'id': 'missing', 'display_enabled': False}]},
                       {'sources': [{'id': 'kept', 'display_enabled': 0}]},
                       {'sources': [{'id': 'kept', 'display_enabled': True, 'url': 'https://changed.example'}]},
                       {'local_display_enabled': 'false'}]:
            self.assertEqual(self.client.patch('/api/calendar', json=change).status_code, 400)
        self.assertEqual((self.root / 'calendar.json').read_bytes(), original)
        self.assertEqual(self.client.patch('/api/calendar', headers={'Origin': 'https://other.example'},
                                          json={'local_display_enabled': False}).status_code, 403)

    def test_source_errors_do_not_hide_other_events_or_reuse_stale_feed(self):
        self.client.post('/api/calendar', json={'sources': [
            self.source('good', url='https://good.example/feed'), self.source('bad', url='https://bad.example/private')]})
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        def download(url, **kwargs):
            if 'bad.example' in url:
                raise clock.requests.RequestException('private secret URL')
            return self.response()
        with patch.object(clock, 'get_local_now', return_value=now), \
             patch.object(clock.requests, 'get', side_effect=download):
            with self.assertLogs(clock.app.logger, level='WARNING') as logs:
                events = clock.get_calendar_events()
            self.assertEqual([event['source_id'] for event in events], ['good'])
            self.assertNotIn('secret', ''.join(logs.output))
            self.assertEqual(self.client.get('/api/calendar').json['errors'], [{'id': 'bad', 'error': 'fetch_failed'}])
            for cached in clock.calendar_feed_cache.values():
                cached['fetched_at'] = 0
            with patch.object(clock.requests, 'get', side_effect=clock.requests.RequestException('offline')):
                self.assertEqual(clock.get_calendar_events(), [])

    def test_query_cache_reuses_feed_for_sources_ranges_and_timezones(self):
        self.client.post('/api/calendar', json={'sources': [self.source('one'), self.source('two')]})
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock.requests, 'get', return_value=self.response()) as fetch, \
             patch.object(clock.recurring_ical_events, 'of', wraps=clock.recurring_ical_events.of) as expand:
            first = clock.get_calendar_events(now, now + timedelta(days=2), ['one', 'two'])
            second = clock.get_calendar_events(now + timedelta(seconds=15), now + timedelta(days=2, seconds=15), ['one'])
            self.assertEqual({event['source_id'] for event in first}, {'one', 'two'})
            self.assertEqual(second[0]['time'], '10:00')
            self.assertEqual(expand.call_count, 1)
            self.assertEqual(fetch.call_count, 1)
            utc = now.astimezone(timezone.utc)
            self.assertEqual(clock.get_calendar_events(utc, utc + timedelta(days=1), ['one'])[0]['time'], '02:00')
            self.assertEqual(fetch.call_count, 1)
            for days in range(2, 8):
                clock.get_calendar_events(now, now + timedelta(days=days), ['one'])
            self.assertLessEqual(len(next(iter(clock.calendar_feed_cache.values()))['queries']), clock.MAX_CALENDAR_QUERY_CACHE)

    def test_distinct_feeds_download_concurrently_and_duplicate_urls_download_once(self):
        self.client.post('/api/calendar', json={'sources': [self.source('one'), self.source('duplicate'),
            self.source('two', url='https://second.example/feed')]})
        barrier = Barrier(2)
        def download(url, **kwargs):
            barrier.wait(timeout=2)
            return self.response()
        now = datetime(2026, 9, 30, 9, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock.requests, 'get', side_effect=download) as fetch:
            events = clock.get_calendar_events(now, now + timedelta(days=1))
        self.assertEqual({event['source_id'] for event in events}, {'one', 'duplicate', 'two'})
        self.assertEqual(fetch.call_count, 2)

    def test_half_open_overlap_and_invalid_query_bounds(self):
        now = datetime(2026, 9, 30, 10, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock.requests, 'get', return_value=self.response()):
            self.assertTrue(clock.get_calendar_events(now, now + timedelta(hours=1)))
            self.assertEqual(clock.get_calendar_events(now - timedelta(hours=1), now), [])
        for start, end in [(now.replace(tzinfo=None), now), (now, now), (now, now + timedelta(days=367))]:
            with self.assertRaises(ValueError):
                clock.get_calendar_events(start, end)

    def test_large_recurrence_rejected_before_expansion_and_failure_cached(self):
        now = datetime(2026, 9, 30, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock.requests, 'get', return_value=self.response(rule='RRULE:FREQ=SECONDLY\r\n')), \
             patch.object(clock.recurring_ical_events, 'of') as expand:
            with self.assertLogs(clock.app.logger, level='WARNING'):
                self.assertEqual(clock.get_calendar_events(now, now + timedelta(days=366)), [])
            self.assertEqual(clock.get_calendar_events(now, now + timedelta(days=366)), [])
            expand.assert_not_called()
        self.assertEqual(self.client.get('/api/calendar').json['errors'], [{'id': 'legacy', 'error': 'event_limit'}])

    def test_local_reminder_timezone_daily_priority_range_and_all_day(self):
        notes = [
            dict(id=1, text='Floating permanent', due_date=''),
            dict(id=2, text='Daily', due_date='2020-01-01 01:00', display_mode='daily',
                 display_start='09:00', display_end='10:00', weekdays=[2]),
            dict(id=3, text='Range', due_date='', display_mode='range',
                 display_start='2026-09-30T11:00', display_end='2026-10-01T12:00'),
            dict(id=4, text='Date', due_date='2026-09-30'),
            dict(id=5, text='Hidden at due', due_date='2026-09-30 08:00', display_mode='range',
                 display_start='2026-09-30T11:00', display_end='2026-09-30T12:00'),
            dict(id=6, text='Disabled', due_date='2026-09-30 10:00', enabled=False),
        ]
        Path(clock.NOTES_FILE).write_text(json.dumps(notes))
        start = datetime(2026, 9, 30, tzinfo=timezone(timedelta(hours=8)))
        local_now = datetime(2026, 9, 30, 1, tzinfo=timezone.utc)
        with patch.object(clock, 'get_local_now', return_value=local_now):
            events = {event['text']: event for event in clock.get_calendar_events(start, start + timedelta(days=1), ['local'])}
            notes[1].update(display_start='09:30', display_end='10:30')
            Path(clock.NOTES_FILE).write_text(json.dumps(notes))
            moved = next(event for event in clock.get_calendar_events(start, start + timedelta(days=1), ['local'])
                         if event['uid'] == '2')
        self.assertEqual(set(events), {'Daily', 'Range', 'Date'})
        self.assertEqual(events['Daily']['time'], '17:00')
        self.assertTrue(events['Daily']['recurring'])
        self.assertEqual(events['Daily']['recurrence_id'], '2026-09-30')
        self.assertEqual(moved['recurrence_id'], events['Daily']['recurrence_id'])
        self.assertEqual(moved['starts_at'] - events['Daily']['starts_at'], 30 * 60 * 1000)
        self.assertFalse(events['Range']['recurring'])
        self.assertEqual(events['Range']['recurrence_id'], '')
        self.assertEqual(events['Range']['time'], '19:00')
        self.assertTrue(events['Date']['all_day'])
        self.assertEqual(events['Date']['starts_at'], int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp() * 1000))


if __name__ == '__main__':
    unittest.main()
