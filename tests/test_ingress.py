import os
import unittest
from unittest.mock import patch

import app as clock


class IngressTest(unittest.TestCase):
    def setUp(self):
        self.client = clock.app.test_client()
        self.header = {'X-Ingress-Path': '/api/hassio_ingress/test-token'}

    def get(self, path='/', remote='172.30.32.2'):
        return self.client.get(path, headers=self.header,
                               environ_overrides={'REMOTE_ADDR': remote})

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


if __name__ == '__main__':
    unittest.main()
