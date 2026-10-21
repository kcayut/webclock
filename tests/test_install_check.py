"""Fresh-install checks use disposable data; no service or container is started."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_check


def create_certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'clock.test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('clock.test')]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    certificate, private_key = directory / 'cert.pem', directory / 'key.pem'
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
    return certificate, private_key


class InstallCheckTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / '.env').write_text('PORT=49123\n')
        (self.root / 'VERSION').write_text('1.1.0\n')
        self.output = io.StringIO()

    def prepare(self, **kwargs):
        with redirect_stdout(self.output):
            install_check.prepare(self.root, kwargs.pop('kind', 'docker'), kwargs.pop('mode', 'self'),
                                  str(self.root), kwargs.pop('existing', False), **kwargs)

    def test_retry_allows_port_fix_but_preserves_identity_and_protection(self):
        self.prepare()
        marker = self.root / install_check.MARKER
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        (self.root / '.env').write_text('WEBCLOCK_HTTP_PORT=8080\n')
        self.prepare(existing=True)
        self.assertEqual(json.loads(marker.read_text())['config']['port'], 8080)
        saved = marker.read_bytes()
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.prepare(mode='managed', guard_only=True)
        self.assertEqual(marker.read_bytes(), saved)
        state = self.root / 'webclock_state'
        state.mkdir()
        (state / 'auth-required').write_text('{"version":1,"mode":"managed"}')
        with self.assertRaisesRegex(RuntimeError, 'authorization'):
            self.prepare()
        self.assertEqual(marker.read_bytes(), saved)

    def test_existing_notes_custom_notes_state_and_symlinks_are_preserved(self):
        notes = self.root / 'notes.json'
        notes.write_text('[{"text":"private"}]')
        (self.root / '.env').write_text('NOTES_FILE=notes.json\n')
        with self.assertRaisesRegex(ValueError, 'reminder data'):
            self.prepare(kind='systemd')
        (self.root / '.env').write_text('WEBCLOCK_STATE_DIR=scripts\n')
        with self.assertRaisesRegex(ValueError, 'program files'):
            self.prepare(kind='systemd')
        (self.root / '.env').write_text('')
        (self.root / 'webclock_state').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare()
        self.assertEqual(notes.read_text(), '[{"text":"private"}]')
        self.assertFalse((self.root / install_check.MARKER).exists())

    def test_invalid_config_and_marker_fail_closed(self):
        for settings in ('WEBCLOCK_HTTP_PORT=0', 'WEBCLOCK_STATE_DIR=/other', 'WEBCLOCK_ALLOW_HTTP=yes',
                         'WEBCLOCK_TLS_CERT=/etc/cert.pem', 'WEBCLOCK_TLS_CERT=/app/tls/../cert.pem'):
            (self.root / '.env').write_text(settings + '\n')
            with self.assertRaises(ValueError):
                self.prepare()
        (self.root / '.env').write_text('')
        marker = self.root / install_check.MARKER
        marker.write_text('[]')
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.prepare(guard_only=True)

    def test_notes_cannot_alias_authorization_or_other_application_state(self):
        for name in ('auth.json', 'auth-required', 'settings.json', 'schedules.json',
                     'device-access.json', 'owners/member/manual_notes.json',
                     '.portable-restore-pending/journal.json'):
            with self.subTest(name=name):
                (self.root / '.env').write_text('NOTES_FILE=webclock_state/' + name + '\n')
                with self.assertRaisesRegex(ValueError, 'overlap'):
                    self.prepare(kind='systemd', guard_only=True)
                self.assertFalse((self.root / install_check.MARKER).exists())
        (self.root / '.env').write_text('NOTES_FILE=webclock_state/reminders.json\n')
        self.prepare(kind='systemd', guard_only=True)

    def test_health_rejects_a_different_running_release(self):
        self.prepare()
        record = json.loads((self.root / install_check.MARKER).read_text())
        with patch.object(install_check.time, 'monotonic', side_effect=[0, 0, 1, 1]), \
                patch.object(install_check.time, 'sleep'), \
                patch.object(install_check, 'check_public_health', return_value={'version': '1.0.0'}):
            with self.assertRaisesRegex(RuntimeError, 'version'):
                install_check.wait_ready(self.root, record, timeout=1)
        self.assertTrue((self.root / install_check.MARKER).exists())

    def test_managed_tls_checks_trust_hostname_and_matching_key(self):
        cert, key = create_certificate(self.root)
        config = {'WEBCLOCK_TLS_CERT': str(cert), 'WEBCLOCK_TLS_KEY': str(key),
                  'WEBCLOCK_UPDATE_HOST': 'clock.test', 'WEBCLOCK_UPDATE_CA': str(cert), 'host': '0.0.0.0'}
        install_check.validate_tls(config, True)
        with self.assertRaises(ValueError):
            install_check.validate_tls({'host': '0.0.0.0'}, True)
        with self.assertRaises(install_check.ssl.SSLError):
            install_check.validate_tls(dict(config, WEBCLOCK_UPDATE_HOST='wrong.test'), True)
        with self.assertRaises(install_check.ssl.SSLError):
            install_check.validate_tls(dict(config, WEBCLOCK_UPDATE_CA=None), True)
        other = self.root / 'other'
        other.mkdir()
        _, other_key = create_certificate(other)
        with self.assertRaises(install_check.ssl.SSLError):
            install_check.validate_tls(dict(config, WEBCLOCK_TLS_KEY=str(other_key)), True)

    def test_http_confirmation_and_tls_upgrade_persist_only_valid_choices(self):
        env = self.root / '.env'
        env.write_text('PORT=49123\n# keep this setting\nWEBCLOCK_ALLOW_HTTP=0\n')
        with patch('builtins.input', side_effect=['n', 'HTTP']), redirect_stdout(self.output):
            install_check.configure_transport(self.root)
        self.assertIn('# keep this setting', env.read_text())
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        config = install_check.configuration(self.root)
        install_check.validate_tls(config, True)
        cert, key = create_certificate(self.root)
        env.write_text(env.read_text() + f'WEBCLOCK_TLS_CERT={cert}\nWEBCLOCK_TLS_KEY={key}\n'
                       f'WEBCLOCK_UPDATE_HOST=wrong.test\nWEBCLOCK_UPDATE_CA={cert}\n')
        original = env.read_bytes()
        with patch('builtins.input', side_effect=AssertionError('TLS must not fall back to HTTP')):
            with self.assertRaises(install_check.ssl.SSLError):
                install_check.configure_transport(self.root)
        self.assertEqual(env.read_bytes(), original)
        env.write_text(env.read_text().replace('wrong.test', 'clock.test'))
        with redirect_stdout(self.output):
            install_check.configure_transport(self.root)
        self.assertEqual(install_check.configuration(self.root)['WEBCLOCK_ALLOW_HTTP'], '0')
        self.assertEqual(env.read_text().count('WEBCLOCK_ALLOW_HTTP='), 1)
        with self.assertRaises(ValueError):
            install_check.validate_tls(dict(config, WEBCLOCK_TLS_CERT=str(cert)), True)

    def test_port_check_precedes_marker(self):
        with patch.object(install_check.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError('busy')
            with self.assertRaisesRegex(ValueError, 'Port 49123 is unavailable'):
                self.prepare(kind='systemd')
        self.assertFalse((self.root / install_check.MARKER).exists())

    def test_health_retries_checks_mode_and_reports_failure(self):
        self.prepare()
        record = json.loads((self.root / install_check.MARKER).read_text())
        with patch.object(install_check, 'check_public_health', side_effect=[OSError('starting'), {'version': '1.1.0'}]) as health, \
                patch.object(install_check.time, 'sleep'):
            install_check.wait_ready(self.root, record)
        self.assertEqual(health.call_count, 2)
        health.assert_called_with('http://host.docker.internal:80', deployment_mode='self', tls_handler=None)
        with patch.object(install_check.time, 'monotonic', side_effect=[0, 0, 1, 1]), \
                patch.object(install_check.time, 'sleep'), \
                patch.object(install_check, 'check_public_health', side_effect=RuntimeError('wrong mode')):
            with self.assertRaisesRegex(RuntimeError, 'wrong mode'):
                install_check.wait_ready(self.root, record, timeout=1)
        self.assertTrue((self.root / install_check.MARKER).exists())

    def test_full_urls_when_host_lookup_fails_or_tls_uses_name(self):
        record = {'kind': 'systemd', 'config': {'host': '::', 'port': 5000}}
        with redirect_stdout(self.output), patch.object(socket, 'getaddrinfo', side_effect=socket.gaierror), \
                patch.object(socket, 'gethostname', return_value='clock-host'):
            install_check.print_urls(record)
        self.assertIn('http://clock-host:5000/admin', self.output.getvalue())
        record['config'].update(WEBCLOCK_TLS_CERT='cert.pem', WEBCLOCK_UPDATE_HOST='clock.test')
        with redirect_stdout(self.output):
            install_check.print_urls(record)
        self.assertIn('https://clock.test:5000/admin', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
