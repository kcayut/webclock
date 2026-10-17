"""Run the public entry in disposable directories with local release downloads."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import update_settings

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'existing'
        self.project.mkdir()
        (self.project / 'VERSION').write_text('1.1.0')
        (self.project / 'private').write_text('preserved')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'invoked.json'
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        FIXTURE_ROOT=str(self.root), INVOKED=str(self.log), XDG_CACHE_HOME=str(self.root / 'cache'))
        (self.bin / 'python3').symlink_to(sys.executable)
        curl = self.bin / 'curl'
        curl.write_text('#!' + sys.executable + '\n' + '''import os, pathlib, shutil, sys
args = sys.argv[1:]
url = next(a for a in args if a.startswith('https://'))
if url.endswith('/latest'):
    print('https://github.com/kcayut/webclock/releases/tag/v1.2.0', end='')
else:
    shutil.copyfile(pathlib.Path(os.environ['FIXTURE_ROOT']) / url.rsplit('/', 1)[1], args[args.index('-o') + 1])
''')
        curl.chmod(0o755)
        (self.bin / 'docker').write_text('#!/bin/sh\nexit 0\n')
        (self.bin / 'docker').chmod(0o755)

    def archive(self, unsafe=False):
        path = self.root / 'webclock-1.2.0.tar.gz'
        files = {'VERSION': b'1.2.0\n', 'portable_docker_update.sh': (ROOT / 'scripts/update/portable_docker_update.sh').read_bytes(),
                 'scripts/docker_update.py':
                 b'import json, os, pathlib, sys\npathlib.Path(os.environ["INVOKED"]).write_text(json.dumps(sys.argv))\n'}
        for name in ('docker_update_install.py', 'docker_update_migrate.py', 'updater_service.py', 'release_versions.py', 'update_clock.py', 'update_settings.py'):
            files['scripts/' + name] = b'# fixture\n'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in files.items():
                item = tarfile.TarInfo('webclock-1.2.0/' + name)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
            if unsafe:
                item = tarfile.TarInfo('webclock-1.2.0/linked')
                item.type, item.linkname = tarfile.SYMTYPE, str(self.project / 'private')
                archive.addfile(item)
        (self.root / 'SHA256SUMS').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')

    def run_bootstrap(self, *args):
        return subprocess.run(['bash', str(ROOT / 'scripts/update/portable_docker_update.sh'), '--project', str(self.project), *args],
                              env=self.env, text=True, capture_output=True)

    def test_verified_release_uses_external_updater_and_preserves_host_files(self):
        self.archive()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertIn(str(self.project), command)
        self.assertIn('1.2.0', command)
        self.assertEqual((self.project / 'VERSION').read_text(), '1.1.0')
        self.assertEqual((self.project / 'private').read_text(), 'preserved')
        self.assertFalse((self.project / 'scripts').exists())

    def test_bad_checksum_or_archive_never_executes(self):
        self.archive()
        (self.root / 'SHA256SUMS').write_text('0' * 64 + '  webclock-1.2.0.tar.gz\n')
        self.assertNotEqual(self.run_bootstrap().returncode, 0)
        self.assertFalse(self.log.exists())
        self.archive(unsafe=True)
        self.assertNotEqual(self.run_bootstrap().returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual((self.project / 'private').read_text(), 'preserved')

    def test_old_installation_can_diagnose_recover_and_preview_cleanup(self):
        self.archive()
        for args in (('--diagnose',), ('--recover', 'current', '--operation', 'up-' + 'a' * 32, '--yes'),
                     ('--prune-backups', '3'), ('--prune-backups', '3', '--yes')):
            with self.subTest(args=args):
                result = self.run_bootstrap(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                command = json.loads(self.log.read_text())
                for value in args:
                    self.assertIn(value, command)
                self.assertNotIn('--version', command)
                if '--yes' not in args:
                    self.assertNotIn('--yes', command)
        self.assertFalse((self.project / 'scripts').exists())
        self.assertEqual((self.project / 'private').read_text(), 'preserved')

    def test_conflicting_actions_never_execute_the_updater(self):
        self.archive()
        for args in (('--check', '--diagnose'), ('--yes',), ('--diagnose', '--enable-updates'),
                     ('--recover', 'current', '--migrate-to', '/opt/webclock')):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_bootstrap(*args).returncode, 0)
                self.assertFalse(self.log.exists())

    def test_cached_recovery_works_offline_and_rejects_modified_tools(self):
        self.archive()
        result = self.run_bootstrap('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        cache = self.root / 'cache/webclock-docker-recovery/1.2.0'
        entry = cache / 'portable_docker_update.sh'
        self.assertTrue(entry.is_file())
        (self.bin / 'curl').write_text('#!/bin/sh\necho unexpected-network >&2\nexit 99\n')
        for args in (('--diagnose',), ('--recover', 'current', '--operation', 'up-' + 'a' * 32, '--yes')):
            result = subprocess.run(['bash', str(entry), '--offline', '--project', str(self.project), *args],
                                    env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('unexpected-network', result.stderr)
        self.log.unlink()
        (cache / 'scripts/docker_update.py').write_text('raise SystemExit("modified")')
        result = self.run_bootstrap('--offline', '--diagnose')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertIn('checksum mismatch', result.stderr)


class HostSettingsTest(unittest.TestCase):
    def test_settings_use_live_persisted_preferences_and_reject_other_installation(self):
        config = Mock()
        config.lstat.return_value = Mock(st_uid=0, st_mode=0o600)
        config.is_symlink.return_value = False
        config.read_text.return_value = json.dumps({'project': '/opt/webclock', 'kind': 'docker',
                                                  'socket_path': '/opt/webclock/webclock_updater_run/control.sock'})
        state = {'update_provider': 'docker', 'channel': 'beta', 'auto_update': True}
        with patch.object(update_settings.os, 'geteuid', return_value=0), \
             patch.object(update_settings, 'Path', side_effect=lambda value: config if value.startswith('/etc/') else Path(value)), \
             patch.object(update_settings, 'request', return_value=state) as request:
            update_settings.configure('docker', auto_update=False)
            self.assertEqual(request.call_args.args[1], {'action': 'configure', 'channel': 'beta', 'auto_update': False})
            request.reset_mock()
            with self.assertRaisesRegex(RuntimeError, 'another installation'):
                update_settings.configure('docker', project='/other', auto_update=False)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
