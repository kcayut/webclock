'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/groups.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../templates/schedules.html'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const plain = value => JSON.parse(JSON.stringify(value));
const elements = new Map();
let active = null;
function element(tag = 'div') {
    const el = {tag, children: [], attributes: {}, listeners: {}, value: '', checked: false, hidden: false,
        disabled: false, textContent: '', selectionStart: 0, selectionEnd: 0,
        setAttribute(key, value) { this.attributes[key] = value; },
        getAttribute(key) { return this.attributes[key]; },
        append(...children) { children.forEach(child => { if (child.parentNode) child.remove(); child.parentNode = this; this.children.push(child); }); },
        replaceChildren(...children) { this.children.forEach(child => { child.parentNode = null; }); this.children = []; this.append(...children); },
        remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; },
        addEventListener(event, callback) { (this.listeners[event] ||= []).push(callback); },
        trigger(event) { return Promise.all((this.listeners[event] || []).map(callback => callback.call(this, {preventDefault() {}}))); },
        focus() { active = this; },
        contains(child) { return this === child || this.children.some(item => item.contains(child)); },
        reportValidity() { return true; }
    };
    let id = '';
    Object.defineProperty(el, 'id', {get: () => id, set(value) { id = value; elements.set(value, el); }});
    return el;
}
for (const match of template.matchAll(/\bid="([^"]+)"/g)) { const el = element(); el.id = match[1]; }
for (const field of ['calendar_source_ids', 'manual_note_ids', 'schedule_ids']) {
    for (const suffix of ['', '-empty']) { const el = element(); el.id = 'group-' + field + suffix; }
}
const $ = id => { assert.ok(elements.has(id), 'Missing ' + id); return elements.get(id); };
$('csrf-token').content = 'test-csrf';
const labels = {
 group_unsaved: 'Unsaved', group_saved_more_drafts: 'More edits remain', group_save_failed: 'Save failed',
 group_stale: 'Stale data', group_invite_details: '{state} {remaining}/{capacity} {expires}',
 group_inherit_value: 'Default {value}', group_invite_active: 'Active', group_member_active: 'Authorized',
 group_invite_none: 'No code', group_members_empty: 'No members', group_new: 'New group',
 group_choose: 'Choose', group_invite_closed: 'Closed', group_capacity_error: 'Invalid capacity',
 group_initialize_confirm: 'Import current content?', group_default_name: 'Default',
 group_delete_confirm: 'Delete {name}?', group_has_members: 'Members remain'
};
$('schedule-i18n').textContent = JSON.stringify({en: labels, 'zh-TW': {...labels, group_unsaved: '未儲存'}, ja: {...labels, group_unsaved: '未保存'}});
const defaultSettings = {brightness: 80, mode: 'normal', timezone_offset: 8, time_format: '24h', language: 'zh-TW',
    night: {enabled: true, start: '22:00', end: '07:00', brightness: 15, black: true}};
const content = {calendar_source_ids: [], manual_note_ids: [], schedule_ids: []};
const makeRow = (id, name) => ({id, name, enabled: true, display_overrides: {}, content: plain(content), effective_settings: plain(defaultSettings)});
const rowA = makeRow('a', 'Room A'), rowB = makeRow('b', 'Room B');
const catalog = {defaults: defaultSettings, calendar_sources: [{id: 'cal', name: 'Calendar'}],
    manual_notes: [{id: 7, text: 'Reminder'}], schedules: [{id: 'alarm', name: 'Alarm'}]};
const requests = [], intervals = [];
const document = {documentElement: {lang: 'en'}, hidden: false,
    get activeElement() { return active; }, getElementById: id => elements.get(id) || null,
    createElement: element, addEventListener() {},
    querySelectorAll(selector) {
        assert.equal(selector, '[data-group-i18n]');
        const all = new Set();
        function visit(el) { if (all.has(el)) return; all.add(el); el.children.forEach(visit); }
        elements.forEach(visit);
        return [...all].filter(el => el.getAttribute('data-group-i18n'));
    }};
// Attach relevant static fields so focus protection sees their stable form parent.
$('group-form').append($('group-name'), $('group-enabled'), $('group-settings'));
const window = {confirm: () => true};
const context = vm.createContext({window, document, Map, Set, Object, Array, JSON, Date, Number, Promise,
    setInterval(callback, delay) { intervals.push({callback, delay}); },
    fetch(url, options) { return new Promise((resolve, reject) => requests.push({url, options, resolve, reject, done: false})); }});
