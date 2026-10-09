"""A copied managed installation keeps account and credential boundaries in HA."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import app as clock
from webclock.services.auth_service import AuthService
from webclock.services.storage import save_json
from webclock.services.device_access_service import DeviceAccessService, _RATE_WINDOWS


PASSWORD = 'restored administrator password'


class HAManagedTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        source = Path(folder.name) / 'bare-metal'
        auth = AuthService(source / 'auth.json')
        auth.setup('admin', PASSWORD, enable_managed=True)
        self.admin_owner = auth.owner_id()
        self.member_owner = auth.create_account('member', PASSWORD)['owner_id']
        for owner, directory in ((self.admin_owner, source),
                                 (self.member_owner, source / 'owners' / self.member_owner)):
            save_json(directory / 'manual_notes.json',
                      [dict(id=1, text='private-' + owner, due_date='', enabled=True)])
        access = DeviceAccessService(source / 'device-access.json', auth.invite_secret(), lambda value: value,
            lambda: dict(clock.DEFAULT_SETTINGS),
            lambda: dict(manual_note_ids=[1], calendar_source_ids=[], schedules=[]))
        group = access.initialize_owner(self.member_owner)
        invite = access.create_invite(self.member_owner, group['id'])
        prepared = access.prepare(self.member_owner, 'bare-metal')
        self.restored_token = prepared['token']
        self.restored_identity = access.join(self.member_owner, self.restored_token, prepared['attempt_id'],
                                            invite['code'], 'bare-metal')['identity']
        self.root = Path(folder.name) / 'ha-data'
        shutil.copytree(source, self.root)
        for change in (
                patch.object(clock, 'SETTINGS_FILE', str(self.root / 'settings.json')),
                patch.object(clock, 'NOTES_FILE', str(self.root / 'manual_notes.json')),
                patch.object(clock, 'ICAL_URL', ''),
                patch.dict(clock.display_settings, clock.DEFAULT_SETTINGS, clear=True),
                patch.dict(clock.app.config, SECRET_KEY=auth.session_secret()),
                patch.object(clock.requests, 'get', side_effect=AssertionError('Unexpected network')),
                patch.dict(os.environ, WEBCLOCK_HA_APP='1', WEBCLOCK_INGRESS='1')):
            change.start()
            self.addCleanup(change.stop)
        _RATE_WINDOWS.clear()
        self.admin = clock.app.test_client()
        self.member = clock.app.test_client()

    def ingress(self, client, path, method='GET', data=None, scheme='http', **extra):
        headers = {'X-Ingress-Path': '/api/hassio_ingress/test-token',
                   'X-Forwarded-Proto': scheme, 'X-Forwarded-Host': 'localhost',
                   'Origin': scheme + '://localhost'}
        headers.update(extra)
        environment = {'REMOTE_ADDR': '172.30.32.2', 'SERVER_PORT': '8099'}
        if method not in ('GET', 'HEAD'):
            csrf = client.get('/api/csrf', headers=headers, environ_overrides=environment)
            headers['X-CSRF-Token'] = csrf.json['csrf_token']
        return client.open(path, method=method, json=data, headers=headers, environ_overrides=environment)

    def login(self, client, name, scheme='http'):
        result = self.ingress(client, '/login', 'POST', dict(username=name, password=PASSWORD), scheme=scheme)
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def display(self, client, path, method='GET', data=None, **headers):
        return client.open(path, method=method, json=data, headers=headers,
                           environ_overrides={'REMOTE_ADDR': '192.0.2.40', 'SERVER_PORT': '8100'})

    def test_restored_accounts_keep_their_private_spaces_behind_ha_login(self):
        self.assertEqual(self.ingress(self.admin, '/api/backup', **{'X-Remote-User-Id': 'HA-admin'}).status_code, 401)
        for client, name, owner, foreign in ((self.admin, 'admin', self.admin_owner, self.member_owner),
                                            (self.member, 'member', self.member_owner, self.admin_owner)):
            self.assertEqual(self.login(client, name).json['owner_id'], owner)
            result = self.ingress(client, '/api/backup')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['owner_id'], owner)
            self.assertIn('private-' + owner, result.text)
            self.assertNotIn('private-' + foreign, result.text)
        self.assertEqual(clock.auth_service().mode(), 'managed')
        self.assertEqual(len(self.ingress(self.admin, '/api/accounts').json['accounts']), 2)
        self.assertEqual(self.ingress(self.member, '/api/accounts').status_code, 403)
        self.assertEqual(self.ingress(self.member, '/mode').status_code, 403)

    def test_session_secure_follows_only_the_trusted_ingress_scheme(self):
        for scheme in ('https', 'http', 'https'):
            client = clock.app.test_client()
            self.login(client, 'admin', scheme)
            cookie = client.get_cookie(clock.app.config['SESSION_COOKIE_NAME'])
            self.assertEqual(cookie.secure, scheme == 'https')
            self.assertTrue(cookie.http_only)
            self.assertEqual(self.ingress(client, '/admin', scheme=scheme).status_code, 200)
            # A LAN request must not mutate the HTTPS listener's cookie policy.
            self.assertEqual(self.display(clock.app.test_client(), '/api/csrf').status_code, 200)
            self.assertEqual(self.ingress(client, '/api/csrf', scheme=scheme).status_code, 200)
            self.assertEqual(client.get_cookie(clock.app.config['SESSION_COOKIE_NAME']).secure, scheme == 'https')

    def test_restored_device_and_new_pairing_remain_scoped_on_lan_display(self):
        restored = clock.app.test_client()
        result = self.display(restored, '/api/v2/device/display',
                              Authorization='Bearer ' + self.restored_token)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json['identity'], self.restored_identity)
        self.assertIn('private-' + self.member_owner, result.text)
        self.assertNotIn('private-' + self.admin_owner, result.text)
        self.login(self.member, 'member')
        group = self.ingress(self.member, '/api/v1/groups/initialize', 'POST', {}).json
        invite = self.ingress(self.member, '/api/v1/groups/' + group['id'] + '/invite', 'POST', {}).json
        device = clock.app.test_client()
        csrf = self.display(device, '/api/csrf').json['csrf_token']
        prepared = self.display(device, '/api/v2/device/join/prepare', 'POST', {}, **{'X-CSRF-Token': csrf})
        self.assertEqual(prepared.status_code, 201, prepared.text)
        self.assertFalse(device.get_cookie('webclock_device', path='/api/v2/device').secure)
        joined = self.display(device, '/api/v2/device/join', 'POST',
                              dict(attempt_id=prepared.json['attempt_id'], code=invite['code']),
                              **{'X-CSRF-Token': csrf})
        self.assertEqual(joined.status_code, 201, joined.text)
        self.assertEqual(joined.json['identity']['owner_id'], self.member_owner)
        # Reconstruct the auth service, as after a server restore/restart.
        clock._auth_services.pop(str((self.root / 'auth.json').resolve()), None)
        result = self.display(device, '/api/v2/device/display')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn('private-' + self.member_owner, result.text)
        self.assertNotIn('private-' + self.admin_owner, result.text)
        self.assertEqual(self.display(self.member, '/api/v2/device/display').status_code, 401)
        self.assertEqual(self.display(device, '/admin').status_code, 404)
        self.assertEqual(self.display(device, '/api/v1/groups').status_code, 404)

    def test_ha_mode_switch_is_unavailable_but_control_credentials_still_work(self):
        self.login(self.admin, 'admin')
        page = self.ingress(self.admin, '/mode')
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="accounts-list"', page.text)
        self.assertIn('data-management-link="mode"', page.text)
        self.assertNotIn('id="mode-form"', page.text)
        created = self.ingress(self.admin, '/api/accounts', 'POST', dict(username='new-member', password=PASSWORD))
        self.assertEqual(created.status_code, 201, created.text)
        for path, method in (('/api/mode/preview', 'POST'), ('/api/mode/switch', 'POST')):
            result = self.ingress(self.admin, path, method, {})
            self.assertEqual(result.status_code, 409, result.text)
            self.assertEqual(result.json['code'], 'mode_change_unavailable_in_ha')
        with patch.object(clock, 'SETTINGS_FILE', str(self.root / 'empty' / 'settings.json')):
            self.assertEqual(self.ingress(self.admin, '/mode').status_code, 409)
        issued = self.ingress(self.admin, '/api/v1/control-clients', 'POST',
                              dict(name='HA', scopes=['schedules:read']))
        self.assertEqual(issued.status_code, 201, issued.text)
        program = clock.app.test_client()
        headers = {'Authorization': 'Bearer ' + issued.json['client']['token']}
        result = self.display(program, '/api/v1/control/identity', **headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json['client']['owner_id'], self.admin_owner)
        self.assertEqual(self.display(program, '/api/v1/control/schedules', 'POST', {}, **headers).status_code, 403)
        self.assertEqual(self.display(self.admin, '/api/v1/control/identity').status_code, 401)
        self.assertEqual(self.display(program, '/api/v2/device/display', **headers).status_code, 401)
        self.assertEqual(self.display(program, '/api/v1/control-clients', **headers).status_code, 404)

    def test_untrusted_headers_and_direct_management_stay_closed(self):
        headers = {'X-Ingress-Path': '/api/hassio_ingress/test-token', 'X-Forwarded-Proto': 'https'}
        self.assertEqual(self.admin.get('/admin', headers=headers,
                         environ_overrides={'REMOTE_ADDR': '127.0.0.1', 'SERVER_PORT': '8099'}).status_code, 403)
        self.assertEqual(self.admin.get('/admin', environ_overrides={'SERVER_PORT': '8099'}).status_code, 403)
        self.assertEqual(self.display(self.admin, '/login').status_code, 404)
        self.assertEqual(self.display(self.admin, '/api/csrf', **headers).status_code, 404)
        with patch.dict(os.environ, WEBCLOCK_HA_APP='0', WEBCLOCK_INGRESS='0'):
            client = clock.app.test_client()
            csrf = client.get('/api/csrf').json['csrf_token']
            result = client.post('/login', json=dict(username='admin', password=PASSWORD),
                                 headers=dict(headers, **{'X-CSRF-Token': csrf}))
            self.assertEqual(result.json['code'], 'https_required')
            self.assertEqual(client.get('/api/v2/device/identity', headers=headers).json['code'], 'https_required')
            self.assertEqual(client.get('/api/v1/control/identity', headers=headers).json['code'], 'tls_required')


if __name__ == '__main__':
    unittest.main()
