"""Program writes, independent credentials, retry safety and target boundaries."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.control_access_service import ControlAccessService
from webclock.services.storage import load_json, save_json


class ControlApiTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for key, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                           ('NOTES_FILE', str(self.root / 'notes.json')), ('ICAL_URL', '')]:
            change = patch.object(clock, key, value)
            change.start()
            self.addCleanup(change.stop)
        self.admin = clock.app.test_client()
        self.program = clock.app.test_client()
        self.csrf = self.admin.get('/api/csrf').json['csrf_token']
        self.admin.environ_base['HTTP_X_CSRF_TOKEN'] = self.csrf
        self.url = '/api/v1/control/'
        self.scopes = ['schedules:read', 'schedules:write', 'events:read', 'events:write', 'assignments:write']

    def issue(self, **changes):
        response = self.admin.post('/api/v1/control-clients', json=dict(name='Test program', scopes=self.scopes, **changes))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['client']

    def call(self, token, method, path, data=None, **kwargs):
        return self.program.open(self.url + path, method=method, json=data,
                                 headers={'Authorization': 'Bearer ' + token}, **kwargs)

    def alarm(self, token, request_id='alarm-request-1', **changes):
        response = self.call(token, 'POST', 'schedules', dict(request_id=request_id,
            schedule=dict(name='Morning', time='07:30', **changes)))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def event(self, token, **changes):
        response = self.call(token, 'POST', 'events', dict(request_id='event-request-1',
            event=dict(title='Meeting', start='2026-10-09T14:00:00+08:00', end='2026-10-09T15:00:00+08:00',
                       display_window=dict(mode='relative', before_minutes=180, end='event_end'), **changes)))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def test_self_requires_explicit_credentials_and_management_csrf(self):
        before = set(self.root.iterdir())
        self.assertEqual(self.program.post(self.url + 'schedules', json={}).status_code, 401)
        self.assertEqual(self.program.post('/api/v1/control-clients', json={}).status_code, 403)
        self.assertEqual(set(self.root.iterdir()), before)
        client = self.issue()
        self.assertEqual(client['mode'], 'self')
        raw = (self.root / 'control-clients.json').read_text()
        self.assertNotIn(client['token'], raw)
        listing = self.admin.get('/api/v1/control-clients')
        self.assertNotIn(client['token'], listing.text)
        self.assertNotIn('digest', listing.text)
        self.assertEqual(self.call('legacy-token', 'GET', 'identity').status_code, 401)
        self.assertEqual(self.admin.post(self.url + 'schedules', json={}).status_code, 401)
        cross = self.program.get(self.url + 'identity', headers={
            'Authorization': 'Bearer ' + client['token'], 'Origin': 'https://evil.invalid'})
        self.assertEqual(cross.status_code, 403)
        self.assertNotIn('Access-Control-Allow-Origin', cross.headers)
        self.assertEqual(self.admin.delete('/api/v1/control-clients/' + client['id']).status_code, 200)
        self.assertEqual(self.call(client['token'], 'GET', 'identity').status_code, 401)

    def test_idempotency_conflicts_revisions_and_delete_never_resurrect(self):
        token = self.issue()['token']
        first = self.alarm(token)
        body = dict(request_id='alarm-request-1', schedule=dict(name='Morning', time='07:30'))
        repeat = self.call(token, 'POST', 'schedules', body)
        self.assertEqual(repeat.status_code, 200)
        self.assertTrue(repeat.json['replayed'])
        self.assertEqual(len(load_json(self.root / 'schedules.json', [])), 1)
        wrong = deepcopy(body)
        wrong['schedule']['time'] = '08:00'
        self.assertEqual(self.call(token, 'POST', 'schedules', wrong).status_code, 409)
        path = 'schedules/' + first['schedule']['id']
        updated = self.call(token, 'PATCH', path, dict(revision=first['revision'], schedule={'time': '08:00'}))
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(self.call(token, 'PATCH', path, dict(revision=first['revision'], schedule={'time': '09:00'})).status_code, 409)
        self.assertEqual(self.call(token, 'DELETE', path, dict(revision=updated.json['revision'])).status_code, 200)
        self.assertEqual(self.call(token, 'POST', 'schedules', body).status_code, 200)
        self.assertEqual(load_json(self.root / 'schedules.json', []), [])

    def test_content_grants_do_not_imply_global_edit_or_source_access(self):
        client = self.issue()
        row = self.alarm(client['token'])
        other = self.issue()
        path = 'schedules/' + row['schedule']['id']
        self.assertEqual(self.call(other['token'], 'GET', path).status_code, 404)
        self.assertEqual(self.call(other['token'], 'GET', 'schedules').json['schedules'], [])
        limited = self.issue(schedule_ids=[row['schedule']['id']])
        self.assertEqual(self.call(limited['token'], 'GET', path).status_code, 200)
        bad = dict(request_id='cannot-read-local', schedule=dict(name='Leak', time='07:30',
            calendar_link=dict(mode='event', source_ids=['local'], offset_minutes=0)))
        self.assertEqual(self.call(other['token'], 'POST', 'schedules', bad).status_code, 403)
        self.assertEqual(self.call(other['token'], 'GET', 'calendar-events?source_id=local').status_code, 403)
        self.assertEqual(self.admin.post('/api/v1/control-clients', json=dict(
            name='Bad', scopes=self.scopes, group_ids=['missing'])).status_code, 400)

    def test_events_linked_alarms_and_group_device_assignment_boundaries(self):
        self.issue()  # Initialize self owner before creating targets.
        with clock.app.test_request_context('/'):
            owner = clock.auth_service().owner_id()
            access = clock.group_service()
            group = access.create_group(owner, {'name': 'Bedroom'})
            foreign = access.create_group(owner, {'name': 'Office'})
            invite = access.create_invite(owner, group['id'])
            attempt = access.prepare(owner, 'fixture')
            joined = access.join(owner, attempt['token'], attempt['attempt_id'], invite['code'], 'fixture')
            device_id = joined['identity']['device_id']
        token = self.issue(group_ids=[group['id']], device_ids=[device_id])['token']
        event = self.event(token)
        event_id = event['event']['id']
        self.assertNotIn('owner_id', event['event'])
        link = dict(mode='event', source_ids=['webclock'], offset_minutes=15,
                    target=dict(source_id='webclock', uid=event_id, scope='occurrence', recurrence_id=''))
        alarm = self.alarm(token, calendar_link=link)
        other = self.issue()['token']
        blocked = self.call(other, 'POST', 'schedules', dict(request_id='foreign-event-link',
            schedule=dict(name='No', time='07:30', calendar_link=link)))
        self.assertEqual(blocked.status_code, 404)
        for kind, identifier in [('events', event_id), ('schedules', alarm['schedule']['id'])]:
            for target_kind, target_id in [('group', group['id']), ('device', device_id)]:
                route = kind + '/' + identifier + '/targets/' + target_kind + '/' + target_id
                current = self.call(token, 'GET', route)
                self.assertEqual(current.status_code, 200, current.json)
                for malformed in ('null', '[]'):
                    invalid = self.program.put(self.url + route, data=malformed,
                        content_type='application/json', headers={'Authorization': 'Bearer ' + token})
                    self.assertEqual(invalid.status_code, 400, invalid.json)
                changed = self.call(token, 'PUT', route, dict(assigned=True, revision=current.json['revision']))
                self.assertEqual(changed.status_code, 200, changed.json)
                self.assertTrue(changed.json['assigned'])
                stale = self.call(token, 'PUT', route, dict(assigned=False, revision=current.json['revision']))
                if current.json['revision'] != changed.json['revision']:
                    self.assertEqual(stale.status_code, 409)
                cleared = self.call(token, 'PUT', route, dict(assigned=False, revision=changed.json['revision']))
                self.assertEqual(cleared.status_code, 200, cleared.json)
                self.assertFalse(cleared.json['assigned'])
            denied = self.call(token, 'GET', kind + '/' + identifier + '/targets/group/' + foreign['id'])
            self.assertEqual(denied.status_code, 403)
        modified = self.call(token, 'PATCH', 'events/' + event_id,
            dict(revision=event['revision'], event={'start': '2026-10-10T14:00:00+08:00', 'end': '2026-10-10T15:00:00+08:00'}))
        self.assertEqual(modified.status_code, 200, modified.json)
        self.assertEqual(modified.json['event']['display_window'], event['event']['display_window'])

    def test_pending_receipt_recovers_saved_resource_but_never_repeats_failed_write(self):
        token = self.issue()['token']
        count = 0
        def fail_completion(path, value):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('disk full')
            save_json(path, value)
        body = dict(request_id='recovery-request-1', schedule=dict(name='Once', time='07:30'))
        with patch('webclock.services.control_service.save_json', side_effect=fail_completion):
            response = self.call(token, 'POST', 'schedules', body)
        self.assertEqual(response.status_code, 500)
        repeated = self.call(token, 'POST', 'schedules', body)
        self.assertEqual(repeated.status_code, 200, repeated.json)
        self.assertEqual(len(load_json(self.root / 'schedules.json', [])), 1)
        body['request_id'] = 'recovery-request-2'
        with patch('webclock.services.control_service.save_schedules', side_effect=OSError('disk full')):
            self.assertEqual(self.call(token, 'POST', 'schedules', body).status_code, 500)
        self.assertEqual(self.call(token, 'POST', 'schedules', body).status_code, 409)

    def test_self_program_alarms_require_explicit_pairing_assignment_and_stay_out_of_legacy_reads(self):
        token = self.issue()['token']
        private = self.alarm(token)['schedule']['id']
        self.assertIsNone(self.program.get('/api/status').json['next_event'])
        ordinary = self.admin.post('/api/v1/schedules', json=dict(
            id='legacy-alarm', name='Ordinary alarm', time='08:00'))
        self.assertEqual(ordinary.status_code, 201, ordinary.json)
        self.assertEqual({row['id'] for row in self.admin.get('/api/v1/schedules').json['schedules']},
                         {private, 'legacy-alarm'})
        initialized = self.admin.post('/api/v1/groups/initialize', json={})
        self.assertEqual(initialized.status_code, 200, initialized.json)
        group = initialized.json
        self.assertEqual(group['content']['schedule_ids'], ['legacy-alarm'])
        with clock.app.test_request_context('/'):
            owner, access = clock.auth_service().owner_id(), clock.group_service()
            invite = access.create_invite(owner, group['id'])
            prepared = access.prepare(owner, 'isolation-fixture')
            access.join(owner, prepared['token'], prepared['attempt_id'], invite['code'], 'isolation-fixture')
        headers = {'Authorization': 'Bearer ' + prepared['token']}
        paired = self.program.get('/api/v2/device/browser-alarms', headers=headers)
        self.assertEqual(paired.status_code, 200, paired.json)
        self.assertEqual(paired.json['enabled_ids'], ['legacy-alarm'])
        scoped = self.issue(group_ids=[group['id']], schedule_ids=[private])['token']
        route = 'schedules/' + private + '/targets/group/' + group['id']
        current = self.call(scoped, 'GET', route)
        assigned = self.call(scoped, 'PUT', route, dict(assigned=True, revision=current.json['revision']))
        self.assertEqual(assigned.status_code, 200, assigned.json)
        paired = self.program.get('/api/v2/device/browser-alarms', headers=headers)
        self.assertEqual(set(paired.json['enabled_ids']), {private, 'legacy-alarm'})
        self.assertEqual([row['id'] for row in self.program.get('/api/v1/device/schedules').json['schedules']],
                         ['legacy-alarm'])
        self.assertEqual(self.program.get('/api/v1/browser-alarms').json['enabled_ids'], ['legacy-alarm'])
        self.assertEqual(self.program.get('/api/status').json['next_event']['text'], 'Ordinary alarm')

    def test_pending_missing_or_corrupt_receipts_never_publish_program_alarms(self):
        token = self.issue()['token']
        calls = 0
        def fail_completion(path, value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('disk full')
            save_json(path, value)
        body = dict(request_id='private-pending-1', schedule=dict(name='Private program alarm', time='07:30'))
        with patch('webclock.services.control_service.save_json', side_effect=fail_completion):
            self.assertEqual(self.call(token, 'POST', 'schedules', body).status_code, 500)
        self.assertEqual(len(load_json(self.root / 'schedules.json', [])), 1)
        receipts = self.root / 'control-requests.json'
        for state in ('pending', 'missing', 'corrupt'):
            if state == 'missing':
                receipts.unlink()
            elif state == 'corrupt':
                receipts.write_text('{broken')
            for route in ('/api/status', '/api/v1/browser-alarms', '/api/v1/device/schedules'):
                response = self.program.get(route)
                with self.subTest(state=state, route=route):
                    if state == 'corrupt':
                        self.assertGreaterEqual(response.status_code, 400)
                    else:
                        self.assertEqual(response.status_code, 200)
                    self.assertNotIn('Private program alarm', response.text)
                    self.assertNotIn('ctl_', response.text)

    def test_assignments_prune_deleted_references_and_preserve_ungranted_content(self):
        foreign = self.issue()['token']
        untouched = self.event(foreign)['event']['id']
        ordinary = self.admin.post('/api/v1/schedules', json=dict(
            id='untouched-alarm', name='Other alarm', time='08:00'))
        self.assertEqual(ordinary.status_code, 201, ordinary.json)
        with clock.app.test_request_context('/'):
            owner, access = clock.auth_service().owner_id(), clock.group_service()
            group = access.create_group(owner, {'name': 'Shared bedroom', 'content': {
                'schedule_ids': ['untouched-alarm'], 'calendar_targets': [dict(
                    source_id='webclock', uid=untouched, scope='occurrence', recurrence_id='')]}})
            invite = access.create_invite(owner, group['id'])
            prepared = access.prepare(owner, 'stale-targets')
            joined = access.join(owner, prepared['token'], prepared['attempt_id'], invite['code'], 'stale-targets')
            device_id = joined['identity']['device_id']
        token = self.issue(group_ids=[group['id']], device_ids=[device_id])['token']
        replacements = {}
        for generation in ('deleted', 'replacement'):
            for kind in ('schedules', 'events'):
                field = 'schedule' if kind == 'schedules' else 'event'
                data = (dict(name=generation, time='07:30') if kind == 'schedules' else
                        dict(title=generation, start='2030-01-01T09:00:00+08:00', end='2030-01-01T10:00:00+08:00'))
                created = self.call(token, 'POST', kind, dict(request_id=generation + '-' + kind, **{field: data}))
                self.assertEqual(created.status_code, 201, created.json)
                item_id = created.json[field]['id']
                # Device first ensures an explicit override exists before the group gains the item.
                for target_kind, target_id in (('device', device_id), ('group', group['id'])):
                    route = kind + '/' + item_id + '/targets/' + target_kind + '/' + target_id
                    current = self.call(token, 'GET', route)
                    assigned = self.call(token, 'PUT', route, dict(assigned=True, revision=current.json['revision']))
                    self.assertEqual(assigned.status_code, 200, assigned.json)
                if generation == 'deleted':
                    deleted = self.call(token, 'DELETE', kind + '/' + item_id, dict(revision=created.json['revision']))
                    self.assertEqual(deleted.status_code, 200, deleted.json)
                else:
                    replacements[kind] = item_id
        with clock.app.test_request_context('/'):
            access = clock.group_service()
            contents = [access.get_group(owner, group['id'])['content'],
                        access.get_device_content(owner, device_id)['effective_content']]
        for content in contents:
            self.assertEqual(set(content['schedule_ids']), {'untouched-alarm', replacements['schedules']})
            self.assertEqual({row['uid'] for row in content['calendar_targets']}, {untouched, replacements['events']})
        self.assertEqual(self.call(token, 'GET', 'events/' + untouched).status_code, 404)
        self.assertEqual(self.call(token, 'GET', 'schedules/untouched-alarm').status_code, 404)

    def test_managed_issuance_requires_admin_and_tokens_cannot_cross_modes(self):
        old = self.issue()['token']
        auth = clock.auth_service()
        auth.setup('admin', 'a-long-test-password', enable_managed=True)
        self.assertEqual(self.call(old, 'GET', 'identity').status_code, 403)
        self.assertEqual(self.call(old, 'GET', 'identity', base_url='https://localhost').status_code, 401)
        anonymous = self.program.post('/api/v1/control-clients', base_url='https://localhost', json={})
        self.assertEqual(anonymous.status_code, 401)
        admin = clock.app.test_client()
        csrf = admin.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        login = admin.post('/login', base_url='https://localhost', data={
            'username': 'admin', 'password': 'a-long-test-password', 'csrf_token': csrf})
        self.assertEqual(login.status_code, 302)
        csrf = admin.get('/api/csrf', base_url='https://localhost').json['csrf_token']
        issued = admin.post('/api/v1/control-clients', base_url='https://localhost',
            headers={'X-CSRF-Token': csrf}, json=dict(name='Managed', scopes=self.scopes))
        self.assertEqual(issued.status_code, 201, issued.json)
        token = issued.json['client']['token']
        self.assertEqual(self.call(token, 'GET', 'identity', base_url='https://localhost').status_code, 200)
        self.assertEqual(admin.get(self.url + 'identity', base_url='https://localhost').status_code, 401)

    def test_page_translation_and_ingress_keep_management_private(self):
        for language in ('zh-TW', 'en', 'ja'):
            with patch.dict(clock.display_settings, language=language):
                page = self.admin.get('/integrations')
                self.assertEqual(page.status_code, 200, page.text)
                self.assertIn('control-create', page.text)
        token = self.issue()['token']
        with patch.dict('os.environ', {'WEBCLOCK_HA_APP': '1'}):
            environ = {'SERVER_PORT': '8100'}
            self.assertEqual(self.admin.get('/integrations', environ_overrides=environ).status_code, 404)
            self.assertEqual(self.admin.get('/api/v1/control-clients', environ_overrides=environ).status_code, 404)
            self.assertEqual(self.call(token, 'GET', 'identity', environ_overrides=environ).status_code, 200)


if __name__ == '__main__':
    unittest.main()
