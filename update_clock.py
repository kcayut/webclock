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
    project = parser.parse_args().project.resolve()
    if os.geteuid() != 0:
        sys.exit('Please run this updater with sudo and the existing project path.')
    if not (project / '.git').exists():
        sys.exit('Standalone updater requires an existing Git checkout as its project path.')
    owner = pwd.getpwuid((project / '.git').stat().st_uid).pw_name
    git = (['runuser', '-u', owner, '--'] if owner != 'root' else []) + ['git']
    try:
        revision = subprocess.run(git + ['rev-parse', '--verify', '@{upstream}^{commit}'],
                                  cwd=project, check=True, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()
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
