"""Release assets must agree on their version and contain committed public files only."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

from scripts.build_release import CLOCK_FILES, build_release, check_versions


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'repository'
        self.root.mkdir()
        self.files = {name: 'public\n' for name in CLOCK_FILES}
        self.files.update({
            'VERSION': '1.1.0\n',
            'custom_components/webclock/manifest.json': json.dumps({'version': '1.1.0'}),
            'custom_components/webclock/const.py': 'VERSION = "1.1.0"\n',
            'homeassistant/addon/config.yaml': 'version: "1.1.0"\nimage: ghcr.io/kcayut/webclock-addon\n',
            'docker-compose.yml': 'image: ghcr.io/kcayut/webclock:${WEBCLOCK_VERSION:-1.1.0}\n',
            'Dockerfile': 'LABEL org.opencontainers.image.version="${BUILD_VERSION}"\n',
            'homeassistant/addon/Dockerfile': 'LABEL org.opencontainers.image.version="${BUILD_VERSION}"\n',
            'install.sh': '#!/bin/sh\nRELEASE_VERSION=""\necho install\n', 'setup.sh': '#!/bin/sh\n',
            'scripts/setup.sh': '#!/bin/sh\n', 'app.py': '# committed application\n',
            'webclock/app.py': '# committed server\n', '.env.example': 'EXAMPLE=1\n',
            '.dockerignore': '.env\n', '.gitignore': '.env\n', 'CHANGELOG.md': '# Release history\n',
            'static/brand/logo.svg': '<svg/>', 'webclock/data/taiwan_calendar.json': '{}',
            '.env': 'secret', 'webclock_state/auth.json': 'secret',
            'webclock/auth.json': 'secret', 'static/tls/private.key': 'secret',
            'scripts/__pycache__/private.pyc': 'secret', 'doc/.webclock-backup-secret/data': 'secret',
            'manual_notes.json': 'secret',
        })

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT)

    def commit(self):
        for name, content in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.root / 'install.sh').chmod(0o755)
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Release Test', '-c', 'user.email=release@example.test', 'commit', '-qm', 'fixture')

    def test_versions_and_tag_must_match(self):
        self.assertEqual(check_versions(self.files.__getitem__, 'v1.1.0'), '1.1.0')
        with self.assertRaisesRegex(ValueError, 'tag'):
            check_versions(self.files.__getitem__, 'v1.0.0')
        for name in ('VERSION', 'custom_components/webclock/manifest.json',
                     'custom_components/webclock/const.py', 'homeassistant/addon/config.yaml', 'docker-compose.yml'):
            changed = dict(self.files)
            changed[name] = changed[name].replace('1.1.0', '1.2.0')
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_versions(changed.__getitem__)

    def test_prerelease_versions_package_with_their_complete_version(self):
        self.files = {name: content.replace('1.1.0', '1.2.0-beta.2') for name, content in self.files.items()}
        self.commit()
        output = self.root.parent / 'beta-assets'
        self.assertEqual(build_release(output, '1.2.0-beta.2', self.root), '1.2.0-beta.2')
        self.assertTrue((output / 'webclock-1.2.0-beta.2.tar.gz').exists())
        self.assertIn('RELEASE_VERSION="1.2.0-beta.2"', (output / 'install.sh').read_text())
        for invalid in ('1.2.0-beta.01', '01.2.0', '1.2.0+build.1'):
            with self.subTest(version=invalid), self.assertRaises(ValueError):
                check_versions(lambda name: self.files[name].replace('1.2.0-beta.2', invalid))

    def test_assets_use_committed_public_files_and_reproducible_checksums(self):
        self.commit()
        (self.root / 'app.py').write_text('local private change')
        (self.root / 'scripts/untracked.py').write_text('local secret')
        output = self.root.parent / 'assets'
        self.assertEqual(build_release(output, '1.1.0', self.root), '1.1.0')
        self.assertIn('RELEASE_VERSION="1.1.0"', (output / 'install.sh').read_text())
        prefix = 'webclock-1.1.0/'
        with tarfile.open(output / 'webclock-1.1.0.tar.gz') as server:
            names = server.getnames()
            self.assertEqual(server.extractfile(prefix + 'app.py').read(), b'# committed application\n')
            self.assertEqual(server.getmember(prefix + 'install.sh').mode, 0o755)
            self.assertIn(prefix + '.env.example', names)
            self.assertIn(prefix + '.dockerignore', names)
            self.assertIn(prefix + '.gitignore', names)
            self.assertIn(prefix + 'CHANGELOG.md', names)
            self.assertIn(prefix + 'webclock/data/taiwan_calendar.json', names)
            self.assertNotIn(prefix + 'scripts/untracked.py', names)
            self.assertFalse(any('secret' in name or 'auth.json' in name or '__pycache__' in name for name in names), names)
            self.assertNotIn(prefix + '.env', names)
            self.assertNotIn(prefix + 'manual_notes.json', names)
        with zipfile.ZipFile(output / 'webclock-clock-1.1.0.zip') as clock:
            names = {name.removeprefix('webclock-clock-1.1.0/') for name in clock.namelist()}
            self.assertEqual(names, CLOCK_FILES | {'static/brand/logo.svg'})
        for row in (output / 'SHA256SUMS').read_text().splitlines():
            digest, name = row.split('  ')
            self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
        second = self.root.parent / 'second'
        build_release(second, '1.1.0', self.root)
        self.assertEqual((output / 'SHA256SUMS').read_bytes(), (second / 'SHA256SUMS').read_bytes())

    def test_packaging_rejects_symlinks_and_wrong_requested_version(self):
        self.commit()
        with self.assertRaisesRegex(ValueError, 'tag'):
            build_release(self.root.parent / 'wrong', '1.2.0', self.root)
        (self.root / 'scripts/linked-secret').symlink_to('/tmp/private-credential')
        self.git('add', 'scripts/linked-secret')
        self.git('-c', 'user.name=Release Test', '-c', 'user.email=release@example.test', 'commit', '-qm', 'symlink')
        with self.assertRaisesRegex(ValueError, 'regular files'):
            build_release(self.root.parent / 'linked', '1.1.0', self.root)


if __name__ == '__main__':
    unittest.main()
