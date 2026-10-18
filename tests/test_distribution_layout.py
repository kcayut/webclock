"""Exercise the distribution after moving development-only files out of scripts."""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from tools.build_release import build_release, is_public


ROOT = Path(__file__).resolve().parents[1]


class DistributionLayoutTest(unittest.TestCase):
    def test_current_source_packages_working_entrypoints_and_build_contexts(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            repository = work / 'repository'
            repository.mkdir()
            # Exercise uncommitted changes without changing the real index or
            # relaxing the release builder's committed-files-only rule.
            names = subprocess.check_output(
                ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
            ).decode().split('\0')
            for name in names:
                source = ROOT / name
                if name and is_public(name) and source.is_file():
                    destination = repository / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            for args in (('init', '-q'), ('config', 'maintenance.auto', 'false'),
                         ('config', 'gc.auto', '0'), ('add', '.'),
                         ('-c', 'user.name=Layout Test', '-c', 'user.email=layout@example.test',
                          'commit', '-qm', 'candidate layout')):
                subprocess.run(['git', *args], cwd=repository, check=True, capture_output=True)
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env['PATH']

            def run(*command):
                result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            version = (repository / 'VERSION').read_text().strip()
            self.assertEqual(run(sys.executable, str(repository / 'tools/build_release.py'), '--check').strip(), version)
            assets = work / 'assets'
            build_release(assets, version, repository)
            with tarfile.open(assets / f'webclock-{version}.tar.gz') as archive:
                archive.extractall(work / 'extracted', filter='data')
            installed = work / 'extracted' / f'webclock-{version}'
            for name in ('install.sh', 'setup.sh', 'update_clock.sh', 'scripts/update/update_clock.sh',
                         'docker_update.sh', 'portable_docker_update.sh',
                         'scripts/update/docker_update.sh', 'scripts/update/portable_docker_update.sh'):
                with self.subTest(entrypoint=name):
                    self.assertIn('usage:', run('bash', str(installed / name), '--help').lower())
            for name in ('update_clock.py', 'scripts/install_check.py', 'scripts/backup_clock.py',
                         'scripts/manage_auth.py', 'scripts/update_settings.py'):
                with self.subTest(entrypoint=name):
                    self.assertIn('usage:', run(sys.executable, str(installed / name), '--help').lower())
            for name in ('update_clock.sh', 'portable_update_clock.sh', 'scripts/enable_updates.sh',
                         'scripts/enable_docker_updates.sh', 'repository.yaml', 'hacs.json',
                         'custom_components/webclock/manifest.json', 'doc/README.md',
                         'doc/installation.md', 'doc/operations/update-operations.md'):
                self.assertTrue((installed / name).is_file(), name)
            for name in ('tools', 'tests', 'homeassistant/tests', '.env', 'webclock_state', 'tls'):
                self.assertFalse((installed / name).exists(), name)
            local_app = work / 'local-app'
            run('bash', str(installed / 'homeassistant/prepare_local_app.sh'), str(local_app))
            self.assertNotIn('\nimage:', (local_app / 'config.yaml').read_text())
            legacy_app = work / 'legacy-command-app'
            run('bash', str(installed / 'scripts/prepare_ha_app.sh'), str(legacy_app))
            self.assertEqual((legacy_app / 'Dockerfile').read_bytes(), (local_app / 'Dockerfile').read_bytes())
            for context, dockerfile in ((installed, installed / 'Dockerfile'),
                                        (installed, installed / 'homeassistant/addon/Dockerfile'),
                                        (local_app, local_app / 'Dockerfile')):
                for line in dockerfile.read_text().splitlines():
                    if line.startswith('COPY '):
                        for source in shlex.split(line)[1:-1]:
                            self.assertTrue((context / source).exists(), (dockerfile, source))


if __name__ == '__main__':
    unittest.main()
