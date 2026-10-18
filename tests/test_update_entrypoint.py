import contextlib
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_UPDATER = '''import json
from pathlib import Path
import subprocess
import sys

def main():
    project = Path(sys.argv[1])
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=project,
                           check=True, text=True, stdout=subprocess.PIPE).stdout
    if dirty:
        sys.exit('Uncommitted files found; nothing updated.')
    print(json.dumps({'file': __file__, 'argv': sys.argv}))

if __name__ == '__main__':
    main()
'''


class UpdateEntrypointTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        original_modules = dict(sys.modules)
        def restore_modules():
            for key in list(sys.modules):
                if key not in original_modules:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = original_modules[key]
        self.addCleanup(restore_modules)
        self.root = Path(temporary.name).resolve()
        self.remote = self.root / 'remote'
        self.project = self.root / 'installed'
        self.git('init', '-b', 'main', str(self.remote))
        self.git('config', 'user.name', 'Test', cwd=self.remote)
        self.git('config', 'user.email', 'test@example.invalid', cwd=self.remote)
        (self.remote / 'app.py').write_text('old source\n')
        self.commit()
        self.git('clone', str(self.remote), str(self.project))
        self.old_head = self.git('rev-parse', 'HEAD', cwd=self.project)
        (self.remote / 'scripts').mkdir()
        (self.remote / 'scripts/update_clock.py').write_text(SAMPLE_UPDATER)
        shutil.copy2(ROOT / 'update_clock.py', self.remote / 'update_clock.py')
        shutil.copy2(ROOT / 'update_clock.sh', self.remote / 'update_clock.sh')
        (self.remote / 'scripts/update').mkdir()
        shutil.copy2(ROOT / 'scripts/update/update_clock.sh', self.remote / 'scripts/update/update_clock.sh')
        self.commit()
        self.git('fetch', cwd=self.project)
        self.standalone = self.root / 'downloaded-updater.py'
        self.standalone.write_text(self.git('show', '@{upstream}:update_clock.py', cwd=self.project))

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def commit(self):
        self.git('add', '.', cwd=self.remote)
        self.git('commit', '-m', 'test version', cwd=self.remote)

    def bootstrap(self, *args, uid=0):
        output = io.StringIO()
        with patch.object(sys, 'argv', [str(self.standalone), *map(str, args)]), \
                patch('os.geteuid', return_value=uid), \
                patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='root')), \
                contextlib.redirect_stdout(output):
            runpy.run_path(str(self.standalone), run_name='__main__')
        return output.getvalue()

    def test_downloaded_root_entrypoint_loads_fetched_source_without_updating_checkout(self):
        result = json.loads(self.bootstrap(self.project))
        self.assertEqual(result['file'], str(self.project / 'scripts/update_clock.py'))
        self.assertEqual(result['argv'], [str(self.standalone), str(self.project)])
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.project), self.old_head)
        self.assertFalse((self.project / 'scripts').exists())
        self.assertEqual(self.git('status', '--porcelain', cwd=self.project), '')

    def test_non_root_and_dirty_project_remain_untouched(self):
        with self.assertRaisesRegex(SystemExit, 'sudo'):
            self.bootstrap(self.project, uid=1000)
        (self.project / 'app.py').write_text('user changes\n')
        with self.assertRaisesRegex(SystemExit, 'Uncommitted files'):
            self.bootstrap(self.project)
        self.assertEqual((self.project / 'app.py').read_text(), 'user changes\n')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.project), self.old_head)
        self.assertFalse((self.project / 'scripts').exists())

    def test_standalone_help_and_missing_project(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            # Help must work before privilege and project validation.
            with patch.object(sys, 'argv', [str(self.standalone), '--help']), \
                    patch('os.geteuid', return_value=1000):
                runpy.run_path(str(self.standalone), run_name='__main__')
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn('existing WebClock Git checkout', output.getvalue())
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            self.bootstrap()
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn('project', error.getvalue())
        with self.assertRaisesRegex(SystemExit, 'existing Git checkout'):
            self.bootstrap(self.root / 'missing')

    def test_missing_upstream_script_reports_actionable_error(self):
        self.git('update-ref', 'refs/remotes/origin/main', self.old_head, cwd=self.project)
        with self.assertRaisesRegex(SystemExit, 'Cannot read the fetched upstream updater'):
            self.bootstrap(self.project)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.project), self.old_head)

    def test_normal_shell_entrypoint_forwards_project_argument(self):
        for name in ('update_clock.sh', 'scripts/update/update_clock.sh'):
            with self.subTest(entrypoint=name):
                result = subprocess.run(['bash', str(self.remote / name), str(self.project)],
                                        cwd=self.root, check=True, text=True, stdout=subprocess.PIPE)
                output = json.loads(result.stdout)
                self.assertEqual(output['argv'][1:], [str(self.project)])
                self.assertEqual(output['file'], str(self.remote / 'scripts/update_clock.py'))

    def test_shell_help_does_not_enable_or_restart_the_updater(self):
        (self.remote / 'scripts/update_clock.py').write_text(
            'import argparse\ndef main():\n    argparse.ArgumentParser().parse_args()\n')
        (self.remote / 'scripts/enable_updates.sh').write_text('echo unexpected-service-change; exit 91\n')
        for name in ('update_clock.sh', 'scripts/update/update_clock.sh'):
            result = subprocess.run(['bash', str(self.remote / name), '--help'], cwd=self.root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('unexpected-service-change', result.stdout)

    def test_normal_import_alias_and_dependency_errors(self):
        import update_clock
        from scripts import update_clock as implementation
        self.assertIs(update_clock, implementation)
        (self.remote / 'scripts/update_clock.py').write_text('import missing_webclock_test_dependency\n')
        result = subprocess.run([sys.executable, str(self.remote / 'update_clock.py')],
                                cwd=self.root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named 'missing_webclock_test_dependency'", result.stderr)
        self.assertNotIn('Cannot read the fetched upstream updater', result.stderr)

    def test_downloaded_entrypoint_preloads_release_versions_from_upstream_commit(self):
        updater_source = '''import json
from pathlib import Path
import sys
try:
    from scripts import release_versions
except ImportError:
    import release_versions

def main():
    print(json.dumps({'channel': release_versions.TEST_CHANNEL}))

if __name__ == '__main__':
    main()
'''
        (self.remote / 'scripts/release_versions.py').write_text("TEST_CHANNEL = 'custom_beta'\n")
        (self.remote / 'scripts/update_clock.py').write_text(updater_source)
        self.commit()
        self.git('fetch', cwd=self.project)
        sys.modules.pop('release_versions', None)
        sys.modules.pop('scripts.release_versions', None)
        result = json.loads(self.bootstrap(self.project))
        self.assertEqual(result['channel'], 'custom_beta')
        self.assertFalse((self.project / 'scripts/release_versions.py').exists())

    def test_scripts_update_clock_fallback_loader_loads_release_versions_from_git(self):
        shutil.copy2(ROOT / 'scripts/release_versions.py', self.remote / 'scripts/release_versions.py')
        shutil.copy2(ROOT / 'scripts/update_clock.py', self.remote / 'scripts/update_clock.py')
        self.commit()
        self.git('fetch', cwd=self.project)
        cmd = [
            sys.executable, '-c',
            'import runpy; runpy.run_path("{}", run_name="__main__")'.format(
                self.remote / 'scripts/update_clock.py'
            ),
            '--help'
        ]
        result = subprocess.run(cmd, cwd=self.project, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Update an existing Linux/systemd installation', result.stdout)


if __name__ == '__main__':
    unittest.main()
