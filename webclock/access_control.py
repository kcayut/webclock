"""Deny private legacy and management entry points in protected installations."""
from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.exceptions import HTTPException

from webclock.csrf import same_origin
from webclock.services.auth_service import AuthStateError


def register_access_control(app, service_getter):
    public = {'index', 'status', 'public_time', 'health', 'service_worker', 'static'}

    def failure(code, status):
        return jsonify(error=code, code=code), status

    @app.before_request
    def authorize():
        g.owner_id = None
        try:
            service = service_getter()
            g.deployment_mode = service.mode()
        except (AuthStateError, OSError, ValueError):
            g.deployment_mode = 'recovery'
            if request.endpoint in public:
                return None
            return failure('auth_recovery_required', 503)

        app.config['SESSION_COOKIE_SECURE'] = g.deployment_mode == 'managed'
        if request.endpoint in public:
            return None
        # Unknown paths and HTTP method errors still use the normal 404/405;
        # they never invoke a data-bearing view.
        if request.endpoint is None:
            return None
        if request.endpoint in {'auth.login', 'csrf_token'}:
            return None
        if g.deployment_mode == 'self':
            return None
        if not same_origin():
            return failure('cross_origin_forbidden', 403)
        # Neither the shared schema-2 token nor an administrator cookie is a
        # per-device identity. The new device API is delivered in B2.
        if request.path.startswith('/api/v1/device/'):
            return failure('legacy_device_api_disabled', 403)
        if request.path == '/api/v1/browser-alarms':
            return failure('device_authorization_required', 401)
        try:
            owner = service.authenticate(session.get('admin_token'))
        except (AuthStateError, OSError, ValueError):
            return failure('auth_recovery_required', 503)
        if not owner:
            if request.path.startswith('/api/') or request.is_json:
                return failure('authentication_required', 401)
            return redirect(url_for('auth.login'))
        g.owner_id = owner
        return None

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/') or request.is_json:
            return jsonify(error=error.description, code=error.name.lower().replace(' ', '_')), error.code
        return error

    @app.context_processor
    def auth_context():
        return {'management_authenticated': bool(getattr(g, 'owner_id', None))}
