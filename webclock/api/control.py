"""Program credentials and narrowly scoped writes for HA, agents and future devices."""
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, g, jsonify, render_template, request

from webclock.auth import client_transport_allowed, management_transport_allowed
from webclock.csrf import same_origin
from webclock.services.auth_service import AuthStateError
from webclock.services.control_access_service import (
    ControlAccessService, ControlAccessError, ControlAccessStateError, GRANT_FIELDS, SCOPES,
)
from webclock.services.control_service import ControlError, ControlService
from webclock.services.device_access_service import AccessError
from webclock.services.event_service import read_events
from webclock.services.schedule_service import TAIPEI, read_schedules
from webclock.services.storage import storage_lock


def register_control(app, directory, auth, groups, owner, context, calendar_sources, calendar_events, holidays,
                     credential_directory=None):
    management = Blueprint('control_management', __name__)
    api = Blueprint('control', __name__, url_prefix='/api/v1/control')

    def credentials():
        return ControlAccessService(Path((credential_directory or directory)()) / 'control-clients.json', auth)

    def authenticate():
        if not same_origin():
            raise ControlError('permission_denied', 403)
        mode = auth().mode()
        if mode == 'managed' and not client_transport_allowed():
            raise ControlError('tls_required', 403)
        header = request.headers.get('Authorization', '')
        token = header[7:] if header.startswith('Bearer ') else None
        clients = credentials()
        client = None
        owners = {row['owner_id'] for row in clients._load()['clients'].values()}
        for candidate in owners:
            if auth().owner_active(candidate):
                client = clients.authenticate(token, candidate, mode)
                if client:
                    break
        if not client:
            raise ControlError('authentication_required', 401)
        g.control_authenticated = True
        g.owner_id = client['owner_id']
        return client

    app.extensions['webclock_control_authorize'] = authenticate

    def service():
        client = authenticate()  # Call inside storage_lock: revoked clients cannot race a write.
        return ControlService(directory(), client, groups(), holidays, calendar_events,
                              [row['id'] for row in calendar_sources()])

    def catalog():
        identity = owner()
        return dict(groups=groups().list_groups(identity),
                    devices=[row for row in groups().list_devices(identity) if row.get('group_id')],
                    sources=[dict(id='local', name='Local reminders'),
                             *[{key: row[key] for key in ('id', 'name')} for row in calendar_sources()]],
                    schedules=read_schedules(directory()),
                    events=[row for row in read_events(directory()) if row['owner_id'] == identity])

    def create_client(data):
        if not isinstance(data, dict):
            raise ControlError('invalid_request')
        for field in GRANT_FIELDS:
            if not isinstance(data.get(field, []), list) or any(not isinstance(v, str) for v in data.get(field, [])):
                raise ControlError('invalid_request')
        identity = owner()
        available = catalog()
        for field, collection in (('group_ids', 'groups'), ('device_ids', 'devices'),
                                  ('calendar_source_ids', 'sources'), ('schedule_ids', 'schedules'), ('event_ids', 'events')):
            if set(data.get(field, [])) - {row['id'] for row in available[collection]}:
                raise ControlError('invalid_request')
        return credentials().create(identity, auth().mode(), data)

    @management.route('/api/v1/control-clients', methods=['GET', 'POST'])
    def clients():
        with storage_lock:
            if request.method == 'POST':
                if auth().mode() == 'managed' and not management_transport_allowed():
                    raise ControlError('tls_required', 403)
                return jsonify(client=create_client(request.get_json())), 201
            return jsonify(mode=auth().mode(), clients=credentials().list(owner()))

    @management.route('/api/v1/control-clients/<client_id>', methods=['DELETE'])
    def revoke(client_id):
        with storage_lock:
            credentials().revoke(owner(), client_id)
            return jsonify(status='revoked')

    @management.route('/integrations')
    def integrations():
        from webclock.translations.control import CONTROL_TRANSLATIONS
        with storage_lock:
            view = context()
            text = CONTROL_TRANSLATIONS[view['language']]
            return render_template('integrations.html', **view, control_text=text,
                                   control_languages=CONTROL_TRANSLATIONS, mode=auth().mode(),
                                   catalog=catalog(), scopes=sorted(SCOPES))

    @api.route('/identity')
    def identity():
        with storage_lock:
            client = authenticate()
            return jsonify(client=client, mode=auth().mode())

    @api.route('/<any(schedules,events):kind>', methods=['GET', 'POST'])
    def collection(kind):
        with storage_lock:
            controller = service()
            if request.method == 'GET':
                return jsonify(controller.list(kind))
            if kind == 'events' and any(row['id'] == 'webclock' and row.get('provider') != 'native'
                                        for row in calendar_sources()):
                raise ControlError('source_id_conflict', 409)
            result, status = controller.create(kind, request.get_json())
            return jsonify(result), status

    @api.route('/<any(schedules,events):kind>/<item_id>', methods=['GET', 'PATCH', 'DELETE'])
    def item(kind, item_id):
        with storage_lock:
            controller = service()
            if request.method == 'GET':
                return jsonify(controller.get(kind, item_id))
            return jsonify(controller.change(kind, item_id, request.get_json(), request.method == 'DELETE'))

    @api.route('/<any(schedules,events):kind>/<item_id>/targets/<target_kind>/<target_id>', methods=['GET', 'PUT'])
    def target(kind, item_id, target_kind, target_id):
        body = None
        if request.method == 'PUT':
            body = request.get_json()
            if not isinstance(body, dict):
                raise ControlError('invalid_request')
        with storage_lock:
            return jsonify(service().target(kind, item_id, target_kind, target_id, body))

    @api.route('/calendar-events')
    def calendar_catalog():
        with storage_lock:
            controller = service()
            controller.require('schedules:read')
            ids = request.args.getlist('source_id')
            if (not ids or set(request.args) != {'source_id'}
                    or set(ids) - set(controller.client['calendar_source_ids'])):
                raise ControlError('permission_denied', 403)
            start = datetime.now(TAIPEI).replace(hour=0, minute=0, second=0, microsecond=0)
            rows = calendar_events(start=start, end=start + timedelta(days=366), source_ids=ids, strict=True)
            fields = ('source_id', 'uid', 'text', 'starts_at', 'ends_at', 'all_day', 'recurring', 'recurrence_id')
            return jsonify(events=[{key: row[key] for key in fields if key in row} for row in rows])

    def error_response(error):
        if isinstance(error, (ControlAccessStateError, AuthStateError)):
            return jsonify(error='control_not_ready', code='control_not_ready'), 503
        if isinstance(error, OSError):
            return jsonify(error='storage_failure', code='storage_failure'), 500
        return jsonify(error=getattr(error, 'code', 'invalid_request'),
                       code=getattr(error, 'code', 'invalid_request')), getattr(error, 'status', 400)

    for blueprint in (management, api):
        for error in (ControlError, ControlAccessError, ControlAccessStateError, AuthStateError, AccessError, ValueError, OSError):
            blueprint.register_error_handler(error, error_response)
    # The application calls the guard before dispatching blueprint handlers.
    app.register_error_handler(ControlError, error_response)
    app.register_error_handler(ControlAccessStateError, error_response)
    app.register_error_handler(ControlAccessError, error_response)
    app.register_blueprint(management)
    app.register_blueprint(api)
