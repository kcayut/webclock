"""Per-device content follows current authorization and category inheritance."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webclock.services.device_access_service import (
    AccessError, DeviceAccessService, calendar_content_allows,
)
from webclock.services.storage import load_json, save_json


class DeviceContentTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'device-access.json'
        self.catalog = dict(calendar_source_ids=['cal1', 'cal2'], manual_note_ids=[1, 2],
                            schedules=[{'id': 'alarm1'}, {'id': 'linked', 'calendar_link':
                                       {'source_ids': ['cal2']}}])
        self.service = self.make_service()
        self.group = self.service.create_group('owner', dict(name='Bedroom', content={
            'calendar_source_ids': ['cal1'], 'manual_note_ids': [1], 'schedule_ids': ['alarm1']}))
        invite = self.service.create_invite('owner', self.group['id'])
        self.devices = []
        for name in ('bed', 'peer'):
            attempt = self.service.prepare('owner', name)
            identity = self.service.join('owner', attempt['token'], attempt['attempt_id'],
                                         invite['code'], name)['identity']
            self.devices.append((identity['device_id'], attempt['token']))
        self.device_id, self.token = self.devices[0]

    def make_service(self):
        return DeviceAccessService(self.path, 's' * 64, deepcopy,
                                   lambda: {'brightness': 80}, lambda: self.catalog)

    def content(self):
        return self.service.get_device_content('owner', self.device_id)

    def update(self, overrides, version=None):
        return self.service.update_device_content('owner', self.device_id, dict(
            content_overrides=overrides, revision=version or self.content()['revision']))

    def test_category_inheritance_empty_override_reset_and_peer_isolation(self):
        initial = self.content()
        self.assertEqual(initial['content_overrides'], {})
        self.assertEqual(set(initial['sources'].values()), {'group'})
        old_identity = self.service.authenticate(self.token, 'owner')
        updated = self.update({'manual_note_ids': [], 'schedule_ids': ['linked']})
        self.assertEqual(updated['effective_content']['calendar_source_ids'], ['cal1'])
        self.assertEqual(updated['effective_content']['manual_note_ids'], [])
        self.assertEqual(updated['effective_content']['schedule_ids'], ['linked'])
        self.assertEqual(updated['sources'], dict(calendar='group', manual_note_ids='device', schedule_ids='device'))
        self.assertNotEqual(self.service.authenticate(self.token, 'owner')['identity_revision'], old_identity['identity_revision'])
        self.assertEqual(self.service.get_device_content('owner', self.devices[1][0]), initial)
        self.assertEqual(self.make_service().get_device_content('owner', self.device_id), updated)
        self.assertEqual(self.service.list_devices('owner')[0]['content_settings'], updated)
        with patch('webclock.services.device_access_service.save_json') as save:
            self.assertEqual(self.update(updated['content_overrides']), updated)
            save.assert_not_called()
        self.service.update_group('owner', self.group['id'], {'content': {
            'calendar_source_ids': ['cal2'], 'manual_note_ids': [2], 'schedule_ids': []}})
        self.assertEqual(self.content()['effective_content']['calendar_source_ids'], ['cal2'])
        self.assertEqual(self.content()['effective_content']['manual_note_ids'], [])
        restored = self.update({})
        self.assertEqual(restored['effective_content'], restored['inherited_content'])
        self.assertEqual(restored['effective_content']['manual_note_ids'], [2])
        self.assertNotIn('content_overrides', load_json(self.path, {})['devices'][self.device_id])

    def test_calendar_override_replaces_entire_category_without_hiding_alarm_dependency(self):
        series = dict(source_id='cal2', uid='weekly', scope='series', recurrence_id='')
        once = dict(series, scope='occurrence', recurrence_id='2026-10-07T01:00:00+00:00')
        self.service.update_group('owner', self.group['id'], {'content': {
            'calendar_targets': [dict(series, source_id='cal1')], 'calendar_exclusions': [dict(once, source_id='cal1')]}})
        updated = self.update(dict(calendar_source_ids=[], calendar_targets=[once],
                                   calendar_exclusions=[series], schedule_ids=['linked']))
        content = self.service.get_group('owner', self.group['id'], self.device_id)['content']
        self.assertEqual(content, updated['effective_content'])
        self.assertEqual(content['calendar_source_ids'], [])
        self.assertTrue(calendar_content_allows(content, once))
        self.assertFalse(calendar_content_allows(content, dict(once, recurrence_id='future-occurrence')))
        self.assertFalse(calendar_content_allows(content, dict(once, source_id='cal1')))
        self.assertEqual(content['schedule_ids'], ['linked'])
        cleared = self.update(dict(calendar_source_ids=[], schedule_ids=['linked']))['effective_content']
        self.assertEqual([cleared[key] for key in ('calendar_source_ids', 'calendar_targets', 'calendar_exclusions')], [[], [], []])
        self.assertEqual(cleared['schedule_ids'], ['linked'])
        self.catalog['calendar_source_ids'].remove('cal2')
        self.assertEqual(self.make_service().get_device_content('owner', self.device_id)['effective_content'], cleared)
        with self.assertRaisesRegex(ValueError, 'missing calendar source'):
            self.update({'schedule_ids': ['linked']})

    def test_stale_device_group_and_move_revisions_reject_without_writing(self):
        version = self.content()['revision']
        self.update({'manual_note_ids': []})
        for mutation in (lambda: None, lambda: self.service.update_group('owner', self.group['id'],
                          {'content': {'manual_note_ids': [2]}})):
            mutation()
            before = self.path.read_bytes()
            with self.assertRaises(AccessError) as error:
                self.update({}, version)
            self.assertEqual((error.exception.status, error.exception.code), (409, 'content_settings_changed'))
            self.assertEqual(self.path.read_bytes(), before)
            version = self.content()['revision']
        destination = self.service.create_group('owner', {'name': 'Office', 'content': {'calendar_source_ids': ['cal2']}})
        self.service.update_device('owner', self.device_id, {'group_id': destination['id']})
        with self.assertRaises(AccessError):
            self.update({}, version)
        content = self.service.get_group('owner', destination['id'], self.device_id)['content']
        self.assertEqual(content['calendar_source_ids'], ['cal2'])
        self.assertEqual(content['manual_note_ids'], [])
        self.assertEqual(content['schedule_ids'], [])
        with self.assertRaises(AccessError):
            self.service.get_group('owner', self.group['id'], self.device_id)

    def test_invalid_references_owner_boundary_and_failed_save_preserve_state(self):
        before, initial = self.path.read_bytes(), self.content()
        for value in (None, [], {'unknown': []}, {'manual_note_ids': [True]}, {'manual_note_ids': [3]},
                      {'schedule_ids': ['missing']}, {'calendar_source_ids': ['missing']},
                      {'calendar_targets': []}, {'calendar_exclusions': []},
                      {'calendar_source_ids': [], 'calendar_targets': [{'source_id': 'missing'}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.update(value)
            self.assertEqual(self.path.read_bytes(), before)
        for call in (lambda: self.service.get_device_content('foreign', self.device_id),
                     lambda: self.service.update_device_content('foreign', self.device_id,
                         dict(content_overrides={}, revision=initial['revision']))):
            with self.assertRaises(AccessError) as error:
                call()
            self.assertEqual(error.exception.status, 404)
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.update({'manual_note_ids': []})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.content(), initial)

    def test_disabled_group_revoked_and_rejoin_identities_cannot_deliver_overrides(self):
        self.update({'manual_note_ids': [2]})
        self.service.update_group('owner', self.group['id'], {'enabled': False})
        with self.assertRaises(AccessError) as error:
            self.service.get_group('owner', self.group['id'], self.device_id)
        self.assertEqual(error.exception.status, 403)
        self.service.update_group('owner', self.group['id'], {'enabled': True})
        original = load_json(self.path, {})
        for changed in (dict(rejoin_required=True, status='disabled'),
                        dict(credential_digest=None, status='revoked')):
            state = deepcopy(original)
            state['devices'][self.device_id].update(changed)
            save_json(self.path, state)
            with self.assertRaises(AccessError) as error:
                self.update({})
            self.assertEqual(error.exception.code, 'device_rejoin_required')
            with self.assertRaises(AccessError):
                self.service.get_group('owner', self.group['id'], self.device_id)

    def test_legacy_missing_overrides_load_but_corrupt_overrides_fail_closed(self):
        initial = load_json(self.path, {})
        self.assertNotIn('content_overrides', initial['devices'][self.device_id])
        self.assertEqual(self.make_service().get_device_content('owner', self.device_id)['content_overrides'], {})
        for value in ({'manual_note_ids': [True]}, {'calendar_targets': []},
                      {'calendar_source_ids': [], 'calendar_exclusions': None}):
            state = deepcopy(initial)
            state['devices'][self.device_id]['content_overrides'] = value
            save_json(self.path, state)
            with self.subTest(value=value), self.assertRaises(AccessError) as error:
                self.make_service().get_device_content('owner', self.device_id)
            self.assertEqual((error.exception.status, error.exception.code), (503, 'access_not_ready'))


if __name__ == '__main__':
    unittest.main()
