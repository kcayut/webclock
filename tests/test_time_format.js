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
// Conditional saves serialize this page's writes and retain drafts on conflicts.
const admin = fs.readFileSync(path.join(__dirname, '../templates/admin.html'), 'utf8');
async function checkSettings() {
    const fields = Object.fromEntries(['time-format-select', 'settings-reload', 'settings-status', 'time-format-status'].map(id => [id, {value:'12h', disabled:false, textContent:''}]));
    fields['csrf-token'] = {content:'settings-csrf-token'};
    let mode = 'failure', requests = [], reloaded = false;
    const context = {currentTimeFormat:'24h', settingsRevision:'first', settingsQueue:Promise.resolve(), settingsConflict:false,
        settingsPending:0, settingsMessage:'', settingsEdits:0, document:{getElementById:id=>fields[id]},
        fetch:async(url, options)=>{ requests.push({url,options}); return {ok:mode==='ok',status:mode==='conflict'?409:500,
            json:async()=>({revision:'version-'+requests.length})}; }, t:key=>key,
        window:{location:{reload:()=>{reloaded=true;}}}};
    context.applyTimeFormat = format => {context.currentTimeFormat = format;fields['time-format-select'].value=format;};
    vm.createContext(context);
    const begin = admin.indexOf('function setTimeFormat(');
    vm.runInContext(admin.slice(begin, admin.indexOf('        applyTimeFormat(currentTimeFormat);', begin)) +
        admin.slice(admin.indexOf('function postSettings('), admin.indexOf('function saveNight(')), context);
    await context.setTimeFormat('12h');
    assert.equal(fields['time-format-select'].value,'12h');
    assert.equal(fields['time-format-select'].disabled,false);
    assert.equal(fields['settings-status'].textContent,'settings_save_error');
    assert.equal(requests[0].options.headers['If-Match'],'"first"');
    assert.equal(requests[0].options.headers['X-CSRF-Token'],'settings-csrf-token');
    assert.equal(reloaded,false);
    mode='ok';
    await Promise.all([context.postSettings({brightness:0}),context.postSettings({timezone_offset:9})]);
    assert.equal(requests[2].options.headers['If-Match'],'"version-2"');
    assert.equal(context.settingsRevision,'version-3');
    mode='conflict';
    await context.postSettings({brightness:30});
    await context.postSettings({brightness:40});
    assert.equal(requests.length,4,'conflict must stop subsequent queued writes');
    assert.equal(fields['settings-status'].textContent,'settings_conflict');
    assert.equal(reloaded,false);
    const latest = {brightness:60,timezone_offset:8,language:'zh-TW',mode:'normal',time_format:'24h',
        night:{enabled:true,black:false,start:'22:00',end:'07:00',brightness:10}};
    for (const id of ['mode-normal','mode-black','brightness-control','bright-val','timezone-select','display-language-select',
        'night-enabled','night-black','night-start','night-end','night-brightness','night-value','night-status']) {
        fields[id] = {value:'draft',textContent:'',checked:false,active:false,
            classList:{toggle(name,value){fields[id].active=value;}},setAttribute(){}};
    }
    const pending = [];
    context.fetch = (url, options) => new Promise(resolve => pending.push({url,options,resolve}));
    context.window.confirm = () => true;
    context.settingsConflict = false;
    vm.runInContext(admin.slice(admin.indexOf('function setMode('), admin.indexOf('function setBrightness(')), context);
    const loading = context.reloadSettings();
    context.setMode('black'); // Buttons do not produce the input/change events watched by the display form.
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(pending.length,2);
    pending[0].resolve({ok:true,json:async()=>({settings:latest,revision:'old-reload'})});
    await loading;
    assert.equal(fields['mode-black'].active,true,'An older reload cannot replace a click made while it was pending');
    assert.equal(context.settingsRevision,'version-3');
    assert.equal(fields['settings-reload'].disabled,true,'The reload button remains disabled while a later write is pending');
    pending[1].resolve({ok:true,json:async()=>({revision:'mode-saved'})});
    await context.settingsQueue;
    assert.equal(context.settingsRevision,'mode-saved');
    assert.equal(fields['mode-black'].active,true);
    assert.equal(fields['settings-reload'].disabled,false);
    context.fetch = async()=>({ok:false});
    await context.reloadSettings();
    assert.equal(context.settingsRevision,'mode-saved');
    assert.equal(fields['night-start'].value,'draft','Failed reload keeps unsaved fields');
    assert.equal(fields['mode-black'].active,true);
    assert.equal(fields['settings-status'].textContent,'settings_load_error');
    context.fetch = async()=>({ok:true,json:async()=>({settings:latest,revision:'latest'})});
    await context.reloadSettings();
    assert.equal(context.settingsRevision,'latest');
    assert.equal(fields['night-start'].value,'22:00');
    assert.equal(fields['mode-normal'].active,true);
    assert.equal(fields['mode-black'].active,false);
    console.log('Shared time formatting, retained settings drafts, conditional saves and serialized writes passed.');
}
checkSettings().catch(error=>{console.error(error);process.exitCode=1;});
