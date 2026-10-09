import os
import unittest
from unittest.mock import patch

import app as clock


class IngressTest(unittest.TestCase):
    def setUp(self):
        self.client = clock.app.test_client()
        self.header = {'X-Ingress-Path': '/api/hassio_ingress/test-token'}

    def get(self, path='/', remote='172.30.32.2', port='80'):
        return self.client.get(path, headers=self.header,
                               environ_overrides={'REMOTE_ADDR': remote, 'SERVER_PORT': port})

    def test_trusted_ingress_prefixes_generated_and_browser_urls(self):
        with patch.dict(os.environ, {'WEBCLOCK_INGRESS': '1'}):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('/api/hassio_ingress/test-token/static/clock.css', page)
        self.assertIn('/api/hassio_ingress/test-token/admin', page)
        self.assertIn("+ \"/api/hassio_ingress/test-token\"", page)
        with patch.dict(os.environ, {'WEBCLOCK_INGRESS': '1'}):
            admin = self.get('/admin')
            login = self.get('/login')
        self.assertEqual(admin.status_code, 200)
        self.assertIn('/api/hassio_ingress/test-token/schedules#alarms', admin.get_data(as_text=True))
        self.assertEqual(login.headers['Location'], '/api/hassio_ingress/test-token/admin')

    def test_ingress_header_requires_trusted_proxy_and_valid_path(self):
        with patch.dict(os.environ, {'WEBCLOCK_INGRESS': '1'}):
            self.assertEqual(self.get(remote='127.0.0.1').status_code, 403)
            self.header['X-Ingress-Path'] = '/api/../admin'
            self.assertEqual(self.get().status_code, 400)

    def test_header_is_ignored_when_ingress_is_disabled(self):
        with patch.dict(os.environ, {'WEBCLOCK_INGRESS': '0'}):
            response = self.get(remote='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('/api/hassio_ingress/test-token/static/', response.get_data(as_text=True))

    def test_https_ingress_preserves_browser_origin_for_csrf_and_management_writes(self):
        origin = 'https://ha.example.test:8123'
        headers = dict(self.header, **{'X-Forwarded-Proto': 'https',
                       'X-Forwarded-Host': 'ha.example.test:8123', 'Origin': origin,
                       'Referer': origin + self.header['X-Ingress-Path'] + '/admin'})
        environment = {'REMOTE_ADDR': '172.30.32.2', 'SERVER_PORT': '8099'}
        with patch.dict(os.environ, WEBCLOCK_INGRESS='1', WEBCLOCK_HA_APP='1'):
            csrf = self.client.get('/api/csrf', headers=headers, environ_overrides=environment)
            self.assertEqual(csrf.status_code, 200)
            headers['X-CSRF-Token'] = csrf.json['csrf_token']
            response = self.client.post('/api/management/language', json={'language': 'en'},
                                        headers=headers, environ_overrides=environment)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'language': 'en'})
            for invalid in ({'X-CSRF-Token': 'wrong'}, {'Origin': 'https://other.example.test'},
                            {'Referer': 'https://other.example.test/admin'}):
                with self.subTest(invalid=invalid):
                    response = self.client.post('/api/management/language', json={'language': 'ja'},
                                                headers=dict(headers, **invalid), environ_overrides=environment)
                    self.assertEqual(response.status_code, 403)
            response = self.client.get('/api/csrf', headers=headers,
                                       environ_overrides=dict(environment, REMOTE_ADDR='127.0.0.1'))
            self.assertEqual(response.status_code, 403)

    def test_ingress_forwarded_origin_requires_valid_single_scheme_and_host(self):
        self.header.update({'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'ha.example.test'})
        with patch.dict(os.environ, WEBCLOCK_INGRESS='1', WEBCLOCK_HA_APP='1'):
            for host in ('ha.local', '192.0.2.1:8123', '[2001:db8::1]:8123'):
                with self.subTest(host=host):
                    self.header.update({'X-Forwarded-Host': host, 'Origin': 'https://' + host})
                    self.assertEqual(self.get('/api/csrf', port='8099').status_code, 200)
            for name, values in (
                    ('X-Forwarded-Proto', ('', 'ftp', 'HTTPS', 'https,http')),
                    ('X-Forwarded-Host', ('', 'ha.test,other.test', 'ha.test/path', 'user@ha.test',
                                          'ha.test:0', 'ha.test:65536', 'ha.test:', 'ha..test',
                                          '-ha.test', 'ha.test ', '[not-ipv6]', '[::::]'))):
                for value in values:
                    with self.subTest(header=name, value=value):
                        self.header.update({'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'ha.test'})
                        self.header[name] = value
                        self.assertEqual(self.get('/api/csrf', port='8099').status_code, 400)

    def test_forwarded_origin_does_not_enable_https_outside_trusted_ingress(self):
        self.header = {'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'ha.example.test',
                       'Origin': 'https://ha.example.test'}
        for enabled, port in (('0', '80'), ('1', '8100')):
            with self.subTest(ingress=enabled, port=port), patch.dict(
                    os.environ, WEBCLOCK_INGRESS=enabled, WEBCLOCK_HA_APP=enabled):
                self.assertEqual(self.get('/api/csrf', port=port).status_code, 403)

    def test_ha_app_separates_ingress_management_from_lan_display(self):
        environment = {'WEBCLOCK_INGRESS': '1', 'WEBCLOCK_HA_APP': '1'}
        with patch.dict(os.environ, environment):
            ingress = self.get('/admin', port='8099')
            direct_ingress = self.client.get('/admin', environ_overrides={'SERVER_PORT': '8099'})
            display = self.client.get('/', environ_overrides={'SERVER_PORT': '8100'})
            display_time = self.client.get('/api/time', environ_overrides={'SERVER_PORT': '8100'})
            display_admin = self.client.get('/admin', environ_overrides={'SERVER_PORT': '8100'})
            display_shared = self.client.get('/api/status', environ_overrides={'SERVER_PORT': '8100'})
            display_traversal = self.client.get('/static/../admin', environ_overrides={'SERVER_PORT': '8100'})
            display_device = self.client.get('/api/v2/device/identity', environ_overrides={'SERVER_PORT': '8100'})
            display_esp = self.client.get('/api/v1/device/config', environ_overrides={'SERVER_PORT': '8100'})
        self.assertEqual(ingress.status_code, 200)
        self.assertEqual(direct_ingress.status_code, 403)
        self.assertEqual(display.status_code, 200)
        self.assertNotIn('id="alarm-manage"', display.get_data(as_text=True))
        self.assertIn('data-deployment-mode="managed"', display.get_data(as_text=True))
        self.assertEqual(display_time.status_code, 200)
        self.assertEqual(display_admin.status_code, 404)
        self.assertEqual(display_shared.status_code, 404)
        self.assertEqual(display_traversal.status_code, 404)
        self.assertNotEqual(display_device.status_code, 404)
        self.assertNotEqual(display_esp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
