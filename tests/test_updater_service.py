import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('updater_service', SCRIPTS / 'updater_service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
finally:
    sys.path.pop(0)


class UpdaterServiceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / 'VERSION').write_text('1.1.0\n')
        self.state = self.project / 'updater-state' / 'state.json'
        self.updater = service.Updater(self.project, self.state)
        self.release = {
            'latest_version': '1.2.0', 'update_available': True,
            'html_url': 'https://github.com/kcayut/webclock/releases/tag/v1.2.0',
            'body': 'New version',
        }
        self.discover = patch.object(service.release_versions, 'discover_release', return_value=self.release).start()
        self.update = patch.object(service.update_clock, 'update', return_value='updated').start()
        self.addCleanup(patch.stopall)

    def run_request(self, request):
        reply = self.updater.dispatch(request)
        if self.updater.worker:
            self.updater.worker.join(timeout=2)
            self.assertFalse(self.updater.worker.is_alive())
        return reply

    def test_check_does_not_install_and_manual_install_rechecks_version(self):
        self.assertTrue(self.run_request({'action': 'check'})['ok'])
        self.assertTrue(self.updater.status()['update_available'])
        self.update.assert_not_called()
        self.assertTrue(self.run_request({'action': 'install', 'expected_version': '1.2.0'})['ok'])
        self.assertEqual(self.discover.call_count, 2)
        self.update.assert_called_once()
        self.assertEqual(self.update.call_args.kwargs['expected_version'], '1.2.0')
        self.assertEqual(self.updater.status()['result'], 'updated')
        self.assertFalse(self.updater.status()['update_available'])

    def test_automatic_check_installs_stable_and_beta_without_hardcoded_versions(self):
        self.updater._check(automatic=True)
        self.assertEqual(self.update.call_args.kwargs['channel'], 'stable')
        self.updater.dispatch({'action': 'configure', 'channel': 'beta', 'auto_update': True})
        self.release['latest_version'] = '2.3.4-beta.2'
        self.updater._check(automatic=True)
        self.assertEqual(self.update.call_args.kwargs['channel'], 'beta')
        self.assertEqual(self.update.call_args.kwargs['expected_version'], '2.3.4-beta.2')

    def test_disable_auto_still_checks_but_never_installs(self):
        self.updater.dispatch({'action': 'configure', 'channel': 'stable', 'auto_update': False})
        self.updater._check(automatic=True)
        self.discover.assert_called_once()
        self.update.assert_not_called()
        restored = service.Updater(self.project, self.state)
        self.assertFalse(restored.status()['auto_update'])

    def test_update_failure_is_sanitized_persisted_and_pauses_automatic_install(self):
        failure = RuntimeError('private https://calendar.invalid/secret and password')
        failure.rollback_succeeded = True
        self.update.side_effect = failure
        self.updater._check(automatic=True)
        status = self.updater.status()
        self.assertEqual(status['result'], 'rolled_back')
        self.assertTrue(status['auto_update_paused'])
        self.assertNotIn('calendar.invalid', self.state.read_text())
        self.assertNotIn('secret', json.dumps(status))
        restored = service.Updater(self.project, self.state)
        restored._check(automatic=True)
        self.update.assert_called_once()
        self.assertTrue(restored.status()['auto_update_paused'])

    def test_manual_retry_after_rollback_resumes_auto_on_success(self):
        failure = RuntimeError('failed')
        failure.rollback_succeeded = True
        self.update.side_effect = failure
        self.updater._check(automatic=True)
        self.update.side_effect = None
        self.run_request({'action': 'install', 'expected_version': '1.2.0'})
        self.assertEqual(self.update.call_count, 2)
        self.assertFalse(self.updater.status()['auto_update_paused'])

    def test_interrupted_update_requires_manual_recovery(self):
        self.updater._change(state='updating', phase='installing')
        restored = service.Updater(self.project, self.state)
        self.assertEqual(restored.status()['state'], 'interrupted')
        self.assertEqual(restored.status()['result'], 'manual_recovery')
        self.assertTrue(restored.status()['auto_update_paused'])

    def test_interrupted_check_is_safe_to_repeat(self):
        self.updater._change(state='checking', phase='checking')
        restored = service.Updater(self.project, self.state)
        self.assertEqual(restored.status()['state'], 'idle')
        self.assertFalse(restored.status()['auto_update_paused'])

    def test_invalid_commands_and_stale_install_cannot_select_paths_or_urls(self):
        for request in (
            [], {'action': 'arbitrary_command'},
            {'action': 'configure', 'channel': 'nightly', 'auto_update': True},
            {'action': 'configure', 'channel': 'stable', 'auto_update': 'true'},
            {'action': 'check', 'url': 'https://attacker.invalid/'},
            {'action': 'install', 'expected_version': '1.2.0'},
        ):
            with self.subTest(request=request):
                self.assertFalse(self.updater.dispatch(request)['ok'])
        self.discover.assert_not_called()
        self.update.assert_not_called()

    def test_changed_release_requires_new_user_choice(self):
        self.updater._check()
        self.release['latest_version'] = '1.3.0'
        self.run_request({'action': 'install', 'expected_version': '1.2.0'})
        self.update.assert_not_called()
        self.assertEqual(self.updater.status()['error'], 'release_changed')
        self.assertEqual(self.updater.status()['latest_version'], '1.3.0')

    def test_only_one_worker_can_run_and_settings_do_not_race(self):
        entered, finish = threading.Event(), threading.Event()

        def blocked(*args):
            entered.set()
            finish.wait(timeout=2)
            return self.release

        self.discover.side_effect = blocked
        self.assertTrue(self.updater.dispatch({'action': 'check'})['ok'])
        self.assertTrue(entered.wait(timeout=1))
        try:
            self.assertEqual(self.updater.dispatch({'action': 'check'})['error'], 'update_busy')
            self.assertEqual(self.updater.dispatch({'action': 'configure', 'channel': 'beta', 'auto_update': False})['error'], 'update_busy')
            self.assertEqual(self.updater.status()['channel'], 'stable')
        finally:
            finish.set()
            self.updater.worker.join(timeout=2)

    def test_check_failure_keeps_auto_check_retry_bounded(self):
        self.discover.side_effect = RuntimeError('private data')
        self.updater._check(automatic=True)
        status = self.updater.status()
        self.assertEqual(status['error'], 'release_check_failed')
        self.assertGreater(status['next_check'], service.time.time() + 3500)
        self.assertNotIn('private data', self.state.read_text())
        self.update.assert_not_called()

    def test_state_has_private_permissions_and_rejects_symlink(self):
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        linked = self.project / 'linked.json'
        linked.symlink_to(self.state)
        with self.assertRaises(RuntimeError):
            service.Updater(self.project, linked)

    def test_successful_upgrade_reloads_the_released_updater_only(self):
        reload = Mock()
        self.updater.on_updated = reload
        self.update.return_value = 'up_to_date'
        self.updater._install('1.2.0')
        reload.assert_not_called()
        self.update.return_value = 'updated'
        self.updater._install('1.2.0')
        reload.assert_called_once_with()
        self.update.side_effect = RuntimeError('failed')
        self.updater._install('1.2.0')
        reload.assert_called_once_with()

    def test_git_release_channel_is_the_source_of_truth(self):
        subprocess = service.subprocess
        run = lambda *args: subprocess.run(['git', *args], cwd=self.project, check=True,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run('init', '-q')
        run('config', 'webclock.releaseChannel', 'beta')
        restored = service.Updater(self.project, self.state)
        self.assertEqual(restored.status()['channel'], 'beta')
        self.assertTrue(restored.dispatch({'action': 'configure', 'channel': 'stable', 'auto_update': True})['ok'])
        self.assertEqual(restored._git_channel(), 'stable')


    def test_sync_channel_handles_root_with_non_root_git_repo(self):
        from types import SimpleNamespace
        (self.project / '.git').mkdir(exist_ok=True)
        with patch('os.geteuid', return_value=0), \
             patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='regular_user')), \
             patch.object(service.shutil, 'which', return_value='/usr/sbin/runuser'), \
             patch.object(service.subprocess, 'run') as mock_run:
            self.updater._sync_channel('beta')
            expected_cmd = [
                'runuser', '-u', 'regular_user', '--',
                'git', '-c', f'safe.directory={self.updater.project}',
                '-C', str(self.updater.project),
                'config', '--local', 'webclock.releaseChannel', 'beta'
            ]
            mock_run.assert_called_once_with(
                expected_cmd, check=True, stdout=service.subprocess.DEVNULL,
                stderr=service.subprocess.DEVNULL, timeout=15
            )

    def test_disk_full_during_progress_does_not_crash(self):
        with patch.object(self.updater, '_save', side_effect=OSError('Disk full')):
            self.updater._change(phase='installing', allow_failure=True)
        self.assertEqual(self.updater.status()['phase'], 'installing')

    def test_state_change_requires_successful_save_before_update(self):
        with patch.object(self.updater, '_save', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):
                self.updater._change(state='updating')

    def test_updating_state_saved_on_disk_preserves_auto_update_paused_after_restart(self):
        self.updater._change(state='updating', phase='checking')
        restored = service.Updater(self.project, self.state)
        self.assertTrue(restored.status()['auto_update_paused'])
        self.assertEqual(restored.status()['state'], 'interrupted')

    def test_dispatch_install_fails_cleanly_if_saving_updating_state_fails(self):
        self.updater.data['update_available'] = True
        self.updater.data['latest_version'] = '1.3.0'
        with patch.object(self.updater, '_save', side_effect=OSError('Disk full')):
            result = self.updater.dispatch({'action': 'install', 'expected_version': '1.3.0'})
            self.assertFalse(result['ok'])
            self.assertEqual(result['error'], 'state_save_failed')
            self.assertIsNone(self.updater.worker)


if __name__ == '__main__':
    unittest.main()
