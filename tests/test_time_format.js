// Run with node tests/test_time_format.js.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/time-format.js'), 'utf8'), context);
const time = context.window.WebClockTime;
for (const [value, expected] of [['00:00', '12:00 AM'], ['12:00', '12:00 PM'], ['13:05', '01:05 PM'], ['23:59', '11:59 PM']]) {
    assert.equal(time.format(value, '12h', 'en'), expected);
    assert.equal(time.format(value, '24h', 'en'), value);
}
assert.equal(time.format('2026-10-03T13:05', '12h', 'zh-TW'), '2026-10-03 下午 01:05');
assert.equal(time.format('00:00:30', '12h', 'ja'), '午前 12:00:30');
assert.equal(time.format('2026-10-03', '12h', 'en'), '2026-10-03');
assert.equal(time.format('25:99', '12h', 'en'), '25:99');

function element(tag = 'input') {
    const node = {tag, children: [], attrs: {}, listeners: {}, type: '', value: '', required: false, disabled: false,
        setAttribute(key, value) { this.attrs[key] = value; }, getAttribute(key) { return this.attrs[key]; },
        appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
        insertBefore(child) { this.appendChild(child); },
        addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); },
        dispatchEvent(event) { (this.listeners[event.type] || []).forEach(fn => fn(event)); }
    };
    Object.defineProperty(node, 'options', {get() { return this.children; }});
    Object.defineProperty(node, 'validity', {get() {
        return {valid: this.disabled || (this.value === '' ? !this.required : this.type !== 'number' ||
            /^\d+$/.test(this.value) && Number(this.value) >= Number(this.min) && Number(this.value) <= Number(this.max))};
    }});
    return node;
}
const canonical = element();
canonical.id = 'alarm'; canonical.type = 'time'; canonical.value = '13:05'; canonical.required = true;
canonical.parentNode = element('div'); canonical.form = element('form');
const label = {textContent: '時間'};
context.document = {createElement: element, querySelector: () => label, createEvent: () => ({initEvent(type) { this.type = type; }})};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/time-inputs.js'), 'utf8'), context);
const refresh = (format = '12h') => context.window.WebClockTimeInputs.refresh({querySelectorAll: () => [canonical]}, format, 'zh-TW');
refresh();
const ui = canonical._clockTimeControl;
assert.equal(canonical.type, 'hidden');
assert.equal(ui.hour.placeholder, '12');
assert.equal(ui.hour.value, '01'); assert.equal(ui.period.value, 'pm');
ui.hour.value = '12'; ui.minute.value = '00'; ui.period.value = 'am'; ui.hour.dispatchEvent({type: 'input'});
assert.equal(canonical.value, '00:00');
ui.period.value = 'pm'; ui.period.dispatchEvent({type: 'change'});
assert.equal(canonical.value, '12:00');
refresh('24h');
assert.equal(ui.hour.value, '12'); assert.equal(ui.period.hidden, true);
assert.equal(ui.hour.placeholder, '00');
ui.hour.value = '23'; ui.hour.dispatchEvent({type: 'input'});
refresh();
assert.equal(ui.hour.value, '11'); assert.equal(ui.period.value, 'pm'); assert.equal(canonical.value, '23:00');
// Switching the preference preserves incomplete input and its actual hour.
ui.minute.value = ''; ui.minute.dispatchEvent({type: 'input'});
refresh('24h');
assert.equal(ui.hour.value, '23'); assert.equal(ui.minute.value, ''); assert.equal(canonical.value, '23:00');
// Native form reset must invalidate the cached proxy fields, even for the same saved time.
canonical.form.dispatchEvent({type: 'reset'});
ui.hour.value = ui.minute.value = '';
refresh('24h');
assert.equal(ui.hour.value, '23'); assert.equal(ui.minute.value, '00');
canonical.disabled = true; refresh();
assert.equal(ui.hour.disabled, true); assert.equal(ui.minute.disabled, true); assert.equal(ui.period.disabled, true);
canonical.disabled = false; canonical.required = false; canonical.value = ''; refresh();
assert.equal(ui.hour.value, ''); assert.equal(ui.hour.required, false);
canonical.type = 'datetime-local'; canonical.value = '2026-10-03T00:00'; refresh();
assert.equal(ui.date.value, '2026-10-03'); assert.equal(ui.date.hidden, false); assert.equal(ui.hour.value, '12');
assert.equal(canonical.value, '2026-10-03T00:00');
canonical.type = 'time'; canonical.value = ''; refresh();
assert.equal(ui.date.hidden, true); assert.equal(ui.date.disabled, true); assert.equal(canonical.value, '');
// Failed preference saves must restore the selection without reloading away drafts.
const admin = fs.readFileSync(path.join(__dirname, '../templates/admin.html'), 'utf8');
const select = {value: '12h', disabled: false};
let reloaded = false, alerted = false;
const settingsContext = {currentTimeFormat: '24h', document: {getElementById: () => select},
    fetch: async () => ({ok: false}), alert: () => { alerted = true; }, t: key => key,
    window: {location: {reload: () => { reloaded = true; }}},
    applyTimeFormat: () => { throw new Error('Failed save must not change active format'); }};
vm.createContext(settingsContext);
vm.runInContext(admin.slice(admin.indexOf('function setTimeFormat('), admin.indexOf("document.addEventListener('visibilitychange'")) +
    admin.slice(admin.indexOf('function postSettings('), admin.indexOf('function saveNight(')), settingsContext);
vm.runInContext("setTimeFormat('12h')", settingsContext).then(() => {
    assert.equal(select.value, '24h'); assert.equal(select.disabled, false);
    assert.equal(alerted, true); assert.equal(reloaded, false);
    console.log('Shared time formatting and inputs: midnight/noon, canonical values, retained drafts, reset, date/time modes and failed saves passed.');
}).catch(error => { console.error(error); process.exitCode = 1; });
