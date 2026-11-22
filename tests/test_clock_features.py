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

    def test_clock_appearance_and_message_settings(self):
        defaults = dict(show_seconds=False, show_date=True, date_format='m/d', show_weekday=True,
                        message_duration=5, message_transition='fade')
        Path(clock.SETTINGS_FILE).write_text('{}')
        for key, value in defaults.items():
            self.assertEqual(clock.load_display_settings()[key], value)
        changed = dict(show_seconds=True, show_date=False, date_format='yyyy-mm-dd', show_weekday=False,
                       message_duration=12, message_transition='up')
        self.assertEqual(self.client.post('/api/control', json=changed).status_code, 200)
        for key, value in changed.items():
            self.assertEqual(clock.load_display_settings()[key], value)
            self.assertEqual(self.status_at('2026-10-01T10:30')['settings'][key], value)
        backup = self.client.get('/api/backup').json
        self.assertEqual(self.client.post('/api/backup', json=backup).status_code, 200)
        self.assertEqual(self.client.get('/api/backup').json, backup)
        before = Path(clock.SETTINGS_FILE).read_bytes()
        for invalid in [dict(show_seconds=1), dict(show_date='false'), dict(show_weekday=None),
                        dict(date_format='invalid'), dict(message_duration=0), dict(message_duration=301),
                        dict(message_duration=1.5), dict(message_duration=True), dict(message_duration='5'),
                        dict(message_transition='invalid')]:
            self.assertEqual(self.client.post('/api/control', json=invalid).status_code, 400)
            self.assertEqual(Path(clock.SETTINGS_FILE).read_bytes(), before)
        for language in clock.SUPPORTED_LANGUAGES:
            page = self.client.get('/admin?lang=' + language).text
            common = page.split('id="display-panel-common"')[1].split('id="display-panel-advanced"')[0]
            for key in defaults:
                self.assertIn('data-display-setting="' + key + '"', common)

    def test_clock_style_api_roundtrip_default_backup_and_invalid_values(self):
        for retired in ('glass', 'orbit', 'paper'):
            Path(clock.SETTINGS_FILE).write_text(json.dumps({'brightness': 41, 'clock_style': retired}))
            before = Path(clock.SETTINGS_FILE).read_bytes()
            loaded = clock.load_display_settings()
            self.assertEqual(loaded['clock_style'], 'classic')
            self.assertEqual(loaded['brightness'], 41)
            self.assertEqual(Path(clock.SETTINGS_FILE).read_bytes(), before,
                             'reading a retired style does not rewrite settings')
        owner_path = Path(clock.SETTINGS_FILE).parent / 'owners' / 'owner2' / 'settings.json'
        owner_path.parent.mkdir(parents=True)
        owner_path.write_text(json.dumps({'language': 'ja', 'clock_style': 'orbit'}))
        owner_before = owner_path.read_bytes()
        owner_loaded = clock.load_display_settings(owner_path)
        self.assertEqual(owner_loaded['clock_style'], 'classic')
        self.assertEqual(owner_loaded['language'], 'ja')
        self.assertEqual(owner_path.read_bytes(), owner_before)
        Path(clock.SETTINGS_FILE).write_text('{}')
        self.assertEqual(clock.load_display_settings()['clock_style'], 'classic')
        self.assertEqual(clock.load_display_settings()['clock_theme'], 'auto')
        current_style = 'classic'
        for style in ('classic', 'flip', 'segment'):
            previous_revision = self.client.get('/api/control').json['revision']
            response = self.client.post('/api/control', json={'clock_style': style})
            self.assertEqual(response.status_code, 200, style)
            self.assertEqual(clock.load_display_settings()['clock_style'], style)
            self.assertEqual(self.status_at('2026-10-01T10:30')['settings']['clock_style'], style)
            self.assertEqual(self.client.get('/api/control').json['settings']['clock_style'], style)
            if style != current_style:
                self.assertNotEqual(response.json['revision'], previous_revision)
            current_style = style
        current_theme = 'auto'
        for theme in ('auto', 'dark', 'light'):
            previous_revision = self.client.get('/api/control').json['revision']
            response = self.client.post('/api/control', json={'clock_theme': theme})
            self.assertEqual(response.status_code, 200, theme)
            self.assertEqual(clock.load_display_settings()['clock_theme'], theme)
            self.assertEqual(self.status_at('2026-10-01T10:30')['settings']['clock_theme'], theme)
            self.assertEqual(self.client.get('/api/control').json['settings']['clock_theme'], theme)
            if theme != current_theme:
                self.assertNotEqual(response.json['revision'], previous_revision)
            current_theme = theme
        page = self.client.get('/admin').text
        self.assertRegex(page, r'id="clock_theme_light"[^>]*checked')
        self.assertNotRegex(page, r'id="clock_theme_dark"[^>]*checked')
        self.assertIn('data-theme-mode="light"', page)
        self.assertIn('var clockThemeSaved = "light";', page)
        backup = self.client.get('/api/backup').json
        backup['settings']['clock_style'] = 'segment'
        backup['settings']['clock_theme'] = 'dark'
        self.assertEqual(self.client.post('/api/backup', json=backup).status_code, 200)
        self.assertEqual(clock.load_display_settings()['clock_style'], 'segment')
        self.assertEqual(clock.load_display_settings()['clock_theme'], 'dark')
        backup['settings'].pop('clock_style')
        backup['settings'].pop('clock_theme')
        self.assertEqual(self.client.post('/api/backup', json=backup).status_code, 200)
        self.assertEqual(clock.load_display_settings()['clock_style'], 'classic')
        self.assertEqual(clock.load_display_settings()['clock_theme'], 'auto')
        for retired in ('glass', 'orbit', 'paper'):
            legacy = self.client.get('/api/backup').json
            legacy['settings'].update(clock_style=retired, brightness=37)
            self.assertEqual(self.client.post('/api/backup', json=legacy).status_code, 200)
            self.assertEqual(clock.load_display_settings()['clock_style'], 'classic')
            self.assertEqual(clock.load_display_settings()['brightness'], 37)
        before = Path(clock.SETTINGS_FILE).read_bytes()
        for invalid in ({'clock_style': 'neon'}, {'clock_style': 'glass'}, {'clock_style': 'orbit'},
                        {'clock_style': 'paper'},
                        {'clock_style': None}, {'clock_style': 3},
                        {'clock_style': ['flip']}, {'clock_style': {'id': 'flip'}}, {'clock_style': True},
                        {'clock_theme': 'neon'}, {'clock_theme': None}, {'clock_theme': 3},
                        {'clock_theme': ['dark']}, {'clock_theme': {'id': 'dark'}}, {'clock_theme': True}):
            self.assertEqual(self.client.post('/api/control', json=invalid).status_code, 400, invalid)
            self.assertEqual(Path(clock.SETTINGS_FILE).read_bytes(), before)
        for invalid in ({'clock_style': 'neon'}, {'clock_style': None}, {'clock_style': 3},
                        {'clock_style': ['flip']}, {'clock_style': {'id': 'flip'}}, {'clock_style': True},
                        {'clock_theme': 'neon'}, {'clock_theme': None}, {'clock_theme': 3},
                        {'clock_theme': ['dark']}, {'clock_theme': {'id': 'dark'}}, {'clock_theme': True}):
            invalid_backup = self.client.get('/api/backup').json
            invalid_backup['settings'].update(invalid)
            self.assertEqual(self.client.post('/api/backup', json=invalid_backup).status_code, 400, invalid)
            self.assertEqual(Path(clock.SETTINGS_FILE).read_bytes(), before)
        for language in clock.SUPPORTED_LANGUAGES:
            page = self.client.get('/admin?lang=' + language).text
            self.assertIn('data-management-tab="styles"', page)
            self.assertIn('data-i18n="clock_style_flip"', page)
            self.assertIn('id="clock-style-preview"', page)
            self.assertIn('data-i18n="clock_style_upgrade_reload_hint"', page)
            self.assertNotIn('id="clock_theme_auto"', page)
            self.assertNotIn('value="auto"', page)
            self.assertIn('id="clock_theme_dark"', page)
            self.assertIn('id="clock_theme_light"', page)
            self.assertRegex(page, r'id="clock_theme_dark"[^>]*checked')
            self.assertNotRegex(page, r'id="clock_theme_light"[^>]*checked')
            self.assertIn('data-theme-mode="dark"', page)
            self.assertIn('var clockThemeSaved = "dark";', page)
            for style in ('classic', 'flip', 'segment'):
                self.assertIn('id="clock_style_' + style + '"', page)
            self.assertNotIn('id="clock_style_glass"', page)
            self.assertNotIn('id="clock_style_orbit"', page)
            self.assertNotIn('id="clock_style_paper"', page)
        self.assertIn(clock.UI_TRANSLATIONS['zh-TW']['clock_style_upgrade_reload_hint'],
                      self.client.get('/admin').text)

    def test_display_page_versioned_assets_cache_headers_and_shared_revision(self):
        rev = clock.display_asset_revision()
        self.assertGreaterEqual(len(rev), 8)
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home.headers['Cache-Control'], 'no-cache')
        self.assertEqual(home.headers['X-WebClock-Display-Revision'], rev)
        home_html = home.get_data(as_text=True)
        self.assertIn(f'data-display-revision="{rev}"', home_html)
        for asset in ('clock.css', 'clock.js', 'clock-styles.css', 'clock-styles.js', 'device-session.js'):
            self.assertIn(f'/static/{asset}?v={rev}', home_html)
        preview = self.client.get('/admin/preview?style=segment&theme=light')
        self.assertEqual(preview.status_code, 200)
        preview_html = preview.get_data(as_text=True)
        for asset in ('clock.css', 'clock-styles.css', 'clock-styles.js', 'clock.js'):
            self.assertIn(f'/static/{asset}?v={rev}', preview_html)
        status = self.client.get('/api/status')
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.headers['Cache-Control'], 'no-store')
        self.assertEqual(status.headers['X-WebClock-Display-Revision'], rev)
        with patch.object(clock, 'display_asset_revision', return_value='injected-rev'):
            self.assertEqual(self.client.get('/').headers['X-WebClock-Display-Revision'], 'injected-rev')
            self.assertEqual(self.client.get('/api/status').headers['X-WebClock-Display-Revision'], 'injected-rev')

    def test_clock_style_preview_is_fixed_pure_and_does_not_write_settings(self):
        before = self.client.get('/api/control').json
        page = self.client.get('/admin/preview?style=segment&sample=1&show_seconds=1&lang=en&theme=dark')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        for required in ('static/clock-styles.css', 'static/clock-styles.js',
                         '10:28', '2026', 'Team meeting', 'var theme = "dark"'):
            self.assertIn(required, html)
        for forbidden in ('device-session.js', 'device-enrollment.js', 'alarms.js',
                          'alarm-audio.js', 'offline.js', 'setInterval(', 'fetch('):
            self.assertNotIn(forbidden, html)
        self.assertEqual(self.client.get('/api/control').json, before)
        legacy_auto = self.client.get('/admin/preview?style=flip&theme=auto')
        self.assertEqual(legacy_auto.status_code, 200)
        self.assertIn('var theme = "dark"', legacy_auto.get_data(as_text=True))
        invalid = self.client.get('/admin/preview?style=neon&date_format=bad&time_format=99&lang=zz')
        self.assertEqual(invalid.status_code, 200)
        self.assertIn('style = "classic"', invalid.get_data(as_text=True))

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
