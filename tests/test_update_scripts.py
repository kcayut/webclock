"""Relocated host entrypoints run from any cwd without touching a real service."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UpdateScriptsTest(unittest.TestCase):
    def test_copied_portable_linux_entry_keeps_channels_project_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            project, commands = work / 'installed', work / 'bin'
            (project / '.git').mkdir(parents=True)
            (project / 'scripts').mkdir()
            (project / 'scripts/enable_updates.sh').write_text('echo enabled >> "$TEST_LOG"\n')
            commands.mkdir()
            log = work / 'commands.log'
            copied = work / 'portable.sh'
            shutil.copy2(ROOT / 'scripts/update/portable_update_clock.sh', copied)
            stubs = {
                'sudo': 'exec "$@"\n',
                'python3': 'printf "python:%s\\n" "$@" >> "$TEST_LOG"\n',
                'git': '''case "$*" in
  *'config --get webclock.releaseChannel') printf '%s' "$TEST_CHANNEL" ;;
  *fetch) echo fetch >> "$TEST_LOG" ;;
  *rev-parse*) echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
  *show*) echo '# synthetic updater' ;;
  *) exit 90 ;;
esac
''',
            }
            for name, body in stubs.items():
                path = commands / name
                path.write_text('#!/bin/bash\nset -eu\n' + body)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'],
                       TEST_LOG=str(log), TMPDIR=str(work))
            for channel in ('stable', 'beta', ''):
                with self.subTest(channel=channel):
                    log.write_text('')
                    result = subprocess.run(['bash', str(copied), str(project)], cwd=work,
                                            env=dict(env, TEST_CHANNEL=channel), capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    lines = log.read_text().splitlines()
                    self.assertIn('python:' + str(project), lines)
                    self.assertEqual('fetch' in lines, not bool(channel))
                    if channel:
                        self.assertIn('python:' + str(project / 'update_clock.py'), lines)
                    else:
                        updater = next(line.removeprefix('python:') for line in lines
                                       if line.startswith('python:') and 'webclock-updater.' in line)
                        self.assertFalse(Path(updater).exists())
                    self.assertIn('enabled', lines)

    def test_docker_entries_resolve_the_installation_and_forward_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            project = work / 'installed'
            (project / 'scripts/update').mkdir(parents=True)
            for name in ('docker_update.sh', 'scripts/update/docker_update.sh'):
                shutil.copy2(ROOT / name, project / name)
            commands = work / 'bin'
            commands.mkdir()
            python = commands / 'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            for name in ('docker_update.sh', 'scripts/update/docker_update.sh'):
                with self.subTest(entrypoint=name):
                    result = subprocess.run(['bash', str(project / name), '--diagnose'], cwd=work,
                        env=dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH']),
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(),
                        [str(project / 'scripts/docker_update.py'), '--project', str(project), '--diagnose'])


if __name__ == '__main__':
    unittest.main()
