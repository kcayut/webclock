'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/groups.js'), 'utf8');
const chooserSource = fs.readFileSync(path.join(__dirname, '../static/calendar-chooser.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../templates/schedules.html'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const plain = value => JSON.parse(JSON.stringify(value));
const elements = new Map();
let active = null;
function element(tag = 'div') {
    const el = {tag, children: [], attributes: {}, listeners: {}, value: '', checked: false, hidden: false,
        disabled: false, open: false, textContent: '', selectionStart: 0, selectionEnd: 0,
        setAttribute(key, value) { this.attributes[key] = value; },
        getAttribute(key) { return this.attributes[key]; },
        append(...children) { children.forEach(child => { if (child.parentNode) child.remove(); child.parentNode = this; this.children.push(child); }); },
        insertBefore(child, before) { if (child.parentNode) child.remove(); child.parentNode = this; this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child); },
        replaceChildren(...children) { this.children.forEach(child => { child.parentNode = null; }); this.children = []; this.append(...children); },
        remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; },
        addEventListener(event, callback) { (this.listeners[event] ||= []).push(callback); },
        trigger(event, details = {}) { return Promise.all((this.listeners[event] || []).map(callback => callback.call(this, {preventDefault() {}, ...details}))); },
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
 group_conflict: 'Conflict retained', group_reload: 'Reload group', group_reload_confirm: 'Discard edits?', group_unsaved: 'Unsaved', group_saved_more_drafts: 'More edits remain', group_save_failed: 'Save failed',
 group_stale: 'Stale data', group_invite_details: '{state} {remaining}/{capacity} {expires}',
 group_inherit_value: 'Default {value}', group_invite_active: 'Active', group_member_active: 'Authorized',
 group_invite_none: 'No code', group_members_empty: 'No members', group_new: 'New group',
 group_choose: 'Choose', group_invite_closed: 'Closed', group_capacity_error: 'Invalid capacity',
 group_initialize_confirm: 'Import current content?', group_default_name: 'Default',
 group_delete_confirm: 'Delete {name}?', group_has_members: 'Members remain',
 group_calendar_unlisted: 'Outside current list: {id} (selection retained)', group_calendar_failed: 'Calendar failed; selection retained',
 group_calendar_all: 'All events including future events', group_calendar_series: 'Whole series including future occurrences'
};
$('schedule-i18n').textContent = JSON.stringify({en: labels, 'zh-TW': {...labels, group_unsaved: '未儲存'}, ja: {...labels, group_unsaved: '未保存'}});
const defaultSettings = {brightness: 80, mode: 'normal', timezone_offset: 8, time_format: '24h', language: 'zh-TW',
    night: {enabled: true, start: '22:00', end: '07:00', brightness: 15, black: true}};
const content = {calendar_source_ids: [], manual_note_ids: [], schedule_ids: []};
const makeRow = (id, name) => ({id, name, revision: id + '-r1', enabled: true, display_overrides: {}, content: plain(content), effective_settings: plain(defaultSettings)});
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
    const parent = $('group-' + (key.startsWith('calendar_targets:') ? 'calendar_source_ids' : key.split(':')[0]));
    return descendants(parent).find(input => input.getAttribute('data-group-content') === key);
}
function descendants(parent) { return parent.children.flatMap(child => [child, ...descendants(child)]); }
const targetChoice = (uid, scope, recurrence = '') => choice('calendar_targets:' + JSON.stringify(['cal', uid, scope, recurrence]));
const detailsOf = input => input.parentNode.parentNode.parentNode;
async function clickChoice(input, checked, shiftKey = false) {
    assert.ok(input, 'Expected an available choice');
    input.checked = checked; await input.trigger('click', {shiftKey}); await input.trigger('change');
}
function calendarReply(events, ok = true) {
    const pending = requests.find(item => !item.done && item.url === '/api/v1/calendar-events?source_id=cal');
    assert.ok(pending, 'Expected lazy calendar request'); pending.done = true;
    pending.resolve({ok, json: async () => ok ? {events} : {code: 'calendar_not_ready'}});
}
async function calendarSelection() {
    catalog.calendar_sources.push({id: 'other', name: 'Other calendar'});
    catalog.manual_notes = [7, 8, 9, 10].map(id => ({id, text: 'Reminder ' + id}));
    catalog.schedules = ['alarm', 'alarm2', 'alarm3'].map(id => ({id, name: id}));
    const row = makeRow('calendar-test', 'Calendar test');
    row.content.calendar_source_ids = ['other'];
    row.content.calendar_targets = [{source_id: 'cal', uid: 'weekly', scope: 'occurrence', recurrence_id: 'outside-window', title: 'Previously selected'}];
    intervals[0].callback(); await load([row, makeRow('new', 'New group')], 'new');
    await trigger('group-select', 'change', row.id); await access(row.id);
    const sourceInput = choice('calendar_source_ids:cal'), sourceTree = detailsOf(sourceInput);
    assert.equal(choice('calendar_source_ids:other').checked, true, 'Old whole-source selections retain their meaning');
    assert.equal(sourceInput.indeterminate, true);
    assert.equal(requests.filter(item => item.url.includes('/calendar-events')).length, 0, 'Collapsed trees do not fetch calendars');
    sourceTree.open = true; await sourceTree.trigger('toggle');
    const event = (uid, recurrence_id, starts_at, recurring = true) => ({source_id: 'cal', uid, recurrence_id, starts_at, recurring, text: uid});
    const events = [event('weekly', 'original-1', '2030-01-01T10:00:00Z'),
        event('weekly', 'original-2', '2030-01-09T10:00:00Z'), event('weekly', 'original-3', '2030-01-15T10:00:00Z'),
        event('single-a', '', '2030-01-20T10:00:00Z', false), event('single-b', '', '2030-01-21T10:00:00Z', false)];
    calendarReply(events); await flush();
    const seriesInput = targetChoice('weekly', 'series'), seriesTree = detailsOf(seriesInput);
    seriesTree.open = true; await seriesTree.trigger('toggle');
    const first = targetChoice('weekly', 'occurrence', 'original-1'), middle = targetChoice('weekly', 'occurrence', 'original-2');
    const last = targetChoice('weekly', 'occurrence', 'original-3'), outside = targetChoice('weekly', 'occurrence', 'outside-window');
    assert.equal(outside.checked, true);
    assert.match(outside.parentNode.children[1].textContent, /Outside current list/);
    await clickChoice(first, true); await clickChoice(last, true, true);
    assert.equal(middle.checked, true, 'Shift-click selects the visible occurrence interval');
    await clickChoice(first, false); middle.parentNode.hidden = true; await clickChoice(last, false, true);
    assert.equal(middle.checked, true, 'Hidden choices are excluded from deselection ranges');
    assert.equal(last.checked, false); middle.parentNode.hidden = false;
    await clickChoice(last, true); middle.disabled = true; await clickChoice(first, true, true);
    assert.equal(first.checked, true); assert.equal(middle.checked, true);
    assert.equal(outside.checked, true, 'Range never drops saved occurrences outside the loaded window');
    // A range anchored inside a now-collapsed series cannot select its hidden children.
    await clickChoice(first, false); seriesTree.open = false; await seriesTree.trigger('toggle');
    await clickChoice(targetChoice('single-a', 'occurrence'), true, true);
    assert.equal(last.checked, true); assert.equal(first.checked, false);
    seriesTree.open = true; await seriesTree.trigger('toggle');
    await clickChoice(seriesInput, true);
    assert.equal(first.checked, true); assert.equal(first.disabled, true);
    assert.equal(targetChoice('weekly', 'occurrence', 'outside-window'), undefined, 'A series replaces its explicit occurrence selections');
    await clickChoice(sourceInput, true);
    assert.equal(seriesInput.disabled, true); assert.equal(targetChoice('single-a', 'occurrence').disabled, true);
    await clickChoice(sourceInput, false);
    assert.equal(first.checked, false); assert.equal(first.disabled, false);
    assert.equal(targetChoice('single-a', 'occurrence').checked, false, 'Unchecking all does not materialize a window snapshot');
    await clickChoice(sourceInput, true); await clickChoice(choice('calendar_source_ids:other'), false, true);
    assert.equal(sourceInput.checked, false, 'Source interval uses the endpoint new state to deselect');
    await clickChoice(seriesInput, true); await clickChoice(targetChoice('single-b', 'occurrence'), true, true);
    assert.equal(targetChoice('single-a', 'occurrence').checked, true, 'Series and one-off events share their source level');
    assert.equal(first.disabled, true, 'Selected series children inherit and remain unavailable to ranges');
    const note = id => choice('manual_note_ids:' + id);
    await clickChoice(note(7), true); await clickChoice(note(10), true, true);
    assert.equal(note(8).checked, true); assert.equal(note(9).checked, true);
    await clickChoice(note(7), false); note(8).parentNode.hidden = true; note(9).disabled = true;
    await clickChoice(note(10), false, true);
    assert.equal(note(8).checked, true); assert.equal(note(9).checked, true);
    assert.equal(note(7).checked, false); assert.equal(note(10).checked, false);
    note(8).parentNode.hidden = false;
    await clickChoice(choice('schedule_ids:alarm3'), true); await clickChoice(choice('schedule_ids:alarm'), true, true);
    assert.equal(choice('schedule_ids:alarm2').checked, true, 'Reverse ranges work for alarms too');
    // change-only activation remains supported, without a mouse click handler.
    choice('schedule_ids:alarm2').checked = false; await choice('schedule_ids:alarm2').trigger('change');
    assert.equal(choice('schedule_ids:alarm2').checked, false);
    const focused = targetChoice('single-a', 'occurrence'); focused.focus();
    document.documentElement.lang = 'en'; window.WebClockGroups.applyLanguage();
    assert.equal(active, focused); assert.equal(sourceTree.open, true); assert.equal(seriesTree.open, true);
    intervals[0].callback(); await load([row, makeRow('new', 'New group')], row.id);
    assert.equal(detailsOf(choice('calendar_source_ids:cal')), sourceTree);
    assert.equal(sourceTree.open, true); assert.equal(seriesTree.open, true); assert.equal(active, focused);
    const refresh = descendants(sourceTree).find(item => item.tag === 'button');
    refresh.trigger('click'); calendarReply([], false); await flush();
    assert.equal(targetChoice('single-a', 'occurrence'), focused, 'Calendar failure preserves nodes and selection');
    assert.equal(focused.checked, true); assert.equal(sourceTree.open, true);
    assert.ok(descendants(sourceTree).some(item => item.textContent === labels.group_calendar_failed));
    await trigger('group-select', 'change', 'new'); await access('new');
    assert.equal(detailsOf(choice('calendar_source_ids:cal')).open, false, 'Expansion belongs to each group draft');
    await trigger('group-select', 'change', row.id); await access(row.id);
    assert.equal(sourceTree.open, true); assert.equal(seriesTree.open, true);
    trigger('group-form', 'submit');
    const saved = JSON.parse(next('/' + row.id, 'PATCH').options.body);
    assert.deepEqual(saved.content.calendar_source_ids, []);
    assert.deepEqual(saved.content.calendar_targets.map(({uid, scope, recurrence_id}) => ({uid, scope, recurrence_id})), [
        {uid: 'weekly', scope: 'series', recurrence_id: ''}, {uid: 'single-a', scope: 'occurrence', recurrence_id: ''},
        {uid: 'single-b', scope: 'occurrence', recurrence_id: ''}]);
    assert.deepEqual(saved.content.manual_note_ids, [8, 9]);
    assert.deepEqual(new Set(saved.content.schedule_ids), new Set(['alarm', 'alarm3']));
    respond('/' + row.id, {code: 'storage_failure'}, 'PATCH', false); await flush(); await access(row.id);
    assert.equal(sourceTree.open, true); assert.equal(seriesTree.open, true); assert.equal(focused.checked, true);
    // A late calendar refresh can update its cache but cannot change the current group or its draft.
    refresh.trigger('click'); await trigger('group-select', 'change', 'new'); await access('new');
    calendarReply(events); await flush();
    assert.equal($('group-select').value, 'new');
    assert.equal($('group-name').value, 'Unsaved group after revoke');
    assert.equal(choice('calendar_source_ids:cal').checked, false);
    await trigger('group-select', 'change', row.id); await access(row.id);
    await clickChoice(seriesInput, false);
    await clickChoice(targetChoice('single-a', 'occurrence'), false);
    await clickChoice(targetChoice('single-b', 'occurrence'), false);
    trigger('group-form', 'submit');
    const cleared = JSON.parse(next('/' + row.id, 'PATCH').options.body);
    assert.deepEqual(cleared.content.calendar_targets, [], 'PATCH explicitly clears prior targets instead of retaining omitted fields');
    respond('/' + row.id, {...row, ...cleared}, 'PATCH'); await flush(); await access(row.id);
}
async function deviceSettingsChecks() {
    const settings = (revision, overrides = {}, inherited = defaultSettings) => ({revision,
        display_overrides: plain(overrides), inherited_settings: plain(inherited),
        effective_settings: {...plain(inherited), ...plain(overrides)},
        sources: Object.fromEntries(window.WebClockDeviceSettings.fields.map(([path]) =>
            [path, path.split('.')[0] in overrides ? 'device' : 'group']))});
    let device = {id: 'display-test', display_settings: settings('one')}, pending, language = 'en';
    const editor = window.WebClockDeviceSettings.create({t: key => language + ':' + key, onBusy() {},
        request(id, method, data) { return new Promise((resolve, reject) => { pending = {id, method, data, resolve, reject}; }); }});
    const root = editor.render(device), form = root.children.find(child => child.tag === 'form');
    const controls = descendants(root), save = controls.find(child => child.type === 'submit');
    const reload = controls.find(child => child.tag === 'button' && child.type === 'button');
    const status = controls.find(child => child.getAttribute('role') === 'status');
    const field = name => $('device-display-test-' + name);
    root.open = true;
    assert.equal(field('brightness').disabled, true);
    await trigger('device-display-test-brightness-policy', 'change', 'custom');
    await trigger('device-display-test-brightness', 'input', '0');
    await trigger('device-display-test-night-policy', 'change', 'custom');
    await trigger('device-display-test-night-enabled', 'input', 'false');
    const firstSave = form.trigger('submit');
    assert.equal(pending.data.display_overrides.brightness, 0);
    assert.equal(pending.data.display_overrides.night.enabled, false);
    assert.equal(Object.keys(pending.data.display_overrides.night).length, 5);
    assert.equal(editor.busy(device.id), true);
    const saved = settings('two', pending.data.display_overrides);
    await trigger('device-display-test-brightness', 'input', '12');
    pending.resolve(saved); await firstSave;
    device.display_settings = saved;
    field('brightness').focus(); language = 'ja';
    assert.equal(editor.render(device), root);
    assert.equal(root.open, true);
    assert.equal(active, field('brightness'));
    assert.equal(field('brightness').value, '12');
    assert.equal(status.textContent, 'ja:group_saved_more_drafts');
    device.display_settings = settings('remote', {brightness: 30});
    editor.render(device);
    assert.equal(field('brightness').value, '12');
    assert.equal(save.disabled, true);
    assert.equal(status.textContent, 'ja:device_display_conflict');
    window.confirm = () => false;
    await reload.trigger('click');
    assert.equal(field('brightness').value, '12');
    window.confirm = () => true;
    const refreshing = reload.trigger('click');
    assert.equal(pending.method, 'GET'); pending.resolve(device.display_settings); await refreshing;
    assert.equal(field('brightness').value, '30');
    await trigger('device-display-test-brightness-policy', 'change', 'inherit');
    assert.equal(field('brightness').disabled, true);
    assert.equal(field('brightness').value, '80');
    const resetting = form.trigger('submit');
    assert.deepEqual(plain(pending.data.display_overrides), {});
    pending.reject(new Error('disk full')); await resetting;
    assert.equal(status.textContent, 'ja:group_save_failed');
    assert.equal(field('brightness-policy').value, 'inherit');
    const conflict = form.trigger('submit');
    pending.reject(Object.assign(new Error('changed'), {code: 'display_settings_changed'})); await flush();
    assert.equal(pending.method, 'GET');
    pending.resolve(settings('remote-new', {brightness: 20})); await conflict;
    assert.equal(field('brightness-policy').value, 'inherit');
    assert.equal(save.disabled, true);
    assert.equal(status.textContent, 'ja:device_display_conflict');
    const reloading = reload.trigger('click');
    await trigger('device-display-test-brightness-policy', 'change', 'custom');
    await trigger('device-display-test-brightness', 'input', '5');
    pending.resolve(settings('latest', {brightness: 50})); await reloading;
    assert.equal(field('brightness').value, '5', 'Slow reload keeps later edits');
    assert.equal(save.disabled, true);
}
async function deviceContentChecks() {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/device-content.js'), 'utf8'), context);
    const target = {source_id: 'cal', uid: 'series', scope: 'occurrence', recurrence_id: 'one', title: 'Meeting'};
    const inherited = {calendar_source_ids: ['cal'], calendar_targets: [], calendar_exclusions: [target], manual_note_ids: [7], schedule_ids: ['alarm']};
    const settings = (revision, overrides = {}) => ({revision, content_overrides: plain(overrides),
        inherited_content: plain(inherited), effective_content: {...plain(inherited), ...plain(overrides)},
        sources: {calendar: 'calendar_source_ids' in overrides ? 'device' : 'group',
            manual_note_ids: 'manual_note_ids' in overrides ? 'device' : 'group', schedule_ids: 'schedule_ids' in overrides ? 'device' : 'group'}});
    let device = {id: 'content-test', content_settings: settings('one')}, pending, language = 'en', catalogFails = false;
    const editor = window.WebClockDeviceContent.create({t: key => language + ':' + key, onBusy() {},
        loadCatalog: async () => {
            if (catalogFails) throw new Error('offline');
            return {calendar_sources: [{id: 'cal', name: 'Calendar'}], manual_notes: [{id: 7, text: 'Reminder'}], schedules: [{id: 'alarm', name: 'Alarm'}]};
        }, loadEvents: async () => ({events: []}),
        request(id, method, data) { return new Promise((resolve, reject) => { pending = {id, method, data, resolve, reject}; }); }});
    const root = editor.render(device); root.open = true;
    await editor.refreshCatalog();
    const form = root.children.find(child => child.tag === 'form');
    const save = descendants(root).find(child => child.type === 'submit');
    const reload = descendants(root).find(child => child.textContent === 'en:device_content_reload');
    const status = form.children.find(child => child.getAttribute('role') === 'status');
    const policy = key => $('device-content-content-test-' + key);
    const select = (key, value) => trigger('device-content-content-test-' + key, 'change', value);
    const contentChoice = key => descendants(root).find(child => child.getAttribute('data-device-content-choice') === key);
    await select('calendar_source_ids', 'custom');
    await select('manual_note_ids', 'custom');
    const note = contentChoice('manual_note_ids:7'); note.checked = false; await note.trigger('change');
    const first = form.trigger('submit');
    assert.equal(pending.method, 'PATCH');
    assert.deepEqual(plain(pending.data), {revision: 'one', content_overrides: {
        calendar_source_ids: ['cal'], calendar_targets: [], calendar_exclusions: [target], manual_note_ids: []}});
    assert.equal(editor.busy(device.id), true);
    const saved = settings('two', pending.data.content_overrides);
    await select('schedule_ids', 'custom');
    pending.resolve(saved); await first;
    device.content_settings = saved;
    note.focus(); language = 'ja';
    assert.equal(editor.render(device), root); assert.equal(active, note); assert.equal(root.open, true);
    assert.equal(note.checked, false); assert.equal(policy('schedule_ids').value, 'custom');
    assert.equal(status.textContent, 'ja:group_saved_more_drafts');
    device.content_settings = settings('moved-group'); editor.render(device);
    assert.equal(note.checked, false); assert.equal(save.disabled, true);
    assert.equal(status.textContent, 'ja:device_content_conflict');
    window.confirm = () => false; await reload.trigger('click'); assert.equal(note.checked, false);
    window.confirm = () => true;
    const loading = reload.trigger('click'); pending.resolve(device.content_settings); await loading;
    assert.equal(policy('manual_note_ids').value, 'inherit');
    await select('calendar_source_ids', 'custom'); await select('calendar_source_ids', 'inherit');
    const restoring = form.trigger('submit'); assert.deepEqual(plain(pending.data.content_overrides), {});
    pending.reject(Object.assign(new Error('conflict'), {code: 'content_settings_changed'})); await flush();
    assert.equal(pending.method, 'GET'); pending.reject(new Error('offline')); await restoring;
    assert.equal(save.disabled, true, 'A failed conflict readback must still block stale writes');
    assert.equal(status.textContent, 'ja:device_content_conflict');
    const slowReload = reload.trigger('click'); await select('manual_note_ids', 'custom');
    note.checked = false; await note.trigger('change');
    device.content_settings = settings('latest'); pending.resolve(device.content_settings); await slowReload;
    assert.equal(note.checked, false, 'Edits during a slow reload survive'); assert.equal(save.disabled, true);
    catalogFails = true; await editor.refreshCatalog();
    assert.equal(contentChoice('manual_note_ids:7'), note); assert.equal(note.checked, false);
    assert.ok(descendants(root).some(child => child.textContent === 'ja:device_content_catalog_failed'));
    const latest = reload.trigger('click'); pending.resolve(device.content_settings); await latest;
    assert.equal(policy('manual_note_ids').value, 'inherit');
    const replacement = editor.render(device, true);
    assert.equal(replacement, root); assert.equal(policy('manual_note_ids').disabled, true);
    editor.forget(device.id); assert.notEqual(editor.render(device), root, 'Revocation discards the device draft');
}
async function main() {
    vm.runInContext(chooserSource, context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/device-settings.js'), 'utf8'), context);
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
    assert.equal(payload.revision, 'a-r1', 'The draft keeps the revision it was based on');
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
    await calendarSelection();
    // Select-all applies to the current catalog, while unavailable selections
    // remain explicit drafts and never become range-selection endpoints.
    const bulkRow = makeRow('bulk-notes', 'Bulk reminders');
    bulkRow.content.manual_note_ids = [7, 999];
    intervals[0].callback(); await load([bulkRow], null);
    await trigger('group-select', 'change', bulkRow.id); await access(bulkRow.id);
    const allNotes = descendants($('group-manual_note_ids')).find(input => input.getAttribute('data-group-select-all') === 'manual_note_ids');
    assert.equal(allNotes.checked, false); assert.equal(allNotes.indeterminate, true);
    allNotes.checked = true; await allNotes.trigger('change');
    assert.equal(allNotes.checked, true); assert.equal(allNotes.indeterminate, false);
    assert.ok([7, 8, 9, 10, 999].every(id => choice('manual_note_ids:' + id).checked));
    await clickChoice(choice('manual_note_ids:8'), false);
    assert.equal(allNotes.checked, false); assert.equal(allNotes.indeterminate, true);
    allNotes.focus();
    document.documentElement.lang = 'en'; window.WebClockGroups.applyLanguage();
    assert.equal(active, allNotes); assert.equal(allNotes.indeterminate, true);
    allNotes.checked = false; await allNotes.trigger('change');
    assert.ok([7, 8, 9, 10].every(id => !choice('manual_note_ids:' + id).checked));
    assert.equal(choice('manual_note_ids:999').checked, true, 'Select-all preserves unavailable historical IDs');
    assert.equal(allNotes.indeterminate, false);
    trigger('group-form', 'submit');
    assert.deepEqual(JSON.parse(next('/bulk-notes', 'PATCH').options.body).content.manual_note_ids, [999]);
    respond('/bulk-notes', {code: 'storage_failed'}, 'PATCH', false); await flush(); await access('bulk-notes');
    assert.equal(allNotes.checked, false); assert.equal(choice('manual_note_ids:999').checked, true);
    catalog.manual_notes = [];
    intervals[0].callback(); await load([bulkRow], 'bulk-notes');
    assert.equal(allNotes.disabled, true); assert.equal(allNotes.checked, false); assert.equal(allNotes.indeterminate, false);
    const deniedOccurrence = {source_id: 'cal', uid: 'weekly', scope: 'occurrence', recurrence_id: 'original-2', title: 'Weekly'};
    const excludedRow = makeRow('exceptions', 'Calendar exceptions');
    excludedRow.content.calendar_source_ids = ['cal']; excludedRow.content.calendar_exclusions = [deniedOccurrence];
    intervals[0].callback(); await load([excludedRow], 'bulk-notes');
    await trigger('group-select', 'change', excludedRow.id); await access(excludedRow.id);
    const sourceCheck = choice('calendar_source_ids:cal'), sourceTree = detailsOf(sourceCheck);
    sourceTree.open = true; await sourceTree.trigger('toggle');
    const weekly = targetChoice('weekly', 'series'), weeklyTree = detailsOf(weekly);
    weeklyTree.open = true; await weeklyTree.trigger('toggle');
    assert.equal(sourceCheck.checked, false); assert.equal(sourceCheck.indeterminate, true, 'Whole source with an exception is shown as partial');
    assert.equal(weekly.checked, false); assert.equal(weekly.indeterminate, true);
    assert.equal(targetChoice('weekly', 'occurrence', 'original-1').checked, true);
    assert.equal(targetChoice('weekly', 'occurrence', 'original-2').checked, false);
    assert.equal(targetChoice('weekly', 'occurrence', 'original-2').disabled, false, 'Exceptions remain explicitly editable');
    await trigger('group-name', 'input', 'Only name changed'); trigger('group-form', 'submit');
    let exceptionPayload = JSON.parse(next('/exceptions', 'PATCH').options.body);
    assert.deepEqual(exceptionPayload.content.calendar_exclusions, [deniedOccurrence], 'Other group edits retain exact exclusions');
    respond('/exceptions', {...excludedRow, ...exceptionPayload}, 'PATCH'); await flush(); await access('exceptions');
    await trigger('group-name', 'input', 'Retained conflict draft'); trigger('group-form', 'submit');
    respond('/exceptions', {code: 'group_settings_changed'}, 'PATCH', false); await flush(); await access('exceptions');
    assert.equal($('group-name').value, 'Retained conflict draft');
    assert.equal($('group-form-status').textContent, 'Conflict retained'); assert.equal($('group-save').disabled, true);
    const requestCount = requests.length;
    await trigger('group-form', 'submit'); assert.equal(requests.length, requestCount, 'Conflicts cannot be resent without reload');
    window.confirm = () => false;
    await trigger('group-reload', 'click'); assert.equal(requests.length, requestCount, 'Cancelling reload preserves the entire draft');
    window.confirm = () => true;
    trigger('group-reload', 'click');
    await trigger('group-name', 'input', 'Typed while reloading');
    respond('/exceptions', {...excludedRow, revision: 'exceptions-r2', name: 'Latest server group'}); respond('/catalog', catalog); await flush();
    assert.equal($('group-name').value, 'Typed while reloading'); assert.equal($('group-save').disabled, true);
    trigger('group-reload', 'click');
    respond('/exceptions', {...excludedRow, revision: 'exceptions-r2', name: 'Latest server group'}); respond('/catalog', catalog); await flush();
    assert.equal($('group-name').value, 'Latest server group'); assert.equal($('group-reload').hidden, true);
    await trigger('group-name', 'input', 'Edited after reload'); trigger('group-form', 'submit');
    const reloadedPayload = JSON.parse(next('/exceptions', 'PATCH').options.body);
    assert.equal(reloadedPayload.revision, 'exceptions-r2');
    respond('/exceptions', {...excludedRow, ...reloadedPayload}, 'PATCH'); await flush(); await access('exceptions');
    await clickChoice(targetChoice('weekly', 'occurrence', 'original-1'), false);
    await clickChoice(targetChoice('weekly', 'occurrence', 'original-2'), true);
    trigger('group-form', 'submit'); exceptionPayload = JSON.parse(next('/exceptions', 'PATCH').options.body);
    assert.deepEqual(exceptionPayload.content.calendar_exclusions.map(item => item.recurrence_id), ['original-1']);
    assert.deepEqual(exceptionPayload.content.calendar_source_ids, ['cal'], 'Editing exceptions never materializes the source into a one-year snapshot');
    respond('/exceptions', {...excludedRow, ...exceptionPayload}, 'PATCH'); await flush(); await access('exceptions');
    await clickChoice(weekly, true);
    assert.equal(weekly.checked, true); assert.equal(weekly.indeterminate, false);
    trigger('group-form', 'submit'); exceptionPayload = JSON.parse(next('/exceptions', 'PATCH').options.body);
    assert.deepEqual(exceptionPayload.content.calendar_exclusions, [], 'Explicit whole-series selection clears its exclusions with an explicit PATCH []');
    respond('/exceptions', {...excludedRow, ...exceptionPayload}, 'PATCH'); await flush(); await access('exceptions');
    const isolated = element();
    let selected;
    const chooser = window.WebClockCalendarChooser.create({container: isolated, t: key => key, onChange: value => { selected = value; }});
    const seriesDeny = {...deniedOccurrence, scope: 'series', recurrence_id: ''};
    chooser.render([{id: 'cal', name: 'Calendar'}], {source_ids: ['cal'], targets: [deniedOccurrence], exclusions: [seriesDeny]}, new Set());
    const isolatedChoice = target => descendants(isolated).find(item => item.getAttribute('data-group-content') === 'calendar_targets:' + JSON.stringify([target.source_id, target.uid, target.scope, target.recurrence_id]));
    const allowedChild = isolatedChoice(deniedOccurrence);
    assert.equal(allowedChild.checked, true, 'An explicit occurrence grant overrides a series exclusion');
    assert.equal(isolatedChoice(seriesDeny).indeterminate, true);
    chooser.render([{id: 'cal', name: 'Calendar'}], {source_ids: ['cal'], targets: [deniedOccurrence], exclusions: [seriesDeny, deniedOccurrence]}, new Set());
    assert.equal(allowedChild.checked, false, 'An exact occurrence exclusion has highest priority');
    assert.doesNotMatch(source, /localStorage|sessionStorage/);
    await deviceSettingsChecks();
    await deviceContentChecks();
    console.log('Group/device UI: inheritance, conflicts, drafts, focus, failures and calendar selection passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
