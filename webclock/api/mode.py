"""Explicit owner-space switching; one protected auth commit after a cold snapshot."""
import os
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, g, jsonify, render_template, request, session

from webclock.services.auth_service import AuthError, AuthStateError
from webclock.services.storage import revision, storage_lock


def register_mode(app, auth, root, notes_file, content_directory, context, clear_cache, legacy_calendar=None):
    api = Blueprint('mode', __name__)

    def admin():
        service = auth()
        owner = getattr(g, 'owner_id', None)
        if service.mode() != 'managed' or not service.is_admin(owner):
            raise AuthError('admin_required', 'Administrator sign in is required.', 403)
        return owner

    def values():
        data = request.get_json()
        if not isinstance(data, dict):
            raise AuthError('invalid_request', 'Expected an object.')
        return data

    def reauthenticate(data):
        if not request.is_secure:
            raise AuthError('https_required', 'HTTPS is required.', 403)
        if auth().mode() == 'managed':
            owner = admin()
            account = next(row for row in auth().list_accounts() if row['owner_id'] == owner)
            username = account['username']
        else:
            username = data.get('username')
        return auth().verify_admin(username, data.get('password'), request.remote_addr)

    def backup_roots():
        state, notes = auth().path.parent.resolve(), Path(notes_file()).resolve()
        from scripts.backup_clock import data_roots
        roots = data_roots(Path(root()), {'WEBCLOCK_STATE_DIR': str(state), 'NOTES_FILE': str(notes)})
        return roots, (state, notes)

    def preview(data):
        service = auth()
        state = service.state()
        if data.get('mode') not in ('self', 'managed'):
            raise AuthError('invalid_mode', 'Select a mode.')
        primary = data.get('primary_owner_id')
        account = state.get('accounts', {}).get(primary)
        if not account or not account['enabled']:
            raise AuthError('invalid_primary_owner', 'Select an enabled primary user.', 409)
        from scripts.backup_clock import inventory
        roots, layout = backup_roots()
        files = {key: inventory(path) for key, path in roots.items()}
        access = app.extensions['webclock_mode_access']()._load()
        spaces = []
        from webclock.services.storage import load_json
        for owner, account in state['accounts'].items():
            directory = content_directory(owner)
            notes = Path(notes_file()) if directory == auth().path.parent else directory / 'manual_notes.json'
            inherited_url = legacy_calendar() if legacy_calendar and owner == state['data_owner_id'] else ''
            calendar = load_json(directory / 'calendar.json', {'url': inherited_url})
            sources = calendar.get('sources', [])
            spaces.append(dict(owner_id=owner, username=account['username'], enabled=account['enabled'],
                active=account['enabled'] and (data['mode'] == 'managed' or owner == primary),
                settings=(directory / 'settings.json').exists(),
                sources=len({row['id'] for row in sources}) + int(bool(calendar.get('url'))),
                private_urls=sum(bool(row.get('url')) for row in sources) + int(bool(calendar.get('url'))),
                reminders=len({row['id'] for row in load_json(notes, [])}),
                schedules=len({row['id'] for row in load_json(directory / 'schedules.json', [])}),
                events=len({row['id'] for row in load_json(directory / 'events.json', [])}),
                groups=sum(row['owner_id'] == owner for row in access['groups'].values()),
                devices=sum(row['owner_id'] == owner for row in access['devices'].values())))
        return dict(mode=data['mode'], primary_owner_id=primary, generation=state['generation'], spaces=spaces,
                    public_content=[], revision=revision([data['mode'], primary, files]))

    @api.route('/mode')
    def page():
        service = auth()
        if service.mode() == 'managed':
            admin()
        from webclock.translations.mode import MODE_TEXT
        view = context()
        return render_template('mode.html', **view, mode_text=MODE_TEXT[view['language']], mode_languages=MODE_TEXT,
            mode=service.mode(), primary_owner_id=service.owner_id(),
            accounts=service.list_accounts() if service.mode() == 'managed' else [])

    @api.route('/api/mode/preview', methods=['POST'])
    def mode_preview():
        data = values()
        reauthenticate(data)
        return jsonify(preview(data))

    @api.route('/api/mode/switch', methods=['POST'])
    def switch():
        with storage_lock:
            data = values()
            identity = reauthenticate(data)
            current = preview(data)
            if data.get('revision') != current['revision'] or data.get('generation') != current['generation']:
                raise AuthError('preview_changed', 'Data changed; preview again.', 409)
            if data['mode'] == 'self' and data.get('confirm_shared') is not True:
                raise AuthError('shared_confirmation_required', 'Confirm shared management access.', 409)
            from scripts.backup_clock import create_backup
            roots, layout = backup_roots()
            parent = Path(os.environ.get('WEBCLOCK_MODE_BACKUP_DIR') or
                          layout[0].parent / ('.webclock-mode-backups-' + layout[0].name))
            if parent.is_symlink():
                raise OSError('Backup directory cannot be a symlink')
            parent.mkdir(mode=0o700, exist_ok=True)
            if parent.stat().st_mode & 0o077:
                raise OSError('Backup directory must be private (chmod 700)')
            backup = create_backup(parent / uuid4().hex, roots, layout)
            result = auth().switch_mode(data['mode'], data['primary_owner_id'], admin_owner_id=identity,
                password=data.get('password'), expected_generation=current['generation'],
                confirm_shared=data.get('confirm_shared') is True)
            clear_cache()
            session.clear()
            return jsonify(**result, backup_id=backup.name)

    @api.route('/api/accounts', methods=['GET', 'POST'])
    def accounts():
        admin()
        if request.method == 'GET':
            return jsonify(accounts=auth().list_accounts())
        data = values()
        if set(data) - {'username', 'password', 'role'}:
            raise AuthError('invalid_request', 'Unknown account fields.')
        return jsonify(account=auth().create_account(data.get('username'), data.get('password'),
                                                    role=data.get('role', 'member'))), 201

    @api.route('/api/accounts/<owner_id>', methods=['PATCH', 'DELETE'])
    def account(owner_id):
        admin()
        if request.method == 'DELETE':
            auth().delete_account(owner_id)
            return jsonify(status='deleted')
        data = values()
        if not data or set(data) - {'enabled', 'role', 'password'}:
            raise AuthError('invalid_request', 'Unknown account fields.')
        return jsonify(account=auth().update_account(owner_id, **data))

    def failure(error):
        if isinstance(error, AuthStateError):
            return jsonify(code='auth_recovery_required'), 503
        if isinstance(error, OSError):
            return jsonify(code='storage_failure'), 500
        response = jsonify(code=getattr(error, 'code', 'invalid_request'))
        response.status_code = getattr(error, 'status', 400)
        if getattr(error, 'retry_after', None):
            response.headers['Retry-After'] = str(error.retry_after)
        return response

    for error in (AuthError, AuthStateError, OSError, ValueError, KeyError, TypeError):
        api.register_error_handler(error, failure)
    app.register_blueprint(api)
