"""Host identity, persisted revocable sessions, throttling and login routes."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from webclock.auth import current_owner, register_auth
from webclock.csrf import register_csrf
from webclock.services.auth_service import (
    AuthError, AuthService, AuthStateError, LOGIN_GLOBAL_LIMIT, LOGIN_SOURCE_LIMIT,
    LOGIN_WINDOW_SECONDS, MAX_LOGIN_SOURCES, SESSION_SECONDS,
)
from webclock.services.storage import save_json


PASSWORD = 'clock administrator password'


class AuthServiceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'auth.json'
        self.timestamp = 1000.0
        self.service = AuthService(self.path, now=lambda: self.timestamp)

    def setup_managed(self):
        return self.service.setup('admin', PASSWORD, enable_managed_test=True)

    def test_missing_file_remains_self_without_automatic_writes(self):
        self.assertEqual(self.service.mode(), 'self')
        self.assertEqual(self.service.owner_id(), 'local-owner')
        self.assertEqual(self.service.session_secret(), self.service.session_secret())
        self.assertIsNone(self.service.authenticate('anything'))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.service.required_path.exists())

    def test_first_explicit_write_persists_stable_owner_and_independent_secrets(self):
        before_secret = self.service.session_secret()
        state = self.service.ensure_initialized()
        self.assertNotEqual(state['owner_id'], 'local-owner')
        self.assertEqual(state, AuthService(self.path).state())
        self.assertNotEqual(state['session_secret'], state['invite_secret'])
        self.assertEqual(state['session_secret'], before_secret)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        snapshot = self.path.read_bytes()
        self.service.ensure_initialized()
        self.assertEqual(self.path.read_bytes(), snapshot)
        identity = self.setup_managed()
        self.assertEqual(identity['owner_id'], state['owner_id'])

    def test_managed_requires_explicit_opt_in_and_cannot_replace_admin(self):
        with self.assertRaises(AuthError) as caught:
            self.service.setup('admin', PASSWORD)
        self.assertEqual(caught.exception.code, 'managed_opt_in_required')
        self.assertFalse(self.path.exists())
        self.setup_managed()
        snapshot = self.path.read_bytes()
        with self.assertRaises(AuthError) as caught:
            self.service.setup('other', PASSWORD, enable_managed_test=True)
        self.assertEqual(caught.exception.code, 'already_initialized')
        self.assertEqual(self.path.read_bytes(), snapshot)

    def test_formal_enablement_preserves_owner_and_invites_but_rotates_sessions(self):
        before = self.service.ensure_initialized()
        result = self.service.setup('admin', PASSWORD, enable_managed=True)
        after = AuthService(self.path).state()
        self.assertEqual(result['mode'], 'managed')
        for key in ('owner_id', 'invite_secret'):
            self.assertEqual(after[key], before[key])
        self.assertNotEqual(after['session_secret'], before['session_secret'])
        self.assertEqual(after['generation'], before['generation'] + 1)
        self.assertTrue(self.service.required_path.exists())
        with self.assertRaises(AuthError):
            self.service.setup('other', PASSWORD, enable_managed=True)

    def test_password_hash_and_session_digest_persist_without_plaintext(self):
        self.setup_managed()
        identity = self.service.login('admin', PASSWORD, 'one')
        state = self.service.state()
        self.assertNotIn(PASSWORD, self.path.read_text())
        self.assertNotIn(identity['token'], self.path.read_text())
        self.assertTrue(state['password_hash'].startswith('scrypt:'))
        digest = hashlib.sha256(identity['token'].encode()).hexdigest()
        self.assertIn(digest, state['sessions'])
        restarted = AuthService(self.path, now=lambda: self.timestamp)
        self.assertEqual(restarted.authenticate(identity['token']), state['owner_id'])
        self.assertEqual(restarted.session_secret(), state['session_secret'])
        self.assertIsNone(restarted.authenticate('wrong'))

    def test_expiry_is_checked_server_side_at_boundary(self):
        self.setup_managed()
        identity = self.service.login('admin', PASSWORD)
        self.timestamp += SESSION_SECONDS - 1
        self.assertEqual(self.service.authenticate(identity['token']), identity['owner_id'])
        self.timestamp += 1
        self.assertIsNone(self.service.authenticate(identity['token']))

    def test_logout_revokes_only_selected_session_and_retains_identity(self):
        self.setup_managed()
        first = self.service.login('admin', PASSWORD)
        second = self.service.login('admin', PASSWORD)
        before = self.service.state()
        self.service.logout(first['token'])
        self.assertIsNone(AuthService(self.path, now=lambda: self.timestamp).authenticate(first['token']))
        self.assertEqual(self.service.authenticate(second['token']), second['owner_id'])
        after = self.service.state()
        for key in ('owner_id', 'invite_secret', 'session_secret', 'generation'):
            self.assertEqual(before[key], after[key])

    def test_password_recovery_revokes_all_sessions_without_changing_device_secret(self):
        self.setup_managed()
        identities = [self.service.login('admin', PASSWORD) for _ in range(2)]
        before = self.service.state()
        self.service.reset_password('replacement administrator password')
        after = self.service.state()
        self.assertEqual(after['owner_id'], before['owner_id'])
        self.assertEqual(after['invite_secret'], before['invite_secret'])
        self.assertNotEqual(after['session_secret'], before['session_secret'])
        self.assertEqual(after['generation'], before['generation'] + 1)
        self.assertEqual(after['sessions'], {})
        for identity in identities:
            self.assertIsNone(self.service.authenticate(identity['token']))
        with self.assertRaises(AuthError):
            self.service.login('admin', PASSWORD)
        self.assertEqual(self.service.login('admin', 'replacement administrator password')['owner_id'], before['owner_id'])

    def test_corrupt_or_missing_protected_state_fails_closed(self):
        self.setup_managed()
        valid = self.service.state()
        for data in (None, [], {}, dict(valid, version=2), dict(valid, generation=True),
                     dict(valid, session_secret='short'), dict(valid, password_hash='plaintext'),
                     dict(valid, sessions={'not-a-digest': {}})):
            with self.subTest(data=data):
                save_json(self.path, data)
                with self.assertRaises(AuthStateError):
                    self.service.mode()
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(AuthStateError):
            self.service.state()
        self.path.unlink()
        with self.assertRaises(AuthStateError):
            self.service.mode()
        with self.assertRaises(AuthStateError):
            self.service.ensure_initialized()
        save_json(self.path, self.service._empty())
        with self.assertRaises(AuthStateError):
            self.service.mode()

    def test_failed_initialization_leaves_required_marker_and_no_open_fallback(self):
        original_save = save_json
        def fail_auth(path, value):
            if Path(path) == self.path:
                raise OSError('disk full')
            return original_save(path, value)
        with patch('webclock.services.auth_service.save_json', side_effect=fail_auth):
            with self.assertRaises(OSError):
                self.setup_managed()
        self.assertTrue(self.service.required_path.exists())
        self.assertFalse(self.path.exists())
        with self.assertRaises(AuthStateError):
            self.service.mode()

    def test_write_failure_does_not_accept_uncommitted_session_or_reset(self):
        self.setup_managed()
        identity = self.service.login('admin', PASSWORD)
        before = self.path.read_bytes()
        with patch('webclock.services.auth_service.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.service.login('admin', PASSWORD)
            with self.assertRaises(OSError):
                self.service.reset_password('replacement administrator password')
            with self.assertRaises(OSError):
                self.service.logout(identity['token'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.service.authenticate(identity['token']), identity['owner_id'])

    def test_source_login_limit_has_retry_after_and_expires(self):
        self.setup_managed()
        for _ in range(LOGIN_SOURCE_LIMIT):
            with self.assertRaises(AuthError) as caught:
                self.service.login('admin', 'wrong password', 'source')
            self.assertEqual(caught.exception.code, 'invalid_credentials')
        with self.assertRaises(AuthError) as caught:
            self.service.login('admin', PASSWORD, 'source')
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, LOGIN_WINDOW_SECONDS)
        self.assertEqual(self.service.login('admin', PASSWORD, 'other')['owner_id'], self.service.owner_id())
        self.timestamp += LOGIN_WINDOW_SECONDS
        self.assertEqual(self.service.login('admin', PASSWORD, 'source')['owner_id'], self.service.owner_id())

    def test_global_login_limit_bounds_source_cache(self):
        self.setup_managed()
        with patch('webclock.services.auth_service.check_password_hash', return_value=False):
            for index in range(LOGIN_GLOBAL_LIMIT + MAX_LOGIN_SOURCES):
                with self.assertRaises(AuthError) as caught:
                    self.service.login('not-admin', 'wrong password', 'source-' + str(index))
                self.assertEqual(caught.exception.status, 401 if index < LOGIN_GLOBAL_LIMIT else 429)
        self.assertLessEqual(len(self.service._login_sources), MAX_LOGIN_SOURCES)
        self.assertEqual(len(self.service._login_global), LOGIN_GLOBAL_LIMIT)


class AuthRoutesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.service = AuthService(Path(directory.name) / 'auth.json')
        self.service.setup('admin', PASSWORD, enable_managed_test=True)
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        self.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=True)
        register_csrf(self.app)
        self.app.secret_key = self.service.session_secret()
        register_auth(self.app, lambda: self.service)
        @self.app.route('/identity')
        def identity():
            return jsonify(owner_id=current_owner(self.service))
        self.client = self.app.test_client()
        self.base = 'https://localhost'
        self.token = self.client.get('/api/csrf', base_url=self.base).json['csrf_token']

    def login(self, **kwargs):
        return self.client.post('/login', base_url=self.base,
                                json={'username': 'admin', 'password': PASSWORD},
                                headers={'X-CSRF-Token': self.token}, **kwargs)

    def test_login_logout_rotate_csrf_and_replay_of_logged_out_cookie_is_denied(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json['csrf_token'], self.token)
        cookie_name = self.app.config['SESSION_COOKIE_NAME']
        cookie = self.client.get_cookie(cookie_name)
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, 'Lax')
        replay = self.app.test_client()
        replay.set_cookie(cookie_name, cookie.value)
        self.assertEqual(replay.get('/identity', base_url=self.base).json['owner_id'], self.service.owner_id())
        self.assertEqual(self.client.post('/logout', base_url=self.base, json={},
                         headers={'X-CSRF-Token': self.token}).status_code, 403)
        logout = self.client.post('/logout', base_url=self.base, json={},
                                 headers={'X-CSRF-Token': response.json['csrf_token']})
        self.assertEqual(logout.status_code, 200)
        self.assertNotEqual(logout.json['csrf_token'], response.json['csrf_token'])
        self.assertIsNone(replay.get('/identity', base_url=self.base).json['owner_id'])

    def test_login_requires_csrf_and_ignores_forwarded_source(self):
        self.assertEqual(self.client.post('/login', base_url=self.base,
                         json={'username': 'admin', 'password': PASSWORD}).status_code, 403)
        for index in range(LOGIN_SOURCE_LIMIT + 1):
            response = self.client.post('/login', base_url=self.base,
                json={'username': 'admin', 'password': 'wrong'},
                headers={'X-CSRF-Token': self.token, 'X-Forwarded-For': '10.0.0.' + str(index)})
            self.assertEqual(response.status_code, 401 if index < LOGIN_SOURCE_LIMIT else 429)
        self.assertIn('Retry-After', response.headers)

    def test_login_form_has_csrf_three_languages_and_no_return_url_redirect(self):
        for language, title in [('zh-TW', '管理員登入'), ('en', 'Administrator sign in'), ('ja', '管理者ログイン')]:
            page = self.client.get('/login?lang=' + language, base_url=self.base)
            self.assertIn(title, page.text)
            self.assertIn('name="csrf_token"', page.text)
        response = self.client.post('/login?next=https://evil.invalid/', base_url=self.base,
            data={'username': 'admin', 'password': PASSWORD, 'csrf_token': self.token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/admin')

    def test_login_uses_deployment_language_without_private_settings(self):
        with patch.dict(os.environ, WEBCLOCK_LANGUAGE='ja'):
            page = self.client.get('/login', base_url=self.base)
        self.assertIn('管理者ログイン', page.text)

    def test_insecure_login_rejected_and_password_never_reflected(self):
        insecure = self.app.test_client()
        token = insecure.get('/api/csrf').json['csrf_token']
        response = insecure.post('/login', json={'username': 'admin', 'password': PASSWORD},
                                 headers={'X-CSRF-Token': token})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.service.state()['sessions'], {})

    def test_login_write_failures_are_sanitized_and_do_not_commit_a_session(self):
        with patch('webclock.services.auth_service.save_json', side_effect=OSError('PRIVATE disk path')):
            response = self.login()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['code'], 'storage_failure')
        self.assertNotIn('PRIVATE', response.text)
        self.assertEqual(self.service.state()['sessions'], {})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_state_failure_between_guard_and_route_is_closed(self):
        self.service.path.unlink()
        response = self.client.get('/login', base_url=self.base)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['code'], 'auth_recovery_required')


if __name__ == '__main__':
    unittest.main()
