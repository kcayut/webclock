"""CSRF protection for the anonymous management UI, independent of device auth."""
import hmac
import secrets
from urllib.parse import urlsplit

from flask import jsonify, request, session


def register_csrf(app):
    # ponytail: one server process, like JSON storage. Restarting requires a fresh
    # management page; shared/persistent sessions belong with future account auth.
    app.secret_key = secrets.token_bytes(32)
    app.config.update(SESSION_COOKIE_NAME='webclock_csrf', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax')

    def token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return session['csrf_token']

    app.jinja_env.globals['csrf_token'] = token

    def same_origin():
        origin = request.headers.get('Origin')
        if origin is not None and origin != request.host_url.rstrip('/'):
            return False
        referer = request.headers.get('Referer')
        if referer:
            try:
                parsed = urlsplit(referer)
                if parsed.scheme + '://' + parsed.netloc != request.host_url.rstrip('/'):
                    return False
            except ValueError:
                return False
        return request.headers.get('Sec-Fetch-Site') != 'cross-site'

    def rejected():
        return jsonify(error='CSRF validation failed; reload the management page.', code='csrf_failed'), 403

    @app.route('/api/csrf')
    def csrf_token():
        if not same_origin():
            return rejected()
        return jsonify(csrf_token=token())

    @app.before_request
    def protect_management_writes():
        if (request.method in ('GET', 'HEAD', 'OPTIONS') or request.endpoint is None
                or request.blueprint == 'server_api.device'):
            return None
        expected = session.get('csrf_token')
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
        if (not same_origin() or not isinstance(expected, str) or not expected
                or not hmac.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8'))):
            return rejected()
        return None
