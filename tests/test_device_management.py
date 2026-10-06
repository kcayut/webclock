"""Management lists and revocation follow authority, never observation IDs."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.device_access_service import DeviceAccessService, _RATE_WINDOWS
from webclock.services.device_service import DeviceService
from webclock.services.storage import load_json, save_json


class DeviceManagementTest(unittest.TestCase):
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
        self.devices = DeviceService(self.root / 'devices.json')
        self.client = clock.app.test_client()
        csrf = self.call('/api/csrf').json['csrf_token']
        self.call('/login', 'POST', data={'username': 'owner', 'password': 'a-long-test-password', 'csrf_token': csrf})
        self.csrf = self.call('/api/csrf').json['csrf_token']
        self.headers = {'X-CSRF-Token': self.csrf}

    def call(self, path, method='GET', **kwargs):
        return self.client.open(path, method=method, base_url='https://localhost', **kwargs)

    def service(self):
        with clock.app.test_request_context('/'):
            return clock.group_service()

    def device(self, name='Device', owner=None, observed=True):
        owner = owner or self.owner
        service = self.service()
        group = service.create_group(owner, {'name': name})
        invite = service.create_invite(owner, group['id'])
        attempt = service.prepare(owner, name)
        identity = service.join(owner, attempt['token'], attempt['attempt_id'], invite['code'], name)['identity']
        if observed:
            self.devices.register({'id': identity['device_id'], 'name': name})
        client = clock.app.test_client()
        client.set_cookie('webclock_device', attempt['token'], path='/api/v2/device')
        return dict(identity=identity, attempt=attempt, client=client, invite=invite)

    def device_call(self, device, path='display', method='GET', **kwargs):
        return device['client'].open('/api/v2/device/' + path, method=method, base_url='https://localhost', **kwargs)

    def rows(self):
        response = self.call('/api/v1/devices')
        self.assertEqual(response.status_code, 200, response.text)
        return {row['id']: row for row in response.json['devices']}

    def remove(self, device):
        return self.call('/api/v1/devices/' + device['identity']['device_id'], 'DELETE', headers=self.headers)

    def update_authorization(self, device, data):
        return self.call('/api/v1/devices/' + device['identity']['device_id'] + '/authorization',
                         'PATCH', json=data, headers=self.headers)

    def display_settings(self, device, overrides=None, revision=None):
        path = '/api/v1/devices/' + device['identity']['device_id'] + '/display-settings'
        if overrides is None:
            return self.call(path)
        revision = revision or self.call(path).json['revision']
        return self.call(path, 'PATCH', headers=self.headers,
                         json=dict(display_overrides=overrides, revision=revision))

    def test_device_display_inheritance_reset_move_and_peer_isolation(self):
        device = self.device('Bedroom')
        service, group_id = self.service(), device['identity']['group_id']
        attempt = service.prepare(self.owner, 'peer')
        peer = service.join(self.owner, attempt['token'], attempt['attempt_id'], device['invite']['code'], 'peer')['identity']
        service.update_group(self.owner, group_id, {'display_overrides': {'brightness': 30}})
        before = self.device_call(device)
        original = service._load()['devices'][device['identity']['device_id']]
        night = dict(clock.DEFAULT_NIGHT, enabled=False, brightness=0, black=False)
        overrides = dict(brightness=0, mode='black', time_format='12h', language='ja', night=night)
        result = self.display_settings(device, overrides)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json['effective_settings']['night'], night)
        self.assertEqual(result.json['sources']['brightness'], 'device')
        self.assertEqual(result.json['sources']['timezone_offset'], 'default')
        self.assertEqual(result.json['sources']['night.enabled'], 'device')
        self.assertEqual(service._load()['devices'][device['identity']['device_id']], dict(original, display_overrides=overrides))
        after = self.device_call(device, headers={'If-None-Match': before.headers['ETag']})
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json['settings']['brightness'], 0)
        self.assertEqual(after.json['settings']['language'], 'ja')
        self.assertNotEqual(after.json['config_revision'], before.json['config_revision'])
        self.assertEqual(after.json['schedule_revision'], before.json['schedule_revision'])
        self.assertEqual(after.json['config_revision'], self.device_call(device, 'browser-alarms').json['config_revision'])
        service.update_group(self.owner, group_id, {'display_overrides': {'brightness': 40, 'timezone_offset': 9}})
        settings = self.display_settings(device).json
        self.assertEqual(settings['effective_settings']['brightness'], 0)
        self.assertEqual(settings['effective_settings']['timezone_offset'], 9)
        self.assertEqual(settings['sources']['timezone_offset'], 'group')
        self.assertEqual(service.get_device_display(self.owner, peer['device_id'])['effective_settings']['brightness'], 40)
        clock.display_settings['time_format'] = '12h'
        clock.display_settings['language'] = 'en'
        reset = self.display_settings(device, {}).json
        self.assertEqual(reset['display_overrides'], {})
        self.assertEqual(reset['effective_settings']['brightness'], 40)
        self.assertEqual(reset['effective_settings']['language'], 'en')
        self.assertEqual(reset['sources']['brightness'], 'group')
        self.assertEqual(reset['sources']['time_format'], 'default')
        self.assertNotIn('display_overrides', service._load()['devices'][device['identity']['device_id']])
        self.assertEqual(self.display_settings(device, {'brightness': 10}).status_code, 200)
        target = service.create_group(self.owner, {'name': 'Office', 'display_overrides': {'timezone_offset': -5}})
        moved = self.update_authorization(device, {'group_id': target['id']})
        self.assertEqual(moved.json['display_settings']['effective_settings']['brightness'], 10)
        self.assertEqual(moved.json['display_settings']['effective_settings']['timezone_offset'], -5)
        self.assertEqual(self.device_call(device).json['settings']['timezone_offset'], -5)
        self.assertEqual(self.rows()[device['identity']['device_id']]['display_settings'], moved.json['display_settings'])

    def test_device_display_conflicts_validation_and_owner_boundary(self):
        device = self.device()
        service = self.service()
        initial = self.display_settings(device).json
        self.assertEqual(self.display_settings(device, {'brightness': 10}, initial['revision']).status_code, 200)
        stale = self.display_settings(device, {'brightness': 20}, initial['revision'])
        self.assertEqual((stale.status_code, stale.json['code']), (409, 'display_settings_changed'))
        current = self.display_settings(device).json
        service.update_group(self.owner, device['identity']['group_id'], {'display_overrides': {'brightness': 30}})
        self.assertEqual(self.display_settings(device, {}, current['revision']).status_code, 409)
        current = self.display_settings(device).json
        clock.display_settings['language'] = 'en'
        self.assertEqual(self.display_settings(device, {}, current['revision']).status_code, 409)
        for invalid in ({'brightness': 101}, {'brightness': False}, {'language': 'zh-CN'},
                        {'night': {'enabled': False}}, {'night': dict(clock.DEFAULT_NIGHT, start='07:00', end='07:00')},
                        {'content': {}}, {'timezone_offset': 8.5}):
            original = service.path.read_bytes()
            self.assertEqual(self.display_settings(device, invalid).status_code, 400, invalid)
            self.assertEqual(service.path.read_bytes(), original)
        foreign = self.device('Foreign', owner='other-owner')
        self.assertEqual(self.display_settings(foreign).status_code, 404)
        self.assertEqual(self.display_settings(foreign, {}, 'unknown').status_code, 404)
        original = service.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('disk full')):
            self.assertEqual(self.display_settings(device, {'brightness': 20}).status_code, 500)
        self.assertEqual(service.path.read_bytes(), original)
        self.assertEqual(self.display_settings(device).json['effective_settings']['brightness'], 10)

    def test_device_display_inflight_change_does_not_return_stale_config_or_304(self):
        device = self.device()
        respond = clock.managed_response
        for index, path in enumerate(('display', 'browser-alarms')):
            before = self.device_call(device, path)
            def update_during_response(*args, **kwargs):
                self.assertEqual(self.display_settings(device, {'brightness': 10 + index}).status_code, 200)
                return respond(*args, **kwargs)
            with patch.object(clock, 'managed_response', side_effect=update_during_response):
                response = self.device_call(device, path, headers={'If-None-Match': before.headers['ETag']})
            self.assertEqual((response.status_code, response.json['code']), (409, 'display_scope_changed'))
            self.assertNotIn('ETag', response.headers)
            self.assertNotIn('settings', response.json)

    def test_move_and_pause_preserve_credential_reports_ack_and_invitation_seats(self):
        device = self.device('Original group')
        device_id = device['identity']['device_id']
        service = self.service()
        attempt = service.prepare(self.owner, 'same-group-peer')
        peer_id = service.join(self.owner, attempt['token'], attempt['attempt_id'],
                               device['invite']['code'], 'same-group-peer')['identity']['device_id']
        target = service.create_group(self.owner, {'name': 'Destination'})
        self.devices.rename(device_id, {'name': 'Preserved admin name'})
        command = self.devices.command(device_id, 'sync')
        self.devices.report({'id': device_id, 'firmware': 'existing-build', 'config_revision': 'old-config',
                             'capabilities': {'audio': False, 'display': True},
                             'acknowledged_commands': [command['id']]})
        self.devices.command(device_id, 'sync')
        before, observed = service._load(), self.devices.path.read_bytes()
        response = self.update_authorization(device, {'group_id': target['id'], 'enabled': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.json['device'], dict(id=device_id, group_id=target['id'], group_name='Destination',
            group_enabled=True, enabled=False, authorization_status='disabled', assignment_revision=2, rejoin_required=False))
        after = service._load()
        self.assertEqual(after['devices'][device_id], dict(before['devices'][device_id], group_id=target['id'],
                                                         enabled=False, status='disabled', assignment_revision=2))
        self.assertEqual(after['devices'][peer_id], before['devices'][peer_id])
        for field in ('groups', 'invites', 'attempts'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(self.devices.path.read_bytes(), observed)
        self.assertEqual(service.authenticate(attempt['token'], self.owner)['group_id'], device['identity']['group_id'])
        row = self.rows()[device_id]
        self.assertEqual(row['name'], 'Preserved admin name')
        self.assertEqual(row['group_name'], 'Destination')
        self.assertEqual(row['capabilities'], {'audio': False, 'display': True})
        self.assertEqual(row['authorization_status'], 'disabled')
        self.assertNotIn('credential_digest', response.text)
        with patch('webclock.services.device_access_service.save_json') as write:
            self.assertEqual(self.update_authorization(device, {'group_id': target['id'], 'enabled': False}).status_code, 200)
            write.assert_not_called()
        resumed = self.update_authorization(device, {'enabled': True})
        self.assertEqual(resumed.json['device']['assignment_revision'], 3)
        identity = self.device_call(device, 'identity')
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.json['group'], {'id': target['id'], 'name': 'Destination'})
        self.assertEqual(identity.json['identity']['credential_generation'], before['devices'][device_id]['credential_generation'])
        self.assertEqual(self.devices.path.read_bytes(), observed)

    def test_authorization_changes_require_owner_session_csrf_and_valid_active_destination(self):
        own, foreign = self.device('Own'), self.device('Foreign', owner='other')
        self.devices.register({'id': 'legacy', 'name': 'Legacy'})
        disabled = self.service().create_group(self.owner, {'name': 'Disabled group', 'enabled': False})
        url = '/api/v1/devices/' + own['identity']['device_id'] + '/authorization'
        before = self.service().path.read_bytes(), self.devices.path.read_bytes()
        anonymous = clock.app.test_client()
        self.assertEqual(anonymous.patch(url, base_url='https://localhost', json={'enabled': False}).status_code, 401)
        for headers in ({}, {'X-CSRF-Token': self.csrf, 'Origin': 'https://foreign.invalid'}):
            self.assertEqual(self.call(url, 'PATCH', json={'enabled': False}, headers=headers).status_code, 403)
        for body in ({}, [], {'enabled': 1}, {'enabled': None}, {'group_id': []}, {'group_id': ''}, {'group_id': 'x' * 129},
                     {'group_id': 1}, {'name': 'Wrong endpoint'}, {'enabled': True, 'unknown': True}):
            self.assertEqual(self.update_authorization(own, body).status_code, 400, body)
        for group_id in (foreign['identity']['group_id'], 'missing'):
            response = self.update_authorization(own, {'enabled': False, 'group_id': group_id})
            self.assertEqual(response.status_code, 404)
        response = self.update_authorization(own, {'group_id': disabled['id'], 'enabled': False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['code'], 'group_disabled')
        for device_id in (foreign['identity']['device_id'], 'legacy', 'missing'):
            response = self.call('/api/v1/devices/' + device_id + '/authorization', 'PATCH',
                                 json={'enabled': False}, headers=self.headers)
            self.assertEqual(response.status_code, 404)
        with patch.object(AuthService, 'mode', return_value='self'):
            response = self.call('/api/v1/devices/legacy/authorization', 'PATCH',
                                 json={'enabled': False}, headers=self.headers)
            self.assertEqual(response.status_code, 404)
        self.assertEqual((self.service().path.read_bytes(), self.devices.path.read_bytes()), before)

    def test_disabled_group_does_not_prevent_pausing_or_moving_its_own_device(self):
        device = self.device()
        service = self.service()
        current_id = device['identity']['group_id']
        target = service.create_group(self.owner, {'name': 'Enabled destination'})
        service.update_group(self.owner, current_id, {'enabled': False})
        response = self.update_authorization(device, {'group_id': current_id, 'enabled': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json['device']['group_enabled'])
        self.assertEqual(response.json['device']['authorization_status'], 'disabled')
        self.assertEqual(self.update_authorization(device, {'enabled': True}).status_code, 200)
        self.assertEqual(self.device_call(device, 'identity').status_code, 403)
        self.assertEqual(self.update_authorization(device, {'group_id': target['id']}).status_code, 200)
        self.assertEqual(self.device_call(device, 'identity').status_code, 200)

    def test_authorization_write_failure_is_atomic_and_safe_to_retry(self):
        device = self.device()
        group = self.service().create_group(self.owner, {'name': 'Target'})
        before = self.service().path.read_bytes(), self.devices.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('PRIVATE path')):
            with self.assertLogs(clock.app.logger, level='ERROR'):
                response = self.update_authorization(device, {'group_id': group['id'], 'enabled': False})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('PRIVATE', response.text)
        self.assertEqual((self.service().path.read_bytes(), self.devices.path.read_bytes()), before)
        self.assertEqual(self.device_call(device).status_code, 200)
        self.assertEqual(self.update_authorization(device, {'group_id': group['id']}).status_code, 200)
        self.assertEqual(self.device_call(device, 'identity').json['identity']['assignment_revision'], 2)

    def test_restored_or_revoked_identity_cannot_be_resumed_or_moved(self):
        device = self.device()
        device_id = device['identity']['device_id']
        service = self.service()
        target = service.create_group(self.owner, {'name': 'Target'})
        original = service._load()
        for changes in ({'status': 'revoked'}, {'status': 'disabled', 'rejoin_required': True},
                        {'status': 'disabled', 'credential_digest': None},
                        {'status': 'revoked', 'rejoin_required': True, 'credential_digest': None,
                         'credential_generation': 2}):
            with self.subTest(changes=changes):
                state = deepcopy(original)
                state['devices'][device_id].update(enabled=False, **changes)
                state['attempts'] = {}
                save_json(service.path, state)
                before = service.path.read_bytes(), self.devices.path.read_bytes()
                for body in ({'enabled': True}, {'enabled': False}, {'group_id': target['id']}):
                    response = self.update_authorization(device, body)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json['code'], 'device_rejoin_required')
                self.assertEqual((service.path.read_bytes(), self.devices.path.read_bytes()), before)
                self.assertIn(self.device_call(device, 'identity').status_code, (401, 403))
                row = self.rows()[device_id]
                self.assertEqual(row['authorization_status'], changes['status'])
                self.assertTrue(row['rejoin_required'])

    def test_move_and_resume_same_cookie_change_scope_and_invalidate_previous_etags(self):
        device = self.device('A')
        service = self.service()
        save_json(self.root / 'manual_notes.json', [{'id': 1, 'text': 'Only A', 'due_date': ''},
                                                    {'id': 2, 'text': 'Only B', 'due_date': ''}])
        service.update_group(self.owner, device['identity']['group_id'], {'content': {'manual_note_ids': [1]}})
        target = service.create_group(self.owner, {'name': 'B', 'content': {'manual_note_ids': [2]}})
        before = self.device_call(device)
        self.assertEqual([row['text'] for row in before.json['events']], ['Only A'])
        old_etag = before.headers['ETag']
        self.assertEqual(self.update_authorization(device, {'group_id': target['id']}).status_code, 200)
        moved = self.device_call(device, headers={'If-None-Match': old_etag})
        self.assertEqual(moved.status_code, 200)
        self.assertNotEqual(moved.headers['ETag'], old_etag)
        self.assertEqual([row['text'] for row in moved.json['events']], ['Only B'])
        old_etag = moved.headers['ETag']
        self.assertEqual(self.update_authorization(device, {'enabled': False}).status_code, 200)
        for path in ('display', 'browser-alarms', 'identity'):
            response = self.device_call(device, path, headers={'If-None-Match': old_etag})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('ETag', response.headers)
            self.assertNotIn('events', response.json)
        self.assertEqual(self.update_authorization(device, {'enabled': True}).status_code, 200)
        resumed = self.device_call(device, headers={'If-None-Match': old_etag})
        self.assertEqual(resumed.status_code, 200)
        self.assertNotEqual(resumed.headers['ETag'], old_etag)
        self.assertEqual([row['text'] for row in resumed.json['events']], ['Only B'])
        self.assertEqual(self.device_call(device, 'identity').json['status'], 'active')

    def test_inflight_responses_after_move_or_pause_cannot_return_old_scope_or_304(self):
        device = self.device('Original')
        target = self.service().create_group(self.owner, {'name': 'Destination'})
        respond = clock.managed_response
        for path, changes in (('display', {'group_id': target['id']}), ('browser-alarms', {'enabled': False})):
            old_etag = self.device_call(device, path).headers['ETag']
            def change_during_response(*args, **kwargs):
                self.service().update_device(self.owner, device['identity']['device_id'], changes)
                return respond(*args, **kwargs)
            with patch.object(clock, 'managed_response', side_effect=change_during_response):
                response = self.device_call(device, path, headers={'If-None-Match': old_etag})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('ETag', response.headers)
            self.assertNotIn('events', response.json)
            self.assertNotIn('schedules', response.json)
        self.service().update_device(self.owner, device['identity']['device_id'], {'enabled': True})
        observed = self.devices.path.read_bytes()
        original = DeviceAccessService.authenticate
        calls = []
        def pause_after_guard(service, token, owner):
            identity = original(service, token, owner)
            calls.append(identity)
            if len(calls) == 1:
                service.update_device(owner, identity['device_id'], {'enabled': False})
            return identity
        with patch.object(DeviceAccessService, 'authenticate', new=pause_after_guard):
            response = self.device_call(device, 'status', 'POST', json={'firmware': 'late-report'},
                                        headers={'Authorization': 'Bearer ' + device['attempt']['token']})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.devices.path.read_bytes(), observed)

    def test_lists_only_owner_authority_and_marks_unreported_without_fabricated_heartbeat(self):
        reported = self.device('Reported')
        missing = self.device('Unreported', observed=False)
        foreign = self.device('Foreign private', owner='another-owner')
        self.devices.register({'id': 'old-observation', 'name': 'Old private observation'})
        before = self.devices.path.read_bytes()
        rows = self.rows()
        self.assertEqual(set(rows), {reported['identity']['device_id'], missing['identity']['device_id']})
        self.assertTrue(rows[reported['identity']['device_id']]['reported'])
        unknown = rows[missing['identity']['device_id']]
        self.assertTrue(unknown['can_revoke'])
        self.assertFalse(unknown['reported'])
        self.assertIsNone(unknown['online'])
        self.assertNotIn('last_seen', unknown)
        self.assertNotIn('registered_at', unknown)
        self.assertEqual(self.devices.path.read_bytes(), before)
        self.assertNotIn('credential_digest', str(rows))
        with patch.object(AuthService, 'mode', return_value='self'):
            rows = self.rows()
            self.assertIn('old-observation', rows)
            self.assertFalse(rows['old-observation']['can_revoke'])
            self.assertTrue(rows['old-observation']['reported'])
            self.assertNotIn(foreign['identity']['device_id'], rows)

    def test_admin_revoke_removes_observations_attempt_and_authority_but_not_other_devices(self):
        first, second = self.device('First'), self.device('Second')
        first_id = first['identity']['device_id']
        before = self.service()._load()
        old_etag = self.device_call(first).headers['ETag']
        response = self.remove(first)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'revoked'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        after = self.service()._load()
        self.assertEqual(after['devices'], {key: row for key, row in before['devices'].items() if key != first_id})
        self.assertEqual(after['attempts'], {key: row for key, row in before['attempts'].items()
                                           if key != first['attempt']['attempt_id']})
        self.assertEqual(after['invites'], before['invites'])
        self.assertEqual(set(self.rows()), {second['identity']['device_id']})
        self.assertEqual({row['id'] for row in self.devices.list()}, {second['identity']['device_id']})
        for path in ('display', 'browser-alarms', 'identity'):
            denied = self.device_call(first, path, headers={'If-None-Match': old_etag})
            self.assertEqual(denied.status_code, 401)
            self.assertNotIn('ETag', denied.headers)
        self.assertEqual(self.device_call(first, 'status', 'POST', json={},
            headers={'Authorization': 'Bearer ' + first['attempt']['token']}).status_code, 401)
        self.assertEqual(self.device_call(second).status_code, 200)
        self.assertEqual(self.remove(first).status_code, 404)

    def test_revoke_owner_session_csrf_origin_and_legacy_boundaries(self):
        own = self.device()
        foreign = self.device('Foreign', owner='other')
        self.devices.register({'id': 'legacy', 'name': 'Legacy'})
        url = '/api/v1/devices/' + own['identity']['device_id']
        anonymous = clock.app.test_client()
        self.assertEqual(anonymous.delete(url, base_url='https://localhost').status_code, 401)
        for headers in ({}, {'X-CSRF-Token': self.csrf, 'Origin': 'https://elsewhere.invalid'}):
            self.assertEqual(self.call(url, 'DELETE', headers=headers).status_code, 403)
        before = self.service().path.read_bytes(), self.devices.path.read_bytes()
        for device_id in (foreign['identity']['device_id'], 'legacy', 'missing'):
            self.assertEqual(self.call('/api/v1/devices/' + device_id, 'DELETE', headers=self.headers).status_code, 404)
            for suffix, method, body in (('', 'PATCH', {'name': 'Spoof'}), ('/commands', 'POST', {'action': 'sync'})):
                response = self.call('/api/v1/devices/' + device_id + suffix, method, json=body, headers=self.headers)
                self.assertEqual(response.status_code, 404)
        with patch.object(AuthService, 'mode', return_value='self'):
            self.assertEqual(self.call('/api/v1/devices/legacy', 'PATCH', json={'name': 'Legacy renamed'},
                headers=self.headers).status_code, 200)
            self.assertEqual(self.call('/api/v1/devices/legacy', 'DELETE', headers=self.headers).status_code, 404)
            self.assertEqual(self.remove(foreign).status_code, 404)
        self.assertEqual(self.service().path.read_bytes(), before[0])
        self.assertEqual(self.devices.list()[0]['name'], 'Device')

    def test_self_leave_uses_shared_observation_cleanup_and_unreported_device_can_be_revoked(self):
        first = self.device('First')
        csrf = first['client'].get('/api/csrf', base_url='https://localhost').json['csrf_token']
        self.assertEqual(self.device_call(first, 'leave', 'POST', json={}, headers={'X-CSRF-Token': csrf}).status_code, 200)
        self.assertEqual(self.rows(), {})
        self.assertEqual(self.devices.list(), [])
        missing = self.device('No report', observed=False)
        self.assertEqual(self.remove(missing).status_code, 200)
        self.assertEqual(self.rows(), {})

    def test_observation_failure_does_not_revoke_and_access_failure_retains_recoverable_authority(self):
        device = self.device()
        before_access, before_observed = self.service().path.read_bytes(), self.devices.path.read_bytes()
        with patch('webclock.services.device_service.save_json', side_effect=OSError('PRIVATE path')):
            with self.assertLogs(clock.app.logger, level='ERROR'):
                response = self.remove(device)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.service().path.read_bytes(), before_access)
        self.assertEqual(self.devices.path.read_bytes(), before_observed)
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('PRIVATE path')):
            with self.assertLogs(clock.app.logger, level='ERROR'):
                response = self.remove(device)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('PRIVATE', response.text)
        self.assertNotIn('retained', response.text)
        self.assertEqual(self.service().path.read_bytes(), before_access)
        self.assertEqual(self.devices.list(), [])
        self.assertFalse(self.rows()[device['identity']['device_id']]['reported'])
        self.assertEqual(self.device_call(device, 'status', 'POST', json={},
            headers={'Authorization': 'Bearer ' + device['attempt']['token']}).status_code, 200)
        self.assertEqual(self.remove(device).status_code, 200)

    def test_full_managed_observations_prune_only_orphans_and_preserve_all_current_owners(self):
        own = self.device(observed=False)
        foreign = self.device('Foreign', owner='other')
        prototype = load_json(self.devices.path, {})[foreign['identity']['device_id']]
        rows = load_json(self.devices.path, {})
        rows.update({f'legacy-{index}': dict(prototype, id=f'legacy-{index}') for index in range(99)})
        save_json(self.devices.path, rows)
        original = self.devices.path.read_bytes()
        with patch.object(AuthService, 'mode', return_value='self'):
            response = self.device_call(own, 'status', 'POST', json={},
                headers={'Authorization': 'Bearer ' + own['attempt']['token']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.devices.path.read_bytes(), original)
        response = self.device_call(own, 'status', 'POST', json={},
            headers={'Authorization': 'Bearer ' + own['attempt']['token']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(load_json(self.devices.path, {})), {own['identity']['device_id'], foreign['identity']['device_id']})
        self.assertEqual(load_json(self.devices.path, {})[foreign['identity']['device_id']], prototype)

    def test_inflight_status_and_display_cannot_restore_revoked_observation_or_return_304(self):
        first = self.device('Reporting')
        original = DeviceAccessService.authenticate
        calls = []
        def revoke_after_guard(service, token, owner):
            identity = original(service, token, owner)
            calls.append(identity)
            if len(calls) == 1:
                service.revoke(owner, identity['device_id'])
            return identity
        with patch.object(DeviceAccessService, 'authenticate', new=revoke_after_guard):
            response = self.device_call(first, 'status', 'POST', json={},
                headers={'Authorization': 'Bearer ' + first['attempt']['token']})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.devices.list(), [])
        second = self.device('Displaying')
        old_etag = self.device_call(second).headers['ETag']
        respond = clock.managed_response
        def revoke_during_display(*args, **kwargs):
            self.service().revoke(self.owner, second['identity']['device_id'])
            return respond(*args, **kwargs)
        with patch.object(clock, 'managed_response', side_effect=revoke_during_display):
            response = self.device_call(second, headers={'If-None-Match': old_etag})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('ETag', response.headers)
        self.assertNotIn('settings', response.json)


if __name__ == '__main__':
    unittest.main()
