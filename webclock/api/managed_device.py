"""Versioned display-device transport; administrator cookies never grant access."""
import time

from flask import Blueprint, g, jsonify, request

from webclock.csrf import same_origin
from webclock.services.auth_service import AuthStateError
from webclock.services.device_access_service import AccessError
from webclock.services.device_service import REPORT_FIELDS, _capabilities, _identifier, _text
from webclock.services.storage import storage_lock


DEVICE_COOKIE = 'webclock_device'
COOKIE_SECONDS = 365 * 24 * 60 * 60
NATIVE_ENDPOINTS = {'managed_device.token_prepare', 'managed_device.token_join', 'managed_device.token_leave'}


def managed_device_api(access_provider, device_provider, auth_provider, display_provider, alarms_provider):
    api = Blueprint('managed_device', __name__, url_prefix='/api/v2/device')

    def failure(error):
        response = jsonify(code=error.code, error=str(error))
        response.status_code = error.status
        if error.retry_after:
            response.headers['Retry-After'] = str(error.retry_after)
        return response

    api.register_error_handler(AccessError, failure)

    @api.errorhandler(AuthStateError)
    def invalid_auth(error):
        return failure(AccessError('Authorization state requires host recovery', 503, 'access_not_ready'))

    @api.errorhandler(OSError)
    def storage_failure(error):
        return failure(AccessError('Unable to save device state', 500, 'storage_failure'))

    @api.errorhandler(ValueError)
    @api.errorhandler(TypeError)
    def invalid_input(error):
        return failure(AccessError('Invalid device request', 400, 'invalid_request'))

    @api.after_request
    def private_response(response):
        response.headers.setdefault('Cache-Control', 'private, no-cache' if request.method in ('GET', 'HEAD')
                                    and response.status_code in (200, 304) else 'no-store')
        if request.endpoint in ('managed_device.identity', 'managed_device.prepare', 'managed_device.join'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers.pop('Access-Control-Allow-Origin', None)
        return response

    def owner():
        return auth_provider().owner_id()

    def authorize():
        """Called by the app guard before its CSRF check, including in self mode."""
        g.device_bearer_authenticated = False
        if not same_origin():
            raise AccessError('Cross-origin device access is forbidden', 403, 'cross_origin_forbidden')
        if auth_provider().mode() == 'managed' and not request.is_secure:
            raise AccessError('HTTPS is required for device access', 403, 'https_required')
        authorization = request.headers.get('Authorization')
        if request.endpoint in NATIVE_ENDPOINTS:
            # This separate JSON transport never accepts ambient browser cookies.
            # The marker is not authentication: prepare grants no authority, and
            # join still needs both the prepared secret and a valid invitation.
            if (not request.is_json or request.headers.get('X-WebClock-Client') != 'native-v1'
                    or request.headers.get('Cookie') or request.headers.get('Origin')
                    or request.headers.get('Referer')
                    or any(key.lower().startswith('sec-fetch-') for key in request.headers.keys())):
                raise AccessError('A native JSON client is required', 403, 'native_client_required')
            if authorization and not authorization.startswith('Bearer '):
                raise AccessError('A device credential is required', 401, 'device_authentication_required')
            g.device_token = authorization[7:] if authorization else None
            if request.endpoint == 'managed_device.token_leave':
                access_provider().authorize_leave(g.device_token, owner())
            g.device_native_request = True
            return None
        token = request.cookies.get(DEVICE_COOKIE)
        if authorization:
            if (request.endpoint in ('managed_device.prepare', 'managed_device.join', 'managed_device.leave')
                    or not authorization.startswith('Bearer ')):
                raise AccessError('A device credential is required', 401, 'device_authentication_required')
            token = authorization[7:]
            g.device_identity = access_provider().authenticate(token, owner())
            g.device_bearer_authenticated = True
        g.device_token = token
        if request.endpoint == 'managed_device.leave':
            return access_provider().authorize_leave(token, owner())
        if request.endpoint in ('managed_device.prepare', 'managed_device.join'):
            return None
        if request.endpoint == 'managed_device.identity':
            g.device_identity_result = access_provider().identity(token, owner())
        elif not g.device_bearer_authenticated:
            g.device_identity = access_provider().authenticate(token, owner())
        return None

    @api.record_once
    def install_authorizer(state):
        state.app.extensions['webclock_device_authorize'] = authorize

    def body(fields, required=()):
        value = request.get_json()
        if not isinstance(value, dict) or set(value) - set(fields) or set(required) - set(value):
            raise ValueError('Invalid device fields')
        return value

    @api.route('/token/prepare', methods=['POST'])
    def token_prepare():
        body(())
        result = access_provider().prepare(owner(), request.remote_addr, g.device_token)
        return jsonify(attempt_id=result['attempt_id'], expires_at=result['expires_at'],
                       token=result['token'] or g.device_token), 201 if result['created'] else 200

    @api.route('/token/join', methods=['POST'])
    def token_join():
        value = body(('attempt_id', 'code'), ('attempt_id', 'code'))
        result = access_provider().join(owner(), g.device_token, value['attempt_id'], value['code'],
                                        request.remote_addr)
        return jsonify(schema_version=3, identity=result['identity'], server_timestamp=int(time.time() * 1000)), \
            201 if result['created'] else 200

    @api.route('/token/leave', methods=['POST'])
    def token_leave():
        body(())
        access_provider().leave(g.device_token, owner())
        return jsonify(status='left')

    @api.route('/join/prepare', methods=['POST'])
    def prepare():
        body(())
        result = access_provider().prepare(owner(), request.remote_addr, g.device_token)
        response = jsonify(attempt_id=result['attempt_id'], expires_at=result['expires_at'])
        response.status_code = 201 if result['created'] else 200
        if result['token'] is not None:
            response.set_cookie(DEVICE_COOKIE, result['token'], max_age=COOKIE_SECONDS,
                secure=auth_provider().mode() == 'managed', httponly=True, samesite='Lax',
                path='/api/v2/device')
        return response

    @api.route('/identity')
    def identity():
        return jsonify(access_provider().identity(g.device_token, owner()))

    @api.route('/join', methods=['POST'])
    def join():
        value = body(('attempt_id', 'code'), ('attempt_id', 'code'))
        result = access_provider().join(owner(), g.device_token, value['attempt_id'], value['code'],
                                        request.remote_addr)
        return jsonify(schema_version=3, identity=result['identity'], server_timestamp=int(time.time() * 1000)), \
            201 if result['created'] else 200

    @api.route('/leave', methods=['POST'])
    def leave():
        body(())
        access_provider().leave(g.device_token, owner())
        response = jsonify(status='left')
        response.delete_cookie(DEVICE_COOKIE, path='/api/v2/device',
                              secure=auth_provider().mode() == 'managed', httponly=True, samesite='Lax')
        return response

    def scoped_response(provider):
        identity = access_provider().authenticate(g.device_token, owner())
        result = provider(identity)
        # A slow calendar request must not return a formerly authorized body/304.
        with storage_lock:
            current = access_provider().authenticate(g.device_token, owner())
            if current['identity_revision'] != identity['identity_revision']:
                raise AccessError('Device assignment changed', 403, 'device_authorization_revoked')
            return result

    @api.route('/display')
    def display():
        return scoped_response(display_provider)

    @api.route('/browser-alarms')
    def browser_alarms():
        return scoped_response(alarms_provider)

    @api.route('/status', methods=['POST'])
    def status():
        value = body(REPORT_FIELDS | {'name', 'device_type', 'capabilities', 'acknowledged_commands'})
        # Validate all fields before reconstructing or changing observation data.
        for key in REPORT_FIELDS & value.keys():
            _text(value[key], key)
        if 'name' in value:
            _text(value['name'], 'name', 100)
        if 'device_type' in value:
            _text(value['device_type'], 'device_type', 50)
        if 'capabilities' in value:
            _capabilities(value['capabilities'])
        acknowledgements = value.get('acknowledged_commands', [])
        if not isinstance(acknowledgements, list) or len(acknowledgements) > 100:
            raise ValueError('Invalid acknowledgements')
        for command_id in acknowledgements:
            _identifier(command_id)
        with storage_lock:
            identity = access_provider().authenticate(g.device_token, owner())
            devices = device_provider()
            device_id = identity['device_id']
            existing = next((row for row in devices.list() if row['id'] == device_id), None)
            if existing is None or 'name' in value:
                authorized_ids = access_provider().device_ids() if auth_provider().mode() == 'managed' else None
                devices.register({'id': device_id, 'name': value.get('name', 'Browser display')}, authorized_ids)
            report = devices.report(dict({key: val for key, val in value.items() if key != 'name'}, id=device_id))
            allowed = REPORT_FIELDS | {'id', 'reported_name', 'device_type', 'capabilities',
                                       'capabilities_reported_at', 'registered_at', 'last_seen', 'online', 'sync_status'}
            safe = {key: val for key, val in report['device'].items() if key in allowed}
            return jsonify(schema_version=3, identity=identity, device=safe, commands=report['commands'],
                           server_timestamp=int(time.time() * 1000))

    return api
