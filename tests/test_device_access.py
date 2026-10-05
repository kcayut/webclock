"""Groups and invitations; atomic enrollment has its own regression suite."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webclock.services.device_access_service import (
    AccessError, CODE_ALPHABET, DeviceAccessService, GLOBAL_LIMIT, SOURCE_LIMIT,
)
from webclock.services.storage import load_json, save_json


class DeviceAccessTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'device-access.json'
        self.now = 1700000000
        self.defaults = dict(brightness=80, mode='normal', timezone_offset=8, language='zh-TW',
                             time_format='24h', night=dict(enabled=True, black=True, brightness=15,
                                                          start='22:00', end='07:00'))
        self.catalog = dict(calendar_source_ids=['cal1', 'cal2'], manual_note_ids=[1],
                            schedules=[{'id': 'alarm1'}, {'id': 'alarm2', 'calendar_link':
                                       {'source_ids': ['cal2']}}])
        self.service = self.make_service()

    def make_service(self):
        return DeviceAccessService(self.path, 'a' * 64, self.validate,
                                   lambda: self.defaults, lambda: self.catalog, clock=lambda: self.now)

    def validate(self, value):
        # Production supplies the existing app.validate_settings validator.
        if set(value) != set(self.defaults) or set(value['night']) != set(self.defaults['night']):
            raise ValueError('Unknown settings')
        for number in (value['brightness'], value['night']['brightness']):
            if type(number) is not int or not 0 <= number <= 100:
                raise ValueError('Invalid brightness')
        if any(type(value['night'][key]) is not bool for key in ('enabled', 'black')):
            raise ValueError('Invalid night switch')
        return deepcopy(value)

    def create(self, **data):
        return self.service.create_group('owner1', dict(name='Clock', **data))

    def test_initialization_is_explicit_idempotent_and_inherits_existing_selections(self):
        self.assertEqual(self.service.list_groups('owner1'), [])
        self.assertFalse(self.path.exists())
        self.catalog['default_content'] = dict(calendar_source_ids=['cal1'], manual_note_ids=[],
                                              schedule_ids=['alarm2'])
        group = self.service.initialize_owner('owner1')
        self.assertEqual(group['content'], self.catalog['default_content'])
        self.assertEqual(group['display_overrides'], {})
        self.assertEqual(group['effective_settings'], self.defaults)
        self.assertEqual(self.make_service().initialize_owner('owner1')['id'], group['id'])
        self.assertEqual(len(self.service.list_groups('owner1')), 1)
        other = self.create()
        self.assertNotEqual(other['id'], group['id'])
        self.assertEqual(other['content'], {key: [] for key in group['content']})
        self.defaults['brightness'] = 50
        self.assertEqual(self.service.get_group('owner1', group['id'])['effective_settings']['brightness'], 50)

    def test_overrides_preserve_false_zero_empty_and_name_changes_do_not_change_content(self):
        group = self.create(display_overrides={'brightness': 0, 'night': {'enabled': False, 'black': False}})
        current = self.service.get_group('owner1', group['id'])
        self.assertEqual(current['effective_settings']['brightness'], 0)
        self.assertIs(current['effective_settings']['night']['enabled'], False)
        self.assertIs(current['effective_settings']['night']['black'], False)
        self.assertEqual(current['effective_settings']['night']['brightness'], 15)
        renamed = self.service.update_group('owner1', group['id'], {'name': 'New name'})
        self.assertEqual(renamed['id'], group['id'])
        self.assertEqual(renamed['content_version'], group['content_version'])
        selected = self.service.update_group('owner1', group['id'], {'content': {'calendar_source_ids': ['cal1']}})
        self.assertEqual(selected['content_version'], group['content_version'] + 1)
        cleared = self.service.update_group('owner1', group['id'], {'display_overrides': {},
                                                                    'content': {'calendar_source_ids': []}})
        self.assertEqual(cleared['effective_settings'], self.defaults)
        self.assertEqual(cleared['content']['calendar_source_ids'], [])
        same = self.service.update_group('owner1', group['id'], {'display_overrides': {'brightness': 80}})
        self.assertEqual(same['content_version'], cleared['content_version'])

    def test_ownership_and_server_ids_cannot_be_reassigned(self):
        group = self.create()
        before = self.path.read_bytes()
        for action in (lambda: self.service.get_group('owner2', group['id']),
                       lambda: self.service.update_group('owner2', group['id'], {'name': 'stolen'}),
                       lambda: self.service.delete_group('owner2', group['id']),
                       lambda: self.service.create_invite('owner2', group['id']),
                       lambda: self.service.get_invite('owner2', group['id']),
                       lambda: self.service.close_invite('owner2', group['id'])):
            with self.assertRaises(AccessError) as error:
                action()
            self.assertEqual(error.exception.status, 404)
            self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.service.list_groups('owner2'), [])
        for data in ({'id': 'chosen'}, {'owner_id': 'owner2'}, {'enabled': 0},
                     {'display_overrides': {'brightness': False}}, {'display_overrides': {'extra': 1}},
                     {'display_overrides': {'night': {'extra': 1}}}, {'name': ''}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.service.update_group('owner1', group['id'], data)
            self.assertEqual(before, self.path.read_bytes())

    def test_content_references_and_linked_alarm_dependencies_are_validated_independently(self):
        group = self.create(content={'schedule_ids': ['alarm2']})
        self.assertEqual(group['content']['calendar_source_ids'], [])
        for content in ({'calendar_source_ids': ['missing']}, {'manual_note_ids': ['missing']},
                        {'schedule_ids': ['missing']}, {'schedule_ids': None}, {'arbitrary': []}):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.create(content=content)
        self.catalog['calendar_source_ids'].remove('cal2')
        with self.assertRaisesRegex(ValueError, 'missing calendar source'):
            self.create(content={'schedule_ids': ['alarm2']})
        self.catalog['schedules'][1]['calendar_link']['source_ids'] = ['local']
        self.create(content={'schedule_ids': ['alarm2']})

    def test_invitation_is_keyed_independently_secret_only_once_and_survives_restart(self):
        group = self.create()
        invitation = self.service.create_invite('owner1', group['id'])
        code = invitation['code']
        self.assertEqual(len(code), 6)
        self.assertLessEqual(set(code), set(CODE_ALPHABET))
        self.assertFalse(set(CODE_ALPHABET) & set('ILO01'))
        self.assertNotEqual(invitation['id'], group['id'])
        self.assertEqual(invitation['remaining'], 5)
        self.assertEqual(invitation['status'], 'active')
        self.assertNotIn(code, self.path.read_text())
        metadata = self.make_service().get_invite('owner1', group['id'])
        self.assertNotIn('code', metadata)
        self.assertNotIn('code_digest', metadata)
        self.assertNotIn(code, json.dumps(self.service.list_groups('owner1')))
        match = self.make_service().check_invite(code.lower(), 'peer')
        self.assertEqual(match['group_id'], group['id'])
        self.assertEqual(self.service.get_invite('owner1', group['id'])['used'], 0)

    def test_regeneration_close_expiry_disable_capacity_and_global_device_limit(self):
        group = self.create()
        def device_row(device_id):
            return dict(id=device_id, owner_id='owner1', group_id=group['id'], enabled=True,
                        status='active', credential_digest=hashlib.sha256(device_id.encode()).hexdigest(),
                        credential_generation=1, created_at='2026-10-05T00:00:00+00:00',
                        assignment_revision=1, rejoin_required=False)
        first = self.service.create_invite('owner1', group['id'], 1)
        state = load_json(self.path, {})
        state['devices']['existing'] = device_row('existing')
        save_json(self.path, state)
        second = self.service.create_invite('owner1', group['id'], 2)
        self.assertEqual(load_json(self.path, {})['devices'], state['devices'])
        with self.assertRaises(AccessError):
            self.service.check_invite(first['code'], 'peer')
        with self.assertRaises(AccessError) as error:
            self.service.delete_group('owner1', group['id'])
        self.assertEqual(error.exception.status, 409)
        self.service.close_invite('owner1', group['id'])
        with self.assertRaises(AccessError):
            self.service.check_invite(second['code'], 'peer')
        current = self.service.create_invite('owner1', group['id'])
        self.now += 600
        self.assertEqual(self.service.get_invite('owner1', group['id'])['status'], 'expired')
        with self.assertRaises(AccessError):
            self.service.check_invite(current['code'], 'peer')
        current = self.service.create_invite('owner1', group['id'])
        self.service.update_group('owner1', group['id'], {'enabled': False})
        with self.assertRaises(AccessError):
            self.service.check_invite(current['code'], 'peer')
        with self.assertRaises(AccessError):
            self.service.create_invite('owner1', group['id'])
        self.service.update_group('owner1', group['id'], {'enabled': True})
        state = load_json(self.path, {})
        state['invites'][group['id']]['used'] = 5
        save_json(self.path, state)
        self.assertEqual(self.service.get_invite('owner1', group['id'])['status'], 'full')
        with self.assertRaises(AccessError):
            self.service.check_invite(current['code'], 'peer')
        state['invites'][group['id']]['used'] = 0
        state['devices'] = {str(i): device_row(str(i)) for i in range(100)}
        save_json(self.path, state)
        self.assertEqual(self.service.get_invite('owner1', group['id'])['remaining'], 0)
        with self.assertRaises(AccessError):
            self.service.check_invite(current['code'], 'peer')
        with self.assertRaises(AccessError):
            self.service.create_invite('owner1', group['id'])

    def test_invalid_capacity_digest_collision_and_disk_failures_preserve_previous_state(self):
        group = self.create()
        for capacity in (0, 101, True, '5', None):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                self.service.create_invite('owner1', group['id'], capacity)
        with patch('webclock.services.device_access_service.secrets.choice', return_value='A'):
            self.service.create_invite('owner1', group['id'])
        before = self.path.read_bytes()
        with patch('webclock.services.device_access_service.secrets.choice', return_value='A'):
            with self.assertRaises(AccessError):
                self.service.create_invite('owner1', group['id'])
        self.assertEqual(before, self.path.read_bytes())
        with patch('webclock.services.device_access_service.save_json', side_effect=OSError('disk full')):
            for action in (lambda: self.service.create_invite('owner1', group['id']),
                           lambda: self.service.close_invite('owner1', group['id']),
                           lambda: self.service.update_group('owner1', group['id'], {'enabled': False}),
                           lambda: self.service.delete_group('owner1', group['id'])):
                with self.assertRaises(OSError):
                    action()
                self.assertEqual(before, self.path.read_bytes())

    def test_per_source_limit_survives_service_recreation_and_has_concrete_retry(self):
        for _ in range(SOURCE_LIMIT):
            with self.assertRaises(AccessError) as error:
                self.make_service().check_invite('bad', 'peer')
            self.assertEqual(error.exception.code, 'invalid_invitation')
        with self.assertRaises(AccessError) as error:
            self.make_service().check_invite('bad', 'peer')
        self.assertEqual(error.exception.status, 429)
        self.assertEqual(error.exception.retry_after, 60)
        self.now += 40
        with self.assertRaises(AccessError) as error:
            self.service.check_invite('bad', 'peer')
        self.assertEqual(error.exception.retry_after, 20)
        self.now += 20
        with self.assertRaises(AccessError) as error:
            self.service.check_invite('bad', 'peer')
        self.assertEqual(error.exception.code, 'invalid_invitation')

    def test_global_rate_limit_bounds_new_sources_and_unknown_codes_do_not_enumerate(self):
        for index in range(GLOBAL_LIMIT):
            with self.assertRaises(AccessError) as error:
                self.service.check_invite('AAAAAA', 'source' + str(index))
            self.assertEqual(str(error.exception), 'Invalid or unavailable invitation')
        with self.assertRaises(AccessError) as error:
            self.service.check_invite('AAAAAA', 'another')
        self.assertEqual((error.exception.status, error.exception.retry_after), (429, 60))
        from webclock.services.device_access_service import _RATE_WINDOWS
        self.assertEqual(len(_RATE_WINDOWS[str(self.path.resolve())]['sources']), GLOBAL_LIMIT)

    def test_missing_secret_and_corrupt_storage_fail_closed(self):
        group = self.create()
        self.service.secret = ''
        with self.assertRaises(AccessError) as error:
            self.service.create_invite('owner1', group['id'])
        self.assertEqual(error.exception.status, 503)
        save_json(self.path, {'version': 2, 'groups': {}, 'invites': {}, 'devices': {}, 'attempts': {}})
        with self.assertRaises(AccessError) as error:
            self.service.list_groups('owner1')
        self.assertEqual(error.exception.status, 503)

    def test_legacy_integer_note_ids_preserve_identity_and_reject_boolean_strings(self):
        # Existing save_note creates integer IDs with max(existing IDs) + 1.
        legacy_notes = [{'id': 1, 'text': 'One'}, {'id': 7, 'text': 'Seven'}]
        self.catalog['manual_note_ids'] = [row['id'] for row in legacy_notes]
        initial = self.service.initialize_owner('owner1')
        self.assertEqual(initial['content']['manual_note_ids'], [1, 7])
        group = self.create(content={'manual_note_ids': [7]})
        self.assertEqual(self.make_service().get_group('owner1', group['id'])['content']['manual_note_ids'], [7])
        for values in ([True], [False], ['1'], [0], [-1], [2]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.create(content={'manual_note_ids': values})

    def test_identifier_collisions_retry_without_overwriting_another_group(self):
        group = self.create()
        from types import SimpleNamespace
        with patch('webclock.services.device_access_service.uuid4',
                   side_effect=[SimpleNamespace(hex=group['id']), SimpleNamespace(hex='next_id')]):
            other = self.create()
        self.assertEqual(other['id'], 'next_id')
        self.assertEqual(self.service.get_group('owner1', group['id']), group)
        with patch('webclock.services.device_access_service.uuid4', return_value=SimpleNamespace(hex=group['id'])):
            with self.assertRaises(AccessError):
                self.service.create_invite('owner1', group['id'])

    def test_invite_transport_contract_and_http_retry_after(self):
        from flask import Flask, jsonify
        from webclock.api.groups import groups_api
        app = Flask(__name__)
        owner = ['owner1']
        app.register_blueprint(groups_api(lambda: self.service, lambda: owner[0]))

        @app.errorhandler(ValueError)
        def invalid(error):
            return jsonify(error=str(error)), 400

        client = app.test_client()
        self.assertEqual(client.get('/api/v1/groups').json, {'groups': []})
        created = client.post('/api/v1/groups', json={'name': 'Room'})
        self.assertEqual(created.status_code, 201)
        group_id = created.json['id']
        url = '/api/v1/groups/' + group_id + '/invite'
        self.assertEqual(client.get(url).json, {'invite': None})
        invited = client.post(url, json={})
        self.assertEqual(invited.status_code, 201)
        self.assertIn('code', invited.json)
        self.assertNotIn('code', client.get(url).json['invite'])
        self.assertEqual(client.delete(url).json['invite']['status'], 'closed')
        for body in ([], None, {'capacity': True}, {'capacity': 101}, {'group_id': group_id}):
            self.assertEqual(client.post(url, json=body).status_code, 400 if body is not None else 415)
        owner[0] = 'owner2'
        self.assertEqual(client.post(url, json={}).status_code, 404)
        owner[0] = 'owner1'
        with patch.object(self.service, 'get_invite',
                          side_effect=AccessError('Too many invitation attempts', 429, 'rate_limited', 17)):
            response = client.get(url)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '17')
        self.assertEqual(response.json['code'], 'rate_limited')
        with patch.object(self.service, 'create_invite', side_effect=OSError('private secret')):
            response = client.post(url, json={})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['code'], 'storage_failed')
        self.assertNotIn('private secret', response.get_data(as_text=True))

    def test_corrupt_json_groups_and_invites_fail_closed_without_rewriting(self):
        group = self.create()
        self.service.create_invite('owner1', group['id'])
        valid = load_json(self.path, {})
        corruptions = []
        for field, value in [('enabled', 'yes'), ('display_overrides', {'brightness': -1}),
                             ('owner_id', None), ('content', {}), ('content_version', True),
                             ('created_at', 'invalid')]:
            damaged = deepcopy(valid)
            damaged['groups'][group['id']][field] = value
            corruptions.append(damaged)
        for field, value in [('code_digest', 'plaintext'), ('used', -1), ('capacity', True),
                             ('owner_id', 'wrong-owner'), ('expires_at', 'invalid'), ('closed', 0)]:
            damaged = deepcopy(valid)
            damaged['invites'][group['id']][field] = value
            corruptions.append(damaged)
        for damaged in corruptions:
            save_json(self.path, damaged)
            before = self.path.read_bytes()
            with self.assertRaises(AccessError) as error:
                self.service.list_groups('owner1')
            self.assertEqual(error.exception.status, 503)
            self.assertEqual(self.path.read_bytes(), before)
        self.path.write_text('{broken JSON')
        with self.assertRaises(AccessError) as error:
            self.service.list_groups('owner1')
        self.assertEqual(error.exception.status, 503)


if __name__ == '__main__':
    unittest.main()
