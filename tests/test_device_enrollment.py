"""Atomic device enrollment, cookie roundtrips, credential scope and transport."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from flask import Flask, jsonify, request

from webclock.access_control import register_access_control
from webclock.auth import register_auth
from webclock.csrf import register_csrf
from webclock.api.managed_device import DEVICE_COOKIE, managed_device_api
from webclock.services.auth_service import AuthService
from webclock.services.device_access_service import (
    AccessError, DeviceAccessService, GLOBAL_LIMIT, SOURCE_LIMIT,
)
from webclock.services.device_service import DeviceService
from webclock.services.storage import load_json, save_json


IDENTITY_FIELDS = {'device_id', 'owner_id', 'group_id', 'credential_generation',
                   'assignment_revision', 'identity_revision'}


def access_service(path, now=None):
    return DeviceAccessService(path, 's' * 43, deepcopy, lambda: {'brightness': 100},
                               lambda: {'schedules': []}, clock=now)


class EnrollmentServiceTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'device-access.json'
        self.now = 1000.0
        self.service = access_service(self.path, lambda: self.now)
        self.owner = 'owner'
        self.group = self.service.create_group(self.owner, {'name': 'Living room'})
        self.invitation = self.service.create_invite(self.owner, self.group['id'], 1)

    def prepare(self, source='peer'):
        return self.service.prepare(self.owner, source)

    def join(self, attempt, **kwargs):
        return self.service.join(self.owner, attempt['token'], attempt['attempt_id'],
                                 kwargs.get('code', self.invitation['code']), kwargs.get('source', 'peer'))

    def assert_error(self, code, call):
        with self.assertRaises(AccessError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_prepare_is_bounded_pending_identity_and_reuses_cookie_without_authority(self):
        prepared = self.prepare()
        state = load_json(self.path, {})
        self.assertEqual(state['devices'], {})
        self.assertEqual(state['invites'][self.group['id']]['used'], 0)
        self.assertEqual(len(state['attempts']), 1)
        self.assertNotIn(prepared['token'], self.path.read_text())
        self.assertEqual(self.service.identity(prepared['token'], self.owner), {
            'status': 'pending', 'attempt_id': prepared['attempt_id'], 'expires_at': 1600000})
        self.assert_error('device_authentication_required',
                          lambda: self.service.authenticate(prepared['token'], self.owner))
        before = self.path.read_bytes()
        reused = self.service.prepare(self.owner, 'peer', prepared['token'])
        self.assertFalse(reused['created'])
        self.assertIsNone(reused['token'])
        self.assertEqual(reused['attempt_id'], prepared['attempt_id'])
        self.assertEqual(before, self.path.read_bytes())

    def test_join_commits_same_credential_owner_group_and_seat_once(self):
        prepared = self.prepare()
        result = self.join(prepared)
        identity = result['identity']
        self.assertTrue(result['created'])
        self.assertEqual(set(identity), IDENTITY_FIELDS)
        self.assertEqual(identity['group_id'], self.group['id'])
        state = load_json(self.path, {})
        row = state['devices'][identity['device_id']]
        self.assertEqual(row['credential_digest'], hashlib.sha256(prepared['token'].encode()).hexdigest())
        self.assertEqual(state['attempts'][prepared['attempt_id']]['device_id'], identity['device_id'])
        self.assertEqual(state['invites'][self.group['id']]['used'], 1)
        self.assertFalse((self.path.parent / 'devices.json').exists())
        self.assertEqual(self.service.authenticate(prepared['token'], self.owner), identity)
        self.assertNotIn(prepared['token'], self.path.read_text())
        self.assertNotIn(self.invitation['code'], self.path.read_text())

    def test_two_devices_racing_for_final_seat_have_only_one_committed_identity(self):
        attempts = [self.prepare('one'), self.prepare('two')]
        barrier = Barrier(2)
        def joining(attempt):
            barrier.wait()
            try:
                return self.join(attempt, source=attempt['attempt_id'])
            except AccessError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(joining, attempts))
        self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
        self.assertIn('invalid_invitation', outcomes)
        state = load_json(self.path, {})
        self.assertEqual(len(state['devices']), 1)
        self.assertEqual(state['invites'][self.group['id']]['used'], 1)

    def test_global_device_limit_applies_to_invites_created_in_different_groups(self):
        other = self.service.create_group(self.owner, {'name': 'Bedroom'})
        invitation = self.service.create_invite(self.owner, other['id'], 100)
        prepared = self.prepare()
        first = self.join(prepared)['identity']
        pending = self.prepare()
        state = load_json(self.path, {})
        prototype = state['devices'][first['device_id']]
        for index in range(99):
            device_id = 'existing-' + str(index)
            state['devices'][device_id] = dict(prototype, id=device_id,
                credential_digest=hashlib.sha256(device_id.encode()).hexdigest())
        save_json(self.path, state)
        before = self.path.read_bytes()
        self.assert_error('invalid_invitation', lambda: self.join(pending, code=invitation['code']))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.service.get_invite(self.owner, other['id'])['used'], 0)

    def test_join_disk_failure_retains_attempt_and_seat_for_clean_retry(self):
        prepared = self.prepare()
        before = self.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.join(prepared)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.service.identity(prepared['token'], self.owner)['status'], 'pending')
        self.assertTrue(self.join(prepared)['created'])

    def test_prepare_disk_failure_does_not_leave_a_half_attempt(self):
        before = self.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(self.path.read_bytes(), before)

    def test_lost_join_response_retries_after_restart_expiry_close_and_regeneration(self):
        prepared = self.prepare()
        original = self.join(prepared)['identity']
        self.now += 601
        self.service = access_service(self.path, lambda: self.now)
        self.service.close_invite(self.owner, self.group['id'])
        self.service.create_invite(self.owner, self.group['id'], 1)
        before = self.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=AssertionError('Retry wrote state')):
            retry = self.join(prepared)
        self.assertFalse(retry['created'])
        self.assertEqual(retry['identity'], original)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.service.get_invite(self.owner, self.group['id'])['used'], 0)

    def test_stale_attempt_cookie_mismatch_and_active_device_cannot_switch_groups(self):
        first, second = self.prepare(), self.prepare()
        before = self.path.read_bytes()
        self.assert_error('join_attempt_conflict', lambda: self.service.join(
            self.owner, first['token'], second['attempt_id'], self.invitation['code'], 'peer'))
        self.assertEqual(before, self.path.read_bytes())
        original = self.join(first)['identity']
        other = self.service.create_group(self.owner, {'name': 'Bedroom'})
        invitation = self.service.create_invite(self.owner, other['id'])
        self.assert_error('join_attempt_conflict', lambda: self.service.prepare(self.owner, 'peer', first['token']))
        self.assert_error('join_attempt_conflict', lambda: self.service.join(
            self.owner, first['token'], second['attempt_id'], invitation['code'], 'peer'))
        # An idempotent replay returns the existing identity, never a new assignment.
        self.assertEqual(self.join(first, code=invitation['code'])['identity'], original)
        self.assertEqual(self.service.get_invite(self.owner, other['id'])['used'], 0)

    def test_wrong_invite_and_other_owner_fail_without_state_change(self):
        prepared = self.prepare()
        other = self.service.create_group('another-owner', {'name': 'Private'})
        code = self.service.create_invite('another-owner', other['id'])['code']
        before = self.path.read_bytes()
        for candidate in ('wrong!', code):
            error = self.assert_error('invalid_invitation', lambda: self.join(prepared, code=candidate))
            self.assertNotIn('Private', str(error))
        self.assertEqual(before, self.path.read_bytes())

    def test_expired_pending_attempt_requires_manual_prepare_again(self):
        prepared = self.prepare()
        self.now += 600
        self.assert_error('device_authentication_required',
                          lambda: self.service.identity(prepared['token'], self.owner))
        self.assert_error('join_attempt_conflict', lambda: self.join(prepared))
        replacement = self.service.prepare(self.owner, 'peer', prepared['token'])
        self.assertTrue(replacement['created'])
        self.assertNotEqual(replacement['token'], prepared['token'])
        self.assertEqual(len(load_json(self.path, {})['attempts']), 1)

    def test_disabled_revoked_cleared_and_wrong_owner_cannot_resurrect_a_completed_attempt(self):
        prepared = self.prepare()
        identity = self.join(prepared)['identity']
        original = load_json(self.path, {})
        for changes in ({'enabled': False}, {'status': 'revoked', 'enabled': False},
                        {'status': 'revoked', 'enabled': False, 'credential_digest': None, 'rejoin_required': True}):
            state = deepcopy(original)
            state['devices'][identity['device_id']].update(changes)
            save_json(self.path, state)
            with self.subTest(changes=changes):
                self.assert_error('device_authorization_revoked', lambda: self.join(prepared))
                self.assert_error('device_authorization_revoked',
                                  lambda: self.service.identity(prepared['token'], self.owner))
        save_json(self.path, original)
        self.assert_error('device_authorization_revoked',
                          lambda: self.service.authenticate(prepared['token'], 'another-owner'))
        self.service.update_group(self.owner, self.group['id'], {'enabled': False})
        self.assert_error('device_authorization_revoked', lambda: self.join(prepared))

    def test_identity_revision_tracks_assignment_not_names_and_member_dto_has_no_secret(self):
        prepared = self.prepare()
        first = self.join(prepared)['identity']
        self.service.update_group(self.owner, self.group['id'], {'name': 'New label'})
        self.assertEqual(self.service.authenticate(prepared['token'], self.owner), first)
        state = load_json(self.path, {})
        state['devices'][first['device_id']]['assignment_revision'] += 1
        save_json(self.path, state)
        self.assertNotEqual(self.service.authenticate(prepared['token'], self.owner)['identity_revision'],
                            first['identity_revision'])
        members = self.service.list_members(self.owner, self.group['id'])
        self.assertEqual(members[0]['id'], first['device_id'])
        self.assertNotIn('credential_digest', members[0])
        self.assert_error('not_found', lambda: self.service.list_members('other', self.group['id']))

    def test_identity_exposes_only_current_authorized_group_label_without_changing_scope(self):
        prepared = self.prepare()
        identity = self.join(prepared)['identity']
        expected = {'status': 'active', 'identity': identity,
                    'group': {'id': self.group['id'], 'name': 'Living room'}}
        self.assertEqual(self.service.identity(prepared['token'], self.owner), expected)
        self.service.update_group(self.owner, self.group['id'], {'name': 'New label'})
        expected['group']['name'] = 'New label'
        self.assertEqual(self.service.identity(prepared['token'], self.owner), expected)
        self.service.update_group(self.owner, self.group['id'], {'enabled': False})
        error = self.assert_error('device_authorization_revoked',
            lambda: self.service.identity(prepared['token'], self.owner))
        self.assertNotIn('New label', str(error))

    def test_leave_revokes_only_self_persists_and_allows_rejoin_with_a_new_cookie(self):
        self.invitation = self.service.create_invite(self.owner, self.group['id'], 3)
        first, second, pending = self.prepare('one'), self.prepare('two'), self.prepare('pending')
        first_identity, second_identity = self.join(first)['identity'], self.join(second)['identity']
        before = self.service._load()
        self.service.leave(first['token'], self.owner)
        restarted = access_service(self.path, lambda: self.now)
        after = restarted._load()
        self.assertEqual(after['devices'], {key: value for key, value in before['devices'].items()
                                           if key != first_identity['device_id']})
        self.assertEqual(after['attempts'], {key: value for key, value in before['attempts'].items()
                                           if key != first['attempt_id']})
        self.assertEqual(after['groups'], before['groups'])
        self.assertEqual(after['invites'], before['invites'])
        self.assertEqual(restarted.authenticate(second['token'], self.owner), second_identity)
        self.assertEqual(restarted.identity(pending['token'], self.owner)['status'], 'pending')
        self.assert_error('device_authentication_required', lambda: restarted.authenticate(first['token'], self.owner))
        self.assert_error('join_attempt_conflict', lambda: self.join(first))
        # Simulate a lost Set-Cookie response: prepare replaces the stale cookie.
        fresh = restarted.prepare(self.owner, 'one', first['token'])
        self.assertNotEqual(fresh['token'], first['token'])
        joined = self.join(fresh)['identity']
        self.assertNotEqual(joined['device_id'], first_identity['device_id'])
        self.assertEqual(self.service.get_invite(self.owner, self.group['id'])['used'], 3)

    def test_leave_requires_own_existing_credential_but_allows_disabled_groups(self):
        prepared = self.prepare()
        before = self.path.read_bytes()
        for token in (None, 'unknown', prepared['token']):
            self.assert_error('device_authentication_required', lambda: self.service.leave(token, self.owner))
        self.assertEqual(before, self.path.read_bytes())
        identity = self.join(prepared)['identity']
        before = self.path.read_bytes()
        self.assert_error('device_authorization_revoked', lambda: self.service.leave(prepared['token'], 'other'))
        self.assertEqual(before, self.path.read_bytes())
        self.service.update_group(self.owner, self.group['id'], {'enabled': False})
        self.service.leave(prepared['token'], self.owner)
        self.assertNotIn(identity['device_id'], self.service._load()['devices'])
        self.assert_error('device_authentication_required', lambda: self.service.leave(prepared['token'], self.owner))

    def test_leave_write_failure_retains_credential_and_attempt_for_retry(self):
        prepared = self.prepare()
        identity = self.join(prepared)['identity']
        before = self.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.service.leave(prepared['token'], self.owner)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.service.authenticate(prepared['token'], self.owner), identity)
        self.assertFalse(self.join(prepared)['created'])
        self.service.leave(prepared['token'], self.owner)
        self.assert_error('device_authentication_required', lambda: self.service.authenticate(prepared['token'], self.owner))

    def test_full_installation_can_issue_a_new_code_and_rejoin_after_leaving(self):
        prepared = self.prepare()
        identity = self.join(prepared)['identity']
        state = self.service._load()
        for index in range(99):
            device_id = 'existing-' + str(index)
            state['devices'][device_id] = dict(state['devices'][identity['device_id']], id=device_id,
                credential_digest=hashlib.sha256(device_id.encode()).hexdigest())
        save_json(self.path, state)
        self.assert_error('device_limit', lambda: self.service.create_invite(self.owner, self.group['id']))
        invitation_before = deepcopy(state['invites'])
        self.service.leave(prepared['token'], self.owner)
        self.assertEqual(len(self.service._load()['devices']), 99)
        self.assertEqual(self.service._load()['invites'], invitation_before)
        self.invitation = self.service.create_invite(self.owner, self.group['id'])
        new_attempt = self.service.prepare(self.owner, 'returning', prepared['token'])
        joined = self.join(new_attempt)['identity']
        self.assertEqual(len(self.service._load()['devices']), 100)
        self.assertNotEqual(identity['device_id'], joined['device_id'])
        self.assert_error('device_authentication_required', lambda: self.service.authenticate(prepared['token'], self.owner))

    def test_prepare_rate_limits_shared_instances_and_bounded_pending_storage(self):
        for _ in range(SOURCE_LIMIT):
            self.prepare('source')
        error = self.assert_error('rate_limited',
            lambda: access_service(self.path, lambda: self.now).prepare(self.owner, 'source'))
        self.assertEqual(error.retry_after, 60)
        for index in range(GLOBAL_LIMIT - SOURCE_LIMIT):
            self.prepare('source-' + str(index))
        self.assert_error('rate_limited', lambda: self.prepare('another-source'))
        self.now += 61
        with patch('webclock.services.device_access_service.PENDING_ATTEMPT_LIMIT', GLOBAL_LIMIT):
            self.assert_error('rate_limited', lambda: self.prepare('another-source'))
            self.now += 600
            self.assertTrue(self.prepare('another-source')['created'])
        self.assertEqual(len(load_json(self.path, {})['attempts']), 1)

    def test_malformed_identity_state_is_rejected_instead_of_silently_authorized(self):
        prepared = self.prepare()
        identity = self.join(prepared)['identity']
        state = load_json(self.path, {})
        del state['devices'][identity['device_id']]['credential_generation']
        save_json(self.path, state)
        self.assert_error('access_not_ready', lambda: self.service.authenticate(prepared['token'], self.owner))


class EnrollmentTransportTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.auth = AuthService(self.root / 'auth.json')
        self.auth.setup('owner', 'long-test-password', enable_managed_test=True)
        self.service = access_service(self.root / 'device-access.json')
        self.devices = DeviceService(self.root / 'devices.json')
        self.group = self.service.create_group(self.auth.owner_id(), {'name': 'Living room'})
        self.invitation = self.service.create_invite(self.auth.owner_id(), self.group['id'], 5)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY=self.auth.session_secret())
        register_access_control(self.app, lambda: self.auth)
        register_csrf(self.app)
        register_auth(self.app, lambda: self.auth)
        self.display_callback = self.display_payload
        self.app.register_blueprint(managed_device_api(
            lambda: self.service, lambda: self.devices, lambda: self.auth,
            lambda identity: self.display_callback(identity), lambda identity: self.display_callback(identity)))
        @self.app.route('/api/private', methods=['GET', 'POST'])
        def private():
            return jsonify(private=True)
        self.client = self.app.test_client()
        self.base = 'https://localhost'
        self.csrf = self.call('/api/csrf').json['csrf_token']

    def display_payload(self, identity):
        response = self.app.response_class(status=304) if request.if_none_match.contains('test-revision') else jsonify(
            schema_version=3, identity=identity, settings={'brightness': 50})
        response.set_etag('test-revision')
        return response

    def call(self, path, method='GET', **kwargs):
        return self.client.open(path, method=method, base_url=self.base, **kwargs)

    def prepare(self):
        return self.call('/api/v2/device/join/prepare', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})

    def join(self, attempt=None):
        attempt = attempt or self.prepare().json['attempt_id']
        return self.call('/api/v2/device/join', 'POST', json={'attempt_id': attempt, 'code': self.invitation['code']},
                         headers={'X-CSRF-Token': self.csrf})

    def cookie(self):
        return self.client.get_cookie(DEVICE_COOKIE, path='/api/v2/device')

    def test_wire_cookie_roundtrip_and_lost_response_retry_do_not_rotate_credential(self):
        prepared = self.prepare()
        self.assertEqual(prepared.status_code, 201)
        self.assertEqual(set(prepared.json), {'attempt_id', 'expires_at'})
        self.assertIsInstance(prepared.json['expires_at'], int)
        cookie = self.cookie()
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, 'Lax')
        self.assertEqual(self.call('/api/v2/device/identity').json,
                         dict(prepared.json, status='pending'))
        reused = self.prepare()
        self.assertEqual(reused.status_code, 200)
        self.assertEqual(reused.json, prepared.json)
        self.assertNotIn('Set-Cookie', reused.headers)
        joined = self.join(prepared.json['attempt_id'])
        self.assertEqual(joined.status_code, 201)
        self.assertEqual(set(joined.json), {'schema_version', 'identity', 'server_timestamp'})
        self.assertEqual(set(joined.json['identity']), IDENTITY_FIELDS)
        self.assertNotIn('Set-Cookie', joined.headers)
        self.assertEqual(self.cookie().value, cookie.value)
        self.assertEqual(self.call('/api/v2/device/identity').json,
                         {'status': 'active', 'identity': joined.json['identity'],
                          'group': {'id': self.group['id'], 'name': 'Living room'}})
        retry = self.join(prepared.json['attempt_id'])
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json['identity'], joined.json['identity'])
        self.assertNotIn('Set-Cookie', retry.headers)

    def test_cookie_rejection_or_other_tab_attempt_cannot_join_or_consume(self):
        first = self.prepare().json
        self.client.delete_cookie(DEVICE_COOKIE, path='/api/v2/device')
        self.assertEqual(self.call('/api/v2/device/identity').status_code, 401)
        self.assertEqual(self.join(first['attempt_id']).status_code, 401)
        second = self.prepare().json
        mismatch = self.join(first['attempt_id'])
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json['code'], 'join_attempt_conflict')
        self.assertEqual(self.service.get_invite(self.auth.owner_id(), self.group['id'])['used'], 0)
        self.assertEqual(self.join(second['attempt_id']).status_code, 201)

    def test_cookie_writes_require_csrf_and_origin_even_with_bearer_shaped_headers(self):
        before = self.service.path.read_bytes()
        self.assertEqual(self.call('/api/v2/device/join/prepare', 'POST', json={}).status_code, 403)
        self.assertEqual(self.call('/api/v2/device/join/prepare', 'POST', json={},
            headers={'X-CSRF-Token': self.csrf, 'Origin': 'https://elsewhere.invalid'}).status_code, 403)
        self.assertEqual(before, self.service.path.read_bytes())
        pending = self.prepare().json
        token = self.cookie().value
        self.assertEqual(self.call('/api/v2/device/status', 'POST', json={},
                                  headers={'Authorization': 'Bearer ' + token}).status_code, 401)
        self.assertEqual(self.call('/api/v2/device/join', 'POST',
            json={'attempt_id': pending['attempt_id'], 'code': self.invitation['code']}).status_code, 403)
        self.join(pending['attempt_id'])
        self.assertEqual(self.call('/api/v2/device/status', 'POST', json={}).status_code, 403)
        self.assertEqual(self.call('/api/v2/device/status', 'POST', json={},
                                  headers={'Authorization': 'Bearer forged'}).status_code, 401)
        response = self.call('/api/v2/device/status', 'POST', json={},
                             headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.call('/api/v2/device/display', headers={
            'Authorization': 'Bearer ' + token, 'Origin': 'https://elsewhere.invalid'}).status_code, 403)

    def test_admin_session_device_cookie_and_shared_token_never_substitute_for_each_other(self):
        login = self.call('/login', 'POST', json={'username': 'owner', 'password': 'long-test-password'},
                          headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(login.status_code, 200)
        self.csrf = login.json['csrf_token']
        self.assertEqual(self.call('/api/private').status_code, 200)
        self.assertEqual(self.call('/api/v2/device/display').status_code, 401)
        self.assertEqual(self.call('/api/v2/device/display', headers={'Authorization': 'Bearer shared-token'}).status_code, 401)
        self.join()
        self.assertEqual(self.call('/api/v2/device/display').status_code, 200)
        self.call('/logout', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(self.call('/api/private').status_code, 401)
        self.assertEqual(self.call('/api/v2/device/display').status_code, 200)
        self.auth.reset_password('a different long password')
        self.assertEqual(self.call('/api/v2/device/display').status_code, 200)
        token = self.cookie().value
        self.assertEqual(self.call('/api/private', headers={'Authorization': 'Bearer ' + token}).status_code, 401)

    def test_status_reconstructs_observation_ignores_foreign_acks_and_hides_admin_name(self):
        identity = self.join().json['identity']
        self.assertFalse(self.devices.path.exists())
        for key in ('id', 'owner_id', 'group_id', 'admin_name'):
            response = self.call('/api/v2/device/status', 'POST', json={key: 'spoof'},
                                 headers={'X-CSRF-Token': self.csrf})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(self.devices.path.exists())
        response = self.call('/api/v2/device/status', 'POST',
            json={'name': 'Browser', 'device_type': 'browser', 'capabilities': {'audio': False},
                  'config_revision': 'revision'}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['device']['id'], identity['device_id'])
        self.devices.rename(identity['device_id'], {'name': 'PRIVATE administrator label'})
        self.devices.register({'id': 'legacy-other', 'name': 'Other'})
        foreign = self.devices.command('legacy-other', 'sync')
        own = self.devices.command(identity['device_id'], 'sync')
        response = self.call('/api/v2/device/status', 'POST', json={'acknowledged_commands': [foreign['id']]},
                             headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.json['commands'], [own])
        self.assertNotIn('admin_name', response.json['device'])
        self.assertNotIn('PRIVATE', response.text)
        self.assertEqual(next(row for row in self.devices.list() if row['id'] == 'legacy-other')['commands'], [foreign])
        acknowledged = self.call('/api/v2/device/status', 'POST', json={'acknowledged_commands': [own['id']]},
                                 headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(acknowledged.json['commands'], [])

    def test_observation_write_failure_does_not_undo_join_or_prevent_later_reconstruction(self):
        identity = self.join().json['identity']
        before = self.service.path.read_bytes()
        with patch('webclock.services.device_service.save_json', side_effect=OSError('PRIVATE path')):
            response = self.call('/api/v2/device/status', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['code'], 'storage_failure')
        self.assertNotIn('PRIVATE', response.text)
        self.assertEqual(self.service.path.read_bytes(), before)
        self.assertEqual(self.call('/api/v2/device/display').status_code, 200)
        response = self.call('/api/v2/device/status', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['device']['id'], identity['device_id'])

    def test_revoke_before_or_during_callback_rejects_old_etag_and_private_body(self):
        self.join()
        self.assertEqual(self.call('/api/v2/device/display', headers={'If-None-Match': '"test-revision"'}).status_code, 304)
        def disable_during_render(identity):
            self.service.update_group(self.auth.owner_id(), self.group['id'], {'enabled': False})
            return self.display_payload(identity)
        self.display_callback = disable_during_render
        response = self.call('/api/v2/device/display', headers={'If-None-Match': '"test-revision"'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json['code'], 'device_authorization_revoked')
        self.assertNotIn('ETag', response.headers)
        self.assertEqual(self.call('/api/v2/device/browser-alarms').status_code, 403)

    def test_assignment_change_during_callback_cannot_return_previous_scope(self):
        joined = self.join().json['identity']
        other = self.service.create_group(self.auth.owner_id(), {'name': 'Bedroom'})
        def move_during_render(identity):
            state = load_json(self.service.path, {})
            state['devices'][joined['device_id']]['group_id'] = other['id']
            state['devices'][joined['device_id']]['assignment_revision'] += 1
            save_json(self.service.path, state)
            return jsonify(private='OLD SCOPE', identity=identity)
        self.display_callback = move_during_render
        response = self.call('/api/v2/device/display')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('OLD SCOPE', response.text)

    def test_storage_failure_and_corruption_use_sanitized_json_and_no_cors(self):
        before = self.service.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('PRIVATE path')):
            response = self.prepare()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['code'], 'storage_failure')
        self.assertEqual(before, self.service.path.read_bytes())
        self.join()
        self.service.path.write_text('{broken')
        response = self.call('/api/v2/device/display')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['code'], 'access_not_ready')
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_managed_http_is_rejected_before_creating_an_attempt(self):
        response = self.client.post('/api/v2/device/join/prepare', json={},
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json['code'], 'https_required')
        self.assertEqual(load_json(self.service.path, {})['attempts'], {})

    def test_leave_clears_scoped_cookie_and_denies_old_token_without_affecting_peer(self):
        joined = self.join().json['identity']
        token = self.cookie().value
        self.devices.register({'id': joined['device_id'], 'name': 'Observed device'})
        observations = self.devices.path.read_bytes()
        peer = self.service.prepare(self.auth.owner_id(), 'peer')
        peer_identity = self.service.join(self.auth.owner_id(), peer['token'], peer['attempt_id'],
                                          self.invitation['code'], 'peer')['identity']
        response = self.call('/api/v2/device/leave', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'left'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIsNone(self.cookie())
        self.assertEqual(self.devices.path.read_bytes(), observations)
        deleted = response.headers['Set-Cookie']
        for marker in ('webclock_device=', 'Max-Age=0', 'Path=/api/v2/device', 'Secure', 'HttpOnly', 'SameSite=Lax'):
            self.assertIn(marker, deleted)
        self.assertNotIn('Domain=', deleted)
        self.assertEqual(self.service.authenticate(peer['token'], self.auth.owner_id()), peer_identity)
        for path in ('identity', 'display', 'browser-alarms'):
            rejected = self.call('/api/v2/device/' + path, headers={
                'Authorization': 'Bearer ' + token, 'If-None-Match': '"test-revision"'})
            self.assertEqual(rejected.status_code, 401, path)
            self.assertNotIn('ETag', rejected.headers)
        self.assertEqual(self.call('/api/v2/device/status', 'POST', json={},
            headers={'Authorization': 'Bearer ' + token}).status_code, 401)
        rejoined = self.join()
        self.assertEqual(rejoined.status_code, 201)
        self.assertNotEqual(rejoined.json['identity']['device_id'], joined['device_id'])
        self.assertNotEqual(self.cookie().value, token)

    def test_leave_requires_cookie_csrf_origin_and_empty_body_before_any_write(self):
        self.join()
        token = self.cookie().value
        before = self.service.path.read_bytes()
        cases = [({}, {}, 403),
                 ({}, {'X-CSRF-Token': self.csrf, 'Origin': 'https://elsewhere.invalid'}, 403),
                 ({}, {'X-CSRF-Token': self.csrf, 'Authorization': 'Bearer ' + token}, 401),
                 ({'id': 'other-device'}, {'X-CSRF-Token': self.csrf}, 400),
                 ({'group_id': 'other-group'}, {'X-CSRF-Token': self.csrf}, 400),
                 ([], {'X-CSRF-Token': self.csrf}, 400)]
        for value, headers, status in cases:
            with self.subTest(body=value, status=status):
                response = self.call('/api/v2/device/leave', 'POST', json=value, headers=headers)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('Set-Cookie', response.headers)
                self.assertEqual(self.service.path.read_bytes(), before)
        self.assertEqual(self.call('/api/v2/device/leave').status_code, 405)
        self.client.delete_cookie(DEVICE_COOKIE, path='/api/v2/device')
        response = self.call('/api/v2/device/leave', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertEqual(self.service.path.read_bytes(), before)

    def test_leave_disabled_group_succeeds_and_failed_storage_does_not_clear_cookie(self):
        self.join()
        token = self.cookie().value
        self.service.update_group(self.auth.owner_id(), self.group['id'], {'enabled': False})
        before = self.service.path.read_bytes()
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('PRIVATE path')):
            response = self.call('/api/v2/device/leave', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['code'], 'storage_failure')
        self.assertNotIn('PRIVATE', response.text)
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertEqual(self.cookie().value, token)
        self.assertEqual(self.service.path.read_bytes(), before)
        response = self.call('/api/v2/device/leave', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.cookie())

    def test_leave_authenticates_before_csrf_and_rechecks_inside_transaction(self):
        for token in (None, 'unknown'):
            if token:
                self.client.set_cookie(DEVICE_COOKIE, token, path='/api/v2/device')
            response = self.call('/api/v2/device/leave', 'POST', json={})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json['code'], 'device_authentication_required')
        self.prepare()
        self.assertEqual(self.call('/api/v2/device/leave', 'POST', json={}).status_code, 401)
        self.join()
        self.assertEqual(self.call('/api/v2/device/leave', 'POST', json={}).json['code'], 'csrf_failed')
        authorize = self.service.authorize_leave
        def removed_after_guard(token, owner):
            authorize(token, owner)
            self.service.leave(token, owner)
        with patch.object(self.service, 'authorize_leave', side_effect=removed_after_guard):
            response = self.call('/api/v2/device/leave', 'POST', json={}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_leave_during_display_cannot_return_previously_authorized_body_or_304(self):
        self.join()
        token = self.cookie().value
        def leave_during_render(identity):
            self.service.leave(token, self.auth.owner_id())
            return self.display_payload(identity)
        self.display_callback = leave_during_render
        response = self.call('/api/v2/device/display', headers={'If-None-Match': '"test-revision"'})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('ETag', response.headers)
        self.assertNotIn('settings', response.json)


if __name__ == '__main__':
    unittest.main()
