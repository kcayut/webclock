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

SETUP_TEXT = {
    'zh-TW': {'title': '建立第一位管理員', 'code': '主機一次性設定碼',
              'hint': '先在主機執行 manage_auth.py setup-code 取得限時設定碼。已有管理員時只能使用原帳號復原。'},
    'en': {'title': 'Set up the first administrator', 'code': 'Host setup code',
           'hint': 'Run manage_auth.py setup-code on the host for a temporary code. Existing administrators must use account recovery.'},
    'ja': {'title': '最初の管理者を設定', 'code': 'ホストの設定コード',
           'hint': 'ホストで manage_auth.py setup-code を実行し、一時コードを取得してください。管理者が存在する場合は復旧を使用します。'},
}


def current_owner(service):
    if service.mode() == 'self':
        return service.owner_id()
    return service.authenticate(session.get('admin_token'))


def management_transport_allowed():
    """HA Ingress authenticates its proxy before accepting the browser origin."""
    return request.is_secure or (os.getenv('WEBCLOCK_HA_APP') == '1'
                                 and request.environ.get('webclock.surface') == 'ingress')


def client_transport_allowed():
    return management_transport_allowed() or (os.getenv('WEBCLOCK_HA_APP') == '1'
                                              and request.environ.get('webclock.surface') == 'display')


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
        return render_template('login.html', language=lang, login_text=LOGIN_TEXT[lang], error=error,
                               back_url=request.script_root.rstrip('/') + '/')

    @auth.route('/setup', methods=['GET', 'POST'])
    def setup():
        service = service_getter()
        if service.state().get('accounts'):
            return jsonify(code='already_initialized'), 409
        lang = language()
        labels = dict(LOGIN_TEXT[lang], **SETUP_TEXT[lang])
        error = None
        status = 200
        if request.method == 'POST':
            if not request.is_secure:
                return jsonify(code='https_required'), 403
            data = request.get_json(silent=True) if request.is_json else request.form
            data = data if hasattr(data, 'get') else {}
            try:
                result = service.complete_setup(data.get('code'), data.get('username'), data.get('password'),
                                                request.remote_addr)
                session.clear()
                if request.is_json:
                    return jsonify(result), 201
                return redirect(request.script_root.rstrip('/') + '/login')
            except AuthError as exc:
                if request.is_json:
                    return jsonify(code=exc.code), exc.status
                error, status = labels.get(exc.code, labels['error']), exc.status
        return render_template('login.html', language=lang, login_text=labels, error=error,
                               setup=True, back_url=request.script_root.rstrip('/') + '/'), status

    @auth.route('/login', methods=['GET', 'POST'])
    def login():
        service = service_getter()
        if service.mode() == 'self':
            return redirect(request.script_root.rstrip('/') + '/admin')
        if request.method == 'GET':
            return page()
        if not management_transport_allowed():
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
        session['auth_generation'] = service.state()['generation']
        if request.is_json:
            return jsonify(owner_id=identity['owner_id'], expires_at=identity['expires_at'],
                           csrf_token=session['csrf_token'])
        return redirect(request.script_root.rstrip('/') + '/admin')

    @auth.route('/logout', methods=['POST'])
    def logout():
        service_getter().logout(session.get('admin_token'))
        session.clear()
        session['csrf_token'] = secrets.token_urlsafe(32)
        if request.is_json:
            return jsonify(ok=True, csrf_token=session['csrf_token'])
        return redirect(request.script_root.rstrip('/') + '/login')

    app.register_blueprint(auth)
