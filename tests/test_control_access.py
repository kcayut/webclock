"""Program secrets, explicit grants, deployment boundaries and safe persistence."""
import copy
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from webclock.services.auth_service import AuthService, AuthStateError
from webclock.services.control_access_service import (
    ControlAccessError, ControlAccessService, ControlAccessStateError, MAX_EXPIRY_SECONDS,
)
from webclock.services.storage import load_json, save_json


class ControlAccessTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'control-access.json'
        self.auth = AuthService(self.path.with_name('auth.json'))
        self.owner = self.auth.ensure_initialized()['owner_id']
        self.timestamp = 1000.0
        self.service = ControlAccessService(self.path, lambda: self.auth, now=lambda: self.timestamp)
        self.payload = {'name': 'Bedroom clock', 'scopes': ['schedules:write', 'events:read'],
                        'group_ids': ['bedroom'], 'device_ids': ['clock-one'],
                        'calendar_source_ids': ['work'], 'schedule_ids': ['existing-alarm'],
                        'event_ids': ['existing-event'], 'expires_in': 120}

    def create(self, **changes):
        return self.service.create(self.owner, self.auth.mode(), dict(self.payload, **changes))

    def authenticate(self, token):
        return self.service.authenticate(token, self.owner, self.auth.mode())

    def test_secret_is_returned_once_and_grants_remain_explicit_across_restart(self):
        self.assertEqual(self.service.list(self.owner), [])
        self.assertFalse(self.path.exists())
        issued = self.create()
        contents = self.path.read_text()
        self.assertNotIn(issued['token'], contents)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        public = self.authenticate(issued['token'])
        self.assertEqual(public['scopes'], self.payload['scopes'])
        self.assertEqual(public['group_ids'], ['bedroom'])
        self.assertNotIn('digest', public)
        self.assertNotIn('token', public)
        self.assertEqual(self.service.list(self.owner), [public])
        self.service = ControlAccessService(self.path, AuthService(self.auth.path), now=lambda: self.timestamp)
        self.assertEqual(self.authenticate(issued['token']), public)
        public['scopes'].append('events:write')
        self.assertNotIn('events:write', self.authenticate(issued['token'])['scopes'])
        for token in (None, 123, [], issued['token'] + 'x', 'wcc_' + 'x' * 43):
            self.assertIsNone(self.authenticate(token))

    def test_expiry_and_individual_revocation(self):
        first = self.create()
        second = self.create(expires_in=180)
        self.service.revoke(self.owner, first['id'])
        self.assertIsNone(self.authenticate(first['token']))
        self.timestamp += 179
        self.assertIsNotNone(self.authenticate(second['token']))
        self.timestamp += 1
        self.assertIsNone(self.authenticate(second['token']))
        with self.assertRaises(ControlAccessError) as caught:
            self.service.revoke(self.owner, first['id'])
        self.assertEqual(caught.exception.status, 404)

    def test_mode_owner_and_restore_secret_bindings(self):
        issued = self.create()
        self.auth.setup('admin', 'long-enough-administrator-password', enable_managed=True)
        self.assertIsNone(self.authenticate(issued['token']))
        managed = self.create()
        self.assertIsNotNone(self.authenticate(managed['token']))
        with self.assertRaises(ControlAccessError):
            self.service.authenticate(managed['token'], self.owner, 'self')
        auth_state = self.auth.state()
        save_json(self.auth.path, dict(auth_state, invite_secret=secrets.token_urlsafe(32)))
        self.assertIsNone(self.authenticate(managed['token']))
        save_json(self.auth.path, dict(auth_state, owner_id='another-owner'))
        with self.assertRaises(AuthStateError):
            self.service.authenticate(managed['token'], 'another-owner', 'managed')
        save_json(self.auth.path, auth_state)
        other = self.auth.create_account('other', 'another account password')['owner_id']
        self.assertIsNone(self.service.authenticate(managed['token'], other, 'managed'))
        self.auth.switch_mode('self', other, admin_owner_id=self.owner,
                             password='long-enough-administrator-password',
                             expected_generation=self.auth.state()['generation'], confirm_shared=True)
        for operation in (lambda: self.service.list(self.owner),
                          lambda: self.service.revoke(self.owner, managed['id']),
                          lambda: self.create()):
            with self.assertRaises(ControlAccessError):
                operation()

    def test_invalid_payloads_never_write_credentials(self):
        self.create()
        before = self.path.read_bytes()
        for payload in (None, [], {}, dict(self.payload, name=''), dict(self.payload, name='bad\nname'),
                        dict(self.payload, owner_id='forged'), dict(self.payload, scopes=[]),
                        dict(self.payload, scopes=['admin']), dict(self.payload, scopes=[{}]),
                        dict(self.payload, scopes=['events:read', 'events:read']),
                        dict(self.payload, group_ids='all'), dict(self.payload, group_ids=['*']),
                        dict(self.payload, group_ids=[[]]), dict(self.payload, group_ids=['a', 'a']),
                        dict(self.payload, schedule_ids=[True]), dict(self.payload, event_ids=['x'] * 1001),
                        dict(self.payload, expires_in=True), dict(self.payload, expires_in=59),
                        dict(self.payload, expires_in=MAX_EXPIRY_SECONDS + 1)):
            with self.subTest(payload=payload), self.assertRaises(ControlAccessError):
                self.service.create(self.owner, 'self', payload)
            self.assertEqual(self.path.read_bytes(), before)

    def test_corruption_fails_closed_without_rewriting_or_accepting_known_token(self):
        issued = self.create()
        good = load_json(self.path, None)
        broken_grants = copy.deepcopy(good)
        broken_grants['clients'][issued['id']]['scopes'] = ['admin']
        broken_expiry = copy.deepcopy(good)
        broken_expiry['clients'][issued['id']]['expires_at'] = float('nan')
        leaked_secret = copy.deepcopy(good)
        leaked_secret['clients'][issued['id']]['token'] = issued['token']
        for state in (None, [], {}, dict(good, version=True), broken_grants, broken_expiry, leaked_secret):
            save_json(self.path, state)
            before = self.path.read_bytes()
            for operation in (lambda: self.authenticate(issued['token']),
                              lambda: self.service.list(self.owner), lambda: self.create(),
                              lambda: self.service.revoke(self.owner, issued['id'])):
                with self.subTest(state=state), self.assertRaises(ControlAccessStateError):
                    operation()
                self.assertEqual(self.path.read_bytes(), before)
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ControlAccessStateError):
            self.authenticate(issued['token'])
        save_json(self.path, good)
        self.auth.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(AuthStateError):
            self.authenticate(issued['token'])

    def test_failed_save_does_not_issue_new_credential_or_revoke_previous_one(self):
        issued = self.create()
        before = self.path.read_bytes()
        with patch('webclock.services.control_access_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.create()
            with self.assertRaises(OSError):
                self.service.revoke(self.owner, issued['id'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNotNone(self.authenticate(issued['token']))


if __name__ == '__main__':
    unittest.main()
