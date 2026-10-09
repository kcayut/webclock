// Run with node tests/test_portable_backup.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = {};
function element(id) {
    return nodes[id] = {id, value: '', disabled: false, hidden: false, checked: false, required: false, textContent: '', handlers: {}, attrs: {},
        addEventListener(type, fn) { this.handlers[type] = fn; }, setAttribute(key, value) { this.attrs[key] = value; },
        removeAttribute(key) { delete this.attrs[key]; }, reportValidity() { return !this.required || this.value.length > 0; }, focus() {},
        emit(type, target = this) { this.handlers[type]({target, preventDefault() {}}); }};
}
const container = element('complete-backup');
const ids = ['export', 'import', 'export-status', 'import-status', 'export-password', 'export-confirm',
    'file', 'import-password', 'preview', 'summary', 'device-note', 'confirm-label', 'confirm', 'restore', 'username', 'admin-password',
    'encrypted', 'export-passwords', 'password-hint', 'export-unencrypted', 'download', 'import-password-field', 'import-unencrypted', 'read'];
ids.forEach(id => element('complete-backup-' + id));
function $(id) { return nodes['complete-backup-' + id]; }
const inputs = ['encrypted', 'download', 'read', 'export-password', 'export-confirm', 'file', 'import-password', 'username', 'admin-password', 'confirm', 'restore'].map($);
container.querySelectorAll = () => inputs;
nodes['csrf-token'] = {content: 'csrf-token'};
$('restore').disabled = $('preview').hidden = true;
$('file').files = [];
$('encrypted').checked = true;
$('import-password').value = 'backup password';
$('username').value = 'admin';
$('admin-password').value = 'admin password';
const requests = [], readers = [], downloads = [];
let respond, language = 'zh-TW';
const window = {t: key => language + ':' + key, location: {},
    webclockUrl: path => '/ingress' + path, setTimeout: fn => fn()};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../static/portable-backup.js'), 'utf8'), {
    window, document: {getElementById: id => nodes[id], documentElement: {lang: 'zh-TW'}, body: {appendChild() {}},
        createElement() { return {click() { downloads.push(this.download); }, remove() {}}; }},
    URL: {createObjectURL: () => 'blob:backup', revokeObjectURL() {}},
    FileReader: class { constructor() { readers.push(this); } readAsArrayBuffer(slice) { this.slice = slice; } },
    FormData: class { constructor() { this.values = {}; } append(key, value) { this.values[key] = value; } },
    fetch(url, options) { requests.push({url, options}); return new Promise(resolve => { respond = resolve; }); }
});
const tick = () => new Promise(resolve => setImmediate(resolve));
const summary = {mode: 'managed', accounts: 2, calendars: 3, notes: 4, alarms: 5, events: 8, groups: 6, devices: 7};
function selectFile(version) {
    const file = {name: 'backup.webclock', slice(start, end) { assert.equal(start, 0); assert.equal(end, 10); return version; }};
    $('file').files = [file]; $('import').emit('change', $('file'));
    return readers.at(-1);
}
function read(reader, version) {
    reader.result = new Uint8Array([87, 69, 66, 67, 76, 79, 67, 75, 0, version]).buffer;
    reader.onload();
}
async function preview(encrypted = true) {
    $('import').emit('submit');
    assert.ok(inputs.every(input => input.disabled), 'Requests disable controls without clearing drafts');
    respond({ok: true, json: async () => ({ticket: 'ticket', summary, encrypted, preserve_devices: true})});
    await tick();
    assert.equal($('preview').hidden, false);
    assert.equal($('restore').disabled, true, 'Preview never authorizes replacement by itself');
}
async function run() {
    assert.equal($('encrypted').checked, true);
    assert.equal($('export-password').required, true);
    assert.equal($('import-password-field').hidden, true);
    assert.equal($('read').disabled, true);
    $('export-password').value = 'encrypted password'; $('export-confirm').value = 'different password';
    $('export').emit('submit');
    assert.equal(requests.length, 0, 'Encrypted backups require matching passwords');
    $('export-confirm').value = 'encrypted password'; $('export').emit('submit');
    assert.deepEqual(JSON.parse(requests.at(-1).options.body), {
        username: 'admin', admin_password: 'admin password', encrypted: true, password: 'encrypted password'});
    assert.ok(inputs.every(input => input.disabled));
    respond({ok: true, blob: async () => ({})}); await tick();
    assert.equal(downloads.length, 1);
    $('encrypted').checked = false; $('encrypted').emit('change');
    assert.equal($('export-passwords').hidden, true);
    assert.equal($('export-password').required, false);
    assert.equal($('export-password').disabled, true);
    assert.equal($('export-unencrypted').hidden, false);
    assert.equal($('download').textContent, 'zh-TW:complete_backup_download_unencrypted');
    $('export-confirm').value = 'mismatch is irrelevant'; $('export').emit('submit');
    assert.deepEqual(JSON.parse(requests.at(-1).options.body), {username: 'admin', admin_password: 'admin password', encrypted: false});
    respond({ok: true, blob: async () => ({})}); await tick();
    assert.equal(downloads.length, 2);
    assert.equal($('export-password').disabled, true, 'Finishing a request keeps unused password fields disabled');
    assert.equal($('export-status').textContent, 'zh-TW:complete_backup_downloaded_unencrypted');
    $('encrypted').checked = true; $('encrypted').emit('change');
    assert.equal($('export-password').value, 'encrypted password', 'Encryption toggles retain the password draft');
    assert.equal($('export-password').required, true);
    const stale = selectFile(1), selected = selectFile(2);
    assert.equal($('read').disabled, true, 'Read waits for file identification');
    read(selected, 2); read(stale, 1); stale.onerror();
    assert.equal($('import-password-field').hidden, true, 'An older file read cannot change the current file type');
    assert.equal($('import-unencrypted').hidden, false);
    assert.equal($('import-status').textContent, '');
    await preview(false);
    assert.equal(requests.at(-1).options.body.values.password, undefined, 'Plaintext imports never upload a leftover password');
    assert.equal(requests.at(-1).options.body.values.admin_password, 'admin password');
    $('confirm').checked = true; $('import').emit('change', $('confirm')); $('restore').emit('click');
    assert.equal(requests.at(-1).options.body.values.password, undefined);
    respond({ok: false, json: async () => ({code: 'preview_changed'})}); await tick();
    read(selectFile(3), 3);
    assert.equal($('read').disabled, true);
    const beforeInvalid = requests.length;
    $('import').emit('submit');
    assert.equal(requests.length, beforeInvalid, 'Unrecognized headers cannot be previewed');
    assert.equal($('import-status').textContent, 'zh-TW:complete_backup_invalid_backup');
    read(selectFile(1), 1);
    assert.equal($('import-password-field').hidden, false);
    assert.equal($('import-password').required, true);
    assert.equal($('import-unencrypted').hidden, true);
    const beforeEncrypted = requests.length;
    $('import').emit('submit');
    assert.equal(requests.at(-1).url, '/ingress/api/backup/complete/preview');
    assert.equal(requests.at(-1).options.headers['X-CSRF-Token'], 'csrf-token');
    assert.equal(requests.at(-1).options.body.values.admin_password, 'admin password');
    respond({ok: false, json: async () => ({code: 'backup_password_or_file_invalid'})});
    await tick();
    assert.equal($('import-password').value, 'backup password');
    assert.equal($('file').files[0].name, 'backup.webclock');
    assert.equal($('import-status').textContent, 'zh-TW:complete_backup_bad_password_or_file');
    assert.equal($('file').disabled, false);
    assert.equal($('restore').disabled, true);
    assert.equal(requests.length, beforeEncrypted + 1, 'Encrypted failures never retry as plaintext');
    assert.equal($('import-password-field').hidden, false);
    await preview();
    assert.match($('summary').textContent, /complete_backup_calendars: 3/);
    assert.equal($('device-note').textContent, 'zh-TW:complete_backup_devices_preserved');
    $('restore').emit('click');
    assert.equal(requests.length, beforeEncrypted + 2, 'Unchecked replacement confirmation cannot send a restore');
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
    console.log('Complete backup supports explicit optional encryption, safe asynchronous file detection, retained drafts, and confirmed restores.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
