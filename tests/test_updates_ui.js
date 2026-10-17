// Run with node tests/test_updates_ui.js.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/updates.js'), 'utf8');
const translations = fs.readFileSync(path.join(__dirname, '../webclock/translations/updates.py'), 'utf8');
const keys = [...translations.matchAll(/'([a-z_]+)':/g)].map(match => match[1]);
const flush = () => new Promise(setImmediate);

function setup() {
    const ids = {};
    function element(id) {
        return ids[id] || (ids[id] = {attrs: {}, listeners: {}, textContent: '', hidden: false, disabled: false,
            classList: {toggle() {}},
            getAttribute(name) { return this.attrs[name]; }, setAttribute(name, value) { this.attrs[name] = value; },
            removeAttribute(name) { delete this.attrs[name]; },
            addEventListener(name, callback) { this.listeners[name] = callback; },
            trigger(name) { this.listeners[name](); }});
    }
    element('update-i18n').textContent = JSON.stringify(Object.fromEntries(['en', 'ja', 'zh-TW'].map(language =>
        [language, Object.fromEntries(keys.map(key => [key, language + ':' + key]))])));
    element('updates').attrs['data-api-url'] = '/api/updates'; element('csrf-token').content = 'csrf-secret';
    const requests = [], timers = new Map();
    let nextTimer = 0, confirm = true, now = 1000000;
    const window = {confirm: () => confirm, addEventListener(name, callback) { this[name] = callback; },
        setTimeout(callback, delay) { timers.set(++nextTimer, {callback, delay}); return nextTimer; },
        clearTimeout(id) { timers.delete(id); }};
    const document = {documentElement: {lang: 'en'}, getElementById: element,
        querySelectorAll: () => Object.values(ids).filter(node => node.attrs['data-update-text'])};
    class Clock extends Date { static now() { return now; } }
    vm.runInNewContext(source, {document, window, Date: Clock, fetch(url, options) {
        return new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
    }});
    return {ids, window, document, requests, timers,
        cancelConfirm() { confirm = false; }, allowConfirm() { confirm = true; },
        advance(milliseconds) { now += milliseconds; },
        poll() { assert.equal(timers.size, 1); const [id, timer] = [...timers][0]; timers.delete(id); timer.callback(); },
        async reply(data, status = 200) {
            assert.ok(requests.length, 'Expected a pending request');
            const request = requests.shift();
            request.resolve({ok: status < 400, status, json: () => Promise.resolve(data)}); await flush(); return request;
        },
        async disconnect() { requests.shift().reject(new TypeError('Failed to fetch')); await flush(); }};
}
const initial = {supported: true, writable: true, current_version: '1.1.0', latest_version: '1.2.0',
    channel: 'stable', auto_update: true, state: 'available', update_available: true, last_checked: 1000,
    release_url: 'https://github.com/kcayut/webclock/releases/tag/v1.2.0', release_notes: '<script>bad()</script>'};

