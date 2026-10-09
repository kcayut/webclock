import copy
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from webclock.services import portable_backup as backup
from webclock.services.auth_service import AuthService
from webclock.services.control_access_service import ControlAccessService
from webclock.services.device_access_service import AccessError, DeviceAccessService
from webclock.services.display_settings import DEFAULT_NIGHT, validate_settings
from webclock.services.storage import load_json, save_json


PASSWORD = 'portable backup password'


def devices(state, auth):
    return DeviceAccessService(state / 'device-access.json', auth.invite_secret, validate_settings,
                               lambda: {'night': dict(DEFAULT_NIGHT)}, lambda: {})


class PortableBackupTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.source = self.root / 'source'
        self.source_notes = self.root / 'external-source-notes.json'
        self.auth = AuthService(self.source / 'auth.json')
        self.auth.setup('admin', 'test account password', enable_managed=True)
        self.owner = self.auth.owner_id()
        self.member = self.auth.create_account('member', 'member account password')['owner_id']
        save_json(self.source_notes, [{'id': 7, 'text': 'Primary owner reminder'}])
        save_json(self.source / 'owners' / self.member / 'manual_notes.json',
                  [{'id': 3, 'text': 'Private member reminder'}])
        save_json(self.source / 'settings.json', {'brightness': 0, 'language': 'en'})
        save_json(self.source / 'owners' / self.member / 'settings.json', {'brightness': 71})
        self.calendar = {'sources': [{'id': 'work', 'name': 'Work', 'provider': 'ics',
            'url': 'https://example.invalid/private-subscription-token', 'display_enabled': True}],
            'local_display_enabled': False}
        self.access = devices(self.source, self.auth)
        self.group = self.access.create_group(self.owner, {'name': 'Desk'})['id']
        invitation = self.access.create_invite(self.owner, self.group)
        prepared = self.access.prepare(self.owner, 'test-local')
        self.token = prepared['token']
        self.identity = self.access.join(self.owner, self.token, prepared['attempt_id'],
                                        invitation['code'], 'test-local')['identity']
        self.control = ControlAccessService(self.source / 'control-clients.json', self.auth)
        self.client = self.control.create(self.owner, 'managed',
                                          {'name': 'HA', 'scopes': ['schedules:read']})
        self.payload = backup.capture(self.source, self.source_notes, calendar=self.calendar)
        self.target = self.root / 'ha-data'
        self.target.mkdir()
        self.notes = self.root / 'external-target-notes.json'
        save_json(self.target / 'options.json', {'language': 'zh-TW', 'display_port': 5000})

    def test_encryption_authentication_and_validation(self):
        raw = backup.encrypt(self.payload, PASSWORD)
        self.assertNotIn(b'private-subscription-token', raw)
        self.assertNotIn(b'password_hash', raw)
        self.assertEqual(backup.decrypt(raw, PASSWORD), self.payload)
        self.assertNotEqual(raw, backup.encrypt(self.payload, PASSWORD))
        for invalid, password in ((raw, 'wrong password here'), (raw[:-1], PASSWORD),
                (raw[:-1] + bytes([raw[-1] ^ 1]), PASSWORD),
                (raw[:len(backup.MAGIC)] + bytes([raw[len(backup.MAGIC)] ^ 1])
                 + raw[len(backup.MAGIC) + 1:], PASSWORD)):
            with self.subTest(password=password), self.assertRaises(backup.BackupError):
                backup.decrypt(invalid, password)
        with self.assertRaises(backup.BackupError):
            backup.encrypt(self.payload, 'short')

    def test_complete_migration_preserves_credentials_and_ha_options(self):
        auth_before = copy.deepcopy(self.payload['files']['auth.json'])
        result = backup.restore(self.payload, self.target, self.notes)
        self.assertTrue(result['preserve_devices'])
        self.assertEqual(result['program_credentials_revoked'], 0)
        self.assertEqual((result['accounts'], result['calendars'], result['notes'],
                          result['groups'], result['devices']), (2, 1, 2, 1, 1))
        self.assertEqual(load_json(self.notes, []), load_json(self.source_notes, []))
        self.assertEqual(load_json(self.target / 'calendar.json', {}), self.calendar)
        self.assertEqual(load_json(self.target / 'options.json', {}),
                         {'language': 'zh-TW', 'display_port': 5000})
        self.assertEqual(load_json(self.target / 'owners' / self.member / 'manual_notes.json', []),
                         [{'id': 3, 'text': 'Private member reminder'}])
        restored_auth = AuthService(self.target / 'auth.json')
        self.assertEqual(devices(self.target, restored_auth).authenticate(self.token, self.owner), self.identity)
        self.assertEqual(ControlAccessService(self.target / 'control-clients.json', restored_auth).authenticate(
            self.client['token'], self.owner, 'managed')['id'], self.client['id'])
        state = restored_auth.state()
        self.assertNotEqual(state['session_secret'], auth_before['session_secret'])
        self.assertEqual(state['sessions'], {})
        self.assertEqual(state['invite_secret'], auth_before['invite_secret'])
        restored_devices = load_json(self.target / 'device-access.json', {})
        self.assertEqual(restored_devices['attempts'], {})
        self.assertTrue(all(row['closed'] for row in restored_devices['invites'].values()))
        self.assertFalse(backup.pending(self.target))
        self.assertEqual(stat.S_IMODE((self.target / backup.PREVIOUS_DIR).stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.target / 'auth.json').stat().st_mode), 0o600)
        self.assertEqual(backup.capture(self.source, self.source_notes, self.calendar)['files'], self.payload['files'])

    def test_existing_restore_revokes_credentials_and_keeps_registry(self):
        backup.restore(self.payload, self.target, self.notes)
        result = backup.restore(self.payload, self.target, self.notes)
        self.assertFalse(result['preserve_devices'])
        self.assertEqual(result['program_credentials_revoked'], 1)
        auth = AuthService(self.target / 'auth.json')
        with self.assertRaises(AccessError):
            devices(self.target, auth).authenticate(self.token, self.owner)
        control = ControlAccessService(self.target / 'control-clients.json', auth)
        self.assertEqual(len(control.list(self.owner)), 1)
        self.assertIsNone(control.authenticate(self.client['token'], self.owner, 'managed'))

    def test_invalid_paths_authorization_and_owner_data_are_rejected(self):
        for name in ('../outside.json', '/tmp/outside.json', 'owners/../auth.json',
                     'owners/unknown/calendar.json', 'options.json', '.env',
                     'owners/' + self.owner + '/calendar.json'):
            damaged = copy.deepcopy(self.payload)
            damaged['files'][name] = {}
            with self.subTest(name=name), self.assertRaises(backup.BackupError):
                backup.restore(damaged, self.target, self.notes)
        damaged = copy.deepcopy(self.payload)
        damaged['files']['auth.json']['accounts'][self.owner]['password_hash'] = 'invalid'
        with self.assertRaises(backup.BackupError):
            backup.restore(damaged, self.target, self.notes)
        damaged = copy.deepcopy(self.payload)
        damaged['files']['devices.json'] = {'desk': 'invalid observation'}
        with self.assertRaises(backup.BackupError):
            backup.restore(damaged, self.target, self.notes)
        self.assertFalse((self.target / 'auth.json').exists())
        self.assertFalse(self.notes.exists())
        self.assertFalse(backup.pending(self.target))

    def test_protected_installation_cannot_restore_anonymous_state(self):
        backup.restore(self.payload, self.target, self.notes)
        empty = self.root / 'empty'
        anonymous = backup.capture(empty, empty / 'manual_notes.json')
        with self.assertRaisesRegex(backup.BackupError, 'protected_restore_required'):
            backup.restore(anonymous, self.target, self.notes)
        self.assertEqual(AuthService(self.target / 'auth.json').mode(), 'managed')

    def test_failed_restore_rolls_back_all_files_and_external_notes(self):
        save_json(self.notes, [{'id': 1, 'text': 'Destination data'}])
        save_json(self.target / 'settings.json', {'brightness': 27})
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in (self.notes, self.target / 'settings.json', self.target / 'options.json')}
        actual = backup._write
        failed = False

        def write(path, raw):
            nonlocal failed
            if path == self.target / 'device-access.json' and not failed:
                failed = True
                raise OSError('injected disk failure')
            return actual(path, raw)

        with patch.object(backup, '_write', write), self.assertRaises(OSError):
            backup.restore(self.payload, self.target, self.notes)
        for name, raw in before.items():
            self.assertEqual((self.root / name).read_bytes(), raw)
        self.assertFalse((self.target / 'auth.json').exists())
        self.assertFalse(backup.pending(self.target))

    def test_interrupted_restore_stays_closed_until_recovery(self):
        save_json(self.notes, [{'id': 1, 'text': 'Keep me'}])
        old_notes = self.notes.read_bytes()
        actual = backup._write

        def write(path, raw):
            if path == self.target / 'device-access.json':
                raise OSError('injected ongoing disk failure')
            return actual(path, raw)

        with patch.object(backup, '_write', write), patch.object(backup, '_remove', side_effect=OSError('disk failure')):
            with self.assertRaises(backup.RecoveryError):
                backup.restore(self.payload, self.target, self.notes)
        self.assertTrue(backup.pending(self.target))
        with self.assertRaises(backup.RecoveryError):
            backup.capture(self.target, self.notes)
        self.assertTrue(backup.recover(self.target, self.notes))
        self.assertFalse(backup.pending(self.target))
        self.assertEqual(self.notes.read_bytes(), old_notes)
        self.assertFalse((self.target / 'auth.json').exists())

    def test_symlinks_and_malformed_json_are_rejected(self):
        outside = self.root / 'outside'
        outside.write_text('untouched')
        (self.target / 'auth.json').symlink_to(outside)
        with self.assertRaises(backup.BackupError):
            backup.restore(self.payload, self.target, self.notes)
        self.assertEqual(outside.read_text(), 'untouched')
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(backup.BackupError):
                backup._parse(raw)

    def test_custom_notes_and_validation_callback(self):
        notes = self.target / 'custom' / 'reminders.json'
        called = []
        backup.restore(self.payload, self.target, notes, validate_content=lambda files: called.append(files))
        self.assertTrue(called)
        self.assertEqual(load_json(notes, []), load_json(self.source_notes, []))
        self.assertEqual(backup.capture(self.target, notes)['files']['manual_notes.json'],
                         load_json(self.source_notes, []))

    def test_legacy_calendar_is_not_a_fresh_installation(self):
        result = backup.preview(self.payload, self.target, self.notes,
                                target_calendar={'url': 'https://example.invalid/old-private'})
        self.assertFalse(result['preserve_devices'])
        empty_calendar = copy.deepcopy(self.payload)
        del empty_calendar['files']['calendar.json']
        backup.restore(empty_calendar, self.target, self.notes,
                       target_calendar={'url': 'https://example.invalid/old-private'})
        self.assertEqual(load_json(self.target / 'calendar.json', {}),
                         {'sources': [], 'local_display_enabled': True})

    def test_previous_snapshot_symlink_is_rejected_before_any_change(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.target / backup.PREVIOUS_DIR).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(backup.BackupError):
            backup.restore(self.payload, self.target, self.notes)
        self.assertFalse((self.target / 'auth.json').exists())
        self.assertFalse(backup.pending(self.target))

    def test_commit_and_cleanup_fsync_failures_report_applied_data(self):
        for boundary in ('commit', 'cleanup'):
            target = self.root / boundary
            target.mkdir()
            notes = target / 'manual_notes.json'
            actual = backup._sync
            failed = False

            def sync(directory):
                nonlocal failed
                marker = target / backup.PENDING_DIR
                if boundary == 'commit':
                    match = directory == marker and load_json(marker / 'journal.json', {}).get('committed')
                else:
                    match = directory == target and (target / backup.PREVIOUS_DIR).exists() and not marker.exists()
                if match and not failed:
                    failed = True
                    raise OSError('injected fsync failure after replace')
                return actual(directory)

            with self.subTest(boundary=boundary), patch.object(backup, '_sync', sync):
                result = backup.restore(self.payload, target, notes)
            self.assertTrue(failed)
            self.assertTrue(result['preserve_devices'])
            self.assertEqual(AuthService(target / 'auth.json').mode(), 'managed')
            self.assertEqual(load_json(notes, []), load_json(self.source_notes, []))
            self.assertFalse(backup.pending(target))

    def test_empty_old_owner_directories_do_not_break_future_backups(self):
        for number in range(100):
            (self.target / 'owners' / ('old-' + str(number))).mkdir(parents=True)
        unknown = self.target / 'owners' / 'old-0' / 'platform-data.txt'
        unknown.write_text('retain unrelated data')
        backup.restore(self.payload, self.target, self.notes)
        result = backup.capture(self.target, self.notes)
        self.assertEqual(len(result['files']['auth.json']['accounts']), 2)
        self.assertEqual(unknown.read_text(), 'retain unrelated data')


if __name__ == '__main__':
    unittest.main()
