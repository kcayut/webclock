"""Relocated host entrypoints run from any cwd without touching a real service."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
                'python3': '''if [ "$1" = - ] || [ "${1:-}" = "" ]; then exec "$REAL_PYTHON" "$@"; fi
printf "python:%s\\n" "$@" >> "$TEST_LOG"
''',
                'git': '''case "$*" in
  *'config --get webclock.releaseChannel') printf '%s' "$TEST_CHANNEL" ;;
  *'rev-parse --abbrev-ref --symbolic-full-name @{upstream}') printf '%s\\n' "${TEST_UPSTREAM_REF:-origin/main}" ;;
  *'remote get-url '*) printf '%s\\n' "${TEST_UPSTREAM_URL:-https://gitea.example/owner/webclock.git}" ;;
  *fetch) echo fetch >> "$TEST_LOG" ;;
  *'rev-parse --verify HEAD^{commit}') echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
  *'rev-parse --verify @{upstream}^{commit}') echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb ;;
  *'merge-base --is-ancestor '*) exit "${TEST_ANCESTOR_EXIT:-0}" ;;
  *'show aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:VERSION') printf '%s\\n' "${TEST_HEAD_VERSION-1.5.0}" ;;
  *'show bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:VERSION') [ -n "${TEST_UPSTREAM_VERSION-1.5.0}" ] && printf '%s\\n' "${TEST_UPSTREAM_VERSION-1.5.0}" || exit 128 ;;
  *':update_clock.py') echo '# synthetic updater' ;;
  *) exit 90 ;;
esac
''',
            }
            for name, body in stubs.items():
                path = commands / name
                path.write_text('#!/bin/bash\nset -eu\n' + body)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'],
                       REAL_PYTHON=sys.executable, TEST_LOG=str(log), TMPDIR=str(work))
            help_result = subprocess.run(['bash', str(copied), '--help'], cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn('--upstream', help_result.stdout)
            (project / 'scripts/update_clock.py').write_text('# --channel --upstream supported\n')
            for channel, expected in (('stable', 'stable'), ('beta', 'beta'), ('', 'stable')):
                with self.subTest(channel=channel, mode='default'):
                    log.write_text('')
                    result = subprocess.run(['bash', str(copied), str(project)], cwd=work,
                                            env=dict(env, TEST_CHANNEL=channel), capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    lines = log.read_text().splitlines()
                    self.assertIn('python:--channel', lines)
                    self.assertIn('python:' + expected, lines)
                    self.assertIn('python:' + str(project), lines)
                    self.assertNotIn('fetch', lines)
                    self.assertIn('python:' + str(project / 'update_clock.py'), lines)
                    self.assertIn('enabled', lines)
            with self.subTest(mode='contemporary_upstream'):
                log.write_text('')
                result = subprocess.run(['bash', str(copied), '--upstream', str(project)], cwd=work,
                                        env=dict(env, TEST_CHANNEL='stable'), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = log.read_text().splitlines()
                self.assertIn('python:' + str(project / 'update_clock.py'), lines)
                self.assertIn('python:--upstream', lines)
                self.assertIn('python:' + str(project), lines)
                self.assertNotIn('fetch', lines)
                self.assertFalse(any('webclock-updater.' in line for line in lines))
                self.assertIn('enabled', lines)
            with self.subTest(mode='pre_1_2_default_refused'):
                log.write_text('')
                (project / 'scripts/update_clock.py').write_text('# legacy pre-1.2 updater without channel flag\n')
                result = subprocess.run(['bash', str(copied), str(project)], cwd=work,
                                        env=dict(env, TEST_CHANNEL=''), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('--channel', result.stderr)
                self.assertEqual(log.read_text(), '')
            shutil.copy2(ROOT / 'scripts/release_versions.py', project / 'scripts/release_versions.py')
            (project / 'scripts/update_clock.py').write_text('# --channel legacy without upstream flag\n')
            with self.subTest(mode='legacy_explicit_upstream'):
                log.write_text('')
                result = subprocess.run(['bash', str(copied), '--upstream', str(project)], cwd=work,
                                        env=dict(env, TEST_CHANNEL='stable',
                                                 TEST_UPSTREAM_URL='http://192.168.1.105:3000/owner/webclock.git'),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = log.read_text().splitlines()
                self.assertIn('fetch', lines)
                self.assertIn('python:' + str(project), lines)
                self.assertIn('python:--upstream', lines)
                updater = next(line.removeprefix('python:') for line in lines
                               if line.startswith('python:') and 'webclock-updater.' in line)
                self.assertFalse(Path(updater).exists())
                self.assertIn('enabled', lines)
            for label, extra_env in (
                ('non_ancestor', {'TEST_ANCESTOR_EXIT': '1'}),
                ('downgrade', {'TEST_HEAD_VERSION': '1.5.0', 'TEST_UPSTREAM_VERSION': '1.4.0'}),
                ('missing_version', {'TEST_HEAD_VERSION': '1.5.0', 'TEST_UPSTREAM_VERSION': ''}),
            ):
                with self.subTest(mode='upstream_guard_' + label):
                    log.write_text('')
                    result = subprocess.run(['bash', str(copied), '--upstream', str(project)], cwd=work,
                                            env=dict(env, TEST_CHANNEL='stable', **extra_env),
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(any(line.startswith('python:') for line in log.read_text().splitlines()))

    def test_docker_entries_resolve_the_installation_and_forward_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            project = work / 'installed'
            project.mkdir(parents=True)
            shutil.copy2(ROOT / 'docker_update.sh', project / 'docker_update.sh')
            commands = work / 'bin'
            commands.mkdir()
            python = commands / 'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            result = subprocess.run(['bash', str(project / 'docker_update.sh'), '--diagnose'], cwd=work,
                env=dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH']),
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(),
                [str(project / 'scripts/docker_update.py'), '--project', str(project), '--diagnose'])
        self.assertFalse((ROOT / 'scripts/update/docker_update.sh').exists())
        self.assertFalse((ROOT / 'scripts/update/update_clock.sh').exists())


if __name__ == '__main__':
    unittest.main()
