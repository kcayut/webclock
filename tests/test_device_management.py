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
