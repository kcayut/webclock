"""Management/device contracts, legacy storage and failure regression checks."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.storage import revision


class ServerApiTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for key, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                           ('NOTES_FILE', str(self.root / 'manual_notes.json')),
                           ('ICAL_URL', '')]:
            mock = patch.object(clock, key, value)
            mock.start()
            self.addCleanup(mock.stop)
        token = patch.dict(os.environ, DEVICE_API_TOKEN='')
        token.start()
        self.addCleanup(token.stop)
        self.client = clock.app.test_client()
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = self.client.get('/api/csrf').json['csrf_token']
        self.schedule = dict(id='wake', name='起床', type='alarm', time='07:30', rule={},
                             enabled=True, skipped_occurrences=[], browser_sound='bell', browser_volume=100, skip_holidays=False)

    def config(self):
        return self.client.get('/api/v1/device/config').json

    def test_persist_skip_revisions_and_conditional_sync(self):
        before = self.config()
        self.assertEqual(before['schema_version'], 2)
        self.assertEqual(set(before), {'schema_version', 'timezone', 'config_revision',
                                       'schedule_revision', 'holiday_revision'})
        old_etag = self.client.get('/api/v1/device/config').headers['ETag']
        self.assertEqual(self.client.post('/api/v1/schedules', json=self.schedule).status_code, 201)
        after = self.config()
        self.assertNotEqual(before['schedule_revision'], after['schedule_revision'])
        for field in ('config_revision', 'holiday_revision'):
            self.assertEqual(before[field], after[field])
        self.assertEqual(self.client.get('/api/v1/device/config', headers={'If-None-Match': old_etag}).status_code, 200)
        for route in ('config', 'schedules', 'holidays'):
            response = self.client.get('/api/v1/device/' + route)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-cache')
            cached = self.client.get('/api/v1/device/' + route, headers={
                'If-None-Match': response.headers['ETag']})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.headers['Cache-Control'], 'private, no-cache')
        response = self.client.get('/api/v1/device/schedules')
        self.assertEqual(response.json['schedules'], [self.schedule])
        self.assertEqual(response.json['revision'], revision([self.schedule]))
        self.assertEqual(self.client.get('/api/v1/device/schedules?revision=' + after['schedule_revision']).status_code, 304)
        now = datetime.fromisoformat('2026-09-23T06:00:00+08:00')
        with patch('webclock.api.management.taipei_now', return_value=now):
            skipped = self.client.post('/api/v1/schedules/wake/skip-next').json
            self.assertEqual(skipped['skipped']['datetime'], '2026-09-23T07:30:00+08:00')
            self.assertEqual(skipped['next_event']['datetime'], '2026-09-24T07:30:00+08:00')
            rows = self.client.get('/api/v1/schedules').json['schedules']
            self.assertTrue(rows[0]['enabled'])
            self.assertEqual(rows[0]['next_occurrence'], skipped['next_event']['datetime'])
        with patch.object(clock, 'get_local_now', return_value=now):
            self.assertEqual(self.client.get('/api/status').json['next_event']['text'], '起床')
        self.assertIn('2026-09-23T07:30:00+08:00', (self.root / 'schedules.json').read_text())
        self.assertEqual(self.client.delete('/api/v1/schedules/wake').status_code, 200)
        self.assertEqual(self.client.delete('/api/v1/schedules/wake').status_code, 404)

    def test_validation_and_failed_writes_leave_data_unchanged(self):
        self.client.post('/api/v1/schedules', json=self.schedule)
        original = (self.root / 'schedules.json').read_bytes()
        for changes in ({'volume': 70}, {'sound': 'default.wav'}, {'repeat': 'once'}, {'snooze_minutes': 5},
                        {'rule': {'weekdays': [0]}}, {'time': '7:30'}, {'type': 'unsupported'}, {'extra': 1},
                        {'browser_sound': 'unknown'}, {'browser_volume': -1}, {'browser_volume': 101},
                        {'browser_volume': True}, {'browser_volume': '50'}, {'browser_volume': 2.5}, {'skip_holidays': 'true'},
                        {'skip_holidays': True, 'rule': {'holiday_only': True}}):
            response = self.client.put('/api/v1/schedules/wake', json=changes)
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual((self.root / 'schedules.json').read_bytes(), original)
        with patch('webclock.services.schedule_service.save_json', side_effect=OSError('full')):
            with self.assertLogs(clock.app.logger, level='ERROR'):
                self.assertEqual(self.client.put('/api/v1/schedules/wake', json={'name': 'New'}).status_code, 500)
        self.assertEqual((self.root / 'schedules.json').read_bytes(), original)
        self.assertEqual(self.client.post('/api/v1/schedules', json=self.schedule).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/schedules', json=[]).status_code, 400)

    def test_preview_rules_validation_and_no_persistence(self):
        route = '/api/v1/schedules/preview'
        before = self.config()['schedule_revision']
        now = datetime.fromisoformat('2026-09-23T06:00:00+08:00')
        cases = [({}, '2026-09-23T07:30:00+08:00'),
                 ({'rule': {'dates': ['2026-09-24']}}, '2026-09-24T07:30:00+08:00'),
                 ({'rule': {'weekdays': [5]}}, '2026-09-25T07:30:00+08:00'),
                 ({'rule': {'dates': ['2026-09-22']}}, None),
                 ({'enabled': False}, None)]
        with patch('webclock.api.management.taipei_now', return_value=now):
            for changes, expected in cases:
                with self.subTest(changes=changes):
                    response = self.client.post(route, json=dict(self.schedule, **changes))
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json, dict(next_occurrence=expected,
                                                        server_time=now.isoformat(), timezone='Asia/Taipei'))
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
            for invalid in ([], {'time': '07:30'}, dict(self.schedule, rule={'dates': ['2026-02-30']}),
                            dict(self.schedule, calendar_link={'mode': 'day', 'source_ids': ['missing']})):
                self.assertEqual(self.client.post(route, json=invalid).status_code, 400)
        self.assertEqual(self.client.post(route, json=self.schedule,
                                         headers={'Origin': 'https://evil.invalid'}).status_code, 403)
        self.assertFalse((self.root / 'schedules.json').exists())
        self.assertEqual(self.config()['schedule_revision'], before)

    def test_preview_edit_preserves_skips_and_matches_update(self):
        self.client.post('/api/v1/schedules', json=dict(self.schedule,
            rule={'weekdays': [3]}, skipped_occurrences=['2026-09-23T07:30:00+08:00']))
        path = self.root / 'schedules.json'
        original, before = path.read_bytes(), self.config()['schedule_revision']
        now = datetime.fromisoformat('2026-09-23T06:00:00+08:00')
        with patch('webclock.api.management.taipei_now', return_value=now):
            preview = self.client.post('/api/v1/schedules/preview', json={'id': 'wake', 'name': '修改名稱'})
            self.assertEqual(preview.status_code, 200, preview.json)
            self.assertEqual(preview.json['next_occurrence'], '2026-09-30T07:30:00+08:00')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(self.config()['schedule_revision'], before)
            self.assertEqual(self.client.put('/api/v1/schedules/wake', json={'name': '修改名稱'}).status_code, 200)
            self.assertEqual(self.client.get('/api/v1/schedules').json['schedules'][0]['next_occurrence'],
                             preview.json['next_occurrence'])

    def test_enable_and_skip_draft_atomically_share_browser_and_device_schedule(self):
        self.client.post('/api/v1/schedules', json=dict(self.schedule, enabled=False, rule={'weekdays': [3]}))
        path = self.root / 'schedules.json'
        original, before = path.read_bytes(), self.config()['schedule_revision']
        now = datetime.fromisoformat('2026-09-23T06:00:00+08:00')
        draft = dict(id='wake', name='週五起床', time='08:00', rule={'weekdays': [5]}, enabled=True)
        skipped, resumed = '2026-09-25T08:00:00+08:00', '2026-10-02T08:00:00+08:00'
        with patch('webclock.api.management.taipei_now', return_value=now):
            self.assertIsNone(self.client.get('/api/v1/schedules').json['schedules'][0]['next_occurrence'])
            response = self.client.post('/api/v1/schedules/preview', json=draft)
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json['next_occurrence'], skipped)
            self.assertEqual(path.read_bytes(), original)
            response = self.client.post('/api/v1/schedules/preview', json=dict(draft, skip_next=True))
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json, dict(skipped_occurrence=skipped, next_occurrence=resumed,
                                                server_time=now.isoformat(), timezone='Asia/Taipei'))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(self.config()['schedule_revision'], before)
            # A stale preview must not save any of the draft's other changes.
            response = self.client.put('/api/v1/schedules/wake', json=dict(draft, skip_next=now.isoformat()))
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual(response.json['error'], 'Occurrence changed; preview again')
            self.assertEqual(path.read_bytes(), original)
            response = self.client.put('/api/v1/schedules/wake', json=dict(draft, enabled=False, skip_next=skipped))
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual(response.json['error'], 'Occurrence changed; preview again')
            self.assertEqual(path.read_bytes(), original)
            response = self.client.put('/api/v1/schedules/wake', json=dict(draft, skip_next=skipped))
            self.assertEqual(response.status_code, 200, response.json)
            saved = response.json
            self.assertTrue(saved['enabled'])
            self.assertEqual(saved['time'], '08:00')
            self.assertEqual(saved['skipped_occurrences'], [skipped])
            self.assertNotIn('skip_next', saved)
            self.assertEqual(self.client.get('/api/v1/schedules').json['schedules'][0]['next_occurrence'], resumed)
            alarms = self.client.get('/api/v1/browser-alarms').json
            self.assertEqual(alarms['enabled_ids'], ['wake'])
            self.assertEqual(alarms['alarms'][0]['occurrence_id'], 'wake@' + resumed)
            self.assertEqual(self.client.get('/api/v1/device/schedules').json['schedules'], [saved])
            self.assertNotEqual(self.config()['schedule_revision'], before)
            original = path.read_bytes()
            response = self.client.post('/api/v1/schedules/wake/skip-next', json={'expected_occurrence': skipped})
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual(path.read_bytes(), original)
            response = self.client.post('/api/v1/schedules/wake/skip-next', json={'expected_occurrence': resumed})
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual(response.json['error'], 'Occurrence already skipped; wait for resume')
            self.assertEqual(path.read_bytes(), original)

    def test_pending_skip_cannot_accumulate_until_original_time_passes(self):
        self.client.post('/api/v1/schedules', json=self.schedule)
        path = self.root / 'schedules.json'
        now = datetime.fromisoformat('2026-09-23T06:00:00+08:00')
        skipped = '2026-09-23T07:30:00+08:00'
        resumed = '2026-09-24T07:30:00+08:00'
        with patch('webclock.api.management.taipei_now', return_value=now) as current:
            response = self.client.post('/api/v1/schedules/wake/skip-next')
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json['skipped']['datetime'], skipped)
            saved, before = path.read_bytes(), self.config()['schedule_revision']
            for stamp in (now, datetime.fromisoformat(skipped)):
                current.return_value = stamp
                for method, url, payload in [
                    ('post', '/api/v1/schedules/preview', {'id': 'wake', 'skip_next': True}),
                    ('put', '/api/v1/schedules/wake', {'name': 'Changed', 'skip_next': resumed}),
                    ('post', '/api/v1/schedules/wake/skip-next', {}),
                    ('post', '/api/v1/schedules/wake/skip-next', {'expected_occurrence': skipped}),
                ]:
                    with self.subTest(stamp=stamp, method=method, payload=payload):
                        response = getattr(self.client, method)(url, json=payload)
                        self.assertEqual(response.status_code, 400, response.json)
                        self.assertEqual(response.json['error'], 'Occurrence already skipped; wait for resume')
                        self.assertEqual(path.read_bytes(), saved)
                        self.assertEqual(self.config()['schedule_revision'], before)
            # The old skip remains through its minute so browser polling cannot ring it.
            current.return_value = datetime.fromisoformat(skipped) + timedelta(seconds=1)
            alarms = self.client.get('/api/v1/browser-alarms').json
            self.assertEqual(alarms['alarms'][0]['occurrence_id'], 'wake@' + resumed)
            response = self.client.post('/api/v1/schedules/wake/skip-next')
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json['skipped']['datetime'], resumed)
            self.assertEqual(json.loads(path.read_text())[0]['skipped_occurrences'], [skipped, resumed])

    def test_skip_preview_boundaries_and_stale_requests_do_not_change_storage(self):
        self.client.post('/api/v1/schedules', json=self.schedule)
        path = self.root / 'schedules.json'
        original = path.read_bytes()
        now = datetime.fromisoformat('2026-09-23T06:00:00+08:00')
        with patch('webclock.api.management.taipei_now', return_value=now) as current:
            for changes, skipped, resumed in [
                ({}, '2026-09-23T07:30:00+08:00', '2026-09-24T07:30:00+08:00'),
                ({'rule': {'dates': ['2026-09-24', '2026-10-01']}},
                 '2026-09-24T07:30:00+08:00', '2026-10-01T07:30:00+08:00'),
                ({'rule': {'dates': ['2026-09-24']}}, '2026-09-24T07:30:00+08:00', None),
                ({'rule': {'dates': ['2026-09-22']}}, None, None),
                ({'enabled': False}, None, None),
            ]:
                with self.subTest(changes=changes):
                    response = self.client.post('/api/v1/schedules/preview',
                                                json=dict(id='wake', skip_next=True, **changes))
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json['skipped_occurrence'], skipped)
                    self.assertEqual(response.json['next_occurrence'], resumed)
                    self.assertEqual(path.read_bytes(), original)
            for invalid in (None, 'true', 1, []):
                self.assertEqual(self.client.post('/api/v1/schedules/preview',
                                                 json={'id': 'wake', 'skip_next': invalid}).status_code, 400)
            for invalid in (None, True, 1, [], 'invalid'):
                self.assertEqual(self.client.put('/api/v1/schedules/wake',
                                                json={'skip_next': invalid}).status_code, 400)
                self.assertEqual(self.client.post('/api/v1/schedules/wake/skip-next',
                                                 json={'expected_occurrence': invalid}).status_code, 400)
                self.assertEqual(path.read_bytes(), original)
            # Crossing the displayed occurrence cannot accidentally skip tomorrow.
            current.return_value = now.replace(hour=7, minute=31)
            response = self.client.post('/api/v1/schedules/wake/skip-next',
                                        json={'expected_occurrence': '2026-09-23T07:30:00+08:00'})
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual(path.read_bytes(), original)
            current.return_value = now.replace(hour=7, minute=30, second=8)
            self.client.put('/api/v1/schedules/wake', json={'skipped_occurrences': ['2026-09-23T07:30:00+08:00']})
            response = self.client.post('/api/v1/schedules/wake/skip-next',
                                        json={'expected_occurrence': '2026-09-24T07:30:00+08:00'})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(self.client.get('/api/v1/browser-alarms').json['alarms'][0]['occurrence_id'],
                             'wake@2026-09-25T07:30:00+08:00')

    def test_private_routes_and_device_token(self):
        for route in ('/api/v1/schedules', '/api/v1/browser-alarms', '/api/v1/devices', '/api/v1/device/config', '/schedules'):
            self.assertEqual(self.client.get(route, headers={'Origin': 'https://evil.invalid'}).status_code, 403)
            self.assertNotIn('Access-Control-Allow-Origin', self.client.get(route).headers)
        with patch.dict(os.environ, DEVICE_API_TOKEN='test-only'):
            for route, method, data in [('config', 'GET', None), ('schedules', 'GET', None),
                                        ('holidays', 'GET', None), ('register', 'POST', {'id': 'one', 'name': 'One'}),
                                        ('status', 'POST', {'id': 'one'})]:
                url = '/api/v1/device/' + route
                self.assertEqual(self.client.open(url, method=method, json=data).status_code, 401)
                response = self.client.open(url, method=method, json=data, headers={'Authorization': 'Bearer test-only'})
                self.assertIn(response.status_code, (200, 201))
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.client.post('/api/v1/schedules', data='x' * (1024 * 1024 + 1),
                                         content_type='application/json').status_code, 413)

    def test_client_registration_shared_sync_heartbeat_and_ack(self):
        self.client.post('/api/v1/schedules', json=self.schedule)
        for device_id in ('bedroom', 'office'):
            self.assertEqual(self.client.post('/api/v1/device/register', json={'id': device_id, 'name': device_id}).status_code, 201)
        response = self.client.post('/api/v1/devices/bedroom/commands', json={'action': 'sync'})
        self.assertEqual(response.status_code, 202)
        command = response.json['command']
        self.assertEqual(self.client.post('/api/v1/devices/bedroom/commands', json={'action': 'sync'}).json['command'], command)
        pending = next(device for device in self.client.get('/api/v1/devices').json['devices']
                       if device['id'] == 'bedroom')['sync_status']
        self.assertEqual(pending['state'], 'pending')
        self.assertEqual(pending['command_id'], command['id'])
        self.assertEqual(self.client.post('/api/v1/device/status', json={'id': 'office'}).json['commands'], [])
        report = self.client.post('/api/v1/device/status', json={'id': 'bedroom'}).json
        self.assertEqual(report['commands'], [command])
        self.assertTrue(report['device']['online'])
        config = self.config()
        revisions = {key: value for key, value in config.items() if key.endswith('_revision')}
        report = self.client.post('/api/v1/device/status', json={
            'id': 'bedroom', **revisions, 'acknowledged_commands': [command['id']]}).json
        self.assertEqual(report['commands'], [])
        self.assertEqual(report['device']['sync_status']['state'], 'confirmed')
        self.assertEqual(report['device']['sync_status']['command_id'], command['id'])
        self.assertEqual(report['device']['sync_status']['requested_at'], command['created_at'])
        self.assertTrue(report['device']['sync_status']['acknowledged_at'])
        self.assertEqual(report['device']['schedule_revision'], config['schedule_revision'])
        devices = self.client.get('/api/v1/devices').json['devices']
        self.assertEqual(len(devices), 2)
        self.assertEqual(self.client.post('/api/v1/device/status', json={'id': 'unregistered'}).status_code, 404)
        for action in ('test_sound', 'restart', 'unknown'):
            self.assertEqual(self.client.post('/api/v1/devices/bedroom/commands', json={'action': action}).status_code, 400)

    def test_device_admin_name_and_capability_contract(self):
        registered = self.client.post('/api/v1/device/register', json={
            'id': 'bedroom', 'name': 'Bedroom', 'device_type': 'esp32-s3',
            'capabilities': {'display': True, 'audio': True}}).json['device']
        self.assertEqual(registered['reported_name'], 'Bedroom')
        self.assertIsNone(registered['admin_name'])
        self.assertEqual(registered['capabilities'], {'display': True, 'audio': True})
        renamed = self.client.patch('/api/v1/devices/bedroom', json={'name': 'Hall clock'}).json['device']
        self.assertEqual(renamed['name'], 'Hall clock')
        self.assertEqual(renamed['reported_name'], 'Bedroom')
        reregistered = self.client.post('/api/v1/device/register', json={
            'id': 'bedroom', 'name': 'Firmware name'}).json['device']
        self.assertEqual(reregistered['name'], 'Hall clock')
        self.assertEqual(reregistered['reported_name'], 'Firmware name')
        reported = self.client.post('/api/v1/device/status', json={
            'id': 'bedroom', 'capabilities': {'background': False}}).json['device']
        self.assertEqual(reported['name'], 'Hall clock')
        self.assertEqual(reported['capabilities'], {'background': False})
        self.assertTrue(reported['capabilities_reported_at'])
        listed = self.client.get('/api/v1/devices').json['devices'][0]
        self.assertEqual(listed, reported)
        for payload in ({'name': ''}, {'name': 'x' * 101}, {'name': 'Name', 'extra': True}):
            self.assertEqual(self.client.patch('/api/v1/devices/bedroom', json=payload).status_code, 400)
        self.assertEqual(self.client.patch('/api/v1/devices/missing', json={'name': 'Name'}).status_code, 404)

    def test_legacy_records_survive_edits_without_exposing_device_settings(self):
        legacy = dict({key: value for key, value in self.schedule.items()
                       if key not in ('browser_sound', 'browser_volume', 'skip_holidays')},
                      sound='missing.wav', volume=25, repeat='once', snooze_minutes=10)
        path = self.root / 'schedules.json'
        path.write_text(json.dumps([legacy]))
        before = path.read_bytes()
        response = self.client.get('/api/v1/device/schedules').json
        self.assertEqual(response['schedules'], [self.schedule])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.client.get('/api/v1/browser-alarms').json['alarms'][0]['sound'], 'bell')
        self.assertEqual(self.client.get('/api/v1/browser-alarms').json['alarms'][0]['volume'], 100)
        self.assertEqual(self.client.put('/api/v1/schedules/wake', json={
            'name': 'Updated', 'browser_sound': 'beep', 'skip_holidays': True}).status_code, 200)
        stored = json.loads(path.read_text())[0]
        self.assertEqual(stored, dict(legacy, name='Updated', browser_sound='beep', browser_volume=100, skip_holidays=True))
        self.assertEqual(self.client.post('/api/v1/schedules', json=dict(self.schedule, id='second')).status_code, 201)
        self.assertEqual(json.loads(path.read_text())[0], stored)
        self.assertFalse((self.root / 'sounds').exists())

    def test_browser_alarms_keep_current_minute_and_local_dismissal(self):
        for row in (self.schedule, dict(self.schedule, id='second', browser_sound='melody', browser_volume=25),
                    dict(self.schedule, id='disabled', enabled=False),
                    dict(self.schedule, id='text', type='reminder')):
            self.assertEqual(self.client.post('/api/v1/schedules', json=row).status_code, 201)
        now = datetime.fromisoformat('2026-09-23T07:30:08+08:00')
        with patch('webclock.api.management.taipei_now', return_value=now) as current:
            response = self.client.get('/api/v1/browser-alarms')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            data = response.json
            self.assertEqual(data['server_timestamp'], int(now.timestamp() * 1000))
            self.assertEqual(data['enabled_count'], 2)
            self.assertEqual(data['enabled_ids'], ['second', 'wake'])
            self.assertTrue(data['holiday_known'])
            self.assertEqual(data['holiday_coverage'], clock.holiday_service.coverage)
            self.assertEqual([row['id'] for row in data['alarms']], ['second', 'wake'])
            for row in data['alarms']:
                self.assertEqual(set(row), {'occurrence_id', 'id', 'name', 'starts_at', 'sound', 'volume'})
                self.assertEqual(row['starts_at'], int(now.replace(second=0).timestamp() * 1000))
                self.assertEqual(row['occurrence_id'], row['id'] + '@2026-09-23T07:30:00+08:00')
            self.assertEqual([row['sound'] for row in data['alarms']], ['melody', 'bell'])
            self.assertEqual([row['volume'] for row in data['alarms']], [25, 100])
            self.assertEqual(self.client.get('/api/v1/browser-alarms').json, data)
            current.return_value = now.replace(second=59, microsecond=999999)
            self.assertEqual(self.client.get('/api/v1/browser-alarms').json['alarms'], data['alarms'])
            current.return_value = now.replace(second=0) + timedelta(minutes=1)
            self.assertTrue(all(row['starts_at'] > data['server_timestamp']
                                for row in self.client.get('/api/v1/browser-alarms').json['alarms']))
        self.assertEqual(self.client.post('/api/v1/browser-alarms', json={'dismiss': 'wake'}).status_code, 405)
        self.assertEqual(self.client.get('/api/v1/device/schedules').json['schedules'][0]['skipped_occurrences'], [])
        self.assertEqual(self.client.put('/api/v1/schedules/wake', json={'enabled': False}).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/browser-alarms').json['enabled_ids'], ['second'])
        self.assertEqual(self.client.delete('/api/v1/schedules/second').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/browser-alarms').json['enabled_ids'], [])

    def test_browser_alarms_exclude_unknown_holidays_without_losing_enabled_count(self):
        self.client.post('/api/v1/schedules', json=dict(self.schedule, skip_holidays=True, browser_sound='silent'))
        now = datetime.fromisoformat('2026-09-25T07:30:08+08:00')
        with patch('webclock.api.management.taipei_now', return_value=now) as current:
            data = self.client.get('/api/v1/browser-alarms').json
            self.assertEqual(data['alarms'][0]['starts_at'], int(datetime.fromisoformat('2026-09-29T07:30:00+08:00').timestamp() * 1000))
            self.assertEqual(data['alarms'][0]['sound'], 'silent')
            current.return_value = datetime.fromisoformat('2028-01-03T07:30:08+08:00')
            data = self.client.get('/api/v1/browser-alarms').json
            self.assertEqual(data['enabled_count'], 1)
            self.assertEqual(data['enabled_ids'], ['wake'])
            self.assertEqual(data['alarms'], [])
            self.assertFalse(data['holiday_known'])

    def test_legacy_entrypoint_languages_and_management_only_surface(self):
        from webclock import app as implementation
        self.assertIs(clock, implementation)
        for language in clock.SUPPORTED_LANGUAGES:
            with patch.dict(clock.display_settings, language=language):
                for route in ('/', '/admin', '/schedules'):
                    response = self.client.get(route)
                    self.assertEqual(response.status_code, 200, route)
                    self.assertIn('lang="' + language + '"', response.text)
                self.assertIn('id="schedule-volume"', response.text)
                for removed in ('enable-audio', 'sound-form', 'schedule-snooze', 'ringing'):
                    self.assertNotIn('id="' + removed + '"', response.text)
        for route in ('/api/v1/sounds', '/api/v1/sounds/default.wav', '/api/v1/device/sounds'):
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/device/status').status_code, 405)
        self.assertEqual(self.client.post('/api/v1/device/schedules', json=self.schedule).status_code, 405)
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_invalid_stored_schedule_is_not_reassigned_or_overwritten(self):
        path = self.root / 'schedules.json'
        for rows in ([{'name': 'missing ID', 'time': '07:30'}], [self.schedule, self.schedule],
                     [dict(self.schedule, unexpected=True)]):
            original = json.dumps(rows)
            path.write_text(original)
            self.assertEqual(self.client.get('/api/v1/device/config').status_code, 400)
            self.assertEqual(self.client.post('/api/v1/schedules', json=self.schedule).status_code, 400)
            self.assertEqual(path.read_text(), original)


if __name__ == '__main__':
    unittest.main()
