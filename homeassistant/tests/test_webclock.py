"""Run with HA installed: python -m unittest discover -s homeassistant/tests."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
from time import monotonic, time
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, PropertyMock, patch

from aiohttp import ClientSession, DummyCookieJar, TCPConnector
from flask import jsonify
from werkzeug.serving import make_server, WSGIRequestHandler

from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers.update_coordinator import UpdateFailed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'homeassistant'))
sys.path.insert(0, str(ROOT / 'tests'))
import test_device_enrollment as enrollment
from custom_components.webclock.api import ApiError, WebClockClient, normalize_url
from custom_components.webclock.config_flow import WebClockConfigFlow, WebClockOptionsFlow
from custom_components.webclock.services import register_services
from custom_components.webclock.coordinator import WebClockCoordinator
from custom_components.webclock.sensor import WebClockSensor
from custom_components.webclock import async_setup_entry, async_unload_entry, websocket_time


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def entry(data=None, options=None):
    return ConfigEntry(domain='webclock', title='WebClock', version=1, minor_version=1,
        source='user', unique_id='webclock-test', data=data or {'server_url': 'https://localhost',
        'device_token': 'a' * 43}, options=options or {}, discovery_keys=MappingProxyType({}),
        subentries_data=[])


def snapshot(stamp=None):
    stamp = stamp or time() * 1000
    shared = {'schema_version': 3,
        'identity': {'device_id': 'device', 'group_id': 'group', 'identity_revision': 'revision'},
        'config_revision': 'config', 'schedule_revision': 'schedule', 'holiday_revision': 'holiday',
        'server_timestamp': stamp, 'lease': {'issued_at': stamp, 'expires_at': stamp + 300_000}}
    alarm = {'id': 'alarm', 'occurrence_id': 'one-occurrence', 'name': 'Wake up', 'starts_at': stamp + 60_000}
    return {'display': {**deepcopy(shared), 'settings': {'timezone_offset': 8, 'language': 'zh-TW', 'time_format': '24h'},
                        'events': [{'text': '<script>private event</script>', 'time': '08:00'}]},
            'alarms': {**deepcopy(shared), 'enabled_count': 1, 'alarms': [alarm]},
            'status': {'identity': shared['identity'], 'commands': []}, 'sampled_at': monotonic()}


class WebClockHATest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.folder.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        self.client = AsyncMock()
        self.client.snapshot.return_value = snapshot()
        self.entry = entry()
        self.coordinator = WebClockCoordinator(self.hass, self.entry, self.client)
        self.coordinator._store = AsyncMock()
        self.coordinator._store.async_load.return_value = None

    async def asyncTearDown(self):
        self.coordinator.close()
        await self.hass.async_stop(force=True)
        self.folder.cleanup()

    async def update(self):
        self.coordinator.data = await self.coordinator._async_update_data()
        self.coordinator.last_update_success = True

    async def test_real_ha_sensors_clock_lease_and_authorization_lifecycle(self):
        await self.update()
        sensors = {key: WebClockSensor(self.coordinator, key) for key in ('time', 'calendar', 'alarms')}
        self.assertEqual(sensors['calendar'].native_value, 1)
        self.assertEqual(sensors['alarms'].extra_state_attributes['alarms'][0]['name'], 'Wake up')
        self.assertEqual(sensors['time'].native_value.tzinfo, timezone.utc)
        self.assertNotIn('device_token', json.dumps(sensors['time'].extra_state_attributes))
        with patch('custom_components.webclock.coordinator.monotonic', return_value=self.coordinator.sampled_at + 42):
            self.assertAlmostEqual(self.coordinator.server_now(), self.coordinator.clock_anchor + 42000)
        with patch('custom_components.webclock.coordinator.time', return_value=self.coordinator.wall_deadline + 1):
            self.assertFalse(sensors['calendar'].available)  # Host sleep cannot extend private leases.
        self.client.snapshot.side_effect = ApiError('cannot_connect')
        with self.assertRaises(UpdateFailed):
            await self.coordinator._async_update_data()
        self.assertTrue(sensors['calendar'].available)  # Still inside the server's lease.
        self.coordinator._clear_private()
        self.assertFalse(sensors['calendar'].available)
        self.assertEqual(sensors['calendar'].extra_state_attributes['events'], [])
        self.assertEqual(sensors['alarms'].extra_state_attributes['alarms'], [])
        self.assertTrue(sensors['time'].available)
        self.client.snapshot.side_effect = ApiError('device_authorization_revoked', 403)
        with self.assertRaises(UpdateFailed):
            await self.coordinator._async_update_data()  # Paused devices keep polling.
        self.client.snapshot.side_effect = None
        await self.update()
        self.assertTrue(sensors['calendar'].available)
        self.client.snapshot.side_effect = ApiError('device_authentication_required', 401)
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.coordinator._async_update_data()
        self.assertFalse(sensors['alarms'].available)

    async def test_snapshot_validation_scope_boundaries_and_ack_order(self):
        data = snapshot()
        WebClockClient.validate_snapshot(data['display'], data['alarms'])
        for mutate in (
            lambda a: a['identity'].update(group_id='another-group'),
            lambda a: a.update(schedule_revision='changed'),
            lambda a: a['lease'].update(expires_at=float('nan')),
            lambda a: a['alarms'][0].update(starts_at=True),
            lambda a: a['alarms'][0].update(starts_at=1e100),
            lambda a: a.update(server_timestamp=1e100),
        ):
            invalid = deepcopy(data)
            mutate(invalid['alarms'])
            with self.assertRaises(ApiError):
                WebClockClient.validate_snapshot(invalid['display'], invalid['alarms'])
        self.client.snapshot.return_value['status']['commands'] = [{'id': 'sync-1', 'action': 'sync'}]
        await self.update()
        self.client.snapshot.assert_awaited_with([])
        await self.update()
        self.client.snapshot.assert_awaited_with(['sync-1'])
        for value in ('https://user:password@host', 'https://host/path', 'https://host?token=secret', 'file:///tmp', 'https://host:abc'):
            with self.assertRaises(ValueError):
                normalize_url(value)
        self.assertEqual(normalize_url('HTTPS://LOCALHOST/'), 'https://localhost')

    async def test_opt_in_alarm_event_persisted_once_revocation_and_no_late_replay(self):
        self.entry = entry(options={'emit_alarm_events': True})
        self.coordinator.entry = self.entry
        await self.update()
        coordinator = self.coordinator
        row = coordinator.data['alarms']['alarms'][0]
        received = []
        self.hass.bus.async_listen('webclock_alarm', lambda event: received.append(event.data))
        key = 'device:' + row['occurrence_id']
        with patch.object(coordinator, 'server_now', return_value=row['starts_at'] + 1):
            await coordinator._fire_alarm(row, key, 'revision')
            await coordinator._fire_alarm(row, key, 'revision')
        await self.hass.async_block_till_done()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['occurrence_id'], row['occurrence_id'])
        self.assertIn(key, coordinator._store.async_save.call_args.args[0])
        restored = WebClockCoordinator(self.hass, self.entry, self.client)
        restored._store = AsyncMock()
        restored._store.async_load.return_value = dict(coordinator._fired)
        await restored._async_setup()
        self.assertIn(key, restored._fired)
        restored.close()
        coordinator._clear_private()
        with patch.object(coordinator, 'server_now', return_value=row['starts_at'] + 1):
            await coordinator._fire_alarm(row, 'different', 'revision')
        self.assertEqual(len(received), 1)
        await self.update()
        with patch.object(coordinator, 'server_now', return_value=row['starts_at'] + 10_000):
            await coordinator._fire_alarm(row, 'too-late', 'revision')
        self.assertEqual(len(received), 1)
        with patch.object(coordinator, 'server_now', side_effect=[row['starts_at'], row['starts_at'] + 3000]):
            await coordinator._fire_alarm(row, 'slow-storage', 'revision')
        self.assertEqual(len(received), 1)  # A slow disk must not publish a late alarm.
        self.assertEqual(len(coordinator._alarm_timers), 0)  # Fired occurrence is not rescheduled.
        coordinator.close()
        self.assertEqual(coordinator._alarm_timers, [])

    async def test_config_flow_saves_credential_but_never_join_code_and_retries_same_attempt(self):
        flow = WebClockConfigFlow()
        flow.hass = self.hass
        flow.context = {'source': 'user'}
        flow._client = AsyncMock()
        flow._client.url = 'https://localhost'
        flow._client.token = 'secret-device-token'
        flow._client.join.side_effect = [ApiError('invalid_invitation', 400), {'device_id': 'new-device'}]
        result = await flow.async_step_user({'server_url': 'https://localhost', 'join_code': 'BAD123'})
        self.assertEqual(result['errors'], {'base': 'invalid_invitation'})
        hints = {str(key): key.description['suggested_value'] for key in result['data_schema'].schema}
        self.assertEqual(hints, {'server_url': 'https://localhost', 'join_code': 'BAD123'})
        result = await flow.async_step_user({'server_url': 'https://localhost', 'join_code': 'A7K9M2'})
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['device_token'], 'secret-device-token')
        self.assertNotIn('join_code', result['data'])
        self.assertNotIn('A7K9M2', json.dumps(result['data']))
        self.assertEqual(flow._client.join.await_count, 2)
        invalid = WebClockClient(object(), 'https://localhost')
        invalid.request = AsyncMock(return_value={'token': '\n' + 'a' * 42, 'attempt_id': 'attempt'})
        with self.assertRaises(ApiError):
            await invalid.join('A7K9M2')
        self.assertIsNone(invalid.token)

    async def test_setup_unload_real_ha_forwarding_and_public_time_command(self):
        with patch('custom_components.webclock.async_create_clientsession', return_value=object()), \
             patch('custom_components.webclock.WebClockClient', return_value=self.client), \
             patch.object(self.hass.config_entries, 'async_forward_entry_setups', new=AsyncMock()) as forward, \
             patch.object(self.hass.config_entries, 'async_unload_platforms', new=AsyncMock(return_value=True)):
            self.entry.runtime_data = self.coordinator
            with patch('custom_components.webclock.WebClockCoordinator', return_value=self.coordinator), \
                 patch.object(self.coordinator, 'async_config_entry_first_refresh', new=AsyncMock()):
                self.assertTrue(await async_setup_entry(self.hass, self.entry))
            forward.assert_awaited_once()
            await self.update()
            connection = unittest.mock.Mock()
            with patch.object(self.hass.config_entries, 'async_get_entry', return_value=self.entry):
                websocket_time(self.hass, connection, {'id': 1, 'entry_id': self.entry.entry_id})
            self.assertEqual(set(connection.send_result.call_args.args[1]), {'server_timestamp'})
            self.assertTrue(await async_unload_entry(self.hass, self.entry))
            await self.entry._async_process_on_unload(self.hass)
            self.assertTrue(self.coordinator._closed)

    async def test_control_actions_keep_credential_and_revision_boundaries(self):
        register_services(self.hass)
        control_entry = SimpleNamespace(state=ConfigEntryState.LOADED, runtime_data=self.coordinator,
                                        options={'write_token': 'program-secret'})
        saved = {'schedule': {'id': 'alarm', 'name': 'Wake'}, 'revision': 'a' * 64}
        self.client.control.return_value = saved
        with patch.object(self.hass.config_entries, 'async_entries', return_value=[control_entry]):
            response = await self.hass.services.async_call('webclock', 'create_alarm', {
                'request_id': 'repeat-safely', 'schedule': {'name': 'Wake', 'time': '07:00'}
            }, blocking=True, return_response=True)
            self.assertEqual(response, saved)
            self.client.control.assert_awaited_once_with('POST', 'schedules', {
                'request_id': 'repeat-safely', 'schedule': {'name': 'Wake', 'time': '07:00'}
            }, None, None, None, token='program-secret')
            with self.assertRaises(__import__('voluptuous').Invalid):
                await self.hass.services.async_call('webclock', 'update_alarm', {
                    'id': 'alarm', 'schedule': {'time': '08:00'}
                }, blocking=True)
            self.client.control.side_effect = ApiError('revision_conflict', 409)
            with self.assertRaisesRegex(ServiceValidationError, 'revision_conflict'):
                await self.hass.services.async_call('webclock', 'update_alarm', {
                    'id': 'alarm', 'revision': 'b' * 64, 'schedule': {'time': '08:00'}
                }, blocking=True)
            control_entry.options = {}
            with self.assertRaisesRegex(ServiceValidationError, 'write token'):
                await self.hass.services.async_call('webclock', 'list_events', {}, blocking=True)
            self.assertEqual(self.client.control.await_count, 2)

    async def test_options_preserve_and_clear_secret_without_rendering_it(self):
        flow = WebClockOptionsFlow()
        flow.hass = self.hass
        configured = entry(options={'write_token': 'stored-secret', 'emit_alarm_events': True})
        with patch.object(WebClockOptionsFlow, 'config_entry', new_callable=PropertyMock, return_value=configured):
            form = await flow.async_step_init()
            self.assertNotIn('stored-secret', str(form))
            result = await flow.async_step_init({'emit_alarm_events': False, 'write_token': ''})
            self.assertEqual(result['data'], {'write_token': 'stored-secret', 'emit_alarm_events': False})
            result = await flow.async_step_init({'clear_write_token': True})
            self.assertNotIn('write_token', result['data'])
            result = await flow.async_step_init({'write_token': 'new-secret'})
            self.assertEqual(result['data']['write_token'], 'new-secret')
            result = await flow.async_step_init({'write_token': 'invalid\nsecret'})
            self.assertEqual(result['errors'], {'base': 'invalid_write_token'})


class NativeEndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def test_control_client_and_cli_against_real_webclock(self):
        import os
        import subprocess
        from test_control_api import ControlApiTest, clock
        fixture = ControlApiTest()
        fixture.setUp()
        fixture.issue()
        with clock.app.test_request_context('/'):
            owner = clock.auth_service().owner_id()
            group = clock.group_service().create_group(owner, {'name': 'Client tests'})
        token = fixture.issue(group_ids=[group['id']])['token']
        server = make_server('127.0.0.1', 0, clock.app, request_handler=QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            async with ClientSession(cookie_jar=DummyCookieJar()) as session:
                client = WebClockClient(session, url, 'not-a-write-token')
                body = {'request_id': 'real-client-event', 'event': {'title': 'Meeting',
                    'start': '2030-10-09T14:00:00+08:00', 'end': '2030-10-09T15:00:00+08:00',
                    'display_window': {'mode': 'relative', 'before_minutes': 60, 'end': 'event_end'}}}
                event = await client.control('POST', 'events', body, token=token)
                repeat = await client.control('POST', 'events', body, token=token)
                self.assertEqual(event['event']['id'], repeat['event']['id'])
                self.assertTrue(repeat['replayed'])
                item_id = event['event']['id']
                current = await client.control('GET', 'events', item_id=item_id,
                    target_kind='group', target_id=group['id'], token=token)
                assigned = await client.control('PUT', 'events', {'assigned': True, 'revision': current['revision']},
                    item_id, 'group', group['id'], token=token)
                self.assertTrue(assigned['assigned'])
                updated = await client.control('PATCH', 'events', {'revision': event['revision'], 'event': {'title': 'Updated'}},
                    item_id, token=token)
                self.assertEqual(updated['event']['title'], 'Updated')
                with self.assertRaises(ApiError) as conflict:
                    await client.control('PATCH', 'events', {'revision': event['revision'], 'event': {'title': 'Stale'}},
                        item_id, token=token)
                self.assertEqual(conflict.exception.code, 'revision_conflict')
            process = await asyncio.to_thread(subprocess.run,
                [sys.executable, str(ROOT / 'scripts/control_clock.py'), 'events', 'list'],
                env=dict(os.environ, WEBCLOCK_SERVER_URL=url, WEBCLOCK_WRITE_TOKEN=token),
                text=True, capture_output=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['events'][0]['event']['title'], 'Updated')
            self.assertNotIn(token, process.stdout + process.stderr)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            fixture.doCleanups()

    async def test_control_transport_separates_token_and_rejects_redirects(self):
        from flask import Flask, redirect, request
        app = Flask(__name__)
        seen = []
        @app.route('/api/v1/control/schedules', methods=['GET', 'POST'])
        def schedules():
            seen.append(dict(request.headers))
            return jsonify(schedule={'id': 'saved'}, revision='a' * 64), 201
        @app.route('/api/v1/control/events')
        def events():
            return redirect('/api/v1/control/schedules', 307)
        server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            async with ClientSession(cookie_jar=DummyCookieJar()) as session:
                client = WebClockClient(session, f'http://127.0.0.1:{server.server_port}', 'display-secret')
                result = await client.control('POST', 'schedules', {'request_id': 'one', 'schedule': {}}, token='program-secret')
                self.assertEqual(result['schedule']['id'], 'saved')
                self.assertEqual(seen[0]['Authorization'], 'Bearer program-secret')
                self.assertNotIn('Cookie', seen[0])
                for resource, item in [('https://elsewhere', None), ('schedules', '../events')]:
                    with self.assertRaises(ApiError):
                        await client.control('GET', resource, item_id=item, token='program-secret')
                with self.assertRaises(ApiError):
                    await client.control('GET', 'events', token='program-secret')
                self.assertEqual(len(seen), 1)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()

    async def test_real_https_client_join_retry_read_status_revoke(self):
        fixture = enrollment.EnrollmentTransportTest()
        fixture.setUp()
        server = make_server('127.0.0.1', 0, fixture.app, ssl_context='adhoc', request_handler=QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        sample = snapshot()
        def display(identity):
            kind = 'alarms' if __import__('flask').request.path.endswith('browser-alarms') else 'display'
            return jsonify({**sample[kind], 'identity': identity})
        fixture.display_callback = display
        try:
            async with ClientSession(cookie_jar=DummyCookieJar(), connector=TCPConnector(ssl=False)) as session:
                client = WebClockClient(session, f'https://127.0.0.1:{server.server_port}')
                identity = await client.join(fixture.invitation['code'])
                self.assertEqual(identity, await client.join(fixture.invitation['code']))
                data = await client.snapshot()
                self.assertEqual(data['display']['events'][0]['text'], '<script>private event</script>')
                self.assertEqual(fixture.devices.list()[0]['device_type'], 'homeassistant')
                self.assertEqual(fixture.service.get_invite(fixture.auth.owner_id(), fixture.group['id'])['used'], 1)
                await client.request('token/leave', {})
                with self.assertRaises(ApiError) as error:
                    await client.snapshot()
                self.assertEqual(error.exception.status, 401)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
