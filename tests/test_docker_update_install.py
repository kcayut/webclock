"""Exercise enrollment in temporary paths; never alter host systemd or /etc."""
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import docker_update, docker_update_install as installer


class DockerEnrollmentTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        (self.project / 'scripts').mkdir(parents=True)
        (self.project / '.env').write_text('WEBCLOCK_VERSION=1.1.0\n')
        (self.project / 'VERSION').write_text('1.1.0\n')
        (self.project / 'docker-compose.yml').write_text('services:\n  webclock:\n    volumes:\n      - ./webclock_updater_run:/run/webclock-updater:ro\n')
        for name in ('updater_service.py', 'docker_update.py', 'release_versions.py', 'update_clock.py', 'update_settings.py'):
            (self.project / 'scripts' / name).write_text('# trusted source\n')
        self.config = self.root / 'config.json'
        self.runtime = self.root / 'runtime'
        self.unit = self.root / 'service'
        patches = [patch.object(installer, 'RUNTIME', self.runtime), patch.object(installer, 'CONFIG', self.config),
                   patch.object(installer, 'UNIT', self.unit), patch.object(installer.os, 'geteuid', return_value=0),
                   patch.object(docker_update.os, 'fchown'), patch.object(docker_update, 'root_owned'),
                   patch.object(installer.subprocess, 'run'), patch.object(docker_update, 'DockerUpdater')]
        mocks = [item.start() for item in patches]
        self.addCleanup(patch.stopall)
        self.ownership = mocks[5]
        self.run = mocks[6]
        self.updater = mocks[7].return_value
        self.updater.read_journal.return_value = None
        self.updater.preflight.return_value = {'source_version': '1.1.0', 'source_image_id': 'sha256:' + '1' * 64,
                                               'deployment_mode': 'self'}
        self.updater.compose_file = self.project / 'docker-compose.yml'
        self.ready = patch.object(installer.update_settings, 'request', return_value={
            'supported': True, 'update_provider': 'docker', 'worker_version': '1.1.0',
            'project_path': str(self.project)}).start()

    def test_enrollment_is_private_explicit_and_preserves_preferences(self):
        installer.enable(self.project)
        config = json.loads(self.config.read_text())
        self.assertFalse(config['auto_update'])
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.project / docker_update.SOCKET_DIR).stat().st_mode & 0o777, 0o700)
        self.assertIn('/usr/local/lib/webclock-docker-updater/updater_service.py', self.unit.read_text())
        self.assertNotIn(str(self.project / 'scripts'), self.unit.read_text())
        self.assertEqual((self.runtime / 'docker_update.py').read_text(), '# trusted source\n')
        config.update(channel='beta', auto_update=True)
        self.config.write_text(json.dumps(config))
        installer.enable(self.project)
        self.assertTrue(json.loads(self.config.read_text())['auto_update'])
        self.assertEqual(json.loads(self.config.read_text())['channel'], 'beta')
        self.assertIn((self.project,), [call.args for call in self.ownership.call_args_list])

    def test_unsafe_owner_stops_before_any_system_change(self):
        self.ownership.side_effect = docker_update.DockerUpdateError('unsafe', code='unsafe_owner')
        with self.assertRaises(docker_update.DockerUpdateError):
            installer.enable(self.project)
        self.run.assert_not_called()
        self.assertFalse(self.config.exists())
        self.assertFalse(self.runtime.exists())

    def test_worker_refresh_uses_release_source_keeps_previous_and_checks_version(self):
        installer.enable(self.project)
        self.assertEqual((self.runtime / 'VERSION').read_text(), '1.1.0\n')
        (self.project / 'scripts/updater_service.py').write_text('# refreshed worker\n')
        installer.enable(self.project)
        self.assertEqual((self.runtime / 'previous/updater_service.py').read_text(), '# trusted source\n')
        (self.project / 'VERSION').write_text('1.2.0\n')
        with self.assertRaisesRegex(RuntimeError, 'match the running image'):
            installer.enable(self.project)

    def test_failed_worker_restart_restores_the_previous_program(self):
        installer.enable(self.project)
        self.run.return_value.returncode = 0
        original = (self.runtime / 'updater_service.py').read_bytes()
        original_config, original_unit = self.config.read_bytes(), self.unit.read_bytes()
        self.updater.unlock.reset_mock()
        (self.project / 'scripts/updater_service.py').write_text('# replacement')
        restarts = []
        def run(command, **kwargs):
            self.updater.unlock.assert_not_called()
            if command[:2] == ['systemctl', 'restart']:
                restarts.append(command)
                if len(restarts) == 1:
                    raise subprocess.CalledProcessError(1, command)
            return Mock(returncode=0)
        self.run.side_effect = run
        with self.assertRaises(subprocess.CalledProcessError):
            installer.enable(self.project)
        self.assertEqual((self.runtime / 'updater_service.py').read_bytes(), original)
        self.assertEqual(self.config.read_bytes(), original_config)
        self.assertEqual(self.unit.read_bytes(), original_unit)
        self.assertEqual(len(restarts), 2)
        self.updater.unlock.assert_called_once()

    def test_failed_first_activation_removes_incomplete_registration(self):
        def run(command, **kwargs):
            self.updater.unlock.assert_not_called()
            if command[:2] == ['systemctl', 'restart']:
                raise subprocess.CalledProcessError(1, command)
            return Mock(returncode=0)
        self.run.side_effect = run
        with self.assertRaises(subprocess.CalledProcessError):
            installer.enable(self.project)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.unit.exists())
        self.assertFalse((self.project / docker_update.SOCKET_DIR / 'configured').exists())
        self.assertFalse((self.runtime / 'updater_service.py').exists())
        self.updater.unlock.assert_called_once()

    def test_wrong_worker_identity_restores_previous_registration(self):
        installer.enable(self.project)
        original = (self.runtime / 'updater_service.py').read_bytes()
        self.run.return_value.returncode = 0
        (self.project / 'scripts/updater_service.py').write_text('# replacement')
        self.ready.return_value['project_path'] = '/another/installation'
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            installer.enable(self.project)
        self.assertEqual((self.runtime / 'updater_service.py').read_bytes(), original)

    def test_socket_readiness_retries_and_has_a_deadline(self):
        state = self.ready.return_value
        self.ready.side_effect = [FileNotFoundError(), state]
        with patch.object(installer.time, 'sleep'):
            installer.wait_until_ready(self.root / 'socket', self.project, '1.1.0')
        self.assertEqual(self.ready.call_count, 2)
        self.ready.side_effect = ConnectionRefusedError()
        with patch.object(installer.time, 'monotonic', side_effect=[0, 0, 11]), \
             patch.object(installer.time, 'sleep'), self.assertRaisesRegex(RuntimeError, '10 seconds'):
            installer.wait_until_ready(self.root / 'socket', self.project, '1.1.0')

    def test_other_installation_and_interrupted_journal_not_overwritten(self):
        self.config.write_text(json.dumps({'project': '/other', 'kind': 'docker'}))
        original = self.config.read_bytes()
        with self.assertRaises(RuntimeError):
            installer.enable(self.project)
        self.assertEqual(self.config.read_bytes(), original)
        self.config.unlink()
        self.updater.read_journal.return_value = {'step': 'starting'}
        with self.assertRaises(RuntimeError):
            installer.enable(self.project)
        self.run.assert_not_called()

    def test_runtime_link_cannot_redirect_privileged_copy(self):
        victim = self.root / 'victim'
        victim.mkdir()
        self.runtime.symlink_to(victim, target_is_directory=True)
        with self.assertRaises(docker_update.DockerUpdateError):
            installer.enable(self.project)
        self.assertEqual(list(victim.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
