"""Cold migration preserves the source and never rolls changed destination data back."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import docker_update, docker_update_migrate as migration


class MigrationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project, self.destination = self.root / 'old', self.root / 'protected'
        self.project.mkdir()
        for name, _ in docker_update.MOUNTS.values():
            path = self.project / name
            if name.endswith('.json'):
                path.write_text('[]')
            else:
                path.mkdir()
        (self.project / 'webclock_state/control-clients.json').write_text('{"revoked":true}')
        (self.project / '.env').write_text('PRIVATE=keep\n')
        (self.project / 'docker-compose.yml').write_text('services:\n  webclock:\n    image: ghcr.io/kcayut/webclock:1.1.0\n')
        self.source = self.root / 'release'
        (self.source / 'scripts').mkdir(parents=True)
        (self.source / 'scripts/docker_update.py').write_text('# release code')
        for name in ('docker_update.sh', 'portable_docker_update.sh'):
            (self.source / name).write_text('# release entry')
        self.old = docker_update.DockerUpdater(self.project)
        self.old.preflight = Mock(return_value={'source_version': '1.1.0', 'source_image_id': 'sha256:' + '1' * 64,
                                               'deployment_mode': 'self', 'container_id': 'original', 'restart_policy': 'always'})
        self.old.stop_service = Mock()
        self.old.start_service = Mock()
        self.old.wait_for_health = Mock()
        self.old.restore_restart_policy = Mock()
        self.old._run = Mock()
        self.new = None
        self.fail_health = False
        self.mutate = False
        def make_new(path):
            if Path(path) == self.project:
                return self.old
            self.new = docker_update.DockerUpdater(path)
            self.new._compose = Mock(return_value=Mock(stdout=json.dumps({'services': {'webclock': {'volumes': []}}})))
            self.new._validate_mounts = Mock()
            self.new.preflight = Mock()
            self.new.stop_service = Mock()
            self.new._container = Mock(return_value={'Id': 'replacement'})
            self.new._run = Mock()
            self.new.start_service = Mock()
            self.new.restore_restart_policy = Mock()
            def wait(*args):
                if self.mutate:
                    (self.destination / 'webclock_state/control-clients.json').write_text('{"new_revocation":true}')
                if self.fail_health:
                    raise RuntimeError('health failed')
            self.new.wait_for_health = Mock(side_effect=wait)
            return self.new
        self.factory = make_new

    def migrate(self):
        real_type = docker_update.DockerUpdater
        def factory(path):
            with patch.object(docker_update, 'DockerUpdater', real_type):
                return self.factory(path)
        with patch.object(migration.os, 'geteuid', return_value=0), \
             patch.object(docker_update, 'root_owned'), \
             patch.object(docker_update, 'DockerUpdater', side_effect=factory):
            return migration.migrate(self.project, self.destination, self.source)

    def test_success_keeps_original_and_blocks_future_updates_from_old_location(self):
        self.assertEqual(self.migrate(), str(self.destination))
        self.assertEqual((self.destination / '.env').read_text(), 'PRIVATE=keep\n')
        self.assertEqual((self.project / 'webclock_state/control-clients.json').read_bytes(),
                         (self.destination / 'webclock_state/control-clients.json').read_bytes())
        self.old._run.assert_called_once_with(['rm', 'original'])
        self.old.start_service.assert_not_called()
        with self.assertRaises(docker_update.DockerUpdateError) as error:
            docker_update.DockerUpdater(self.project).preflight()
        self.assertEqual(error.exception.code, 'migration_pending')

    def test_failed_start_recovers_only_when_destination_data_is_unchanged(self):
        self.fail_health = True
        with self.assertRaises(RuntimeError):
            self.migrate()
        self.old.start_service.assert_called_once()
        self.old.restore_restart_policy.assert_called_once_with('sha256:' + '1' * 64, 'always')
        self.assertEqual(json.loads((self.project / '.docker-migration.json').read_text())['step'], 'rolled_back')

    def test_source_checkout_layout_keeps_both_update_entrypoints(self):
        entries = self.source / 'scripts/update'
        entries.mkdir()
        (self.source / 'portable_docker_update.sh').rename(entries / 'portable_docker_update.sh')
        (entries / 'docker_update.sh').write_text('# nested Docker entry')
        self.migrate()
        self.assertEqual((self.destination / 'portable_docker_update.sh').read_text(), '# release entry')
        self.assertEqual((self.destination / 'docker_update.sh').read_text(), '# release entry')
        self.assertEqual((self.destination / 'scripts/update/docker_update.sh').read_text(), '# nested Docker entry')

    def test_new_writes_are_retained_and_old_copy_is_not_restarted(self):
        self.fail_health = self.mutate = True
        with self.assertRaises(RuntimeError):
            self.migrate()
        self.old.start_service.assert_not_called()
        self.assertEqual(json.loads((self.project / '.docker-migration.json').read_text())['step'], 'manual_recovery')
        self.assertIn('new_revocation', (self.destination / 'webclock_state/control-clients.json').read_text())

    def test_unsupported_worker_path_is_rejected_before_stopping(self):
        self.destination = self.root / 'has spaces'
        with self.assertRaisesRegex(RuntimeError, 'Unsupported installation path'):
            self.migrate()
        self.old.stop_service.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_config_change_during_copy_prevents_container_replacement(self):
        self.old._assert_config = Mock(side_effect=RuntimeError('config changed'))
        with self.assertRaisesRegex(RuntimeError, 'config changed'):
            self.migrate()
        self.old._run.assert_not_called()
        self.new.start_service.assert_not_called()


if __name__ == '__main__':
    unittest.main()
