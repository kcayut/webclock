// Run with node tests/test_portable_backup.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = {};
function element(id) {
    return nodes[id] = {id, value: '', disabled: false, hidden: false, checked: false, textContent: '', handlers: {}, attrs: {},
        addEventListener(type, fn) { this.handlers[type] = fn; }, setAttribute(key, value) { this.attrs[key] = value; },
        removeAttribute(key) { delete this.attrs[key]; }, reportValidity() { return true; }, focus() {},
        emit(type, target = this) { this.handlers[type]({target, preventDefault() {}}); }};
}
const container = element('complete-backup');
const ids = ['export', 'import', 'export-status', 'import-status', 'export-password', 'export-confirm',
    'file', 'import-password', 'preview', 'summary', 'device-note', 'confirm-label', 'confirm', 'restore', 'username', 'admin-password'];
ids.forEach(id => element('complete-backup-' + id));
function $(id) { return nodes['complete-backup-' + id]; }
const inputs = ['export-password', 'export-confirm', 'file', 'import-password', 'username', 'admin-password', 'confirm', 'restore'].map($);
container.querySelectorAll = () => inputs;
nodes['csrf-token'] = {content: 'csrf-token'};
$('restore').disabled = $('preview').hidden = true;
$('file').files = [{name: 'backup.webclock'}];
$('import-password').value = 'backup password';
$('username').value = 'admin';
$('admin-password').value = 'admin password';
const requests = [];
let respond, language = 'zh-TW';
const window = {t: key => language + ':' + key, location: {},
    webclockUrl: path => '/ingress' + path};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../static/portable-backup.js'), 'utf8'), {
    window, document: {getElementById: id => nodes[id], documentElement: {lang: 'zh-TW'}},
    FormData: class { constructor() { this.values = {}; } append(key, value) { this.values[key] = value; } },
    fetch(url, options) { requests.push({url, options}); return new Promise(resolve => { respond = resolve; }); }
});
const tick = () => new Promise(resolve => setImmediate(resolve));
const summary = {mode: 'managed', accounts: 2, calendars: 3, notes: 4, alarms: 5, events: 8, groups: 6, devices: 7};
async function preview() {
    $('import').emit('submit');
    assert.ok(inputs.every(input => input.disabled), 'Requests disable controls without clearing drafts');
    respond({ok: true, json: async () => ({ticket: 'ticket', summary, preserve_devices: true})});
    await tick();
    assert.equal($('preview').hidden, false);
    assert.equal($('restore').disabled, true, 'Preview never authorizes replacement by itself');
}
async function run() {
    $('import').emit('submit');
    assert.equal(requests[0].url, '/ingress/api/backup/complete/preview');
    assert.equal(requests[0].options.headers['X-CSRF-Token'], 'csrf-token');
    assert.equal(requests[0].options.body.values.admin_password, 'admin password');
    respond({ok: false, json: async () => ({code: 'backup_password_or_file_invalid'})});
    await tick();
    assert.equal($('import-password').value, 'backup password');
    assert.equal($('file').files[0].name, 'backup.webclock');
    assert.equal($('import-status').textContent, 'zh-TW:complete_backup_bad_password_or_file');
    assert.equal($('file').disabled, false);
    assert.equal($('restore').disabled, true);
    await preview();
    assert.match($('summary').textContent, /complete_backup_calendars: 3/);
    assert.equal($('device-note').textContent, 'zh-TW:complete_backup_devices_preserved');
    $('restore').emit('click');
    assert.equal(requests.length, 2, 'Unchecked replacement confirmation cannot send a restore');
    $('confirm').checked = true; $('import').emit('change', $('confirm'));
    assert.equal($('restore').disabled, false);
    language = 'en'; window.PortableBackup.applyLanguage();
    assert.match($('summary').textContent, /^en:/);
    assert.equal($('confirm').checked, true, 'Language changes retain the confirmation and drafts');
    assert.equal($('import-password').value, 'backup password');
    $('import-password').value = 'changed password'; $('import').emit('input', $('import-password'));
    assert.equal($('preview').hidden, true);
    assert.equal($('restore').disabled, true);
    assert.equal($('confirm').checked, false);
    await preview();
    $('admin-password').emit('input');
    assert.equal($('preview').hidden, true, 'Administrator edits also invalidate the preview');
    await preview();
    $('confirm').checked = true; $('import').emit('change', $('confirm')); $('restore').emit('click');
    const restore = requests.at(-1);
    assert.equal(restore.url, '/ingress/api/backup/complete/restore');
    assert.equal(restore.options.body.values.ticket, 'ticket');
    assert.equal(restore.options.body.values.confirm, 'yes');
    respond({ok: false, json: async () => ({code: 'preview_changed'})});
    await tick();
    assert.equal($('import-password').value, 'changed password');
    assert.equal($('preview').hidden, true);
    assert.equal($('restore').disabled, true);
    assert.equal($('file').disabled, false);
    await preview();
    $('confirm').checked = true; $('import').emit('change', $('confirm')); $('restore').emit('click');
    respond({ok: true, json: async () => ({ok: true, redirect: '/ingress/login'})});
    await tick();
    assert.equal(window.location.href, '/ingress/login', 'Server redirects already contain the Ingress prefix');
    assert.equal($('import-password').value, '');
    console.log('Complete backup preserves failed drafts and requires a current preview plus explicit replacement confirmation.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
