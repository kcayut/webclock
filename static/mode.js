(function () {
    'use strict';
    var labels = JSON.parse(document.getElementById('mode-i18n').textContent);
    var accounts = JSON.parse(document.getElementById('mode-accounts').textContent);
    var form = document.getElementById('mode-form'), preview = null, busy = false;
    var target = document.getElementById('mode-target'), primary = document.getElementById('mode-primary');
    var apply = document.getElementById('mode-apply'), status = document.getElementById('mode-status');
    function text(key) { return labels[document.documentElement.lang][key] || labels[document.documentElement.lang].error; }
    function setStatus(key) { status.dataset.modeText = key; status.textContent = text(key); }
    function url(path) { return window.webclockUrl ? window.webclockUrl(path) : path; }
    function request(path, method, data) {
        return fetch(url(path), {method: method, credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.getElementById('csrf-token').content},
            body: data === undefined ? undefined : JSON.stringify(data)}).then(function (response) {
                return response.json().then(function (body) { if (!response.ok) throw new Error(body.code); return body; });
            });
    }
    function input() {
        var username = document.getElementById('mode-username');
        return {mode: target.value, primary_owner_id: primary.value, password: document.getElementById('mode-password').value,
            username: username ? username.value : undefined, confirm_shared: document.getElementById('mode-confirm').checked};
    }
    function invalidate() { preview = null; if (apply) apply.disabled = true; renderPreview(); }
    function renderPreview() {
        var box = document.getElementById('mode-preview'); if (!box) return; box.textContent = '';
        if (!preview) return;
        preview.spaces.forEach(function (space) {
            var row = document.createElement('article'), title = document.createElement('strong'), details = document.createElement('p');
            title.textContent = space.username + ' · ' + text(space.active ? 'active' : 'dormant');
            details.textContent = ['settings', 'sources', 'private_urls', 'reminders', 'schedules', 'events', 'groups', 'devices'].map(function (key) {
                return text(key) + ': ' + Number(space[key]);
            }).join(' · ');
            row.appendChild(title); row.appendChild(details); box.appendChild(row);
        });
        var publicNote = document.createElement('p'); publicNote.textContent = text('public'); box.appendChild(publicNote);
    }
    function renderAccounts() {
        var list = document.getElementById('accounts-list'); if (!list) return;
        list.textContent = '';
        accounts.forEach(function (account) {
            var row = document.createElement('p'), name = document.createElement('span');
            name.textContent = account.username + ' (' + account.role + ') '; row.appendChild(name);
            ['toggle', 'delete'].forEach(function (action) {
                var button = document.createElement('button'); button.type = 'button';
                button.textContent = text(action === 'delete' ? 'delete' : account.enabled ? 'disable' : 'enable');
                button.onclick = function () {
                    if (busy || !window.confirm(text('account_confirm'))) return;
                    busy = true; button.disabled = true;
                    request('/api/accounts/' + encodeURIComponent(account.owner_id), action === 'delete' ? 'DELETE' : 'PATCH',
                        action === 'delete' ? undefined : {enabled: !account.enabled}).then(function () {
                        window.location.href = url('/login');
                    }).catch(function (error) { busy = false; button.disabled = false; setStatus(error.message); });
                };
                row.appendChild(button);
            });
            list.appendChild(row);
        });
    }
    function changed(event) {
        if (event.target.id === 'mode-confirm') {
            apply.disabled = busy || !preview || (target.value === 'self' && !event.target.checked);
        } else invalidate();
    }
    if (form) form.addEventListener('input', changed);
    if (form) form.addEventListener('change', changed);
    if (form) form.onsubmit = function (event) {
        event.preventDefault(); if (busy) return; invalidate(); busy = true;
        var sent = JSON.stringify(input());
        request('/api/mode/preview', 'POST', input()).then(function (data) {
            if (JSON.stringify(input()) !== sent) return;
            preview = data; renderPreview();
            apply.disabled = target.value === 'self' && !document.getElementById('mode-confirm').checked;
            setStatus('ready');
        }).catch(function (error) { setStatus(error.message); }).finally(function () { busy = false; });
    };
    if (apply) apply.onclick = function () {
        if (busy || !preview) return;
        busy = true; apply.disabled = true;
        var data = input(); data.revision = preview.revision; data.generation = preview.generation;
        request('/api/mode/switch', 'POST', data).then(function (result) {
            document.getElementById('mode-password').value = '';
            window.location.href = url(result.mode === 'managed' ? '/login' : '/admin');
        }).catch(function (error) { busy = false; invalidate(); setStatus(error.message); });
    };
    var create = document.getElementById('account-create');
    if (create) create.onsubmit = function (event) {
        event.preventDefault(); if (busy) return; busy = true;
        request('/api/accounts', 'POST', {username: document.getElementById('account-name').value,
            password: document.getElementById('account-password').value}).then(function (result) {
            accounts.push(result.account); renderAccounts(); create.reset(); invalidate();
            if (primary) {
                var option = document.createElement('option'); option.value = result.account.owner_id;
                option.textContent = result.account.username; primary.appendChild(option);
            }
            setStatus('created');
        }).catch(function (error) { setStatus(error.message); }).finally(function () { busy = false; });
    };
    window.applyManagementLanguage = function () {
        document.querySelectorAll('[data-mode-text]').forEach(function (node) { node.textContent = text(node.dataset.modeText); });
        document.title = text('title') + ' · WebClock'; renderPreview(); renderAccounts();
    };
    renderAccounts();
}());
