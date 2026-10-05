"""Management login routes. App-wide authorization is registered by app.py."""
import os
import secrets

from flask import Blueprint, jsonify, redirect, render_template, request, session

from webclock.services.auth_service import AUTH_SCHEMA_VERSION, AuthError, AuthStateError


LOGIN_TEXT = {
    'zh-TW': {'title': '管理員登入', 'username': '帳號', 'password': '密碼', 'submit': '登入',
              'back': '返回時鐘', 'invalid_credentials': '帳號或密碼錯誤。',
              'rate_limited': '登入嘗試過多，請稍後再試。', 'error': '無法登入，請稍後再試。',
              'hint': '帳號由主機管理員建立；顯示群組加入碼無法用於登入。'},
    'en': {'title': 'Administrator sign in', 'username': 'Username', 'password': 'Password',
           'submit': 'Sign in', 'back': 'Back to clock', 'invalid_credentials': 'Invalid username or password.',
           'rate_limited': 'Too many attempts. Please try again later.', 'error': 'Unable to sign in.',
           'hint': 'Accounts are created on the host. Display group invitation codes cannot sign in.'},
    'ja': {'title': '管理者ログイン', 'username': 'ユーザー名', 'password': 'パスワード',
           'submit': 'ログイン', 'back': '時計に戻る', 'invalid_credentials': 'ユーザー名またはパスワードが違います。',
           'rate_limited': '試行回数が多すぎます。しばらくしてから再試行してください。', 'error': 'ログインできません。',
           'hint': 'アカウントはホスト上で作成します。表示グループの参加コードではログインできません。'},
}


def current_owner(service):
    if service.mode() == 'self':
        return service.owner_id()
    return service.authenticate(session.get('admin_token'))


def register_auth(app, service_getter):
    auth = Blueprint('auth', __name__)

    @auth.errorhandler(AuthStateError)
    def state_failure(error):
        return jsonify(error='Authorization state requires host recovery.', code='auth_recovery_required'), 503

    @auth.errorhandler(OSError)
    def storage_failure(error):
        return jsonify(error='Unable to save authorization state.', code='storage_failure'), 500

    @auth.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def language():
        value = request.args.get('lang', app.config.get('WEBCLOCK_LANGUAGE',
                                                      os.getenv('WEBCLOCK_LANGUAGE', 'zh-TW')))
        return value if value in LOGIN_TEXT else 'zh-TW'

    def page(error=None):
        lang = language()
        return render_template('login.html', language=lang, login_text=LOGIN_TEXT[lang], error=error)

    @auth.route('/login', methods=['GET', 'POST'])
    def login():
        service = service_getter()
        if service.mode() == 'self':
            return redirect('/admin')
        if request.method == 'GET':
            return page()
        if not request.is_secure:
            return jsonify(error='HTTPS is required for administrator login.', code='https_required'), 403
        values = request.get_json(silent=True) if request.is_json else request.form
        values = values if hasattr(values, 'get') else {}
        try:
            identity = service.login(values.get('username'), values.get('password'), request.remote_addr)
        except AuthError as exc:
            if request.is_json:
                response = jsonify(error=str(exc), code=exc.code)
            else:
                response = app.make_response(page(LOGIN_TEXT[language()].get(exc.code, LOGIN_TEXT[language()]['error'])))
            response.status_code = exc.status
            if exc.retry_after:
                response.headers['Retry-After'] = str(exc.retry_after)
            return response
        previous = session.get('admin_token')
        if previous:
            service.logout(previous)
        session.clear()
        session['admin_token'] = identity['token']
        session['csrf_token'] = secrets.token_urlsafe(32)
        if request.is_json:
            return jsonify(owner_id=identity['owner_id'], expires_at=identity['expires_at'],
                           csrf_token=session['csrf_token'])
        return redirect('/admin')

    @auth.route('/logout', methods=['POST'])
    def logout():
        service_getter().logout(session.get('admin_token'))
        session.clear()
        session['csrf_token'] = secrets.token_urlsafe(32)
        if request.is_json:
            return jsonify(ok=True, csrf_token=session['csrf_token'])
        return redirect('/login')

    app.register_blueprint(auth)
