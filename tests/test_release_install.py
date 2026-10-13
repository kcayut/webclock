"""Exercise the public bootstrap without network, Docker or system changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import update_clock

ROOT = Path(__file__).resolve().parents[1]


class ReleaseInstallTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        seed = self.root / 'webclock-1.1.0'
        seed.mkdir()
        (seed / 'VERSION').write_text('1.1.0\n')
        (seed / '.env.example').write_text('PORT=5000\n')
        (seed / 'setup.sh').write_text('''#!/bin/bash
set -eu
project="$(cd "$(dirname "$0")" && pwd)"
printf '%s\\n' "$@" > "$project/setup-args"
exit "${SETUP_EXIT:-0}"
''')
        archive = self.assets / 'webclock-1.1.0.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            stream.add(seed, arcname=seed.name)
        (self.assets / 'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        FIXTURE_ASSETS=str(self.assets), FIXTURE_ROOT=str(self.root))
        for name in ('PORT', 'WEBCLOCK_HTTP_PORT', 'WEBCLOCK_VERSION'):
            self.env.pop(name, None)
        self.command('docker', 'pass')
        self.command('uname', 'print("Linux")')
        self.command('apt-get', 'raise SystemExit("Unexpected package installation")')
        self.command('systemctl', 'pass')
        self.command('git', '''
if sys.argv[1] == 'clone':
    shutil.copytree(Path(os.environ['FIXTURE_ROOT']) / 'webclock-1.1.0', sys.argv[-1])
    (Path(sys.argv[-1]) / '.git').mkdir()
elif sys.argv[1] == '-C':
    (Path(sys.argv[2]) / 'git-config').write_text(' '.join(sys.argv[3:]))
''')
        self.command('curl', '''
args = sys.argv[1:]
url = next(value for value in args if value.startswith('https://'))
with (Path(os.environ['FIXTURE_ROOT']) / 'downloads').open('a') as log:
    log.write(url + '\\n')
if url.endswith('/latest'):
    print('https://github.com/kcayut/webclock/releases/tag/v1.1.0', end='')
else:
    shutil.copyfile(Path(os.environ['FIXTURE_ASSETS']) / url.rsplit('/', 1)[1], args[args.index('-o') + 1])
''')

    def command(self, name, source):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\nimport os, sys, shutil\nfrom pathlib import Path\n' + source)
        path.chmod(0o755)

    def install(self, *args):
        return subprocess.run(['/bin/bash', str(ROOT / 'install.sh'), '--dir', str(self.root / 'installed'), *args],
                              env=self.env, cwd=self.root, capture_output=True, text=True)

    def test_docker_latest_download_is_verified_pinned_and_preserves_port(self):
        self.env['WEBCLOCK_HTTP_PORT'] = '8080'
        result = self.install('--docker')
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.root / 'installed'
        self.assertIn('WEBCLOCK_VERSION=1.1.0', (installed / '.env').read_text())
        self.assertIn('WEBCLOCK_HTTP_PORT=8080', (installed / '.env').read_text())
        self.assertFalse((installed / '.webclock-bootstrap').exists())
        self.assertNotEqual(self.install('--docker').returncode, 0)

    def test_corrupt_download_never_creates_destination(self):
        with (self.assets / 'webclock-1.1.0.tar.gz').open('ab') as stream:
            stream.write(b'corruption')
        result = self.install('--docker', '--version', '1.1.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse((self.root / 'installed').exists())
        self.assertNotIn('/latest', (self.root / 'downloads').read_text())

    def test_failed_setup_can_resume_without_replacing_source_or_data(self):
        self.env['SETUP_EXIT'] = '1'
        self.assertNotEqual(self.install('--docker').returncode, 0)
        installed = self.root / 'installed'
        (installed / 'user-data').write_text('keep')
        downloaded = (self.root / 'downloads').read_text()
        self.env['SETUP_EXIT'] = '0'
        result = self.install('--docker')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((installed / 'user-data').read_text(), 'keep')
        self.assertEqual((self.root / 'downloads').read_text(), downloaded)
        self.assertFalse((installed / '.webclock-bootstrap').exists())

    def test_linux_pins_tag_channel_and_empty_bash_array_works(self):
        result = self.install('--version', '1.1.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'installed/git-config').read_text(), 'config webclock.releaseChannel stable')
        self.assertNotIn('/latest', (self.root / 'downloads').read_text())
        self.assertNotEqual(self.install('--version', '../main').returncode, 0)

    def test_explicit_prerelease_install_tracks_beta_channel(self):
        (self.root / 'webclock-1.1.0/VERSION').write_text('1.2.0-beta.1\n')
        result = self.install('--version', '1.2.0-beta.1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'installed/git-config').read_text(), 'config webclock.releaseChannel beta')
        self.assertIn('WEBCLOCK_VERSION=1.2.0-beta.1', (self.root / 'installed/.env').read_text())

    def test_invalid_prerelease_never_downloads_or_creates_destination(self):
        for invalid in ('1.2.0-beta.01', '1.2.0-', '1.2.0-rc..1', '1.2.0+build.1'):
            with self.subTest(version=invalid):
                self.assertNotEqual(self.install('--version', invalid).returncode, 0)
                self.assertFalse((self.root / 'downloads').exists())
                self.assertFalse((self.root / 'installed').exists())


class ReleaseUpdateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / 'VERSION').write_text('1.1.0\n')
        self.release = {'tag_name': 'v1.1.1', 'latest_version': '1.1.1', 'update_available': True}

    def test_stable_channel_selects_only_a_published_versioned_tag(self):
        calls = []
        def run(args, cwd=None):
            calls.append(args)
            if args[1:3] == ['config', '--get']:
                return 'stable'
            if args[1] == 'rev-parse':
                return 'release-commit'
            if args[1] == 'show':
                return '1.1.1'
            return ''
        with patch.object(update_clock, 'run', side_effect=run), \
             patch.object(update_clock.release_versions, 'discover_release', return_value=self.release) as discover:
            self.assertEqual(update_clock.update_target(self.project, ['git']), 'release-commit')
            discover.assert_called_once_with('stable', '1.1.0')
        self.assertIn(['git', 'fetch', 'https://github.com/kcayut/webclock.git', 'tag', 'v1.1.1'], calls)
        self.assertFalse(any('@{upstream}' in call for call in calls))

    def test_unchanged_release_does_not_fetch_or_reset(self):
        with patch.object(update_clock, 'run') as git, \
             patch.object(update_clock.release_versions, 'discover_release',
                          return_value={**self.release, 'update_available': False}):
            self.assertIsNone(update_clock.update_target(self.project, ['git'], channel='stable'))
            git.assert_not_called()

    def test_explicit_beta_and_pinned_version_are_checked_before_fetching(self):
        candidate = {**self.release, 'tag_name': 'v1.2.0-beta.1', 'latest_version': '1.2.0-beta.1'}
        with patch.object(update_clock, 'run') as git, \
             patch.object(update_clock.release_versions, 'discover_release', return_value=candidate) as discover:
            with self.assertRaisesRegex(RuntimeError, 'Available release changed'):
                update_clock.update_target(self.project, ['git'], channel='beta', expected_version='1.1.1')
            discover.assert_called_once_with('beta', '1.1.0')
            git.assert_not_called()

    def test_tag_must_contain_its_claimed_product_version(self):
        with patch.object(update_clock, 'run', return_value='1.1.0'), \
             patch.object(update_clock.release_versions, 'discover_release', return_value=self.release):
            with self.assertRaisesRegex(RuntimeError, 'tag and product version differ'):
                update_clock.update_target(self.project, ['git'], channel='stable')

    def test_unknown_channel_is_rejected_before_network_access(self):
        with patch.object(update_clock.release_versions, 'discover_release') as discover:
            with self.assertRaisesRegex(RuntimeError, 'Unknown WebClock release channel'):
                update_clock.update_target(self.project, ['git'], channel='nightly')
            discover.assert_not_called()

    def test_developer_checkout_keeps_its_configured_upstream(self):
        def run(args, cwd=None):
            if args[1] == 'config':
                raise subprocess.CalledProcessError(1, args)
            return 'development-commit' if args[1] == 'rev-parse' else ''
        with patch.object(update_clock, 'run', side_effect=run), \
             patch.object(update_clock.release_versions, 'discover_release') as network:
            self.assertEqual(update_clock.update_target(Path('/test'), ['git']), 'development-commit')
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
