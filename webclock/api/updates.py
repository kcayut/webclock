"""Administrator controls for the independent Linux update service."""
import json
import os
from pathlib import Path
import socket

from flask import Blueprint, g, jsonify, render_template, request, url_for

from webclock import __version__
from webclock.csrf import same_origin


SOCKET_PATH = os.getenv('WEBCLOCK_UPDATER_SOCKET', '/run/webclock-updater/control.sock')
CONFIG_PATH = os.getenv('WEBCLOCK_UPDATER_CONFIG', '/etc/webclock-updater.json')


def updater_request(action, **values):
    """Only the fixed local helper can execute an update; Flask never runs commands."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(SOCKET_PATH)
        connection.sendall(json.dumps(dict(action=action, **values)).encode() + b'\n')
        with connection.makefile('rb') as stream:
            raw = stream.readline(262145)
    if len(raw) > 262144 or not raw.endswith(b'\n'):
        raise ValueError('Invalid updater response')
    result = json.loads(raw)
    if not isinstance(result, dict) or not isinstance(result.get('status'), dict):
        raise ValueError('Invalid updater response')
    return result


def platform_info():
    """Identify the installation platform and native update provider."""
    if os.getenv('WEBCLOCK_HA_APP') == '1':
        return {
            'installation_type': 'ha_app',
            'update_provider': 'supervisor',
            'management_url': '/config/updates',
        }
    if Path('/.dockerenv').exists() or os.getenv('WEBCLOCK_DOCKER') == '1':
        return {
            'installation_type': 'docker',
            'update_provider': 'docker',
            'management_url': None,
        }
    return {
        'installation_type': 'bare_metal',
        'update_provider': 'systemd',
        'management_url': None,
    }


def platform_managed():
    """True when the host platform manages updates without a local update helper."""
    return platform_info()['update_provider'] == 'supervisor'


def register_updates(app, auth, context):
    api = Blueprint('updates', __name__)

    def admin():
        return auth().mode() == 'managed' and auth().is_admin(getattr(g, 'owner_id', None))

    def unsupported():
        return platform_managed()

    def failure(code, status=403):
        return jsonify(error=code, code=code), status

    @api.before_request
    def authorize():
        if not same_origin():
            return failure('cross_origin_forbidden')
        if auth().mode() == 'managed' and not admin():
            return failure('admin_required')
        if request.method != 'GET':
            if not admin():
                return failure('managed_required')
            if unsupported():
                return failure('unsupported', 409)

    def status_view(state):
        state = dict(state)
        info = platform_info()
        if info['installation_type'] == 'docker':
            if state.get('update_provider') != 'docker':
                state.update(supported=False, reason='provider_mismatch')
            # Report the running image, never the host checkout or a staged .env value.
            state['current_version'] = __version__
        state.update(info)
        state['writable'] = admin() and state.get('supported', False)
        if not admin() or not state.get('supported'):
            state.pop('project_path', None)
        if not admin() and state.get('supported'):
            state['reason'] = 'managed_required'
        return state

    def unavailable(reason):
        info = platform_info()
        return status_view(dict(supported=False, reason=reason, state='idle', current_version=__version__,
                                channel='stable', auto_update=False, update_available=False,
                                installation_type=info['installation_type'],
                                update_provider=info['update_provider'],
                                management_url=info['management_url']))

    @api.route('/updates')
    def page():
        from webclock.translations.updates import UPDATE_TRANSLATIONS
        view = context()
        return render_template('updates.html', **view, update_languages=UPDATE_TRANSLATIONS,
                               update_text=UPDATE_TRANSLATIONS[view['language']],
                               update_api_url=url_for('updates.status'))

    @api.route('/api/updates')
    def status():
        if unsupported():
            return jsonify(unavailable('unsupported'))
        try:
            result = updater_request('status')
            return jsonify(status_view(result['status']))
        except (OSError, ValueError):
            if Path(CONFIG_PATH).exists() or Path(SOCKET_PATH).with_name('configured').exists():
                return failure('updater_unavailable', 503)
            return jsonify(unavailable('not_configured'))

    def command(action, fields):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != fields:
            return failure('invalid_request', 400)
        if action == 'configure' and (data['channel'] not in ('stable', 'beta')
                                      or type(data['auto_update']) is not bool):
            return failure('invalid_request', 400)
        if action == 'install' and (not isinstance(data['expected_version'], str)
                                    or len(data['expected_version']) > 100):
            return failure('invalid_request', 400)
        try:
            if platform_info()['installation_type'] == 'docker':
                observed = updater_request('status')['status']
                if observed.get('update_provider') != 'docker' or not observed.get('supported'):
                    return failure('provider_mismatch', 409)
            result = updater_request(action, **data)
        except (OSError, ValueError):
            return failure('updater_unavailable', 503)
        if not result.get('ok'):
            return failure(result.get('error', 'updater_failed'), 409)
        return jsonify(status_view(result['status']))

    @api.route('/api/updates/check', methods=['POST'])
    def check():
        return command('check', set())

    @api.route('/api/updates/settings', methods=['POST'])
    def settings():
        return command('configure', {'channel', 'auto_update'})

    @api.route('/api/updates/install', methods=['POST'])
    def install():
        return command('install', {'expected_version'})

    @api.after_request
    def private(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    app.register_blueprint(api)
