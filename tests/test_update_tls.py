"""Exercise updater TLS using a temporary local HTTPS server and certificate."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
from threading import Thread
import unittest
from urllib.error import URLError

import update_clock as updater


@unittest.skipUnless(shutil.which('openssl'), 'TLS integration check requires openssl')
class UpdateTLSTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.project = Path(directory.name)
        (cls.project / 'openssl.cnf').write_text('''
[req]
distinguished_name = dn
x509_extensions = extensions
prompt = no
[dn]
CN = webclock.invalid
[extensions]
subjectAltName = DNS:webclock.invalid,DNS:localhost,IP:127.0.0.1
basicConstraints = critical,CA:TRUE
keyUsage = critical,digitalSignature,keyEncipherment,keyCertSign
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
''')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-config', str(cls.project / 'openssl.cnf'), '-keyout', str(cls.project / 'key.pem'),
                        '-out', str(cls.project / 'cert.pem')], check=True, capture_output=True)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', 'http://127.0.0.1:1/api/health')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', 'session=csrf; Secure; Path=/')
                self.end_headers()
                payload = ({'csrf_token': 'test-token'} if self.path == '/api/csrf' else
                           {'status': 'ok', 'auth_schema': 1, 'deployment_mode': 'managed'})
                self.wfile.write(json.dumps(payload).encode())

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if self.headers.get('X-CSRF-Token') != 'test-token' or self.headers.get('Cookie') != 'session=csrf':
                    self.send_error(403)
                    return
                self.do_GET()

        cls.server = HTTPServer(('127.0.0.1', 0), Handler)
        cls.addClassCleanup(cls.server.server_close)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.project / 'cert.pem', cls.project / 'key.pem')
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        thread = Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = 'https://127.0.0.1:' + str(cls.server.server_port)

    def handler(self, **overrides):
        return updater.update_tls_handler(self.project, {
            'WEBCLOCK_TLS_CERT': 'cert.pem', 'WEBCLOCK_TLS_KEY': 'key.pem',
            'WEBCLOCK_UPDATE_CA': 'cert.pem', **overrides,
        })

    def test_local_ip_and_explicit_certificate_name_keep_certificate_verification(self):
        for name in (None, 'webclock.invalid'):
            with self.subTest(name=name):
                handler = self.handler(WEBCLOCK_UPDATE_HOST=name)
                self.assertEqual(updater.check_public_health(self.url, tls_handler=handler)['status'], 'ok')
                self.assertEqual(updater.http_json(self.url + '/api/control', {'brightness': 40},
                                                  tls_handler=handler)['status'], 'ok')
                self.assertTrue(handler._context.check_hostname)
                self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)

    def test_untrusted_or_wrong_host_certificate_is_rejected(self):
        for overrides in ({'WEBCLOCK_UPDATE_CA': None}, {'WEBCLOCK_UPDATE_HOST': 'wrong.invalid'}):
            with self.subTest(overrides=overrides), self.assertRaises(URLError) as rejected:
                updater.http_json(self.url + '/api/health', tls_handler=self.handler(**overrides))
            self.assertIsInstance(rejected.exception.reason, ssl.SSLCertVerificationError)

    def test_https_health_check_cannot_redirect_to_http_or_another_server(self):
        with self.assertRaisesRegex(RuntimeError, 'must not redirect'):
            updater.http_json(self.url + '/redirect', tls_handler=self.handler())

    def test_plain_http_does_not_require_tls_configuration(self):
        self.assertIsNone(updater.update_tls_handler(self.project, {}))


if __name__ == '__main__':
    unittest.main()