(async () => {
    const app = setup(), el = app.ids;
    assert.equal(app.requests[0].url, '/api/updates');
    await app.reply(initial);
    assert.equal(el['update-worker'].hidden, true);
    assert.equal(el['update-install'].disabled, false);
    assert.equal(el['update-notes'].textContent, initial.release_notes, 'Release notes must remain text');
    assert.equal(el['update-release-link'].href, initial.release_url);
    el['update-channel'].value = 'beta'; app.cancelConfirm(); el['update-channel'].trigger('change');
    assert.equal(app.requests.length, 0, 'Cancelling Beta must not change the host');
    assert.equal(el['update-channel'].value, 'stable');
    app.allowConfirm(); el['update-channel'].value = 'beta'; el['update-channel'].trigger('change');
    let request = await app.reply({...initial, channel: 'beta'});
    assert.equal(request.options.headers['X-CSRF-Token'], 'csrf-secret');
    assert.deepEqual(JSON.parse(request.options.body), {channel: 'beta', auto_update: true});
    el['update-auto'].checked = false; el['update-auto'].trigger('change');
    request = await app.reply({...initial, channel: 'beta', auto_update: false});
    assert.deepEqual(JSON.parse(request.options.body), {channel: 'beta', auto_update: false});
    app.document.documentElement.lang = 'ja'; app.window.applyManagementLanguage('ja');
    assert.equal(el['update-channel-hint'].textContent, 'ja:beta_hint');
    assert.equal(el['update-auto'].checked, false);
    el['update-install'].trigger('click');
    assert.deepEqual(JSON.parse(app.requests[0].options.body), {expected_version: '1.2.0'});
    await app.disconnect();
    assert.equal(el['update-status'].textContent, 'ja:reconnecting');
    assert.equal(el['update-install'].disabled, true);
    app.advance(121000); app.poll(); await app.disconnect();
    assert.equal(el['update-status'].textContent, 'ja:reconnect_long');
    assert.equal(el['update-reconnect-help'].hidden, false);
    app.poll(); request = await app.reply({...initial, current_version: '1.2.0', state: 'idle', update_available: false, result: 'updated'});
    assert.equal(request.options.method, 'GET', 'Reconnect must poll, never repeat an install');
    assert.equal(el['update-status'].textContent, 'ja:updated');
    assert.equal(el['update-reconnect-help'].hidden, true);
    app.poll(); await app.reply({...initial, state: 'failed', result: 'rolled_back', auto_update_paused: true});
    assert.equal(el['update-status'].textContent, 'ja:rolled_back');
    assert.equal(el['update-auto-paused'].hidden, false);
    app.poll(); await app.reply({...initial, state: 'failed', result: 'manual_recovery'});
    assert.equal(el['update-status'].textContent, 'ja:manual_recovery');
    app.poll(); await app.reply({...initial, state: 'interrupted', result: 'failed'});
    assert.equal(el['update-status'].textContent, 'ja:interrupted');
    app.poll(); await app.reply({...initial, channel: 'stable', current_version: '1.3.0-beta.1', update_available: false,
        release_url: 'javascript:alert(1)'});
    assert.equal(el['update-status'].textContent, 'ja:waiting_stable');
    assert.equal(el['update-release-link'].hidden, true);
    assert.equal(el['update-release-link'].attrs.href, undefined);
    app.poll(); await app.reply({}, 401);
    assert.equal(el['update-status'].textContent, 'ja:sign_in');
    assert.equal(app.timers.size, 0, 'An expired session must stop repeated unauthorized requests');

        for (const [reason, supported, message] of [['managed_required', true, 'managed_required'],
        ['not_configured', false, 'not_configured'], ['unsupported', false, 'unsupported']]) {
        const other = setup(); await other.reply({...initial, reason, supported, writable: false});
        assert.equal(other.ids['update-status'].textContent, 'en:' + message);
        assert.equal(other.ids['update-install'].disabled, true);
        assert.equal(other.ids['update-auto'].disabled, true);
        assert.equal(other.ids['update-enable'].hidden, reason !== 'not_configured');
        other.window.pagehide(); assert.equal(other.timers.size, 0);
        other.window.pageshow(); assert.equal(other.requests.length, 1, 'Pageshow must resume update status polling');
        await other.reply({...initial, reason, supported, writable: false});
        assert.equal(other.timers.size, 1);
    }

    const dockerApp = setup();
    await dockerApp.reply({...initial, installation_type: 'docker', supported: false, reason: 'not_configured', writable: false});
    assert.equal(dockerApp.ids['update-enable'].hidden, false);
    assert.equal(dockerApp.ids['update-enable-cmd'].textContent, '', 'Never guess a host path');
    dockerApp.ids['update-project-path'].value = "/srv/clock's data";
    dockerApp.ids['update-project-path'].trigger('input');
    let maintenance = dockerApp.ids['update-enable-cmd'].textContent;
    assert.ok(maintenance.includes('/releases/download/v1.1.0/portable_docker_update.sh'));
    assert.ok(maintenance.includes("--project '/srv/clock'\\''s data'"));
    assert.ok(maintenance.includes("--version '1.1.0' --refresh-worker"));
    assert.ok(maintenance.includes('mktemp'));
    assert.ok(!maintenance.includes('/opt/webclock'));
    dockerApp.ids['update-project-path'].value = '/srv/clock\ncommand';
    dockerApp.ids['update-project-path'].trigger('input');
    assert.equal(dockerApp.ids['update-worker-cmd'].textContent, '');
    const configuredDocker = setup();
    await configuredDocker.reply({...initial, installation_type: 'docker', project_path: '/srv/custom-clock'});
    assert.equal(configuredDocker.ids['update-project-path'].value, '/srv/custom-clock');
    assert.ok(configuredDocker.ids['update-worker-cmd'].textContent.includes("--project '/srv/custom-clock'"));
    assert.equal(dockerApp.ids['update-enable-title'].textContent, 'en:docker_enable_title');

    const haApp = setup();
    await haApp.reply({...initial, installation_type: 'ha_app', supported: false, reason: 'unsupported', writable: false, management_url: '/config/updates'});
    assert.equal(haApp.ids['update-enable'].hidden, true);
    assert.equal(haApp.ids['update-ha-app'].hidden, false);
    assert.equal(haApp.ids['update-ha-link'].href, '/config/updates');

    const queuedApp = setup(), queuedEl = queuedApp.ids;
    await queuedApp.reply(initial);
    queuedApp.poll(); // Start background polling GET request
    assert.equal(queuedApp.requests.length, 1);
    assert.equal(queuedEl['update-auto'].disabled, true, 'Controls must be disabled while polling');
    // User toggles auto update checkbox during poll
    queuedEl['update-auto'].checked = false;
    queuedEl['update-auto'].trigger('change');
    // First request is the poll GET
    await queuedApp.reply(initial);
    // Queued settings change POST must be sent immediately after poll completes
    assert.equal(queuedApp.requests.length, 1, 'Queued settings change must be dispatched after poll');
    assert.equal(queuedApp.requests[0].url, '/api/updates/settings');
    assert.deepEqual(JSON.parse(queuedApp.requests[0].options.body), {channel: 'stable', auto_update: false});
    await queuedApp.reply({...initial, auto_update: false});
    assert.equal(queuedEl['update-auto'].checked, false);

    console.log('Update UI channel consent, settings, reconnect, recovery, access and release text checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
