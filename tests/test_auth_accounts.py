"""Multi-account identity, protected self transitions and host setup regression."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import manage_auth
from webclock.services.auth_service import AuthError, AuthService, AuthStateError
from webclock.services.storage import save_json

PASSWORD = 'original administrator password'
MEMBER_PASSWORD = 'other owner private password'


class AuthAccountsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'auth.json'
        self.timestamp = 1000.0
        self.service = AuthService(self.path, now=lambda: self.timestamp)

    def accounts(self):
        admin = self.service.setup('admin', PASSWORD, enable_managed=True)['owner_id']
        member = self.service.create_account('member', MEMBER_PASSWORD)['owner_id']
        return admin, member

    def switch(self, mode, primary, admin, **kwargs):
        return self.service.switch_mode(mode, primary, admin_owner_id=admin, password=PASSWORD,
            expected_generation=self.service.state()['generation'], confirm_shared=True, **kwargs)

    def test_setup_code_wrong_expired_used_and_existing_administrator(self):
        code = self.service.issue_setup_code(10)
        self.assertNotIn(code['code'], self.path.read_text())
        owner = self.service.owner_id()
        with self.assertRaises(AuthError) as error:
            self.service.complete_setup('wrong', 'admin', PASSWORD)
        self.assertEqual(error.exception.code, 'invalid_setup_code')
        self.assertEqual(self.service.state()['accounts'], {})
        self.timestamp += 10
        with self.assertRaises(AuthError):
            self.service.complete_setup(code['code'], 'admin', PASSWORD)
        fresh = self.service.issue_setup_code()
        self.assertNotEqual(code['code'], fresh['code'])
        with self.assertRaises(AuthError):
            self.service.complete_setup(code['code'], 'admin', PASSWORD)
        self.assertEqual(self.service.complete_setup(fresh['code'], 'admin', PASSWORD)['owner_id'], owner)
        with self.assertRaises(AuthError) as error:
            self.service.complete_setup(fresh['code'], 'replacement', PASSWORD)
        self.assertEqual(error.exception.code, 'already_initialized')
        with self.assertRaises(AuthError):
            self.service.issue_setup_code()
        self.switch('self', owner, owner)
        with self.assertRaises(AuthError):
            self.service.setup('replacement', PASSWORD, enable_managed=True)
        with self.assertRaises(AuthError):
            self.service.issue_setup_code()

    def test_setup_cli_emits_code_without_password_and_cannot_rebind(self):
        output = StringIO()
        with patch.object(manage_auth, 'load_dotenv'), patch.object(manage_auth.getpass, 'getpass') as password, \
                redirect_stdout(output):
            self.assertEqual(manage_auth.main(['--state-dir', str(self.path.parent), 'setup-code']), 0)
        password.assert_not_called()
        code = output.getvalue().split('One-use setup code: ')[1].splitlines()[0]
        service = AuthService(self.path)
        service.complete_setup(code, 'admin', PASSWORD)
        self.assertEqual(service.mode(), 'managed')
        self.assertNotIn(code, self.path.read_text())

    def test_competing_initial_setup_consumes_code_once(self):
        code = self.service.issue_setup_code()['code']
        def apply(username):
            try:
                return self.service.complete_setup(code, username, PASSWORD)['username']
            except AuthError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(apply, ('first', 'second')))
        self.assertIn('already_initialized', results)
        self.assertEqual(len(self.service.state()['accounts']), 1)
        self.assertIn(self.service.state()['username'], results)

    def test_legacy_managed_is_normalized_without_disk_migration(self):
        admin, _member = self.accounts()
        state = self.service.state()
        for field in ('accounts', 'administrator_id', 'data_owner_id'):
            del state[field]
        save_json(self.path, state)
        before = self.path.read_bytes()
        normalized = self.service.state()
        self.assertEqual(normalized['accounts'][admin]['role'], 'admin')
        self.assertEqual(normalized['data_owner_id'], admin)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.service.login('admin', PASSWORD)['owner_id'], admin)

    def test_roundtrip_keeps_accounts_and_primary_member_role_rotates_credentials(self):
        admin, member = self.accounts()
        before = self.service.state()
        login = self.service.login('member', MEMBER_PASSWORD)
        self.assertEqual(self.service.authenticate(login['token']), member)
        self.assertFalse(self.service.is_admin(member))
        self.timestamp += 7
        self.switch('self', member, admin)
        state = AuthService(self.path).state()
        self.assertEqual(state['accounts'], before['accounts'])
        self.assertEqual(state['data_owner_id'], admin)
        self.assertEqual(state['owner_id'], member)
        self.assertEqual(state['scope_changed_at'], 1007000)
        self.assertEqual(state['explicit_self_generation'], state['generation'])
        self.assertNotEqual(state['invite_secret'], before['invite_secret'])
        self.assertNotEqual(state['session_secret'], before['session_secret'])
        self.assertIsNone(self.service.authenticate(login['token']))
        self.assertFalse(self.service.owner_active(admin))
        self.assertTrue(self.service.owner_active(member))
        with self.assertRaises(AuthError):
            self.service.login('admin', PASSWORD)
        for action in (lambda: self.service.create_account('third', PASSWORD),
                       lambda: self.service.update_account(admin, enabled=False),
                       lambda: self.service.delete_account(member)):
            with self.assertRaises(AuthError) as error:
                action()
            self.assertEqual(error.exception.code, 'managed_required')
        self.assertEqual(self.service.verify_admin('admin', PASSWORD, 'return'), admin)
        self.switch('managed', member, admin, source='return')
        self.assertEqual(self.service.state()['accounts'], before['accounts'])
        self.assertEqual(self.service.state()['owner_id'], member)
        self.assertEqual(self.service.state()['data_owner_id'], admin)
        self.assertEqual(self.service.login('member', MEMBER_PASSWORD)['owner_id'], member)
        self.assertTrue(self.service.owner_active(admin))
        self.assertIsNone(self.service.authenticate(login['token']))

    def test_admin_password_primary_and_confirmation_are_required(self):
        admin, member = self.accounts()
        state = self.service.state()
        base = dict(mode='self', primary_owner_id=member, admin_owner_id=admin,
                    password=PASSWORD, expected_generation=state['generation'], confirm_shared=True)
        for override, code in (({'admin_owner_id': member}, 'admin_required'),
                               ({'password': 'incorrect password'}, 'invalid_credentials'),
                               ({'primary_owner_id': None}, 'invalid_primary_owner'),
                               ({'primary_owner_id': []}, 'invalid_primary_owner'),
                               ({'confirm_shared': False}, 'sharing_confirmation_required'),
                               ({'expected_generation': state['generation'] - 1}, 'generation_conflict')):
            with self.subTest(code=code), self.assertRaises(AuthError) as error:
                self.service.switch_mode(**dict(base, **override), source=code)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(self.service.state(), state)
        with self.assertRaises(AuthError) as error:
            self.service.verify_admin('member', MEMBER_PASSWORD, 'member')
        self.assertEqual(error.exception.code, 'admin_required')
        self.service.update_account(member, enabled=False)
        with self.assertRaises(AuthError) as error:
            self.switch('self', member, admin, source='disabled')
        self.assertEqual(error.exception.code, 'invalid_primary_owner')

    def test_disabled_and_primary_account_protection_and_session_revocation(self):
        admin, member = self.accounts()
        login = self.service.login('member', MEMBER_PASSWORD)
        self.service.update_account(member, enabled=False)
        self.assertFalse(self.service.owner_active(member))
        self.assertIsNone(self.service.authenticate(login['token']))
        with self.assertRaises(AuthError):
            self.service.login('member', MEMBER_PASSWORD)
        self.service.update_account(member, enabled=True)
        self.switch('self', member, admin)
        self.switch('managed', member, admin)
        for owner in (admin, member):
            with self.assertRaises(AuthError):
                self.service.update_account(owner, enabled=False)
            with self.assertRaises(AuthError):
                self.service.delete_account(owner)
        with self.assertRaises(AuthError):
            self.service.update_account(admin, role='member')

    def test_simultaneous_transition_only_commits_once(self):
        admin, member = self.accounts()
        generation = self.service.state()['generation']
        def apply(_):
            try:
                return self.service.switch_mode('self', member, admin_owner_id=admin,
                    password=PASSWORD, expected_generation=generation, confirm_shared=True)['mode']
            except AuthError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(apply, range(2)))
        self.assertCountEqual(results, ['self', 'generation_conflict'])
        self.assertEqual(AuthService(self.path).state()['generation'], generation + 1)

    def test_successful_reauthentication_does_not_exhaust_roundtrip_budget(self):
        admin, member = self.accounts()
        self.service.login('admin', PASSWORD, 'browser')
        for mode in ('self', 'managed', 'self', 'managed'):
            self.assertEqual(self.service.verify_admin('admin', PASSWORD, 'browser'), admin)
            self.switch(mode, member, admin, source='browser')
        self.assertEqual(len(self.service._login_sources['browser']), 1)
        with self.assertRaises(AuthError):
            self.service.verify_admin('admin', 'wrong', 'browser')
        self.assertEqual(len(self.service._login_sources['browser']), 2)

    def test_failed_switch_preserves_old_state_and_restart(self):
        admin, member = self.accounts()
        before = self.path.read_bytes()
        with patch('webclock.services.auth_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.switch('self', member, admin)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(AuthService(self.path).mode(), 'managed')

    def test_protected_self_corruption_never_falls_open(self):
        admin, member = self.accounts()
        self.switch('self', member, admin)
        valid = self.service.state()
        for invalid in (dict(valid, explicit_self_generation=None), dict(valid, accounts={}),
                        dict(valid, owner_id='../escape'), dict(valid, data_owner_id='../escape'),
                        dict(valid, administrator_id=[])):
            save_json(self.path, invalid)
            with self.assertRaises(AuthStateError):
                AuthService(self.path).state()
        invalid = dict(valid, accounts={owner: dict(account) for owner, account in valid['accounts'].items()})
        invalid['accounts'][member]['enabled'] = False
        save_json(self.path, invalid)
        with self.assertRaises(AuthStateError):
            AuthService(self.path).mode()
        self.path.unlink()
        with self.assertRaises(AuthStateError):
            AuthService(self.path).mode()

    def test_host_password_recovery_in_self_keeps_mode_and_accounts(self):
        admin, member = self.accounts()
        member_hash = self.service.state()['accounts'][member]['password_hash']
        self.switch('self', member, admin)
        self.service.reset_password('new recovered admin password')
        self.assertEqual(self.service.mode(), 'self')
        self.assertEqual(self.service.owner_id(), member)
        self.assertEqual(self.service.verify_admin('admin', 'new recovered admin password'), admin)
        self.assertEqual(self.service.state()['accounts'][member]['password_hash'], member_hash)
        self.assertTrue(all('password_hash' not in account for account in self.service.list_accounts()))

    def test_delete_retains_dormant_data_identity_and_revokes_access(self):
        _admin, member = self.accounts()
        login = self.service.login('member', MEMBER_PASSWORD)
        self.service.delete_account(member)
        account = self.service.state()['accounts'][member]
        self.assertFalse(account['enabled'])
        self.assertEqual(account['deleted_at'], self.timestamp)
        self.assertFalse(self.service.owner_active(member))
        self.assertNotIn(member, [account['owner_id'] for account in self.service.list_accounts()])
        self.assertIsNone(self.service.authenticate(login['token']))
        with self.assertRaises(AuthError):
            self.service.update_account(member, enabled=True)


if __name__ == '__main__':
    unittest.main()
