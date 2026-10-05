// Run with node tests/test_calendar_ui.js.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const admin = fs.readFileSync(path.join(__dirname, '../templates/admin.html'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, '../static/calendar-settings.js'), 'utf8');
const chooserSource = fs.readFileSync(path.join(__dirname, '../static/calendar-chooser.js'), 'utf8');
assert.ok(admin.indexOf('class="note-list cards"') < admin.indexOf('id="calendar-source-settings"'));
assert.match(admin, /<details id="calendar-source-settings" class="panel calendar-source-settings">/);
assert.doesNotMatch(source, /localStorage|sessionStorage/);
const created = [];
let active = null;
function element(tag = 'div') {
    let ownText = '';
    const item = {tag, id: '', children: [], attrs: {}, listeners: {}, disabled: false, hidden: false,
        value: '', checked: false, type: '', className: '', parentNode: null,
        setAttribute(key, value) { this.attrs[key] = String(value); },
        getAttribute(key) { return this.attrs[key]; },
        removeAttribute(key) { delete this.attrs[key]; },
        appendChild(child) { if (child.parentNode) child.remove(); this.children.push(child); child.parentNode = this; return child; },
        append(...children) { children.forEach(child => this.appendChild(child)); },
        insertBefore(child, before) { if (child.parentNode) child.remove(); this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child); child.parentNode = this; },
        removeChild(child) { this.children.splice(this.children.indexOf(child), 1); child.parentNode = null; },
        remove() { if (this.parentNode) this.parentNode.removeChild(this); },
        contains(child) { return this === child || this.children.some(item => item.contains(child)); },
        addEventListener(name, listener) { this.listeners[name] = listener; },
        trigger(name, details = {}) { assert.ok(this.listeners[name], name + ' listener'); return this.listeners[name].call(this, {preventDefault() {}, ...details}); },
        focus() { this.focused = true; active = this; }
    };
    Object.defineProperty(item, 'textContent', {
        get() { return ownText + this.children.map(child => child.textContent).join(''); },
        set(value) { ownText = value; this.children = []; }
    });
    Object.defineProperty(item, 'innerHTML', {set() { ownText = ''; this.children = []; }});
    created.push(item);
    return item;
}
const elements = new Map(Array.from(admin.matchAll(/\bid="([^"]+)"/g), match => [match[1], element()]));
const providers = ['apple', 'google', 'ics'];
providers.forEach(provider => elements.set('calendar-sources-' + provider, element()));
const buttons = providers.map(provider => {
    const button = element('button');
    button.setAttribute('data-calendar-add', provider);
    return button;
});
const $ = id => { assert.ok(elements.has(id), id); return elements.get(id); };
$('csrf-token').content = 'calendar-csrf-token';
$('timezone-select').value = '8';
$('time-format-select').value = '24h';
const requests = [];
let language = 'en', autoList = true;
const context = vm.createContext({
    document: {documentElement: {lang: 'en'}, get activeElement() { return active; }, getElementById: $, createElement: element, querySelectorAll(selector) {
        assert.equal(selector, '[data-calendar-add]'); return buttons;
    }},
    window: {t(key) { return key === 'calendar_source_count' ? (language === 'en' ? '{count} sources configured' : '已設定 {count} 個來源') : key; }},
    XMLHttpRequest: class {
        open(method, url) { this.method = method; this.url = url; }
        constructor() { this.headers = {}; }
        setRequestHeader(name, value) { this.headers[name] = value; }
        send(body) {
            this.body = body;
            if (autoList && this.url === '/api/calendar/display-items') reply(this, 200, {items: []});
            else requests.push(this);
        }
    }
});
vm.runInContext(chooserSource, context);
vm.runInContext(source, context);
function take(method, url = '/api/calendar') {
    const index = requests.findIndex(request => request.method === method && request.url === url);
    assert.ok(index >= 0, 'Expected ' + method + ' ' + url);
    const request = requests.splice(index, 1)[0];
    assert.equal(request.headers['X-CSRF-Token'], method === 'GET' ? undefined : 'calendar-csrf-token');
    return request;
}
function reply(request, status, data) {
    request.status = status; request.responseText = JSON.stringify(data); request.onload();
}
function descendants(item) { return item.children.flatMap(child => [child, ...descendants(child)]); }
function sourceRows(provider) { return $('calendar-sources-' + provider).children; }
function input(row, kind) { return descendants(row).find(item => item.tag === 'input' && item.id.startsWith('calendar-' + kind + '-')); }
function button(row, key) { return descendants(row).find(item => item.tag === 'button' && item.textContent === key); }
function display(id) { return descendants($('calendar-display-list')).find(item => item.getAttribute('data-calendar-source') === id || item.getAttribute('data-group-content') === 'calendar_source_ids:' + id); }
function submit(id) { $(id).trigger('submit'); }
const initial = {local_display_enabled: true, errors: [{id: 'google1', error: 'fetch_failed'}], sources: [
    {id: 'apple1', name: 'Home', provider: 'apple', url: 'https://apple.example/home.ics', display_enabled: true},
    {id: 'google1', name: 'Work', provider: 'google', url: 'https://google.example/work.ics', display_enabled: true}
]};
assert.equal($('calendar-source-fields').disabled, true);
reply(take('GET'), 500, {error: 'load_failed'});
assert.equal($('calendar-display-status').textContent, 'calendar_load_error');
assert.equal($('calendar-retry').hidden, false);
submit('calendar-form'); submit('calendar-display-form');
assert.equal(requests.length, 0, 'Failed load must never enable a destructive empty save');
$('calendar-retry').trigger('click');
reply(take('GET'), 200, null);
assert.equal($('calendar-display-fields').disabled, true);
$('calendar-retry').trigger('click');
reply(take('GET'), 200, initial);
assert.equal($('calendar-source-fields').disabled, false);
assert.equal($('calendar-source-summary').textContent, '2 sources configured');
assert.equal($('calendar-source-errors').textContent, 'Work: calendar_fetch_failed');
assert.equal(display('local').checked, true);
assert.equal(sourceRows('apple').length, 1);
assert.equal(sourceRows('google').length, 1);
const appleRow = sourceRows('apple')[0];
assert.equal(input(appleRow, 'url').type, 'password');
button(appleRow, 'calendar_show').trigger('click');
assert.equal(input(appleRow, 'url').type, 'text');
input(appleRow, 'name').value = 'Home edited';
input(appleRow, 'url').value = 'webcal://apple.example/new.ics';
buttons[1].trigger('click');
const added = sourceRows('google')[1];
assert.equal(input(added, 'url').type, 'password');
assert.equal(input(added, 'url').focused, true);
input(added, 'url').value = 'https://google.example/second.ics';
display('local').checked = false;
display('google1').checked = false;
display('google1').trigger('change');
submit('calendar-display-form');
const firstPatch = take('PATCH');
assert.deepEqual(JSON.parse(firstPatch.body), {local_display_enabled: false, calendar_targets: [], sources: [
    {id: 'apple1', display_enabled: true}, {id: 'google1', display_enabled: false}
]});
assert.doesNotMatch(firstPatch.body, /url|provider|name|new\.ics/);
assert.equal($('calendar-source-fields').disabled, true, 'Serialize source and display saves');
submit('calendar-form'); assert.equal(requests.length, 0);
reply(firstPatch, 500, {error: 'save_failed'});
assert.equal(display('google1').checked, false);
assert.equal(input(appleRow, 'url').value, 'webcal://apple.example/new.ics');
assert.equal($('calendar-display-status').textContent, 'calendar_save_error');
submit('calendar-display-form');
const selected = {local_display_enabled: false, sources: initial.sources.map(item => ({...item, display_enabled: item.id !== 'google1'}))};
reply(take('PATCH'), 200, selected);
assert.equal(input(appleRow, 'name').value, 'Home edited');
assert.equal(input(appleRow, 'url').value, 'webcal://apple.example/new.ics', 'Visibility save must retain unsaved URL input');
assert.equal(sourceRows('google').length, 2, 'Visibility save must retain unsaved new sources');
display('apple1').checked = false;
display('apple1').trigger('change');
submit('calendar-form');
const post = take('POST');
const payload = JSON.parse(post.body);
assert.equal(payload.local_display_enabled, false);
assert.equal(payload.sources[0].display_enabled, true, 'Source save must not submit an unsaved display selection');
assert.equal(payload.sources[1].display_enabled, false);
assert.equal(payload.sources[0].url, 'webcal://apple.example/new.ics');
assert.equal(payload.sources[0].name, 'Home edited');
assert.equal(payload.sources[2].id, undefined, 'New source IDs belong to the server');
reply(post, 400, {error: 'invalid_settings'});
assert.equal($('calendar-status').textContent, 'calendar_invalid_settings');
assert.equal(input(appleRow, 'url').value, 'webcal://apple.example/new.ics');
submit('calendar-form');
take('POST').ontimeout();
assert.equal($('calendar-status').textContent, 'calendar_save_error');
assert.equal($('calendar-source-fields').disabled, false);
submit('calendar-form');
const persisted = {local_display_enabled: false, sources: payload.sources.map((item, index) => ({...item, id: item.id || 'google2', url: item.url.replace('webcal:', 'https:')}))};
reply(take('POST'), 200, persisted);
assert.equal($('calendar-source-summary').textContent, 'saved · 3 sources configured');
assert.equal($('calendar-source-settings').open, false);
assert.equal($('calendar-source-errors').textContent, '');
assert.equal(input(sourceRows('apple')[0], 'url').type, 'password');
assert.equal(display('apple1').checked, false, 'Unsaved display selection survives source save');
assert.equal($('calendar-display-status').textContent, 'calendar_display_pending');
assert.equal(display('google2').checked, true);
assert.equal($('calendar-status').textContent, 'calendar_saved');
input(sourceRows('apple')[0], 'url').value = 'https://private.example/unsaved.ics';
input(sourceRows('apple')[0], 'name').value = 'Unsaved source';
language = 'zh-TW';
context.window.CalendarSettings.applyLanguage();
assert.equal($('calendar-source-summary').textContent, 'saved · 已設定 3 個來源');
assert.equal(display('apple1').checked, false, 'Language changes preserve unsaved selection');
assert.equal(input(sourceRows('apple')[0], 'url').value, 'https://private.example/unsaved.ics');
assert.equal(input(sourceRows('apple')[0], 'name').value, 'Unsaved source');
buttons[2].trigger('click');
submit('calendar-form');
assert.equal($('calendar-status').textContent, 'calendar_required');
assert.equal(requests.length, 0);
button(sourceRows('ics')[0], 'calendar_remove_source').trigger('click');
providers.forEach(provider => sourceRows(provider).slice().forEach(row => button(row, 'calendar_remove_source').trigger('click')));
submit('calendar-form');
const clear = take('POST');
assert.deepEqual(JSON.parse(clear.body), {sources: [], local_display_enabled: false});
reply(clear, 200, {sources: [], local_display_enabled: false});
assert.equal(display('local').checked, false);
assert.equal($('calendar-source-summary').textContent, 'saved · 已設定 0 個來源');
for (let i = 0; i < 20; i++) buttons[0].trigger('click');
assert.ok(buttons.every(item => item.disabled));
buttons[0].trigger('click');
assert.equal(sourceRows('apple').length, 20);
console.log('Calendar sources: masking, load protection, multiple providers, independent visibility saves and retained drafts passed.');

async function calendarWindows() {
    const flush = () => new Promise(resolve => setImmediate(resolve));
    const plain = value => JSON.parse(JSON.stringify(value));
    const key = target => JSON.stringify([target.source_id, target.uid, target.scope, target.recurrence_id || '']);
    const occurrence = {source_id: 'cal', uid: 'weekly', scope: 'occurrence', recurrence_id: 'original-start', title: 'Weekly'};
    const series = {...occurrence, scope: 'series', recurrence_id: ''};
    const relative = {mode: 'relative', before_minutes: 60, end: 'event_end'};
    const sourceConfig = {id: 'cal', name: 'Calendar', provider: 'apple', url: 'https://private.example/calendar.ics', display_enabled: true};
    let config = {sources: [sourceConfig], local_display_enabled: false, calendar_targets: [{...occurrence, display_window: relative}]};
    sourceRows('apple').slice(1).forEach(row => button(row, 'calendar_remove_source').trigger('click'));
    input(sourceRows('apple')[0], 'name').value = sourceConfig.name;
    input(sourceRows('apple')[0], 'url').value = sourceConfig.url;
    submit('calendar-form');
    autoList = false;
    reply(take('POST'), 200, config);
    const item = (id, target, time, extra = {}) => ({id, source_name: 'Calendar', text: 'Weekly', starts_at: Date.parse(time),
        ends_at: Date.parse(time) + 3600000, all_day: false, recurring: true, selection_scope: 'source',
        target: {...target, display_window: config.calendar_targets.find(entry => key(entry) === key(target))?.display_window || {mode: 'day'}},
        series_target: {...series, display_window: config.calendar_targets.find(entry => key(entry) === key(series))?.display_window || {mode: 'day'}},
        window_start: 0, window_end: 0, visible: false, status: 'ready', ...extra});
    const items = () => [item('first', occurrence, '2030-01-02T03:00:00Z'),
        item('second', {...occurrence, recurrence_id: 'next-start'}, '2030-01-02T05:00:00Z')];
    const listReply = data => reply(take('GET', '/api/calendar/display-items'), 200, {items: data || items()});
    const card = id => $('calendar-current-list').children.find(entry => entry.getAttribute('data-calendar-item') === id);
    const field = (entry, name) => descendants(entry).find(child => child.getAttribute('data-calendar-window') === name);
    const form = entry => descendants(entry).find(child => child.tag === 'form');
    function change(entry, name, value) { const input = field(entry, name); input.value = value; input.trigger('change'); return input; }
    function saveReply(request) {
        const payload = JSON.parse(request.body);
        config = {...config, ...payload, sources: payload.sources ? config.sources.map(source => ({...source, ...payload.sources.find(entry => entry.id === source.id)})) : config.sources};
        reply(request, 200, plain(config));
    }
    function note(id, time) {
        const li = element('li'), input = element('input'); li.setAttribute('data-note-id', id); li.setAttribute('data-sort-time', time);
        input.value = 'Unsent manual note'; li.appendChild(input); $('calendar-current-list').appendChild(li); return {li, input};
    }
    const firstNote = note('dated', '2030-01-02 10:00'), laterNote = note('later', '2030-01-02 12:00'), undated = note('undated', '');
    firstNote.input.focus();
    listReply();
    assert.deepEqual($('calendar-current-list').children.map(entry => entry.getAttribute('data-note-id') || entry.getAttribute('data-calendar-item')),
        ['dated', 'first', 'later', 'second', 'undated'], 'Calendar occurrences use actual start and management timezone when merging manual notes');
    assert.equal(active, firstNote.input);
    assert.equal(firstNote.input.value, 'Unsent manual note');
    assert.equal(field(card('first'), 'calendar_window_mode').value, 'relative');
    assert.equal(field(card('first'), 'calendar_window_before').value, '1');
    assert.equal(field(card('first'), 'calendar_window_unit').value, '60');
    assert.equal(field(card('second'), 'calendar_window_mode').value, 'day', 'New event display defaults to its event day');
    assert.equal(field(card('second'), 'calendar_window_before').disabled, true, 'Inactive relative inputs do not participate in native validation');
    const firstCard = card('first');
    change(firstCard, 'calendar_window_mode', 'absolute');
    assert.equal(field(firstCard, 'calendar_window_before').disabled, true);
    assert.equal(field(firstCard, 'display_start').disabled, false);
    change(firstCard, 'display_start', '2030-01-01T10:00');
    const focused = change(firstCard, 'display_end', '2030-01-02T20:00'); focused.focus();
    $('calendar-list-refresh').trigger('click'); listReply();
    language = 'ja'; context.window.CalendarSettings.applyLanguage();
    assert.equal(card('first'), firstCard, 'List refresh reuses editor DOM');
    assert.equal(active, focused); assert.equal(focused.value, '2030-01-02T20:00');
    change(firstCard, 'calendar_window_scope', 'series');
    assert.equal(field(firstCard, 'calendar_window_mode').value, 'day', 'Changing scope does not carry an occurrence absolute window into the series');
    assert.equal(field(firstCard, 'calendar_window_mode').children.find(option => option.value === 'absolute').disabled, true);
    change(firstCard, 'calendar_window_mode', 'relative'); change(firstCard, 'calendar_window_before', '3'); change(firstCard, 'calendar_window_unit', '1440');
    input(sourceRows('apple')[0], 'url').value = 'https://private.example/unsaved-again.ics';
    display('local').checked = true; display('local').trigger('change');
    form(firstCard).trigger('submit');
    let patch = take('PATCH');
    const timing = JSON.parse(patch.body);
    assert.deepEqual(Object.keys(timing), ['calendar_targets'], 'Window save does not submit unsaved tree/local/source fields');
    assert.deepEqual(timing.calendar_targets.find(target => target.scope === 'series').display_window, {mode: 'relative', before_minutes: 4320, end: 'day_end'});
    reply(patch, 500, {error: 'save_failed'});
    assert.equal(field(firstCard, 'calendar_window_before').value, '3', 'A failed window save retains entered values');
    form(firstCard).trigger('submit'); saveReply(take('PATCH')); listReply();
    assert.equal(display('local').checked, true, 'Window save preserves pending local selection');
    assert.equal(input(sourceRows('apple')[0], 'url').value, 'https://private.example/unsaved-again.ics');
    change(firstCard, 'calendar_window_scope', 'occurrence');
    assert.equal(field(firstCard, 'calendar_window_mode').value, 'absolute');
    assert.equal(field(firstCard, 'display_start').value, '2030-01-01T10:00', 'Both scope drafts survive switching and successful saves');
    form(firstCard).trigger('submit'); patch = take('PATCH');
    assert.deepEqual(JSON.parse(patch.body).calendar_targets.find(target => target.scope === 'occurrence').display_window,
        {mode: 'absolute', start: '2030-01-01T10:00', end: '2030-01-02T20:00'});
    saveReply(patch); listReply();
    submit('calendar-display-form'); patch = take('PATCH');
    assert.equal(JSON.parse(patch.body).calendar_targets.length, 2, 'Pending selection save preserves windows saved through cards');
    saveReply(patch); listReply();

    const sourceInput = display('cal'), sourceTree = sourceInput.parentNode.parentNode.parentNode;
    sourceTree.open = true; sourceTree.trigger('toggle');
    const events = [
        {source_id: 'cal', uid: 'weekly', recurring: true, recurrence_id: 'original-start', text: 'Weekly', starts_at: '2030-01-02T03:00:00Z'},
        {source_id: 'cal', uid: 'weekly', recurring: true, recurrence_id: 'next-start', text: 'Weekly', starts_at: '2030-01-09T03:00:00Z'},
        {source_id: 'cal', uid: 'single', recurring: false, recurrence_id: '', text: 'Single', starts_at: '2030-01-03T03:00:00Z'}
    ];
    reply(take('GET', '/api/v1/calendar-events?source_id=cal'), 200, {events}); await flush();
    const choice = target => descendants($('calendar-display-list')).find(entry => entry.getAttribute('data-group-content') === 'calendar_targets:' + key(target));
    function click(input, checked, shift = false) { input.checked = checked; input.trigger('click', {shiftKey: shift}); input.trigger('change'); }
    click(sourceInput, false); click(sourceInput, true);
    submit('calendar-display-form'); patch = take('PATCH');
    assert.equal(JSON.parse(patch.body).calendar_targets.length, 2, 'Whole-source selection does not erase explicit window overrides');
    saveReply(patch); listReply();
    click(sourceInput, false);
    const seriesInput = choice(series); click(seriesInput, false); click(seriesInput, true);
    submit('calendar-display-form'); patch = take('PATCH');
    assert.equal(JSON.parse(patch.body).calendar_targets.find(target => target.scope === 'occurrence').display_window.mode, 'absolute', 'Whole-series selection keeps occurrence window overrides');
    saveReply(patch);
    const seriesItem = item('stable-series', series, '2030-01-02T03:00:00Z', {selection_scope: 'series'});
    listReply([seriesItem, items()[0]]);
    assert.equal(field(card('stable-series'), 'calendar_window_scope').value, 'series');
    assert.equal(field(card('stable-series'), 'calendar_window_scope').children.length, 1, 'Series summary card edits the series rule');
    change(card('stable-series'), 'calendar_window_mode', 'relative'); change(card('stable-series'), 'calendar_window_before', '9');
    const seriesCard = card('stable-series');
    $('calendar-list-refresh').trigger('click');
    listReply([{...seriesItem, starts_at: Date.parse('2030-01-09T03:00:00Z')}, items()[0]]);
    assert.equal(card('stable-series'), seriesCard); assert.equal(field(seriesCard, 'calendar_window_before').value, '9', 'Next occurrence changes keep the series editor draft');
    $('calendar-list-refresh').trigger('click'); reply(take('GET', '/api/calendar/display-items'), 503, {error: 'Calendar catalog unavailable'});
    assert.equal(card('stable-series'), seriesCard); assert.equal($('calendar-list-status').textContent, 'calendar_list_failed');
    $('calendar-list-refresh').trigger('click');
    const staleList = take('GET', '/api/calendar/display-items');
    form(seriesCard).trigger('submit'); saveReply(take('PATCH'));
    reply(staleList, 200, {items: []});
    assert.equal(card('stable-series'), seriesCard, 'A response started before a window mutation cannot replace current cards');
    listReply([{...seriesItem, status: 'missing', starts_at: null}, items()[0]]);
    assert.match(seriesCard.textContent, /group_calendar_unlisted/);
    // Source edits invalidate the chooser catalog but retain the source tree.
    submit('calendar-form'); patch = take('POST');
    config.sources[0].url = JSON.parse(patch.body).sources[0].url;
    reply(patch, 200, config); listReply();
    const reload = take('GET', '/api/v1/calendar-events?source_id=cal');
    reply(reload, 503, {error: 'unavailable'}); await flush();
    assert.equal(sourceTree.open, true);
    // Clear the explicit selections; the PATCH must send [] rather than omit.
    click(choice(series), false);
    const branch = choice(series).parentNode.parentNode.parentNode; branch.open = true; branch.trigger('toggle');
    click(choice(occurrence), false);
    submit('calendar-display-form'); patch = take('PATCH');
    assert.deepEqual(JSON.parse(patch.body).calendar_targets, []);
    saveReply(patch); listReply([]);
    assert.equal(firstNote.input.value, 'Unsent manual note');
    assert.equal(laterNote.li.parentNode, $('calendar-current-list')); assert.equal(undated.li.parentNode, $('calendar-current-list'));
    assert.equal(requests.length, 0);
    console.log('Calendar tree and windows: scoped drafts, source/series inheritance, relative/absolute saves, list ordering, stable focus, failures and stale responses passed.');
}
calendarWindows().catch(error => { console.error(error); process.exitCode = 1; });
