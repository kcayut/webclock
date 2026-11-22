"""Compatibility entry point for the guarded updater."""
from pathlib import Path
import sys


def bootstrap():
    """Load the already-fetched updater when this entry point was copied to /tmp."""
    import argparse
    import os
    import pwd
    import subprocess

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='existing WebClock Git checkout')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--channel', choices=('stable', 'beta'),
                       help='switch this installation to the stable or beta release channel first')
    group.add_argument('--upstream', action='store_true',
                       help='update from the checkout\'s already-configured Git upstream (for example Gitea)')
    project = parser.parse_args().project.resolve()
    if os.geteuid() != 0:
        sys.exit('Please run this updater with sudo and the existing project path.')
    if not (project / '.git').exists():
        sys.exit('Standalone updater requires an existing Git checkout as its project path.')
    owner = pwd.getpwuid((project / '.git').stat().st_uid).pw_name
    git = (['runuser', '-u', owner, '--'] if owner != 'root' else []) + ['git', '-c', 'safe.directory=' + str(project)]
    try:
        head = subprocess.run(git + ['rev-parse', '--verify', 'HEAD^{commit}'],
                              cwd=project, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()
        revision = subprocess.run(git + ['rev-parse', '--verify', '@{upstream}^{commit}'],
                                  cwd=project, check=True, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()
        if subprocess.run(git + ['merge-base', '--is-ancestor', head, revision],
                          cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            sys.exit('Upstream commit does not descend from the installed version; refusing non-fast-forward update or downgrade.')
        old_ver_proc = subprocess.run(git + ['show', head + ':VERSION'], cwd=project, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        new_ver_proc = subprocess.run(git + ['show', revision + ':VERSION'], cwd=project, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        old_ver = old_ver_proc.stdout.strip() if old_ver_proc.returncode == 0 else ''
        new_ver = new_ver_proc.stdout.strip() if new_ver_proc.returncode == 0 else ''
        if old_ver_proc.returncode == 0 and new_ver_proc.returncode != 0:
            sys.exit('Upstream commit is missing VERSION; refusing downgrade.')

        def check_version_with(module):
            parse_version = getattr(module, 'parse_version', None)
            if not callable(parse_version):
                return False
            try:
                if parse_version(new_ver) < parse_version(old_ver):
                    sys.exit(f'Downgrades are unsupported ({old_ver} -> {new_ver}).')
            except ValueError as error:
                sys.exit(str(error))
            return True

        checked_version = False
        if old_ver:
            head_rv = subprocess.run(git + ['show', head + ':scripts/release_versions.py'],
                                     cwd=project, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if head_rv.returncode == 0:
                import types
                head_rv_mod = types.ModuleType('_head_release_versions')
                exec(compile(head_rv.stdout, str(project / 'scripts/release_versions.py'), 'exec'), head_rv_mod.__dict__)
                checked_version = check_version_with(head_rv_mod)
        try:
            rv_source = subprocess.run(git + ['show', revision + ':scripts/release_versions.py'],
                                       cwd=project, check=True, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
            rv_filename = str(project / 'scripts/release_versions.py')
            import types
            rv_mod = types.ModuleType('release_versions')
            exec(compile(rv_source, rv_filename, 'exec'), rv_mod.__dict__)
            sys.modules['release_versions'] = rv_mod
            if 'scripts' in sys.modules:
                scripts_mod = sys.modules['scripts']
            else:
                try:
                    import scripts as scripts_mod
                except ImportError:
                    scripts_mod = types.ModuleType('scripts')
                    scripts_mod.__path__ = [str(project / 'scripts')]
                    sys.modules['scripts'] = scripts_mod
            sys.modules['scripts.release_versions'] = rv_mod
            setattr(scripts_mod, 'release_versions', rv_mod)
            if old_ver and not checked_version:
                checked_version = check_version_with(rv_mod)
        except (OSError, subprocess.CalledProcessError):
            pass
        if old_ver and not checked_version:
            try:
                import scripts.release_versions as local_rv
                check_version_with(local_rv)
            except ImportError:
                pass
        source = subprocess.run(git + ['show', revision + ':scripts/update_clock.py'],
                                cwd=project, check=True, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        sys.exit('Cannot read the fetched upstream updater. Run git fetch and verify the branch upstream.\n' + detail)
    filename = str(project / 'scripts/update_clock.py')
    exec(compile(source, filename, 'exec'), {'__name__': '__main__', '__file__': filename,
                                          '__package__': None, '__cached__': None})


if __name__ == '__main__':
    if (Path(__file__).resolve().parent / 'scripts/update_clock.py').is_file():
        from scripts import update_clock as implementation
        implementation.main()
    else:
        bootstrap()
else:
    from scripts import update_clock as implementation
    sys.modules[__name__] = implementation
