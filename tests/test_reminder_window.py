import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app as clock


class ReminderWindowTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'manual_notes.json'
        notes_patch = patch.object(clock, 'NOTES_FILE', str(self.path))
        notes_patch.start()
        self.addCleanup(notes_patch.stop)
        calendar_patch = patch.object(clock, 'get_calendar_events', return_value=[])
        calendar_patch.start()
        self.addCleanup(calendar_patch.stop)
        self.client = clock.app.test_client()

    def visible(self, local_time):
        now = datetime.fromisoformat(local_time).replace(tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock, 'get_local_now', return_value=now):
            response = self.client.get('/api/status')
        self.assertEqual(response.status_code, 200)
        return response.json['events']

    def test_cross_day_boundaries_and_storage(self):
        response = self.client.post('/add', data={
            'note_text': 'meeting', 'note_date': '2026-09-12', 'note_time': '10:00',
            'display_start': '2026-09-10T09:00', 'display_end': '2026-09-12T18:00',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(json.loads(self.path.read_text())[0]['display_end'], '2026-09-12T18:00')
        for moment, expected in [
            ('2026-09-10T08:59:59', []),
            ('2026-09-10T09:00:00', [{'text': 'meeting', 'time': '10:00'}]),
            ('2026-09-11T00:00:00', [{'text': 'meeting', 'time': '10:00'}]),
            ('2026-09-12T17:59:59', [{'text': 'meeting', 'time': '10:00'}]),
            ('2026-09-12T18:00:00', []),
        ]:
            with self.subTest(moment=moment):
                self.assertEqual(self.visible(moment), expected)
        self.assertEqual(len(clock.load_notes()), 1)

    def test_legacy_notes_and_clear_window(self):
        self.path.write_text(json.dumps([
            {'id': 1, 'text': 'always'},
            {'id': 2, 'text': 'today', 'due_date': '2026-09-10 18:00'},
            {'id': 3, 'text': 'tomorrow', 'due_date': '2026-09-11'},
        ]))
        self.assertEqual(self.visible('2026-09-10T08:00'), [
            {'text': 'today', 'time': '18:00'}, {'text': 'always', 'time': ''},
        ])
        self.assertEqual(self.client.post('/schedule/1', data={
            'display_start': '2026-09-11T09:00', 'display_end': '2026-09-11T10:00',
        }).status_code, 302)
        self.assertEqual(self.visible('2026-09-10T08:00'), [{'text': 'today', 'time': '18:00'}])
        self.assertEqual(self.client.post('/schedule/1', data={}).status_code, 302)
        self.assertEqual(len(self.visible('2026-09-10T08:00')), 2)
        self.assertEqual(self.client.post('/schedule/999', data={}).status_code, 404)
        self.assertEqual(len(clock.load_notes()), 3)

    def test_invalid_windows_preserve_data_and_draft(self):
        clock.save_note('existing', '')
        original = self.path.read_bytes()
        for start, end in [
            ('2026-09-10T09:00', ''), ('', '2026-09-10T10:00'),
            ('2026-09-10T09:00', '2026-09-10T09:00'),
            ('2026-09-10T10:00', '2026-09-10T09:00'),
            ('2026-02-30T09:00', '2026-09-10T10:00'),
            ('garbage', '2026-09-10T10:00'),
            ('2026-09-10T09:00+08:00', '2026-09-10T10:00'),
        ]:
            for route in ('/add', '/schedule/1'):
                with self.subTest(start=start, end=end, route=route):
                    response = self.client.post(route, data={
                        'note_text': 'draft kept', 'display_start': start, 'display_end': end,
                    })
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(b'role="alert"', response.data)
                    if route == '/add':
                        self.assertIn(b'value="draft kept"', response.data)
                    self.assertEqual(self.path.read_bytes(), original)

    def test_configured_timezone_and_bad_stored_window(self):
        clock.save_note('morning', '', '2026-09-10T09:00', '2026-09-10T10:00')
        clock.save_note('invalid', '', 'invalid', '2026-09-10T10:00')
        instant = datetime(2026, 9, 10, 1, 30, tzinfo=timezone.utc)
        with patch.object(clock, 'datetime') as mocked_datetime:
            mocked_datetime.now.side_effect = lambda tz: instant.astimezone(tz)
            mocked_datetime.strptime = datetime.strptime
            with patch.dict(clock.display_settings, timezone_offset=8):
                self.assertEqual(self.client.get('/api/status').json['events'], [
                    {'text': 'morning', 'time': ''},
                ])
            with patch.dict(clock.display_settings, timezone_offset=0):
                self.assertEqual(self.client.get('/api/status').json['events'], [])

    def test_legacy_post_and_all_admin_languages(self):
        self.assertEqual(self.client.post('/add', data={'note_text': 'old client'}).status_code, 302)
        self.assertEqual(self.visible('2026-09-10T09:00'), [{'text': 'old client', 'time': ''}])
        for language in clock.SUPPORTED_LANGUAGES:
            with patch.dict(clock.display_settings, language=language):
                response = self.client.get('/admin')
                self.assertEqual(response.status_code, 200)
                self.assertIn(clock.UI_TRANSLATIONS[language]['display_window'].encode(), response.data)

    def test_daily_windows_including_overnight(self):
        response = self.client.post('/add', data={
            'note_text': 'daily', 'note_date': '2026-01-01',
            'display_mode': 'daily', 'display_start': '09:00', 'display_end': '18:00',
        })
        self.assertEqual(response.status_code, 302)
        for moment, shown in [
            ('2026-09-10T08:59:59', False), ('2026-09-10T09:00', True),
            ('2026-09-10T17:59:59', True), ('2026-09-10T18:00', False),
            ('2026-09-11T09:00', True),
        ]:
            with self.subTest(moment=moment):
                self.assertEqual(bool(self.visible(moment)), shown)
        self.assertEqual(self.client.post('/schedule/1', data={
            'display_mode': 'daily', 'display_start': '22:00', 'display_end': '06:00',
        }).status_code, 302)
        for moment, shown in [
            ('2026-09-10T21:59:59', False), ('2026-09-10T22:00', True),
            ('2026-09-11T00:00', True), ('2026-09-11T05:59:59', True),
            ('2026-09-11T06:00', False), ('2026-09-11T12:00', False),
        ]:
            with self.subTest(moment=moment):
                self.assertEqual(bool(self.visible(moment)), shown)
        page = self.client.get('/admin').data
        self.assertIn(b'type="time" name="display_start" value="22:00"', page)

    def test_invalid_daily_windows_and_mode(self):
        clock.save_note('existing', '')
        original = self.path.read_bytes()
        for start, end in [('09:00', ''), ('', '18:00'), ('09:00', '09:00'),
                           ('24:00', '06:00'), ('9:00', '18:00'),
                           ('2026-09-10T09:00', '18:00')]:
            response = self.client.post('/schedule/1', data={
                'display_mode': 'daily', 'display_start': start, 'display_end': end,
            })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.client.post('/schedule/1', data={
            'display_mode': 'unknown',
        }).status_code, 400)
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
