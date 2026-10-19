"""Command-aware Docker fixtures; these are not real Docker/HA deployment tests."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import docker_update as module

OLD = 'sha256:' + '1' * 64
NEW = 'sha256:' + '2' * 64


class DockerFixture:
    def __init__(self, project):
        self.project = project
        self.image_id = OLD
        self.running = True
        self.restart_policy = 'always'
        self.calls = []
        self.fail_pull = False
        self.fail_start = False
        self.bad_health = False
        self.mutate = False
        self.wrong_labels = False
        self.wrong_arch = False
        self.extra_service = False
        self.other_writer = False
        self.security_options = []
        self.missing = False
        self.remove_on_failure = False
        self.endpoint = 'unix:///var/run/docker.sock'
        self.actual_environment = self.environment()
        self.applied_compose = (self.project / 'docker-compose.yml').read_bytes()

    def environment(self):
        _, env = module.parse_env_file(self.project / '.env')
        return {**env, 'NOTES_FILE': '/app/webclock_state/manual_notes.json'}

    def mounts(self):
        return [{'Type': 'bind', 'Source': str(self.project / name), 'Destination': target, 'RW': rw}
                for target, (name, rw) in module.MOUNTS.items()]

    def container(self):
        return {'Id': 'container', 'Image': self.image_id, 'State': {'Running': self.running},
                'HostConfig': {'RestartPolicy': {'Name': self.restart_policy}},
                'RestartCount': 0, 'Mounts': self.mounts(),
                'Config': {'Env': [key + '=' + value for key, value in self.actual_environment.items()],
                           'Labels': {'com.docker.compose.project': 'other' if self.wrong_labels else 'webclock',
                                      'com.docker.compose.service': 'webclock',
                                      'com.docker.compose.project.working_dir': str(self.project),
                                      'com.docker.compose.project.config_files': str(self.project / 'docker-compose.yml')}},
                'NetworkSettings': {'Ports': {'5000/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '18500'}]}}}

    def reference(self):
        return re.search(r'(?m)^\s+image:\s*(\S+)', (self.project / 'docker-compose.yml').read_text())[1]

    def config(self):
        services = {'webclock': {'image': self.reference(), 'environment': self.environment(),
                    'command': None, 'entrypoint': None,
                    'restart': self.configured_restart(),
                    'ports': [{'target': 5000, 'published': '18500'}],
                    'volumes': [{'type': 'bind', 'source': m['Source'], 'target': m['Destination'],
                                 'read_only': not m['RW']} for m in self.mounts()]}}
        if self.extra_service:
            services['other'] = {'image': 'busybox'}
        return {'name': 'webclock', 'services': services}

    def configured_restart(self):
        match = re.search(r'(?m)^\s+restart:\s*(\S+)', (self.project / 'docker-compose.yml').read_text())
        return match[1].strip('"') if match else 'always'

    def restart_daemon(self):
        if self.restart_policy == 'always':
            self.running = True

    def health(self, **kwargs):
        if not self.running or (self.bad_health and self.image_id == NEW):
            return None
        return {'status': 'ok', 'deployment_mode': 'self', 'version': '1.1.0' if self.image_id == OLD else '1.2.0'}

    def run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        args = cmd[1:]
        if args[:1] == ['--host']:
            args = args[2:]
        output = ''
        if args[:2] == ['context', 'inspect']:
            output = [{'Endpoints': {'docker': {'Host': self.endpoint}}}]
        elif args[:1] == ['compose']:
            pos = next(i for i, item in enumerate(args) if item in ('config', 'ps', 'stop', 'up'))
            action = args[pos]
            if action == 'config':
                output = self.config()
            elif action == 'ps':
                output = '' if self.missing else 'container\n'
            elif action == 'stop':
                self.running = False
            elif action == 'up':
                compose = (self.project / 'docker-compose.yml').read_bytes()
                recreate = self.missing or compose != self.applied_compose or self.environment() != self.actual_environment
                self.missing = False
                reference = self.reference()
                self.image_id = NEW if reference == NEW else OLD
                self.actual_environment = self.environment()
                self.running = True
                if recreate:
                    self.restart_policy = self.configured_restart()
                self.applied_compose = compose
                if self.image_id == NEW:
                    if self.mutate:
                        (self.project / 'webclock_state' / 'control-clients.json').write_text('{"revoked": true}')
                    if self.fail_start:
                        self.missing = self.remove_on_failure
                        self.running = not self.missing
                        raise subprocess.CalledProcessError(1, cmd, stderr='private output')
        elif args[:1] == ['update']:
            self.restart_policy = args[1].split('=', 1)[1]
        elif args[:2] == ['image', 'inspect']:
            image_id = NEW if args[2] in (NEW, module.REPOSITORY + ':1.2.0') else OLD
            output = [{'Id': image_id, 'Os': 'linux', 'Architecture': 'arm64' if self.wrong_arch and image_id == NEW else 'amd64',
                       'Config': {'Labels': {'org.opencontainers.image.source': 'https://github.com/kcayut/webclock',
                                            'org.opencontainers.image.version': '1.2.0' if image_id == NEW else '1.1.0'}}}]
        elif args[:1] == ['inspect']:
            output = [self.container()]
            if self.other_writer:
                output.append({'Id': 'second', 'Mounts': self.mounts()})
        elif args[:1] == ['pull']:
            if self.fail_pull:
                raise subprocess.CalledProcessError(1, cmd, stderr='private output')
        elif args[:1] == ['info']:
            output = self.security_options
        elif args[:1] == ['ps']:
            output = 'container\n' if self.running else ''
            if self.other_writer:
                output += 'second\n'
        else:
            raise AssertionError('Unexpected Docker command: ' + repr(args))
        return subprocess.CompletedProcess(cmd, 0, json.dumps(output) if not isinstance(output, str) else output, '')


class DockerUpdateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        (self.project / 'docker-compose.yml').write_text('services:\n  webclock:\n    image: ghcr.io/kcayut/webclock:1.1.0\n')
        (self.project / '.env').write_text('# keep\nWEBCLOCK_VERSION=1.1.0\nWEBCLOCK_HTTP_PORT=18500\n')
        (self.project / '.env').chmod(0o640)
        (self.project / 'VERSION').write_text('1.1.0\n')
        for name, _ in module.MOUNTS.values():
            path = self.project / name
            if name.endswith('.json'):
                path.write_text('[]')
            else:
                path.mkdir()
        (self.project / 'webclock_state' / 'control-clients.json').write_text('{"revoked": false}')
        self.engine = DockerFixture(self.project)
        self.updater = module.DockerUpdater(self.project, runner=self.engine.run)
        self.addCleanup(self.updater.unlock)
        patcher = patch.object(self.updater, '_check_health', side_effect=self.engine.health)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(module.release_versions, 'discover_release', return_value={
            'latest_version': '1.2.0', 'update_available': True, 'prerelease': False})
        self.release = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(module.time, 'sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def update(self):
        return self.updater.update(expected_version='1.2.0')

    def assert_failed(self, recovered=None):
        with self.assertRaises(module.DockerUpdateError) as error:
            self.update()
        self.assertIs(error.exception.rollback_succeeded, recovered)
        return error.exception

    def test_success_pins_exact_image_without_rewriting_host_version(self):
        self.assertEqual(self.update(), 'updated')
        self.assertEqual(self.engine.reference(), NEW)
        self.assertEqual((self.project / 'VERSION').read_text(), '1.1.0\n')
        self.assertEqual(self.updater.read_journal()['step'], 'completed')
        self.assertEqual((self.project / '.env').stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.updater.backup_dir.stat().st_mode & 0o777, 0o700)
        up = next(cmd for cmd, _ in self.engine.calls if 'up' in cmd)
        self.assertIn('--no-build', up)
        self.assertEqual(up[up.index('--pull') + 1], 'never')
        self.assertIn('--project-name', up)
        self.assertEqual(self.engine.restart_policy, 'always')

    def test_backup_failure_restores_restart_policy_even_without_container_recreation(self):
        original = (self.project / 'docker-compose.yml').read_bytes()
        with patch.object(self.updater, 'backup', side_effect=OSError('disk full')):
            self.assert_failed(True)
        self.assertEqual((self.project / 'docker-compose.yml').read_bytes(), original)
        self.assertEqual(self.engine.restart_policy, 'always')

    def test_explicit_command_overrides_including_empty_values_are_rejected(self):
        for key in ('command', 'entrypoint'):
            for value in ('', [], ['python', 'other.py']):
                with self.subTest(key=key, value=value):
                    config = self.engine.config()
                    config['services']['webclock'][key] = value
                    with patch.object(self.engine, 'config', return_value=config):
                        self.assertEqual(self.assert_failed().code, 'unsupported_compose')
        self.assertEqual(self.updater.preflight()['source_version'], '1.1.0')

    def test_copied_backup_is_verified_before_starting_the_new_image(self):
        copy = shutil.copy2
        def corrupt(source, target, *args, **kwargs):
            result = copy(source, target, *args, **kwargs)
            if Path(target).name == 'manual_notes.json':
                Path(target).write_text('corrupted copy')
            return result
        with patch.object(module.shutil, 'copy2', side_effect=corrupt):
            self.assert_failed(True)
        self.assertEqual(self.engine.image_id, OLD)
        self.assertEqual((self.project / 'manual_notes.json').read_text(), '[]')

    def test_live_write_during_backup_does_not_become_a_valid_snapshot(self):
        copy = shutil.copy2
        def change_after_copy(source, target, *args, **kwargs):
            result = copy(source, target, *args, **kwargs)
            if Path(source) == self.project / 'manual_notes.json':
                Path(source).write_text('[{"text":"new reminder"}]')
            return result
        with patch.object(module.shutil, 'copy2', side_effect=change_after_copy):
            self.assert_failed(True)
        self.assertEqual(self.engine.image_id, OLD)
        self.assertIn('new reminder', (self.project / 'manual_notes.json').read_text())

    def test_config_cutover_power_loss_can_recover_both_images(self):
        class PowerLoss(BaseException):
            pass
        for filename in ('docker-compose.yml', '.env'):
            for choice in ('current', 'previous'):
                with self.subTest(filename=filename, choice=choice):
                    case = DockerUpdateTest()
                    case.setUp()
                    write = module.atomic_write
                    def cut_power(path, *args, **kwargs):
                        write(path, *args, **kwargs)
                        if path == case.project / filename:
                            raise PowerLoss()
                    try:
                        with patch.object(module, 'atomic_write', side_effect=cut_power):
                            with self.assertRaises(PowerLoss):
                                case.update()
                        journal = case.updater.read_journal()
                        case.engine.restart_daemon()
                        self.assertFalse(case.engine.running)
                        result = case.updater.recover(choice, journal['op_id'], confirmed=True)
                        self.assertEqual(result, 'completed' if choice == 'current' else 'rolled_back')
                        self.assertEqual(case.engine.restart_policy, 'always')
                    finally:
                        case.doCleanups()

    def test_failed_image_stays_stopped_across_daemon_restart(self):
        self.engine.fail_start = self.engine.mutate = True
        self.assert_failed(False)
        self.assertEqual(self.engine.restart_policy, 'no')
        self.engine.restart_daemon()
        self.assertFalse(self.engine.running)

    def test_new_image_cannot_auto_restart_before_health_confirmation(self):
        observed = []
        def observe(phase):
            if phase == 'health_check':
                observed.append((self.engine.restart_policy, self.engine.configured_restart()))
        self.updater.update(expected_version='1.2.0', progress=observe)
        self.assertEqual(observed, [('no', 'no')])
        self.assertEqual(self.engine.restart_policy, 'always')

    def test_recovery_keeps_changed_data_and_requires_transaction_confirmation(self):
        self.engine.mutate = True
        self.engine.fail_start = True
        self.assert_failed(False)
        journal = self.updater.read_journal()
        operation = journal['op_id']
        state = (self.project / 'webclock_state/control-clients.json').read_bytes()
        for choice, op, confirmed in [('current', operation, False), ('current', 'wrong', True),
                                      ('previous', operation, True)]:
            with self.subTest(choice=choice, op=op), self.assertRaises(module.DockerUpdateError):
                self.updater.recover(choice, op, confirmed=confirmed)
        self.engine.fail_start = False
        self.engine.mutate = False
        self.assertEqual(self.updater.recover('current', operation, confirmed=True), 'completed')
        self.assertEqual(self.engine.image_id, NEW)
        self.assertEqual((self.project / 'webclock_state/control-clients.json').read_bytes(), state)
        self.assertTrue((self.project / '.docker-update-history' / (operation + '.json')).is_file())

    def test_recover_previous_refuses_modified_configuration(self):
        self.update()
        journal = self.updater.read_journal()
        journal['step'] = 'manual_recovery'
        self.updater.write_journal(journal)
        (self.project / '.env').write_text('WEBCLOCK_HTTP_PORT=18501\n')
        with self.assertRaises(module.DockerUpdateError) as error:
            self.updater.recover('previous', journal['op_id'], confirmed=True)
        self.assertEqual(error.exception.code, 'configuration_changed')
        self.assertTrue(self.engine.running)

    def test_recovery_previous_requires_unchanged_data_and_checks_health(self):
        self.update()
        journal = self.updater.read_journal()
        journal['step'] = 'starting'
        self.updater.write_journal(journal)
        self.engine.running = False
        self.assertEqual(self.updater.recover('previous', journal['op_id'], confirmed=True), 'rolled_back')
        self.assertTrue(self.engine.running)
        self.assertEqual(self.engine.image_id, OLD)

    def test_retention_preview_keeps_unresolved_unknown_and_latest_backup(self):
        self.update()
        latest = self.updater.read_journal()['op_id']
        for index, step in enumerate(('completed', 'rolled_back', 'manual_recovery')):
            operation = 'up-' + str(index) * 32
            path = self.updater.backup_dir / operation
            path.mkdir()
            (path / 'transaction.json').write_text(json.dumps({'op_id': operation, 'step': step}))
            os.utime(path, (index + 1, index + 1))
        preview = self.updater.prune_backups(1)
        self.assertFalse(preview['applied'])
        self.assertEqual(len(preview['remove']), 2)
        self.assertTrue(all((self.updater.backup_dir / name).exists() for name in preview['remove']))
        self.updater.prune_backups(1, confirmed=True)
        self.assertTrue((self.updater.backup_dir / latest).exists())
        self.assertTrue((self.updater.backup_dir / ('up-' + '2' * 32)).exists())
        self.assertGreater(self.updater.diagnose()['backup_bytes'], 0)
        with self.assertRaises(module.DockerUpdateError):
            self.updater.prune_backups(0, confirmed=True)

    def test_start_failure_recovers_original_image_and_never_copies_state(self):
        self.engine.fail_start = True
        self.assert_failed(True)
        self.assertEqual(self.engine.image_id, OLD)
        self.assertEqual(self.engine.reference(), OLD)
        self.assertTrue(self.engine.running)
        self.assertEqual(self.updater.read_journal()['step'], 'rolled_back')

    def test_failed_create_with_no_remaining_container_can_recover(self):
        self.engine.fail_start = self.engine.remove_on_failure = True
        self.assert_failed(True)
        self.assertEqual(self.engine.image_id, OLD)
        self.assertTrue(self.engine.running)

    def test_rootless_daemon_does_not_receive_updates(self):
        self.engine.security_options = ['name=rootless']
        self.assertEqual(self.assert_failed().code, 'unsupported_daemon')

    def test_new_revocation_and_schema_changes_force_manual_recovery(self):
        self.engine.fail_start = self.engine.mutate = True
        self.assert_failed(False)
        self.assertFalse(self.engine.running)
        self.assertEqual(json.loads((self.project / 'webclock_state/control-clients.json').read_text()), {'revoked': True})
        backup = Path(self.updater.read_journal()['backup_path'])
        self.assertEqual(json.loads((backup / 'webclock_state/control-clients.json').read_text()), {'revoked': False})
        before = list(self.engine.calls)
        self.assert_failed(False)
        self.assertEqual(self.engine.calls, before)

    def test_health_failure_rolls_back_if_data_unchanged(self):
        real_wait = self.updater.wait_for_health
        def wait(version, *args):
            if version == '1.2.0':
                raise module.DockerUpdateError('not healthy')
            return real_wait(version, *args)
        with patch.object(self.updater, 'wait_for_health', side_effect=wait):
            self.assert_failed(True)
        self.assertEqual(self.engine.image_id, OLD)

    def test_backup_failure_requires_verified_original_health(self):
        with patch.object(self.updater, 'backup', side_effect=OSError('disk full')):
            self.assert_failed(True)
        self.assertTrue(self.engine.running)
        self.assertEqual(self.engine.image_id, OLD)

    def test_backup_failure_with_failed_recovery_is_not_success(self):
        with patch.object(self.updater, 'backup', side_effect=OSError()), \
             patch.object(self.updater, 'wait_for_health', side_effect=RuntimeError()):
            self.assert_failed(False)
        self.assertFalse(self.engine.running)

    def test_pull_failure_never_stops_service(self):
        self.engine.fail_pull = True
        self.assert_failed()
        self.assertTrue(self.engine.running)
        self.assertFalse(any('stop' in cmd for cmd, _ in self.engine.calls))
        self.assertNotIn('private', self.updater.journal_file.read_text())

    def test_wrong_architecture_never_stops_service(self):
        self.engine.wrong_arch = True
        self.assert_failed()
        self.assertTrue(self.engine.running)

    def test_journal_write_failure_after_stop_still_recovers(self):
        real_write = self.updater.write_journal
        def write(data):
            if data['step'] == 'backed_up':
                raise OSError('disk full')
            real_write(data)
        with patch.object(self.updater, 'write_journal', side_effect=write):
            self.assert_failed(True)
        self.assertTrue(self.engine.running)

    def test_interrupted_or_corrupt_journal_blocks_new_transaction(self):
        for content in ('{broken', '{"step":"starting"}'):
            with self.subTest(content=content):
                self.updater.journal_file.write_text(content)
                self.assert_failed(False)
                self.assertEqual(self.engine.calls, [])

    def test_release_revalidated_even_with_version_argument(self):
        self.release.return_value['latest_version'] = '1.3.0'
        self.assertEqual(self.assert_failed().code, 'release_changed')
        self.assertFalse(any('pull' in cmd for cmd, _ in self.engine.calls))

    def test_changed_config_during_pull_does_not_stop_service(self):
        real_pull = self.updater.pull_image
        def pull(*args):
            result = real_pull(*args)
            with (self.project / '.env').open('a') as output:
                output.write('TZ=UTC\n')
            return result
        with patch.object(self.updater, 'pull_image', side_effect=pull):
            self.assert_failed()
        self.assertFalse(any('stop' in cmd for cmd, _ in self.engine.calls))

    def test_changed_config_after_backup_is_not_overwritten_by_rollback(self):
        backup = self.updater.backup
        def changing_backup(*args):
            result = backup(*args)
            with (self.project / '.env').open('a') as output:
                output.write('TZ=UTC\n')
            return result
        with patch.object(self.updater, 'backup', side_effect=changing_backup):
            self.assert_failed(False)
        self.assertIn('TZ=UTC', (self.project / '.env').read_text())
        self.assertFalse(self.engine.running)

    def test_env_preserves_comments_permissions_and_does_not_execute_values(self):
        env = self.project / '.env'
        env.write_text('# keep\nexport WEBCLOCK_VERSION = "1.1.0" # version\nSECRET=$(touch nope)\n')
        module.atomic_write(env, module.versioned_env(env.read_bytes(), '1.2.0'))
        self.assertIn('export WEBCLOCK_VERSION = 1.2.0 # version', env.read_text())
        self.assertIn('SECRET=$(touch nope)', env.read_text())
        self.assertEqual(env.stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.project / 'nope').exists())

    def test_compose_overrides_and_extra_services_are_not_silently_ignored(self):
        override = self.project / 'docker-compose.override.yml'
        override.write_text('services: {}')
        self.assertEqual(self.assert_failed().code, 'unsupported_compose')
        self.assertEqual(self.engine.calls, [])
        override.unlink()
        self.engine.extra_service = True
        self.assertEqual(self.assert_failed().code, 'unsupported_compose')

    def test_wrong_project_and_shared_writers_are_rejected(self):
        self.engine.wrong_labels = True
        self.assertEqual(self.assert_failed().code, 'wrong_installation')
        self.engine.wrong_labels = False
        self.engine.other_writer = True
        self.assertEqual(self.assert_failed().code, 'shared_data')

    def test_remote_daemon_rejected(self):
        self.engine.endpoint = 'tcp://remote:2375'
        self.assertEqual(self.assert_failed().code, 'unsupported_daemon')

    def test_environment_cannot_override_version_or_context(self):
        with patch.dict(os.environ, WEBCLOCK_VERSION='evil', DOCKER_HOST='tcp://evil', COMPOSE_PROJECT_NAME='evil'):
            self.updater.preflight()
        for _, options in self.engine.calls:
            self.assertNotIn('DOCKER_HOST', options['env'])
            self.assertNotIn('COMPOSE_PROJECT_NAME', options['env'])
            self.assertNotIn('WEBCLOCK_VERSION', options['env'])

    def test_symlink_data_not_copied_or_followed(self):
        (self.project / 'webclock_state/private').symlink_to(self.project / '.env')
        with self.assertRaises(module.DockerUpdateError):
            self.updater.backup('test')
        self.assertFalse((self.updater.backup_dir / 'test').exists())

    def test_lock_is_exclusive_and_symlink_is_refused(self):
        self.updater.lock()
        another = module.DockerUpdater(self.project)
        with self.assertRaises(module.DockerUpdateError):
            another.lock()
        self.updater.unlock()
        self.updater.lock_file.unlink()
        self.updater.lock_file.symlink_to(self.project / '.env')
        with self.assertRaises(module.DockerUpdateError):
            self.updater.lock()

    def test_observer_cannot_abort_recovery(self):
        self.engine.fail_start = True
        with self.assertRaises(module.DockerUpdateError) as error:
            self.updater.update(progress=lambda phase: (_ for _ in ()).throw(RuntimeError()))
        self.assertTrue(error.exception.rollback_succeeded)

    def test_https_uses_container_ca_mapping_and_hostname(self):
        ca = self.project / 'tls/ca.pem'
        ca.write_text('test fixture')
        with (self.project / '.env').open('a') as output:
            output.write('WEBCLOCK_TLS_CERT=/app/tls/fullchain.pem\nWEBCLOCK_TLS_KEY=/app/tls/privkey.pem\n'
                         'WEBCLOCK_UPDATE_CA=/app/tls/ca.pem\nWEBCLOCK_UPDATE_HOST=clock.example\n')
        self.engine.actual_environment = self.engine.environment()
        with patch.object(module.update_clock, 'update_tls_handler', return_value='tls') as handler:
            self.updater.preflight()
        self.assertEqual(self.updater.health_url, 'https://127.0.0.1:18500/api/health')
        self.assertEqual(handler.call_args.args[1]['WEBCLOCK_UPDATE_CA'], str(ca))
        self.assertEqual(handler.call_args.args[1]['WEBCLOCK_UPDATE_HOST'], 'clock.example')


if __name__ == '__main__':
    unittest.main()
