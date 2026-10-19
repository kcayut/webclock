"""Exercise installers in disposable folders; never install packages or services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import app as clock

ROOT = Path(__file__).resolve().parents[1]


class InstallationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'webclock'
        (self.project / 'scripts').mkdir(parents=True)
        for name in ('setup.sh', '.env.example', 'requirements.txt'):
            shutil.copy2(ROOT / name, self.project / name)
        source = (ROOT / 'scripts/setup.sh').read_text().replace(
            '/etc/systemd/system/webclock.service', str(self.root / 'webclock.service'))
        (self.project / 'scripts/setup.sh').write_text(source)
        (self.project / 'scripts/enable_updates.sh').write_text('printf "enable_updates\\n" >> "$INSTALL_LOG"\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        INSTALL_LOG=str(self.root / 'commands'), REAL_PYTHON=sys.executable,
                        SUDO_USER='installer-test')
        for key in ('WEBCLOCK_STATE_DIR', 'NOTES_FILE', 'PORT', 'WEBCLOCK_TLS_CERT', 'WEBCLOCK_TLS_KEY'):
            self.env.pop(key, None)
        for name in ('install_check.py', 'update_clock.py'):
            shutil.copy2(ROOT / 'scripts' / name, self.project / 'scripts' / name)
        runner = self.project / 'scripts/install_runner.py'
        runner.write_text('''import os
import install_check
from unittest.mock import patch
def wait(*args, **kwargs):
    if os.environ.get('FAIL_HEALTH'):
        raise RuntimeError('simulated readiness failure')
install_check.wait_ready = wait
with patch.object(install_check.socket, 'socket'):
    install_check.main()
''')
        self.env['PYTHONPATH'] = str(ROOT)
        self.env['TEST_PROJECT'] = str(self.project)
        self.command('docker', '''printf 'docker %s\\n' "$*" >> "$INSTALL_LOG"
if [[ "$*" == 'compose run '* && " $* " == *' --no-build '* ]]; then
    echo 'unknown flag: --no-build' >&2; exit 1
fi
if [ "$*" = 'compose ps -aq' ]; then printf '%s' "${EXISTING_CONTAINER:-}"; fi
if [ "$*" = 'compose config --images' ]; then echo webclock-test; fi
if [[ "$*" == *'scripts/install_check.py'* ]]; then
    while [ "$1" != scripts/install_check.py ]; do shift; done
    shift
    exec "$REAL_PYTHON" scripts/install_runner.py "$@"
fi
if [[ "$*" == *'manage_auth.py setup'* && "$*" != "${FAIL_DOCKER:-unused}" ]]; then
    "$REAL_PYTHON" -c 'from pathlib import Path; from webclock.services.auth_service import AuthService; AuthService(Path("webclock_state/auth.json")).setup("admin", "installer-test-password", enable_managed=True)'
fi
if [ "$*" = "${FAIL_DOCKER:-unused}" ]; then exit 1; fi
''')

    def command(self, name, source):
        path = self.bin / name
        path.write_text('#!/bin/bash\nset -eu\n' + source)
        path.chmod(0o755)
        return path

    def run_setup(self, *args):
        return subprocess.run(['bash', str(self.project / 'setup.sh'), *args], cwd=self.root,
                              env=self.env, text=True, capture_output=True)

    def log(self):
        return (self.root / 'commands').read_text()

    def test_docker_release_pull_health_and_explicit_build(self):
        self.env['WEBCLOCK_HTTP_PORT'] = '8181'
        self.command('python3', 'exit 91\n')
        result = self.run_setup('--docker')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.project / 'manual_notes.json').read_text()), [])
        self.assertEqual((self.project / '.env').stat().st_mode & 0o777, 0o600)
        self.assertIn('WEBCLOCK_HTTP_PORT=8181', (self.project / '.env').read_text())
        log = self.log()
        self.assertIn('compose pull webclock', log)
        self.assertNotIn('compose build', log)
        self.assertNotIn('enable_updates', log)
        self.assertIn('-p 8181:5000', log)
        self.assertLess(log.index('compose up -d --no-build'), log.index('install_check.py wait'))
        self.assertIn(':8181/admin', result.stdout)
        self.assertFalse((self.project / '.webclock-install.json').exists())
        (self.root / 'commands').unlink()
        result = self.run_setup('--docker', '--build')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('compose build', self.log())
        self.assertNotIn('compose pull', self.log())

    def test_managed_rejects_missing_tls_before_password_or_start(self):
        result = self.run_setup('--docker', '--managed')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('valid HTTPS', result.stderr)
        self.assertNotIn('manage_auth', self.log())
        self.assertNotIn('compose up', self.log())

    def test_failed_managed_health_resumes_without_resetting_credentials(self):
        from tests.test_install_check import create_certificate
        cert, key = create_certificate(self.root)
        args = ('--docker', '--managed', '--tls-cert', str(cert), '--tls-key', str(key),
                '--tls-host', 'clock.test', '--tls-ca', str(cert))
        self.env['FAIL_HEALTH'] = '1'
        result = self.run_setup(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        auth = self.project / 'webclock_state/auth.json'
        original = auth.read_bytes()
        self.assertTrue((self.project / '.webclock-install.json').exists())
        self.assertEqual(self.log().count('manage_auth.py setup'), 1)
        self.env.pop('FAIL_HEALTH')
        self.env['EXISTING_CONTAINER'] = 'pending-container'
        self.env['WEBCLOCK_HTTP_PORT'] = '8282'
        result = self.run_setup(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(auth.read_bytes(), original)
        self.assertEqual(self.log().count('manage_auth.py setup'), 1)
        self.assertIn('https://clock.test:8282/admin', result.stdout)
        self.assertFalse((self.project / '.webclock-install.json').exists())

    def test_docker_failure_prevents_start(self):
        self.env['FAIL_DOCKER'] = 'compose pull webclock'
        self.assertNotEqual(self.run_setup('--docker').returncode, 0)
        self.assertNotIn('compose up', self.log())
        self.env['FAIL_DOCKER'] = 'compose ps -aq'
        self.assertNotEqual(self.run_setup('--docker').returncode, 0)
        self.assertNotIn('compose up', self.log())

    def test_existing_data_and_containers_are_preserved(self):
        (self.project / '.env').write_text('PORT=9123\nWEBCLOCK_LANGUAGE=ja\n')
        (self.project / 'manual_notes.json').write_text('[{"text":"keep"}]')
        state = self.project / 'webclock_state'
        state.mkdir()
        (state / 'auth-required').write_text('protected')
        before = {p: p.read_bytes() for p in (self.project / '.env', self.project / 'manual_notes.json', state / 'auth-required')}
        self.assertNotEqual(self.run_setup('--docker', '--managed').returncode, 0)
        self.assertNotIn('compose build', self.log())
        self.env['EXISTING_CONTAINER'] = 'existing-container'
        self.assertNotEqual(self.run_setup('--docker').returncode, 0)
        self.assertNotIn('compose up', self.log())
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_bare_metal_defaults_and_existing_unit_guard(self):
        self.command('uname', 'echo Linux\n')
        self.command('id', 'if [ "$1" = -u ]; then echo 0; else echo installer-test; fi\n')
        self.command('systemctl', '''printf 'systemctl %s\\n' "$*" >> "$INSTALL_LOG"
if [ "$1" = cat ]; then exit "${UNIT_MISSING:-1}"; fi
if [ "$1" = show ]; then echo "$TEST_PROJECT"; fi
''')
        self.command('apt-get', 'printf "apt-get %s\\n" "$*" >> "$INSTALL_LOG"\n')
        self.command('chown', ':\n')
        self.command('install', 'mkdir -p "${@: -1}"\n')
        self.command('runuser', 'shift 3; exec "$@"\n')
        venv = self.project / 'venv/bin'
        venv.mkdir(parents=True)
        python = self.command('python-wrapper', '''if [ "$1" = -m ]; then exit 0; fi
if [ "$1" = scripts/install_check.py ]; then shift; exec "$REAL_PYTHON" scripts/install_runner.py "$@"; fi
exec "$REAL_PYTHON" "$@"
''')
        shutil.copy2(python, venv / 'python')
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('5000', result.stdout)
        unit = (self.root / 'webclock.service').read_text()
        self.assertIn('User=installer-test', unit)
        self.assertIn('systemctl restart webclock', self.log())
        self.assertLess(self.log().index('systemctl restart webclock'), self.log().index('enable_updates'))
        self.assertNotIn('manage_auth', self.log())
        (self.root / 'commands').unlink()
        self.env['UNIT_MISSING'] = '0'
        self.assertNotEqual(self.run_setup().returncode, 0)
        self.assertNotIn('apt-get', self.log())
        self.assertEqual((self.root / 'webclock.service').read_text(), unit)

    def test_ha_package_is_complete_and_does_not_replace_or_include_private_state(self):
        destination = self.root / 'local-app'
        script = ROOT / 'homeassistant/prepare_local_app.sh'
        result = subprocess.run(['bash', str(script), str(destination)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('config.yaml', 'Dockerfile', 'DOCS.md', 'CHANGELOG.md', 'icon.png', 'app.py', 'sw.js', 'VERSION', 'requirements.txt',
                     'webclock/ha_app.py', 'templates/index.html', 'static/clock.js'):
            self.assertTrue((destination / name).is_file(), name)
        self.assertNotIn('\nimage:', (destination / 'config.yaml').read_text())
        for name in ('.env', 'webclock_state', 'manual_notes.json', 'tls', '.git', 'venv'):
            self.assertFalse((destination / name).exists(), name)
        (destination / 'keep').write_text('keep')
        result = subprocess.run(['bash', str(script), str(destination)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((destination / 'keep').read_text(), 'keep')
        result = subprocess.run(['bash', str(script), 'relative-app'], cwd=self.root, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'relative-app/config.yaml').is_file())

    def test_hacs_download_is_a_self_contained_integration(self):
        hacs = json.loads((ROOT / 'hacs.json').read_text())
        self.assertEqual(hacs['name'], 'WebClock')
        self.assertTrue(hacs['homeassistant'])
        components = ROOT / 'custom_components'
        self.assertEqual([p.name for p in components.iterdir() if p.is_dir() and not p.name.startswith('__')], ['webclock'])
        component = components / 'webclock'
        manifest = json.loads((component / 'manifest.json').read_text())
        self.assertEqual(manifest['domain'], 'webclock')
        self.assertTrue(manifest['config_flow'])
        for name in ('__init__.py', 'config_flow.py', 'sensor.py', 'strings.json', 'services.yaml',
                     'www/webclock-cards.js', 'brand/icon.png',
                     'translations/en.json', 'translations/zh-Hant.json', 'translations/ja.json'):
            self.assertTrue((component / name).is_file(), name)
        self.assertFalse((ROOT / 'homeassistant/custom_components').exists())

    def test_http_tls_and_incomplete_tls_configuration(self):
        for values, expected in (({}, None), ({'WEBCLOCK_TLS_CERT': 'cert.pem', 'WEBCLOCK_TLS_KEY': 'key.pem'}, ('cert.pem', 'key.pem'))):
            with patch.dict(os.environ, values, clear=True), patch.object(clock.app, 'run') as run:
                clock.main()
                run.assert_called_once_with(host='0.0.0.0', port=5000, ssl_context=expected)
        for key in ('WEBCLOCK_TLS_CERT', 'WEBCLOCK_TLS_KEY'):
            with patch.dict(os.environ, {key: 'file.pem'}, clear=True), patch.object(clock.app, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'both'):
                    clock.main()
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
