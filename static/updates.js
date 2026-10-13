(function () {
    'use strict';
    var labels = JSON.parse(document.getElementById('update-i18n').textContent);
    var base = document.getElementById('updates').getAttribute('data-api-url');
    var status = document.getElementById('update-status');
    var channel = document.getElementById('update-channel');
    var automatic = document.getElementById('update-auto');
    var check = document.getElementById('update-check');
    var install = document.getElementById('update-install');
    var snapshot = null, pending = false, disconnected = false, disconnectedSince = 0, stopped = false, timer = null, notice = '';
    function text(key) { return labels[document.documentElement.lang][key] || labels.en[key] || key; }
    function localized(node, key) {
        node.setAttribute('data-update-text', key); node.textContent = text(key);
    }
    function date(value) {
        if (!value) return text('never');
        var parsed = new Date(typeof value === 'number' ? value * 1000 : value);
        return isNaN(parsed.getTime()) ? text('never') : parsed.toLocaleString(document.documentElement.lang);
    }
    function busy() { return snapshot && (snapshot.state === 'updating' || snapshot.state === 'checking'); }
    function message() {
        if (disconnected && Date.now() - disconnectedSince >= 120000) return 'reconnect_long';
        if (disconnected) return snapshot && snapshot.state === 'updating' ? 'reconnecting' : 'connection_lost';
        if (pending) return 'saving';
        if (notice) return notice;
        if (!snapshot) return 'loading';
        if (!snapshot.supported) return snapshot.reason === 'not_configured' ? 'not_configured' : 'unsupported';
        if (!snapshot.writable) return 'managed_required';
        if (snapshot.state === 'checking') return 'checking';
        if (snapshot.state === 'updating') return labels.en['phase_' + snapshot.phase] ? 'phase_' + snapshot.phase : 'updating';
        if (snapshot.result === 'manual_recovery') return 'manual_recovery';
        if (snapshot.result === 'rolled_back') return 'rolled_back';
        if (snapshot.state === 'interrupted') return 'interrupted';
        if (snapshot.state === 'failed' || snapshot.error) return 'failed';
        if (snapshot.update_available) return 'available';
        if (snapshot.result === 'updated' || snapshot.result === 'success') return 'updated';
        if (snapshot.channel === 'stable' && String(snapshot.current_version).indexOf('-') !== -1) return 'waiting_stable';
        return snapshot.last_checked ? 'up_to_date' : 'not_checked';
    }
    function render() {
        var key = message();
        localized(status, key);
        status.classList.toggle('error', ['failed', 'manual_recovery', 'rolled_back', 'request_failed', 'sign_in'].indexOf(key) !== -1);
        var enabled = !!(snapshot && snapshot.supported && snapshot.writable && !pending && !busy() && !disconnected);
        check.disabled = !enabled; channel.disabled = !enabled; automatic.disabled = !enabled;
        install.disabled = !enabled || !snapshot.update_available;
        document.getElementById('update-enable').hidden = !snapshot || snapshot.reason !== 'not_configured';
        document.getElementById('update-reconnect-help').hidden = !(disconnected && Date.now() - disconnectedSince >= 120000);
        document.getElementById('update-auto-paused').hidden = !snapshot || !snapshot.auto_update_paused;
        if (!snapshot) return;
        document.getElementById('update-current').textContent = snapshot.current_version || '—';
        document.getElementById('update-latest').textContent = snapshot.latest_version || '—';
        document.getElementById('update-last-checked').textContent = date(snapshot.last_checked);
        document.getElementById('update-next-check').textContent = date(snapshot.next_check);
        channel.value = snapshot.channel || 'stable'; automatic.checked = !!snapshot.auto_update;
        localized(document.getElementById('update-channel-hint'), channel.value === 'beta' ? 'beta_hint' : 'stable_hint');
        var link = document.getElementById('update-release-link');
        var safeUrl = /^https:\/\/github\.com\/kcayut\/webclock\/releases\/tag\/v[0-9A-Za-z.+-]+$/.test(snapshot.release_url || '');
        document.getElementById('update-release').hidden = !snapshot.latest_version;
        link.hidden = !safeUrl;
        if (safeUrl) link.href = snapshot.release_url;
        else link.removeAttribute('href');
        document.getElementById('update-notes').textContent = snapshot.release_notes || text('no_notes');
    }
    function schedule() {
        window.clearTimeout(timer);
        if (!stopped) timer = window.setTimeout(refresh, busy() || disconnected ? 3000 : 30000);
    }
    function request(path, data) {
        return fetch(base + path, {method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.getElementById('csrf-token').content},
            body: data === undefined ? undefined : JSON.stringify(data)}).then(function (response) {
            if (response.redirected || response.status === 401 || response.status === 403) throw new Error('sign_in');
            if (!response.ok) throw new Error('request_failed');
            return response.json();
        });
    }
    var queuedChange = null;
    function refresh() {
        if (pending || stopped) return;
        pending = true; render();
        return request('').then(function (data) {
            snapshot = data; disconnected = false; disconnectedSince = 0; notice = '';
        }).catch(function (error) {
            if (error.message === 'sign_in') { notice = 'sign_in'; disconnected = false; stopped = true; }
            else { if (!disconnected) disconnectedSince = Date.now(); disconnected = true; }
        }).then(function () {
            pending = false;
            if (queuedChange) {
                var next = queuedChange;
                queuedChange = null;
                change(next.path, next.data);
            } else {
                render();
                schedule();
            }
        });
    }
    function change(path, data) {
        if (busy() || disconnected) return;
        if (pending) {
            queuedChange = {path: path, data: data};
            return;
        }
        window.clearTimeout(timer); pending = true; notice = ''; render();
        return request(path, data).then(function (result) {
            snapshot = result; disconnected = false; disconnectedSince = 0;
        }).catch(function (error) {
            if (error.message === 'sign_in') { notice = 'sign_in'; stopped = true; }
            else if (error.message === 'request_failed') notice = 'request_failed';
            else {
                if (!disconnected) disconnectedSince = Date.now(); disconnected = true;
                // The server may have accepted the install before restarting. Only poll; never resubmit it.
                if (path === '/install') snapshot.state = 'updating';
            }
        }).then(function () {
            pending = false;
            if (queuedChange) {
                var next = queuedChange;
                queuedChange = null;
                change(next.path, next.data);
            } else {
                render();
                schedule();
            }
        });
    }
    check.addEventListener('click', function () { change('/check', {}); });
    install.addEventListener('click', function () {
        if (snapshot && snapshot.update_available) change('/install', {expected_version: snapshot.latest_version});
    });
    function saveSettings() {
        if (!snapshot) return;
        var selected = channel.value;
        if (selected === 'beta' && snapshot.channel !== 'beta' && !window.confirm(text('beta_confirm'))) {
            render(); return;
        }
        change('/settings', {channel: selected, auto_update: automatic.checked});
    }
    channel.addEventListener('change', saveSettings); automatic.addEventListener('change', saveSettings);
    window.applyManagementLanguage = function (language) {
        document.querySelectorAll('[data-update-text]').forEach(function (node) {
            node.textContent = labels[language][node.getAttribute('data-update-text')];
        });
        document.title = text('title') + ' · WebClock'; render();
    };
    window.addEventListener('pagehide', function () { stopped = true; window.clearTimeout(timer); });
    window.addEventListener('pageshow', function () {
        if (stopped && notice !== 'sign_in') {
            stopped = false;
            schedule();
            refresh();
        }
    });
    if (typeof document.addEventListener === 'function') {
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible' && stopped && notice !== 'sign_in') {
                stopped = false;
                schedule();
                refresh();
            }
        });
    }
    refresh();
}());
