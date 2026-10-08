#!/usr/bin/env python3
"""Host-only administrator setup/recovery; stop WebClock before making changes."""
import argparse
import getpass
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webclock.services.auth_service import AuthError, AuthService, AuthStateError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, help='Override WEBCLOCK_STATE_DIR.')
    actions = parser.add_subparsers(dest='action', required=True)
    setup = actions.add_parser('setup', help='Explicitly enable managed mode on a stopped installation.')
    setup.add_argument('--username', required=True)
    setup.add_argument('--enable-managed', '--enable-managed-test', dest='enable_managed', action='store_true',
                       help='Enable administrator login and require each display to join with its own code. '
                            '--enable-managed-test remains a compatible alias.')
    recovery = actions.add_parser('reset-password', help='Recover an existing administrator; revoke all login sessions.')
    recovery.add_argument('--username', help='Existing administrator username; defaults to the original administrator.')
    setup_code = actions.add_parser('setup-code', help='Issue a one-use code for first web administrator setup.')
    setup_code.add_argument('--expires-in', type=int, default=600, help='Code lifetime in seconds (1 to 3600; default 600).')
    actions.add_parser('status', help='Print mode/owner only, without exposing secrets.')
    args = parser.parse_args(argv)
    load_dotenv(ROOT / '.env')
    path = (args.state_dir or Path(os.getenv('WEBCLOCK_STATE_DIR', str(ROOT / 'webclock_state')))) / 'auth.json'
    service = AuthService(path)
    try:
        if args.action == 'status':
            data = service.state()
            print('mode=' + data['mode'] + ' owner_id=' + data['owner_id'])
            return 0
        if args.action == 'setup-code':
            result = service.issue_setup_code(args.expires_in)
            print('One-use setup code: ' + result['code'])
            print('Expires at Unix time ' + str(result['expires_at']) + '. Enter it at /setup over HTTPS.')
            return 0
        if args.action == 'setup' and not args.enable_managed:
            parser.error('setup requires --enable-managed; existing displays must join with a code after restart')
        # Never put a password on the command line, environment, or stdout.
        password = getpass.getpass('New administrator password (at least 12 characters): ')
        if password != getpass.getpass('Confirm password: '):
            raise AuthError('password_mismatch', 'Passwords do not match.')
        if args.action == 'setup':
            result = service.setup(args.username, password, enable_managed=args.enable_managed)
        else:
            result = service.reset_password(password, username=args.username)
        print('Administrator saved. owner_id=' + result['owner_id'] + '. Restart WebClock before use.')
        return 0
    except (AuthError, AuthStateError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
