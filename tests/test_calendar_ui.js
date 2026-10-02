// Run with node tests/test_calendar_ui.js.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const admin = fs.readFileSync(path.join(__dirname, '../templates/admin.html'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, '../static/calendar-settings.js'), 'utf8');
assert.ok(admin.indexOf('class="note-list cards"') < admin.indexOf('id="calendar-source-settings"'));
assert.match(admin, /<details id="calendar-source-settings" class="panel calendar-source-settings">/);
assert.doesNotMatch(source, /localStorage|sessionStorage/);
const created = [];
function element(tag = 'div') {
    let ownText = '';
    const item = {tag, id: '', children: [], attrs: {}, listeners: {}, disabled: false, hidden: false,
        value: '', checked: false, type: '', className: '', parentNode: null,
        setAttribute(key, value) { this.attrs[key] = String(value); },
        getAttribute(key) { return this.attrs[key]; },
        removeAttribute(key) { delete this.attrs[key]; },
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
        removeChild(child) { this.children.splice(this.children.indexOf(child), 1); child.parentNode = null; },
        addEventListener(name, listener) { this.listeners[name] = listener; },
        trigger(name) { assert.ok(this.listeners[name], name + ' listener'); return this.listeners[name].call(this, {preventDefault() {}}); },
        focus() { this.focused = true; }
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
const requests = [];
let language = 'en';
const context = vm.createContext({
    document: {getElementById: $, createElement: element, querySelectorAll(selector) {
        assert.equal(selector, '[data-calendar-add]'); return buttons;
    }},
    window: {t(key) { return key === 'calendar_source_count' ? (language === 'en' ? '{count} sources configured' : '已設定 {count} 個來源') : key; }},
    XMLHttpRequest: class {
        open(method, url) { this.method = method; assert.equal(url, '/api/calendar'); }
        constructor() { this.headers = {}; }
        setRequestHeader(name, value) { this.headers[name] = value; }
        send(body) { this.body = body; requests.push(this); }
    }
});
vm.runInContext(source, context);
function take(method) {
    assert.ok(requests.length, 'Expected ' + method);
    const request = requests.shift(); assert.equal(request.method, method);
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
function display(id) { return descendants($('calendar-display-list')).find(item => item.getAttribute('data-calendar-source') === id); }
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
assert.deepEqual(JSON.parse(firstPatch.body), {local_display_enabled: false, sources: [
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
