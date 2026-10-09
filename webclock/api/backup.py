"""One portable backup with optional encryption and a revision-bound restore."""
import hashlib
import json
import secrets
import time
from pathlib import Path

from flask import Blueprint, g, jsonify, request, session, url_for

from webclock.auth import management_transport_allowed
from webclock.services.auth_service import AuthError, AuthStateError
from webclock.services import portable_backup
from webclock.services.storage import storage_lock


def register_backup(app, auth, notes_file, legacy_calendar, validate_content, refreshed, defaults):
    api = Blueprint('complete_backup', __name__)
    # Bound uploads before CSRF accesses multipart form data.
    @app.before_request
    def limit_backup_upload():
        if request.blueprint == api.name and (request.content_length is None
                or request.content_length > 32 * 1024 * 1024):
            return jsonify(code='backup_too_large'), 413
    app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())

    def authorize(values):
        service = auth()
        state = service.state()
        if state['mode'] == 'managed' and not service.is_admin(getattr(g, 'owner_id', None)):
            raise AuthError('admin_required', 'Administrator authorization is required.', 403)
        if state['accounts']:
            if not management_transport_allowed():
                raise AuthError('https_required', 'A protected management connection is required.', 403)
            service.verify_admin(values.get('username'), values.get('admin_password'), request.remote_addr)
        return service.path.parent

    def capture(materialize=False):
        payload = portable_backup.capture(auth().path.parent, Path(notes_file()),
            calendar=legacy_calendar(), validate_content=validate_content)
        if materialize:
            # Carry effective source defaults too (e.g. WEBCLOCK_LANGUAGE),
            # without importing the source machine's environment or paths.
            state = payload['files']['auth.json']
            for owner in set(state['accounts']) | {state['data_owner_id']}:
                name = 'settings.json' if owner == state['data_owner_id'] else 'owners/' + owner + '/settings.json'
                payload['files'][name] = dict(defaults(), **payload['files'].get(name, {}))
            portable_backup.validate(payload, validate_content)
        return payload

    def target_revision():
        files = capture()['files']
        if not (auth().path.parent / 'auth.json').exists():
            files.pop('auth.json', None)
        # Heartbeat telemetry and other open login sessions do not change what
        # the user reviewed. Content, accounts and access grants still do.
        has_device_history = bool(files.pop('devices.json', None))
        if 'auth.json' in files:
            files['auth.json']['sessions'] = {}
        return hashlib.sha256(json.dumps([files, has_device_history], sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':')).encode()).hexdigest()

    def uploaded():
        item = request.files.get('file')
        if item is None:
            raise AuthError('invalid_backup', 'Select a backup file.')
        raw = item.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise AuthError('backup_too_large', 'Backup is too large.', 413)
        payload = portable_backup.decode(raw, request.form.get('password'), validate_content=validate_content)
        if payload['files']['auth.json']['mode'] == 'managed' and not management_transport_allowed():
            raise AuthError('https_required', 'A protected management connection is required.', 403)
        return raw, payload

    @api.route('/api/backup/complete/export', methods=['POST'])
    def export():
        values = request.get_json(silent=True)
        if not isinstance(values, dict):
            raise AuthError('invalid_backup', 'Expected an object.')
        with storage_lock:
            authorize(values)
            data = portable_backup.encode(capture(materialize=True), values.get('password'),
                                          encrypted=values.get('encrypted', True))
        response = app.response_class(data, mimetype='application/octet-stream')
        response.headers['Content-Disposition'] = 'attachment; filename="webclock-backup.webclock"'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @api.route('/api/backup/complete/preview', methods=['POST'])
    def preview():
        with storage_lock:
            state = authorize(request.form)
            raw, payload = uploaded()
            summary = portable_backup.preview(payload, state, Path(notes_file()), validate_content=validate_content,
                                              target_calendar=legacy_calendar())
            ticket = secrets.token_urlsafe(32)
            session['backup_preview'] = dict(ticket=ticket, file=hashlib.sha256(raw).hexdigest(),
                                            target=target_revision(), expires=time.time() + 600)
            return jsonify(ticket=ticket, summary=summary, preserve_devices=summary['preserve_devices'],
                           encrypted=raw.startswith(portable_backup.MAGIC))

    @api.route('/api/backup/complete/restore', methods=['POST'])
    def restore():
        with storage_lock:
            state = authorize(request.form)
            reviewed = session.get('backup_preview', {})
            if (request.form.get('confirm') != 'yes' or not reviewed
                    or not secrets.compare_digest(str(request.form.get('ticket', '')), reviewed['ticket'])
                    or reviewed['expires'] < time.time()):
                raise AuthError('preview_changed', 'Preview the backup again.', 409)
            raw, payload = uploaded()
            if (reviewed['file'] != hashlib.sha256(raw).hexdigest()
                    or reviewed['target'] != target_revision()):
                session.pop('backup_preview', None)
                raise AuthError('preview_changed', 'Data changed. Preview the backup again.', 409)
            result = portable_backup.restore(payload, state, Path(notes_file()), validate_content=validate_content,
                                              target_calendar=legacy_calendar())
            refreshed()
            session.clear()
            destination = url_for('auth.login') if auth().mode() == 'managed' else url_for('admin') + '#backup'
            return jsonify(ok=True, summary=result, redirect=destination)

    @api.errorhandler(AuthError)
    def auth_error(error):
        return jsonify(code=error.code), error.status

    @api.errorhandler(AuthStateError)
    def auth_state_error(error):
        return jsonify(code='auth_recovery_required'), 503

    @api.errorhandler(ValueError)
    def invalid(error):
        return jsonify(code=getattr(error, 'code', 'invalid_backup')), getattr(error, 'status', 400)

    @api.errorhandler(OSError)
    def failed(error):
        # Never include filesystem paths, decrypted data or credential values.
        return jsonify(code='restore_failed'), 500

    @api.errorhandler(portable_backup.RecoveryError)
    def recovery_failed(error):
        return jsonify(code='restore_recovery_required'), 503

    app.register_blueprint(api)

    @app.context_processor
    def backup_context():
        service = auth()
        try:
            state = service.state()
        except (AuthStateError, OSError, ValueError):
            return dict(complete_backup_available=False, complete_backup_admin_reauth=False,
                        complete_backup_admin_username='')
        owner = getattr(g, 'owner_id', None)
        available = state['mode'] == 'self' or service.is_admin(owner)
        account = state['accounts'].get(owner, {})
        return dict(complete_backup_available=available,
                    complete_backup_admin_reauth=bool(state['accounts']),
                    complete_backup_admin_username=account.get('username', ''))
