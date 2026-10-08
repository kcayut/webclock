"""A single authorization timestamp closes invitations and pending enrollment."""
from pathlib import Path
import tempfile
import unittest

from webclock.services.device_access_service import AccessError, DeviceAccessService
from webclock.services.display_settings import validate_settings, DEFAULT_NIGHT


class DeviceModeScopeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 1000.0
        self.scope = 0
        self.path = Path(folder.name) / 'device-access.json'
        self.service = DeviceAccessService(self.path, 'a' * 43, validate_settings,
            lambda: {'mode': 'normal', 'brightness': 100, 'timezone_offset': 8,
                     'language': 'zh-TW', 'time_format': '24h', 'night': DEFAULT_NIGHT},
            lambda: {'calendar_source_ids': [], 'manual_note_ids': [], 'schedules': []},
            clock=lambda: self.now, scope_started=lambda: self.scope)
        self.owner = 'owner'
        self.group = self.service.create_group(self.owner, {'name': 'Clock'})

    def test_transition_closes_old_invites_and_pending_credentials_but_keeps_joined_identity(self):
        invitation = self.service.create_invite(self.owner, self.group['id'])
        joined_attempt = self.service.prepare(self.owner, 'joined')
        joined = self.service.join(self.owner, joined_attempt['token'], joined_attempt['attempt_id'],
                                   invitation['code'], 'joined')['identity']
        pending = self.service.prepare(self.owner, 'pending')
        before = self.path.read_bytes()
        self.scope = self.now  # Exact boundary must also invalidate prior enrollment.
        self.now += 0.01
        self.assertEqual(self.service.get_invite(self.owner, self.group['id'])['status'], 'closed')
        with self.assertRaises(AccessError) as error:
            self.service.check_invite(invitation['code'], 'old-code')
        self.assertEqual(error.exception.code, 'invalid_invitation')
        with self.assertRaises(AccessError):
            self.service.identity(pending['token'], self.owner)
        fresh_invite = self.service.create_invite(self.owner, self.group['id'])
        self.assertEqual(fresh_invite['status'], 'active')
        with self.assertRaises(AccessError) as error:
            self.service.join(self.owner, pending['token'], pending['attempt_id'], fresh_invite['code'], 'old-attempt')
        self.assertEqual(error.exception.code, 'join_attempt_conflict')
        self.assertEqual(self.service.authenticate(joined_attempt['token'], self.owner), joined)
        replacement = self.service.prepare(self.owner, 'replacement', pending['token'])
        self.assertTrue(replacement['created'])
        self.assertNotEqual(replacement['token'], pending['token'])
        self.assertNotEqual(replacement['attempt_id'], pending['attempt_id'])
        self.assertNotIn(pending['attempt_id'], self.service._load()['attempts'])
        identity = self.service.join(self.owner, replacement['token'], replacement['attempt_id'],
                                     fresh_invite['code'], 'new-attempt')['identity']
        self.assertEqual(identity['group_id'], self.group['id'])
        self.assertNotEqual(self.path.read_bytes(), before)

    def test_scope_change_is_read_only_until_new_enrollment_is_requested(self):
        invitation = self.service.create_invite(self.owner, self.group['id'])
        pending = self.service.prepare(self.owner, 'pending')
        before = self.path.read_bytes()
        self.scope = self.now
        self.assertEqual(self.service.get_invite(self.owner, self.group['id'])['status'], 'closed')
        with self.assertRaises(AccessError):
            self.service.identity(pending['token'], self.owner)
        with self.assertRaises(AccessError):
            self.service.join(self.owner, pending['token'], pending['attempt_id'], invitation['code'], 'join')
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
