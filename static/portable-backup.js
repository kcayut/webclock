/* Complete backups are confined to the management page. */
(function () {
    'use strict';
    var container = document.getElementById('complete-backup');
    if (!container) return;
    var preview = null, busy = false, importEncrypted = null, inspectedFile, readVersion = 0;
    function $(id) { return document.getElementById('complete-backup-' + id); }
    function t(key) { return window.t('complete_backup_' + key); }
    function status(kind, key, failed) {
        var node = $(kind + '-status');
        node.textContent = key ? t(key) : '';
        if (key) node.setAttribute('data-i18n', 'complete_backup_' + key);
        else node.removeAttribute('data-i18n');
        node.className = failed ? 'form-error' : '';
    }
    function controls(value) {
        busy = value;
        container.setAttribute('aria-busy', String(busy));
        container.querySelectorAll('input, button').forEach(function (node) { node.disabled = busy; });
        $('export-password').disabled = $('export-confirm').disabled = busy || !$('encrypted').checked;
        $('import-password').disabled = busy || importEncrypted !== true;
        $('read').disabled = busy || importEncrypted === null;
        $('restore').disabled = busy || !preview || !$('confirm').checked;
    }
    function renderOptions() {
        var encrypted = $('encrypted').checked;
        $('export-passwords').hidden = $('password-hint').hidden = !encrypted;
        $('export-unencrypted').hidden = encrypted;
        $('export-password').required = $('export-confirm').required = encrypted;
        var key = encrypted ? 'download' : 'download_unencrypted';
        $('download').textContent = t(key);
        $('download').setAttribute('data-i18n', 'complete_backup_' + key);
        $('import-password-field').hidden = importEncrypted !== true;
        $('import-password').required = importEncrypted === true;
        $('import-unencrypted').hidden = importEncrypted !== false;
        controls(busy);
    }
    function invalidate() {
        preview = null;
        $('preview').hidden = true;
        $('confirm').checked = false;
        $('restore').disabled = true;
    }
    function auth() {
        return {username: $('username') ? $('username').value : '', admin_password: $('admin-password') ? $('admin-password').value : ''};
    }
    function validAuth() {
        return !$('username') || ($('username').reportValidity() && $('admin-password').reportValidity());
    }
    function upload() {
        var data = new FormData(), credentials = auth();
        data.append('file', $('file').files[0]);
        if (importEncrypted) data.append('password', $('import-password').value);
        data.append('username', credentials.username);
        data.append('admin_password', credentials.admin_password);
        return data;
    }
    function request(action, data, json) {
        var path = '/api/backup/complete/' + action;
        var headers = {'X-CSRF-Token': document.getElementById('csrf-token').content};
        if (json) headers['Content-Type'] = 'application/json';
        return fetch(window.webclockUrl ? window.webclockUrl(path) : path, {
            method: 'POST', credentials: 'same-origin', headers: headers,
            body: json ? JSON.stringify(data) : data
        }).then(function (response) {
            if (response.ok) return action === 'export' ? response.blob() : response.json();
            return response.json().catch(function () { return {}; }).then(function (body) {
                throw new Error(body.code || body.error || 'error');
            });
        });
    }
    function failure(kind, error) {
        var aliases = {backup_password_or_file_invalid: 'bad_password_or_file', protected_restore_required: 'downgrade_forbidden',
            unsafe_data_path: 'invalid_backup', invalid_data_file: 'invalid_backup', invalid_owner_data: 'invalid_backup', invalid_authorization: 'invalid_backup'};
        var code = aliases[error.message] || error.message;
        var known = ['bad_password_or_file', 'invalid_backup', 'backup_too_large', 'preview_changed',
            'admin_required', 'invalid_credentials', 'https_required', 'restore_failed', 'restore_recovery_required', 'downgrade_forbidden', 'invalid_backup_password'];
        status(kind, known.indexOf(code) >= 0 ? code : 'error', true);
    }
    function inspectFile() {
        var file = $('file').files[0];
        if (file === inspectedFile) return;
        inspectedFile = file;
        var version = ++readVersion;
        importEncrypted = null; invalidate(); renderOptions(); status('import', '');
        if (!file) return;
        var reader = new FileReader();
        function current() { return version === readVersion && file === $('file').files[0]; }
        function failed() { if (current()) failure('import', new Error('invalid_backup')); }
        reader.onerror = failed;
        reader.onload = function () {
            if (!current()) return;
            var bytes = new Uint8Array(reader.result), prefix = [87, 69, 66, 67, 76, 79, 67, 75, 0];
            if (bytes.length !== 10 || !prefix.every(function (byte, index) { return bytes[index] === byte; }) || (bytes[9] !== 1 && bytes[9] !== 2)) {
                failed(); return;
            }
            importEncrypted = bytes[9] === 1; renderOptions();
        };
        try { reader.readAsArrayBuffer(file.slice(0, 10)); } catch (error) { failed(); }
    }
    function renderPreview() {
        if (!preview) return;
        var summary = preview.summary;
        var parts = [t(summary.mode === 'managed' ? 'managed' : 'self')];
        if (summary.created_at) {
            var date = new Date(summary.created_at);
            if (!isNaN(date.getTime())) parts.push(t('created_at') + ': ' + date.toLocaleString(document.documentElement.lang));
        }
        ['accounts', 'calendars', 'notes', 'alarms', 'events', 'groups', 'devices'].forEach(function (key) {
            parts.push(t(key) + ': ' + Number(summary[key] || 0));
        });
        $('summary').textContent = parts.join(' · ');
        var preserve = preview.preserve_devices === true;
        $('device-note').textContent = t(preserve ? 'devices_preserved' : 'devices_rejoin');
        $('confirm-label').textContent = t(preserve ? 'confirm_migration' : 'confirm_replace');
        $('preview').hidden = false;
    }
    $('export').addEventListener('submit', function (event) {
        event.preventDefault();
        if (busy || !validAuth()) return;
        var encrypted = $('encrypted').checked;
        if (encrypted && (!$('export-password').reportValidity() || !$('export-confirm').reportValidity())) return;
        if (encrypted && $('export-password').value !== $('export-confirm').value) {
            status('export', 'password_mismatch', true); $('export-confirm').focus(); return;
        }
        var data = auth(); data.encrypted = encrypted;
        if (encrypted) data.password = $('export-password').value;
        controls(true); status('export', 'working');
        request('export', data, true).then(function (blob) {
            var link = document.createElement('a'), objectUrl = URL.createObjectURL(blob);
            link.href = objectUrl;
            link.download = 'webclock-' + new Date().toISOString().slice(0, 10) + '.webclock';
            document.body.appendChild(link); link.click(); link.remove();
            window.setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 1000);
            status('export', encrypted ? 'downloaded' : 'downloaded_unencrypted');
        }).catch(function (error) { failure('export', error); }).finally(function () { controls(false); });
    });
    $('import').addEventListener('submit', function (event) {
        event.preventDefault();
        if (busy || importEncrypted === null || !validAuth() || !$('file').files[0] || (importEncrypted && !$('import-password').reportValidity())) return;
        invalidate(); var data = upload();
        controls(true); status('import', 'working');
        request('preview', data).then(function (result) {
            if (!result.ticket || !result.summary || typeof result.encrypted !== 'boolean') throw new Error('invalid_backup');
            importEncrypted = result.encrypted; renderOptions();
            preview = result; renderPreview(); status('import', 'ready');
        }).catch(function (error) { failure('import', error); }).finally(function () { controls(false); });
    });
    $('restore').addEventListener('click', function () {
        if (busy || !preview || !$('confirm').checked || !validAuth()) return;
        var data = upload(); data.append('ticket', preview.ticket); data.append('confirm', 'yes');
        controls(true); status('import', 'restoring');
        request('restore', data).then(function (result) {
            status('import', 'restored');
            $('import-password').value = '';
            if ($('admin-password')) $('admin-password').value = '';
            var path = result.redirect;
            if (typeof path !== 'string' || path.charAt(0) !== '/' || path.charAt(1) === '/' || path.charAt(1) === '\\') {
                path = window.webclockUrl ? window.webclockUrl('/admin#backup') : '/admin#backup';
            }
            window.location.href = path;
        }).catch(function (error) {
            invalidate(); failure('import', error); controls(false);
        });
    });
    ['input', 'change'].forEach(function (event) {
        $('import').addEventListener(event, function (change) {
            if (change.target === $('confirm')) controls(busy);
            else if (change.target === $('file')) inspectFile();
            else { invalidate(); status('import', ''); }
        });
        ['username', 'admin-password'].forEach(function (id) {
            if ($(id)) $(id).addEventListener(event, invalidate);
        });
    });
    $('encrypted').addEventListener('change', function () { renderOptions(); status('export', ''); });
    window.PortableBackup = {applyLanguage: function () { renderOptions(); renderPreview(); }};
    renderOptions(); inspectFile();
}());
