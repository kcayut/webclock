"""Hardware-neutral pull API; device execution belongs to an external client."""
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from webclock.services.device_service import DeviceService
from webclock.services.schedule_service import read_legacy_schedules
from webclock.services.storage import revision, storage_lock


def conditional(payload, digest=None):
    digest = digest or revision(payload)
    if request.args.get('revision') == digest or request.if_none_match.contains(digest):
        response = current_app.response_class(status=304)
    else:
        response = jsonify(payload)
    response.set_etag(digest)
    response.headers['Cache-Control'] = 'private, no-cache'
    return response


def device_api(state_directory, holidays, device_directory=None):
    api = Blueprint('device', __name__, url_prefix='/api/v1/device')

    def device_schedules():
        # Schema 2 clients cannot evaluate calendar links; never send a rule they
        # could mistake for an unconditional daily alarm.
        return [{key: value for key, value in row.items() if key != 'calendar_link'}
                for row in read_legacy_schedules(state_directory()) if not row.get('calendar_link')]

    def devices():
        return DeviceService(Path((device_directory or state_directory)()) / 'devices.json')

    @api.route('/config')
    def config():
        with storage_lock:
            payload = dict(schema_version=2, timezone='Asia/Taipei')
            payload.update(config_revision=revision(payload),
                           schedule_revision=revision(device_schedules()),
                           holiday_revision=revision(holidays.export()))
            return conditional(payload)

    @api.route('/schedules')
    def schedules():
        with storage_lock:
            rows = device_schedules()
            digest = revision(rows)
            return conditional(dict(revision=digest, schedules=rows), digest)

    @api.route('/holidays')
    def calendar():
        payload = holidays.export()
        digest = revision(payload)
        return conditional(dict(payload, revision=digest), digest)

    @api.route('/register', methods=['POST'])
    def register():
        return jsonify(device=devices().register(request.get_json())), 201

    @api.route('/status', methods=['POST'])
    def report():
        return jsonify(devices().report(request.get_json()))

    return api
