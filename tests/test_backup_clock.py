import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import backup_clock as backup


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/backup_clock.py'


class HostBackupTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def installation(self, name, external=False):
        project = self.root / name
        (project / 'webclock').mkdir(parents=True)
        (project / 'webclock/app.py').write_text('# test installation\n')
        values = {}
        if external:
            values = {'WEBCLOCK_STATE_DIR': str(self.root / (name + '-state')),
                      'NOTES_FILE': str(self.root / (name + '-notes.json'))}
        (project / '.env').write_text('DEVICE_API_TOKEN=test-only-secret\n' + ''.join(
            key + '=' + value + '\n' for key, value in values.items()))
        (project / 'manual_notes.json').write_text('[{"text":"legacy ' + name + '"}]')
        (project / 'webclock_state').mkdir()
        state, notes = backup.updater.data_layout(project, values, modular=True)
        state.mkdir(exist_ok=True)
        samples = {
            'settings.json': {'brightness': 0, 'night': {'enabled': True, 'brightness': 0}},
            'calendar.json': {'sources': [{'url': 'https://calendar.example.invalid/private-test'}]},
            'schedules.json': {'schema_version': 2, 'items': [
                {'id': name, 'browser_volume': 0, 'skip_next': True}]},
            'devices.json': {'devices': [{'id': name, 'enabled': True}]},
            'before-import.json': {'items': [{'id': 'before-' + name}]},
        }
        for filename, value in samples.items():
            (state / filename).write_text(json.dumps(value))
        (state / 'empty').mkdir()
        notes.write_text('[{"text":"current ' + name + '"}]')
        if external:
            (project / 'webclock_state/legacy-settings.json').write_text('{"brightness":0}')
        return project, values, backup.data_roots(project, values)

    def snapshot(self, roots):
        result = {}
        for role, path in roots.items():
            result[role] = None if not path.exists() else {
                item.relative_to(path).as_posix(): None if item.is_dir() else item.read_bytes()
                for item in [path, *path.rglob('*')]
            }
        return result

    def command(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)],
                              cwd=self.root, text=True, capture_output=True)

    def test_roundtrip_to_another_installation_preserves_all_data_and_rollback(self):
        for external in (False, True):
            with self.subTest(external=external):
                project, values, roots = self.installation('source-' + str(external), external)
                target, target_values, target_roots = self.installation('target-' + str(external), external)
                original, previous = self.snapshot(roots), self.snapshot(target_roots)
                directory = self.root / ('backup-' + str(external))
                rollback = self.root / ('rollback-' + str(external))
                backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE((directory / 'manifest.json').stat().st_mode), 0o600)
                manifest = backup.verify_backup(directory)
                self.assertEqual(set(manifest['data']), set(roots))
                backup.restore_backup(directory, target_roots, rollback, target, target_values)
                restored = self.snapshot(target_roots)
                for role in roots:
                    if role != 'env':
                        self.assertEqual(restored[role], original[role])
                loaded = backup.configuration(target)
                self.assertEqual(loaded['DEVICE_API_TOKEN'], 'test-only-secret')
                self.assertEqual(backup.updater.data_layout(target, loaded, modular=True),
                                 backup.updater.data_layout(target, target_values, modular=True))
                self.assertEqual(self.snapshot(roots), original)
                self.assertEqual(self.snapshot({role: rollback / 'data' / role for role in roots}), previous)
                backup.verify_backup(rollback)
                self.assertEqual(list(self.root.rglob('.webclock-restore-*')), [])

    def test_configuration_precedence_has_no_environment_or_file_side_effects(self):
        project, values, roots = self.installation('configuration', True)
        original = self.snapshot(roots)
        os.environ['WEBCLOCK_STATE_DIR'] = 'environment-state'
        before = dict(os.environ)
        self.assertEqual(backup.configuration(project)['WEBCLOCK_STATE_DIR'], 'environment-state')
        loaded = backup.configuration(project, self.root / 'chosen-state', self.root / 'chosen-notes')
        self.assertEqual(loaded['WEBCLOCK_STATE_DIR'], str(self.root / 'chosen-state'))
        self.assertEqual(loaded['NOTES_FILE'], str(self.root / 'chosen-notes'))
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(self.snapshot(roots), original)

    def test_invalid_archive_is_rejected_before_target_writes(self):
        project, values, roots = self.installation('invalid')
        original = self.snapshot(roots)
        for corruption in ('hash', 'unknown-role', 'role-traversal', 'file-traversal', 'layout-traversal', 'symlink'):
            with self.subTest(corruption=corruption):
                directory = self.root / corruption
                rollback = self.root / (corruption + '-rollback')
                backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
                path = directory / 'manifest.json'
                manifest = json.loads(path.read_text())
                if corruption == 'hash':
                    (directory / 'data/default_state/settings.json').write_text('{}')
                elif corruption == 'symlink':
                    (directory / 'data/default_state/link').symlink_to(project / '.env')
                else:
                    if corruption == 'layout-traversal':
                        manifest['layout']['notes']['relative'] = '../outside'
                    elif corruption == 'file-traversal':
                        manifest['data']['default_state']['../outside'] = {'type': 'directory'}
                    else:
                        manifest['data']['unknown' if corruption == 'unknown-role' else '../outside'] = None
                    path.write_text(json.dumps(manifest))
                with patch.object(backup, 'copy_data') as copy, patch.object(backup.os, 'replace') as replace:
                    with self.assertRaises(ValueError):
                        backup.restore_backup(directory, roots, rollback, project, values)
                    copy.assert_not_called()
                    replace.assert_not_called()
                self.assertEqual(self.snapshot(roots), original)
                self.assertFalse(rollback.exists())

    def test_changed_nested_filenames_or_state_suffix_are_rejected_before_staging(self):
        project, values, roots = self.installation('layout')
        directory, rollback = self.root / 'layout-backup', self.root / 'layout-rollback'
        backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
        original = self.snapshot(roots)
        for target_values in ({'NOTES_FILE': 'webclock_state/other-notes.json'},
                              {'WEBCLOCK_STATE_DIR': 'webclock_state/nested'}):
            with self.subTest(target_values=target_values):
                target_roots = backup.data_roots(project, target_values)
                self.assertEqual(set(target_roots), set(roots))
                with patch.object(backup, 'copy_data') as copy:
                    with self.assertRaisesRegex(ValueError, 'layout'):
                        backup.restore_backup(directory, target_roots, rollback, project, target_values)
                    copy.assert_not_called()
                self.assertEqual(self.snapshot(roots), original)
                self.assertFalse(rollback.exists())

    def test_symlink_and_overlapping_paths_cannot_be_backed_up(self):
        project, values, roots = self.installation('unsafe')
        directory = self.root / 'unsafe-backup'
        (project / 'webclock_state/link').symlink_to(project / '.env')
        with patch.object(backup, 'copy_data') as copy:
            with self.assertRaises(ValueError):
                backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
            copy.assert_not_called()
        self.assertFalse(directory.exists())
        with self.assertRaises(ValueError):
            backup.create_backup(project / 'webclock_state/backup', roots,
                                 backup.updater.data_layout(project, values, modular=True))
        self.assertFalse((project / 'webclock_state/backup').exists())

    def test_restore_rejects_target_symlink_before_staging(self):
        project, values, roots = self.installation('source-links', True)
        directory = self.root / 'links-backup'
        backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
        notes = roots['notes']
        notes.unlink()
        notes.symlink_to(project / '.env')
        before = (project / '.env').read_bytes()
        with patch.object(backup, 'copy_data') as copy:
            with self.assertRaises((ValueError, RuntimeError)):
                backup.restore_backup(directory, roots, self.root / 'links-rollback', project, values)
            copy.assert_not_called()
        self.assertEqual((project / '.env').read_bytes(), before)
        self.assertTrue(notes.is_symlink())

    def test_replace_failure_rolls_back_every_changed_role_and_keeps_backup(self):
        project, values, roots = self.installation('replace-source')
        target, target_values, target_roots = self.installation('replace-target')
        directory, rollback = self.root / 'replace-backup', self.root / 'replace-rollback'
        backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
        previous = self.snapshot(target_roots)
        real_replace = backup.os.replace

        def fail_once(source_path, target_path):
            if Path(source_path).name == 'incoming' and Path(target_path) == target_roots['default_state']:
                raise OSError('simulated replacement failure')
            return real_replace(source_path, target_path)

        with patch.object(backup.os, 'replace', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'simulated'):
                backup.restore_backup(directory, target_roots, rollback, target, target_values)
        self.assertEqual(self.snapshot(target_roots), previous)
        self.assertEqual(self.snapshot({role: rollback / 'data' / role for role in roots}), previous)
        backup.verify_backup(rollback)
        self.assertEqual(list(self.root.rglob('.webclock-restore-*')), [])

    def test_copy_failure_never_replaces_original_data_or_leaves_partial_backup(self):
        project, values, roots = self.installation('copy')
        original = self.snapshot(roots)
        directory, rollback = self.root / 'copy-backup', self.root / 'copy-rollback'
        backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
        real_copy = backup.copy_data
        for operation in ('staging', 'rollback', 'create'):
            with self.subTest(operation=operation):
                calls = 0

                def fail_copy(source, target):
                    nonlocal calls
                    calls += 1
                    if (operation != 'rollback' and calls == 2) or (operation == 'rollback' and rollback in target.parents):
                        raise OSError('simulated copy failure')
                    return real_copy(source, target)

                with patch.object(backup, 'copy_data', side_effect=fail_copy):
                    with self.assertRaisesRegex(OSError, 'simulated'):
                        if operation == 'create':
                            backup.create_backup(rollback, roots, backup.updater.data_layout(project, values, modular=True))
                        else:
                            backup.restore_backup(directory, roots, rollback, project, values)
                self.assertEqual(self.snapshot(roots), original)
                backup.verify_backup(directory)
                self.assertFalse(rollback.exists())
                self.assertEqual(list(self.root.rglob('.webclock-restore-*')), [])

    def test_interrupt_after_successful_rename_restores_present_and_absent_targets(self):
        project, values, roots = self.installation('interrupt-source')
        directory = self.root / 'interrupt-backup'
        backup.create_backup(directory, roots, backup.updater.data_layout(project, values, modular=True))
        real_replace = backup.os.replace
        for missing in (False, True):
            with self.subTest(missing=missing):
                target, target_values, target_roots = self.installation('interrupt-target-' + str(missing))
                interrupted_target = target_roots['legacy_notes']
                if missing:
                    interrupted_target.unlink()
                previous = self.snapshot(target_roots)
                rollback = self.root / ('interrupt-rollback-' + str(missing))

                def interrupt_after_replace(source_path, target_path):
                    real_replace(source_path, target_path)
                    if ((missing and Path(source_path).name == 'incoming' and target_path == interrupted_target)
                            or (not missing and source_path == interrupted_target and Path(target_path).name == 'previous')):
                        raise KeyboardInterrupt('simulated interrupt after successful rename')

                with patch.object(backup.os, 'replace', side_effect=interrupt_after_replace):
                    with self.assertRaisesRegex(KeyboardInterrupt, 'successful rename'):
                        backup.restore_backup(directory, target_roots, rollback, target, target_values)
                self.assertEqual(self.snapshot(target_roots), previous)
                self.assertEqual(self.snapshot({role: rollback / 'data' / role for role in roots}), previous)
                backup.verify_backup(rollback)
                self.assertEqual(list(self.root.rglob('.webclock-restore-*')), [])

    def test_cli_requires_explicit_stop_and_restore_confirmation_and_honors_lock(self):
        project, values, roots = self.installation('cli')
        original = self.snapshot(roots)
        directory, rollback = self.root / 'cli-backup', self.root / 'cli-rollback'
        for arguments in (('create', directory), ('restore', directory, '--yes', '--rollback-dir', rollback),
                          ('restore', directory, '--stopped', '--rollback-dir', rollback),
                          ('restore', directory, '--stopped', '--yes')):
            with self.subTest(arguments=arguments):
                result = self.command(*arguments, '--project', project)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(roots), original)
                self.assertFalse(directory.exists())
        with backup.installation_lock(project):
            result = self.command('create', directory, '--project', project, '--stopped')
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(directory.exists())
        result = self.command('create', directory, '--project', project, '--stopped')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.command('verify', directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('test-only-secret', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