function next(path, method = 'GET') {
    const request = requests.find(item => !item.done && item.url === '/api/v1/groups' + path && item.options.method === method);
    assert.ok(request, method + ' ' + path); return request;
}
function respond(path, data, method = 'GET', ok = true) {
    const request = next(path, method); request.done = true; request.resolve({ok, json: () => Promise.resolve(plain(data))}); return request;
}
async function access(id, invitation = null, members = []) {
    respond('/' + id + '/invite', {invite: invitation}); respond('/' + id + '/members', {members}); await flush();
}
async function load(rows = [rowA, rowB], selected = 'a') {
    respond('', {groups: rows}); respond('/catalog', catalog); await flush(); if (selected) await access(selected);
}
function trigger(id, event, value) { if (value !== undefined) $(id).value = value; return $(id).trigger(event); }
function choice(key) {
    const parent = $('group-' + key.split(':')[0]);
    return parent.children.map(child => child.children[0]).find(input => input.getAttribute('data-group-content') === key);
}
async function main() {
    vm.runInContext(source, context);
    await load();
    assert.equal($('group-name').value, 'Room A');
    assert.equal(intervals[0].delay, 15000);
    assert.equal($('group-brightness').disabled, true);
    await trigger('group-name', 'input', 'Draft A');
    $('group-name').focus(); $('group-name').selectionStart = 1; $('group-name').selectionEnd = 4;
    intervals[0].callback(); await load([makeRow('a', 'Remote A'), rowB]);
    assert.equal($('group-name').value, 'Draft A');
    assert.equal(active, $('group-name')); assert.equal(active.selectionStart, 1); assert.equal(active.selectionEnd, 4);
    await trigger('group-select', 'change', 'b'); await access('b');
    await trigger('group-name', 'input', 'Draft B');
    await trigger('group-select', 'change', 'a'); await access('a');
    assert.equal($('group-name').value, 'Draft A');
    await trigger('group-brightness-policy', 'change', 'custom');
    await trigger('group-brightness', 'input', '0');
    await trigger('group-night-enabled-policy', 'change', 'custom');
    await trigger('group-night-enabled', 'input', 'false');
    const note = choice('manual_note_ids:7'); note.checked = true; await note.trigger('change');
    trigger('group-form', 'submit');
    const save = next('/a', 'PATCH');
    assert.equal(save.options.headers['X-CSRF-Token'], 'test-csrf');
    const payload = JSON.parse(save.options.body);
    assert.equal(payload.display_overrides.brightness, 0);
    assert.equal(payload.display_overrides.night.enabled, false);
    assert.deepEqual(payload.content.manual_note_ids, [7]);
    assert.deepEqual(payload.content.calendar_source_ids, []);
    const count = requests.length; await trigger('group-form', 'submit'); assert.equal(requests.length, count, 'No duplicate save');
    await trigger('group-name', 'input', 'Later A');
    await trigger('group-select', 'change', 'b'); await access('b');
    $('group-name').focus(); $('group-name').selectionStart = 2; $('group-name').selectionEnd = 5;
    document.documentElement.lang = 'ja'; window.WebClockGroups.applyLanguage();
    assert.equal($('group-name').value, 'Draft B'); assert.equal(active, $('group-name'));
    assert.equal(active.selectionStart, 2); assert.equal(active.selectionEnd, 5);
    respond('/a', {...rowA, ...payload}, 'PATCH'); await flush(); await access('b');
    assert.equal($('group-name').value, 'Draft B', 'Other group save cannot overwrite current draft');
    await trigger('group-select', 'change', 'a'); await access('a');
    assert.equal($('group-name').value, 'Later A', 'Late save keeps later input');
    assert.equal($('group-form-status').textContent, 'More edits remain');
    trigger('group-form', 'submit'); respond('/a', {code: 'storage_failed'}, 'PATCH', false); await flush(); await access('a');
    assert.equal($('group-name').value, 'Later A'); assert.equal($('group-form-status').textContent, 'Save failed');
    intervals[0].callback(); respond('', {}, 'GET', false); respond('/catalog', catalog); await flush();
    assert.equal($('group-refresh-status').textContent, 'Stale data'); assert.equal($('group-name').value, 'Later A');
    // Draft capacity, zero/false and empty content survive group and language changes.
    await trigger('group-invite-capacity', 'input', '2');
    trigger('group-invite-create', 'click');
    const invitationRequest = next('/a/invite', 'POST');
    assert.deepEqual(JSON.parse(invitationRequest.options.body), {capacity: 2});
    const pendingCount = requests.length; await trigger('group-invite-create', 'click'); assert.equal(requests.length, pendingCount);
    const invitation = {id: 'invite1', group_id: 'a', status: 'active', remaining: 2, capacity: 2, expires_at: '2030-01-01T00:00:00Z'};
    respond('/a/invite', {...invitation, code: 'ABC234'}, 'POST'); await flush();
    assert.equal($('group-code').textContent, 'ABC234'); assert.equal($('group-code-box').hidden, false);
    document.documentElement.lang = 'zh-TW'; window.WebClockGroups.applyLanguage();
    assert.equal($('group-code').textContent, 'ABC234');
    await trigger('group-select', 'change', 'b'); await access('b');
    assert.equal($('group-code').textContent, '');
    await trigger('group-select', 'change', 'a'); await access('a', invitation, [{id: 'device', status: 'active', enabled: true, online: null}]);
    assert.equal($('group-code').textContent, '', 'List reload must not reveal a previous code');
    assert.equal($('group-invite-capacity').value, '2');
    assert.equal($('group-members').children[0].children[0].textContent, 'device');
    trigger('group-invite-create', 'click');
    await trigger('group-select', 'change', 'b'); await access('b');
    respond('/a/invite', {...invitation, id: 'invite2', code: 'DEF234'}, 'POST'); await flush();
    assert.equal($('group-code').textContent, '', 'Late invitation cannot show on another group');
    await trigger('group-select', 'change', 'a'); await access('a', {...invitation, id: 'invite2'});
    assert.equal($('group-code').textContent, '');
    await trigger('group-brightness-policy', 'change', 'inherit');
    assert.equal($('group-brightness').disabled, true); assert.equal($('group-brightness').value, '80');
    const selectedNote = choice('manual_note_ids:7'); selectedNote.checked = false; await selectedNote.trigger('change');
    trigger('group-form', 'submit');
    const cleared = JSON.parse(next('/a', 'PATCH').options.body);
    assert.equal('brightness' in cleared.display_overrides, false); assert.deepEqual(cleared.content.manual_note_ids, []);
    respond('/a', {...rowA, ...cleared}, 'PATCH'); await flush(); await access('a');
    await trigger('group-add', 'click');
    assert.equal($('group-name').value, ''); assert.equal($('group-access').hidden, true);
    await trigger('group-name', 'input', 'New room'); trigger('group-form', 'submit');
    assert.deepEqual(JSON.parse(next('', 'POST').options.body).content, content);
    respond('', makeRow('new', 'New room'), 'POST'); await flush(); await access('new');
    assert.equal($('group-select').value, 'new'); assert.equal($('group-name').value, 'New room');
    await trigger('group-name', 'input', 'Unsaved group after revoke');
    $('group-name').focus(); $('group-name').selectionStart = 1; $('group-name').selectionEnd = 4;
    await trigger('group-select', 'change', 'new');
    await access('new', null, [{id: 'revoked', name: 'Revoked member'}, {device_id: 'kept', name: 'Kept member'}]);
    await trigger('group-select', 'change', 'new');
    const oldInvite = next('/new/invite'), oldMembers = next('/new/members');
    window.WebClockGroups.memberRemoved('revoked');
    assert.equal($('group-members').children.length, 1);
    assert.equal($('group-members').children[0].children[0].textContent, 'Kept member');
    oldInvite.done = oldMembers.done = true;
    oldInvite.resolve({ok: true, json: async () => ({invite: null})});
    oldMembers.resolve({ok: true, json: async () => ({members: [{id: 'revoked', name: 'Stale revoked member'}]})});
    await flush();
    assert.equal($('group-members').children[0].children[0].textContent, 'Kept member', 'Late member reads cannot restore revoked access');
    await access('new', null, [{device_id: 'kept', name: 'Kept member'}]);
    assert.equal($('group-name').value, 'Unsaved group after revoke');
    assert.equal(active, $('group-name')); assert.equal(active.selectionStart, 1); assert.equal(active.selectionEnd, 4);
    window.WebClockGroups.memberRemoved('kept');
    assert.equal($('group-members').children[0].textContent, 'No members');
    await access('new');
    assert.doesNotMatch(source, /localStorage|sessionStorage/);
    console.log('Group UI: inheritance, isolated drafts, focus, polling, failures, slow saves, code secrecy and member state passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
