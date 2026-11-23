"""Management of private ringtone clips and self-mode alarm playback."""
from pathlib import Path
from urllib.parse import unquote

from flask import Blueprint, Response, abort, g, jsonify, request

from webclock.csrf import same_origin
from webclock.services import ringtones
from webclock.services.schedule_service import read_legacy_schedules, read_schedules
from webclock.services.storage import save_json


def audio_response(directory, key):
    if not ringtones.ID.fullmatch(key):
        abort(404)
    raw = ringtones.audio(directory, key)
    response = Response(raw, mimetype='audio/wav')
    response.headers.update({'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                             'Cross-Origin-Resource-Policy': 'same-origin',
                             'Content-Disposition': 'inline; filename="ringtone.wav"'})
    return response


def assigned_audio(directory, rows, key):
    if not any(row['enabled'] and row.get('custom_sound') == key for row in rows):
        abort(404)
    return audio_response(directory, key)


def register_ringtones(app, directory, state_root, upload_window):
    api = Blueprint('ringtones', __name__)

    @api.before_request
    def require_origin():
        if not same_origin():
            abort(403)

    @app.before_request
    def bound_upload():
        if request.endpoint == 'ringtones.upload':
            if request.content_length is None or request.content_length > ringtones.MAX_BYTES:
                return jsonify(code='ringtone_too_large'), 413
            request.max_content_length = ringtones.MAX_BYTES
            if request.mimetype != 'audio/wav':
                return jsonify(code='invalid_wave'), 415

    @api.errorhandler(ringtones.RingtoneError)
    def invalid(error):
        return jsonify(code=error.code), error.status

    @api.get('/api/ringtones')
    def listing():
        return jsonify(ringtones=ringtones.catalog(directory()))

    @api.post('/api/ringtones')
    def upload():
        encoded_name = request.headers.get('X-Ringtone-Name', '')
        if len(encoded_name) > 720:
            raise ringtones.RingtoneError('invalid_ringtone_name')
        try:
            name = ringtones.validate_name(unquote(encoded_name, errors='strict'))
        except UnicodeDecodeError as exc:
            raise ringtones.RingtoneError('invalid_ringtone_name') from exc
        target = directory()
        if len(ringtones.catalog(target)) >= ringtones.MAX_CLIPS:
            raise ringtones.RingtoneError('ringtone_quota', 409)
        with ringtones.upload_slot():
            with upload_window():
                raw = request.stream.read(ringtones.MAX_BYTES + 1)
                ringtones.validate_wave(raw)
            if directory() != target:
                abort(409)
            return jsonify(ringtones.add(target, name, raw, state_root())), 201

    def delete_clips(keys):
        target = directory()
        rows = ringtones.library(target)
        if any(key not in rows for key in keys):
            abort(404)
        used = {row.get('custom_sound') for row in read_schedules(target)}
        if used.intersection(keys):
            return jsonify(code='ringtone_in_use', ids=[key for key in keys if key in used]), 409
        for key in keys:
            del rows[key]
        save_json(Path(target) / 'ringtones.json', rows)
        return '', 204

    @api.delete('/api/ringtones')
    def delete_selected():
        data = request.get_json()
        keys = data.get('ids') if isinstance(data, dict) else None
        if (not isinstance(keys, list) or not 1 <= len(keys) <= ringtones.MAX_CLIPS
                or any(not isinstance(key, str) or not ringtones.ID.fullmatch(key) for key in keys)
                or len(set(keys)) != len(keys)):
            abort(400)
        return delete_clips(keys)

    def requested_name():
        data = request.get_json()
        return ringtones.validate_name(data.get('name') if isinstance(data, dict) else None)

    @api.post('/api/ringtones/<key>/copy')
    def copy_clip(key):
        target = directory()
        name = requested_name()
        raw = ringtones.audio(target, key)
        return jsonify(ringtones.add(target, name, raw, state_root())), 201

    @api.route('/api/ringtones/<key>', methods=['GET', 'PATCH', 'DELETE'])
    def item(key):
        if request.method == 'DELETE':
            return delete_clips([key])
        target = directory()
        if request.method == 'PATCH':
            return jsonify(ringtones.rename(target, key, requested_name(), state_root()))
        return audio_response(target, key)

    @api.get('/api/v1/ringtones/<key>')
    def shared_alarm_audio(key):
        if g.deployment_mode != 'self':
            abort(403)
        target = directory()
        return assigned_audio(target, (row for row in read_legacy_schedules(target) if not row.get('targets')), key)

    app.register_blueprint(api)
