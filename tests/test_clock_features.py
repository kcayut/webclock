import copy
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import app as clock


class ClockFeaturesTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, value in [('NOTES_FILE', str(self.root / 'notes.json')),
                            ('SETTINGS_FILE', str(self.root / 'settings.json')),
                            ('ICAL_URL', '')]:
            item = patch.object(clock, name, value)
            item.start()
            self.addCleanup(item.stop)
        item = patch.dict(clock.display_settings, copy.deepcopy(clock.DEFAULT_SETTINGS), clear=True)
        item.start()
        self.addCleanup(item.stop)
        self.client = clock.app.test_client()
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = self.client.get('/api/csrf').json['csrf_token']

    def status_at(self, value):
        now = datetime.fromisoformat(value).replace(tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock, 'get_local_now', return_value=now), patch.object(clock, 'get_calendar_events', return_value=[]):
            return self.client.get('/api/status').json

    def test_shared_settings_version_rejects_stale_page_and_preserves_failed_write(self):
        initial = self.client.get('/api/control')
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.headers['Cache-Control'], 'no-store')
        headers = {'If-Match': '"' + initial.json['revision'] + '"'}
        saved = self.client.post('/api/control', json={'brightness': 0}, headers=headers)
        self.assertEqual(saved.status_code, 200)
        self.assertNotEqual(saved.json['revision'], initial.json['revision'])
        before = Path(clock.SETTINGS_FILE).read_bytes()
        stale = self.client.post('/api/control', json={'brightness': 50}, headers=headers)
        self.assertEqual((stale.status_code, stale.json['code']), (409, 'settings_changed'))
        self.assertEqual(Path(clock.SETTINGS_FILE).read_bytes(), before)
        headers['If-Match'] = '"' + saved.json['revision'] + '"'
        with patch.object(clock, 'save_display_settings', side_effect=OSError('disk full')):
            self.assertEqual(self.client.post('/api/control', json={'brightness': 80}, headers=headers).status_code, 500)
        self.assertEqual(self.client.get('/api/control').json['revision'], saved.json['revision'])
        self.assertEqual(clock.display_settings['brightness'], 0)
        # Existing maintenance/updater clients remain compatible.
        self.assertEqual(self.client.post('/api/control', json={'brightness': 40}).status_code, 200)

    def test_clock_keeps_language_switching_without_management_labels(self):
        page = self.client.get('/').text
        labels = json.loads(re.search(r'var I18N = (.*);', page).group(1))
        self.assertEqual(set(labels), set(clock.SUPPORTED_LANGUAGES))
        for language, pack in labels.items():
            self.assertNotIn('calendar_url', pack)
            self.assertNotIn('backup_title', pack)
            self.assertNotIn('countdown', pack)
            self.assertNotIn('standard_time_unavailable', pack)
            for key in ['weekdays', 'offline_ready', 'offline_unavailable', 'offline_failed',
                        'connection_connecting', 'connection_connected', 'connection_saved',
                        'connection_standalone', 'connection_unreadable', 'connection_unavailable',
                        'connection_timeout', 'delete']:
                self.assertEqual(pack[key], clock.UI_TRANSLATIONS[language][key])
            with patch.dict(clock.display_settings, language=language):
                localized_page = self.client.get('/').text
                for key in re.findall(r'data-clock-i18n="([^"]+)"', localized_page):
                    self.assertIn(key, pack)
                    self.assertIn(pack[key], localized_page)
        self.assertIn('calendar_url', self.client.get('/admin').text)

    def test_weekday_overnight_edit_pause_and_countdown(self):
        fields = dict(note_text='garbage', display_mode='daily', display_start='22:00', display_end='06:00',
                      weekdays_present='1', weekdays=['0', '3'])
        self.assertEqual(self.client.post('/add', data=fields).status_code, 302)
        for time, visible in [('2026-09-14T21:59', False), ('2026-09-14T22:00', True),
                              ('2026-09-15T05:59', True), ('2026-09-15T06:00', False),
                              ('2026-09-15T22:00', False), ('2026-09-17T22:00', True)]:
            self.assertEqual(bool(self.status_at(time)['events']), visible, time)
        status = self.status_at('2026-09-14T21:45')
        self.assertEqual(status['next_event']['starts_at'] - status['server_timestamp'], 15 * 60000)
        self.assertEqual(self.client.post('/toggle/1').status_code, 302)
        status = self.status_at('2026-09-14T22:00')
        self.assertEqual(status['events'], [])
        self.assertIsNone(status['next_event'])
        fields.update(note_text='updated', note_date='2026-09-18', note_time='10:00')
        self.assertEqual(self.client.post('/schedule/1', data=fields).status_code, 302)
        note = clock.load_notes()[0]
        self.assertFalse(note['enabled'])
        self.assertEqual(note['text'], 'updated')
        self.assertEqual(note['due_date'], '2026-09-18 10:00')
        self.assertEqual(self.client.post('/toggle/1').status_code, 302)
        self.assertEqual(len(self.status_at('2026-09-14T22:00')['events']), 1)
        self.assertEqual(self.client.post('/toggle/999').status_code, 404)
        before = Path(clock.NOTES_FILE).read_bytes()
        for invalid in [dict(fields, weekdays=['7']), dict(fields, note_text=' '),
                        dict(fields, note_date='2026-02-30'), dict(fields, note_date='')]:
            self.assertEqual(self.client.post('/schedule/1', data=invalid).status_code, 400)
            self.assertEqual(Path(clock.NOTES_FILE).read_bytes(), before)

    def test_time_format_persistence_api_and_legacy_backup(self):
        legacy = {key: value for key, value in clock.DEFAULT_SETTINGS.items() if key != 'time_format'}
        Path(clock.SETTINGS_FILE).write_text(json.dumps(legacy))
        self.assertEqual(clock.load_display_settings()['time_format'], '24h')
        original_config = self.client.get('/api/v1/device/config').json
        for value in ('12h', '24h'):
            self.assertEqual(self.client.post('/api/control', json={'time_format': value}).status_code, 200)
            self.assertEqual(clock.load_display_settings()['time_format'], value)
            self.assertEqual(clock.template_context()['time_format'], value)
            self.assertEqual(self.client.get('/api/v1/schedules').json['time_format'], value)
            self.assertEqual(self.status_at('2026-10-01T10:30')['settings']['time_format'], value)
            self.assertEqual(self.client.get('/api/v1/device/config').json, original_config)
        backup = self.client.get('/api/backup').json
        backup['settings']['time_format'] = '12h'
        self.assertEqual(self.client.post('/api/backup', json=backup).status_code, 200)
        self.assertEqual(self.client.get('/api/backup').json, backup)
        before = Path(clock.SETTINGS_FILE).read_bytes()
        for value in ('', '24', 'invalid', None, 12, True, []):
            self.assertEqual(self.client.post('/api/control', json={'time_format': value}).status_code, 400)
            invalid = copy.deepcopy(backup)
            invalid['settings']['time_format'] = value
            self.assertEqual(self.client.post('/api/backup', json=invalid).status_code, 400)
            self.assertEqual(Path(clock.SETTINGS_FILE).read_bytes(), before)
        backup['settings'].pop('time_format')
        self.assertEqual(self.client.post('/api/backup', json=backup).status_code, 200)
        self.assertEqual(clock.load_display_settings()['time_format'], '24h')

    def test_night_and_backup_roundtrip_validation_rollback(self):
        night = dict(enabled=True, start='22:00', end='07:00', brightness=12, black=True)
        self.assertEqual(self.client.post('/api/control', json={'night': night}).status_code, 200)
        self.assertEqual(clock.load_display_settings()['night'], night)
        self.assertEqual(self.client.get('/api/control').json['settings']['night'], night)
        self.assertEqual(self.client.get('/admin').status_code, 200)
        for invalid in [dict(night, brightness=101), dict(night, start='7:00'), dict(night, end='22:00'),
                        dict(night, enabled=1), dict(night, black='true'), {}, dict(night, extra=True)]:
            self.assertEqual(self.client.post('/api/control', json={'night': invalid}).status_code, 400)
            self.assertEqual(clock.load_display_settings()['night'], night)
        self.client.post('/add', data={'note_text': 'saved'})
        response = self.client.get('/api/backup')
        original = response.json
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(set(original), {'version', 'settings', 'notes'})
        self.assertNotIn('ICAL_URL', response.text)
        self.assertEqual(self.client.post('/api/backup', json=original, headers={'Origin': 'https://foreign.example'}).status_code, 403)
        for change in [dict(original, version=True), dict(original, version=2), dict(original, notes=[{'text': 'missing id'}]),
                       dict(original, notes=original['notes'] * 2), dict(original, settings={'night': {}}),
                       dict(original, notes=[dict(original['notes'][0], enabled='yes')])]:
            self.assertEqual(self.client.post('/api/backup', json=change).status_code, 400)
            self.assertEqual(self.client.get('/api/backup').json, original)
        self.assertEqual(self.client.post('/api/backup', data='x' * (1024 * 1024 + 1), content_type='application/json').status_code, 413)
        incoming = copy.deepcopy(original)
        incoming['notes'][0]['text'] = 'new'
        incoming['settings']['brightness'] = 40
        with patch.object(clock, 'save_display_settings', side_effect=OSError('full')):
            with self.assertLogs(clock.app.logger, level='ERROR'):
                self.assertEqual(self.client.post('/api/backup', json=incoming).status_code, 500)
        self.assertEqual(self.client.get('/api/backup').json, original)
        self.assertEqual(json.loads((self.root / 'before-import.json').read_text()), original)
        self.assertEqual(self.client.post('/api/backup', json=incoming).status_code, 200)
        self.assertEqual(self.client.get('/api/backup').json, incoming)
        self.assertEqual(clock.load_display_settings(), incoming['settings'])
        # Older backups acquire the new disabled night mode without losing reminders.
        del incoming['settings']['night']
        self.assertEqual(self.client.post('/api/backup', json=incoming).status_code, 200)
        self.assertFalse(clock.load_display_settings().get('night', clock.DEFAULT_NIGHT)['enabled'])

    def test_dated_and_calendar_countdown_and_localized_admin(self):
        self.client.post('/add', data=dict(note_text='meeting', note_date='2026-09-17', note_time='10:00'))
        self.client.post('/add', data=dict(note_text='all day', note_date='2026-09-17'))
        status = self.status_at('2026-09-17T09:45')
        self.assertEqual(status['next_event']['text'], 'meeting')
        self.assertEqual(status['next_event']['starts_at'] - status['server_timestamp'], 900000)
        self.assertIsNone(self.status_at('2026-09-17T10:00')['next_event'])
        for language in clock.SUPPORTED_LANGUAGES:
            with patch.dict(clock.display_settings, language=language):
                response = self.client.get('/admin')
                self.assertEqual(response.status_code, 200)
                for key in ['night_title', 'repeat_hint', 'backup_title', 'edit_note', 'pause']:
                    self.assertIn(clock.UI_TRANSLATIONS[language][key], response.text)
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response.content_type)
        response.close()

    def test_calendar_timestamps_and_all_day_exclusion(self):
        payload = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART:20260917T020000Z\r\nSUMMARY:Call\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20260917\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        now = datetime(2026, 9, 17, 9, 45, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(clock, 'get_local_now', return_value=now), \
             patch.object(clock, 'ICAL_URL', 'https://calendar.example/test.ics'), \
             patch.object(clock, 'calendar_feed_cache', {}), \
             patch.object(clock.requests, 'get', return_value=SimpleNamespace(content=payload, raise_for_status=lambda: None)):
            data = self.client.get('/api/status').json
        self.assertEqual(data['next_event'], {'text': 'Call', 'starts_at': int(now.timestamp() * 1000) + 900000})
        self.assertEqual(data['events'], [{'text': 'Call', 'time': '10:00'}, {'text': 'Holiday', 'time': ''}])

    def test_docker_migration_is_once_and_preserves_legacy_file(self):
        legacy = self.root / 'legacy.json'
        legacy.write_text('[{"id": 1, "text": "keep"}]')
        clock.migrate_notes(str(legacy))
        self.assertEqual(clock.load_notes()[0]['text'], 'keep')
        legacy.write_text('[{"id": 2, "text": "old file changed"}]')
        clock.migrate_notes(str(legacy))
        self.assertEqual(clock.load_notes()[0]['text'], 'keep')
        Path(clock.NOTES_FILE).unlink()
        legacy.write_text('corrupt')
        with self.assertRaises(ValueError):
            clock.migrate_notes(str(legacy))
        self.assertFalse(Path(clock.NOTES_FILE).exists())
        legacy.write_text('')
        clock.migrate_notes(str(legacy))
        self.assertEqual(clock.load_notes(), [])
        Path(clock.NOTES_FILE).write_text('')
        self.assertEqual(clock.load_notes(), [])


if __name__ == '__main__':
    unittest.main()
