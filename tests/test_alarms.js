// Run with: node tests/test_alarms.js (no browser or test framework required).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const script = fs.readFileSync(path.join(root, 'static/alarms.js'), 'utf8');
const audioScript = fs.readFileSync(path.join(root, 'static/alarm-audio.js'), 'utf8');
for (const code of [script, audioScript]) {
    assert.doesNotMatch(code, /\b(?:const|let|async)\b|=>|\?\./, 'clock extras must remain ES5');
}
assert.ok(!fs.readFileSync(path.join(root, 'index.html'), 'utf8').includes('alarms.js'));

function browser(storage = {}, usePerformance = false) {
    let instant = Date.parse('2026-09-30T00:00:00Z');
    let elapsed = 0;
    const nodes = {}, handlers = {}, requests = [], timers = [];
    const node = id => nodes[id] || (nodes[id] = {
        textContent: '', style: {}, attrs: {}, checked: true,
        classList: {items: new Set(), add(x) { this.items.add(x); }, remove(x) { this.items.delete(x); },
            toggle(x, on) { on ? this.add(x) : this.remove(x); }},
        setAttribute(key, value) { this.attrs[key] = value; },
    });
    const addEventListener = (name, handler) => (handlers[name] || (handlers[name] = [])).push(handler);
    const sound = {ready: false, played: [], volumes: [], stopped: 0, unlocked: 0,
        isReady() { return this.ready; }, unlock() { this.ready = true; ++this.unlocked; },
        play(value, volume) { if (this.ready) { this.played.push(value); this.volumes.push(volume); } return this.ready; }, stop() { ++this.stopped; }};
    const window = {serverUrl: 'http://clock.example', location: {origin: 'http://clock.example'},
        AlarmAudio: sound, addEventListener};
    if (usePerformance) window.performance = {now: () => elapsed};
    const context = vm.createContext({window,
        document: {getElementById: node, body: node('body'), addEventListener, hidden: false},
        Date: function () { this.getTime = () => instant; },
        t: key => key,
        readStoredJson: (key, fallback) => storage[key] ? JSON.parse(storage[key]) : fallback,
        writeStoredJson: (key, value) => { storage[key] = JSON.stringify(value); },
        readStoredValue: (key, fallback) => storage[key] || fallback,
        writeStoredValue: (key, value) => { storage[key] = value; },
        setInterval: (callback, delay) => timers.push({callback, delay}),
        XMLHttpRequest: function () {
            this.open = (method, url) => { this.url = url; };
            this.send = () => requests.push(this);
        },
        Intl: undefined, Promise: undefined, fetch: undefined,
    });
    vm.runInContext('Number.isFinite = undefined;', context);
    vm.runInContext(script, context);
    const tick = () => timers.find(timer => timer.delay === 1000).callback();
    const poll = () => timers.find(timer => timer.delay === 15000).callback();
    function dispatch(type) {
        const event = {type, preventDefault() { this.prevented = true; }, stopPropagation() {}, stopImmediatePropagation() {}};
        (handlers[type] || []).forEach(handler => handler(event));
        if (type === 'click' && !event.prevented) node('alarm-bell').onclick();
    }
    function reply(alarms, request = requests[requests.length - 1], enabledIds = alarms.map(item => item.id), serverTimestamp = instant) {
        request.status = 200;
        request.responseText = JSON.stringify({alarms, enabled_count: enabledIds.length, enabled_ids: enabledIds,
            server_timestamp: serverTimestamp, holiday_known: true});
        request.onload();
    }
    return {node, window, sound, requests, tick, poll, dispatch, reply,
        advance(ms) { instant += ms; elapsed += ms; }, adjustClock(ms) { instant += ms; }, now: () => instant,
        ringing: () => node('body').classList.items.has('alarm-ringing')};
}
const alarm = (browser, name = 'Morning', sound = 'bell', offset = 1000) => ({
    id: name, occurrence_id: name + '@' + (browser.now() + offset), name, sound, starts_at: browser.now() + offset,
});

const saved = {};
const page = browser(saved);
const due = alarm(page);
page.reply([due]);
assert.equal(page.node('alarm-bell').style.display, 'block');
assert.equal(page.node('alarm-status').textContent, 'alarm_enable_sound');
page.node('alarm-bell').onclick();
page.advance(1000); page.tick();
assert.ok(page.ringing());
assert.deepEqual(page.sound.played, ['bell']);
assert.deepEqual(page.sound.volumes, [100], 'old API responses default to maximum volume');
page.dispatch('touchend');
assert.equal(page.node('alarm-prompt').textContent, 'alarm_second_tap');
page.dispatch('click');
assert.ok(page.ringing(), 'one touch plus its generated click must not dismiss');
page.advance(150); page.dispatch('touchend');
assert.ok(!page.ringing());
page.dispatch('click');
assert.equal(page.sound.unlocked, 1, 'generated click after dismissal must not unlock/replay sound');
page.poll(); page.reply([due]); page.tick();
assert.ok(!page.ringing(), 'same occurrence must stay dismissed');
const reloaded = browser(saved);
reloaded.advance(1500); reloaded.reply([due]); reloaded.tick();
assert.ok(!reloaded.ringing(), 'dismissal survives a reload in the same minute');
reloaded.reply([alarm(reloaded, 'Morning', 'digital')]);
reloaded.advance(1000); reloaded.tick();
assert.ok(reloaded.ringing(), 'next occurrence still rings without unlocking audio');
assert.equal(reloaded.sound.played.length, 0, 'locked audio still has the visual alarm');
reloaded.dispatch('click'); reloaded.dispatch('click');
assert.ok(!reloaded.ringing());

const simultaneous = browser();
simultaneous.reply([alarm(simultaneous, 'A', 'silent'), alarm(simultaneous, 'B', 'beep')]);
simultaneous.node('alarm-bell').onclick();
simultaneous.advance(1000); simultaneous.tick();
assert.ok(simultaneous.node('alarm-name').textContent.includes('(+1)'));
assert.deepEqual(simultaneous.sound.played, ['beep']);
simultaneous.reply([], undefined, ['A', 'B']);
assert.ok(simultaneous.ringing(), 'a one-time alarm continues after its occurrence leaves the next-event list');
simultaneous.reply([], undefined, ['A']);
assert.ok(simultaneous.ringing(), 'disabling one simultaneous alarm preserves the other');
assert.equal(simultaneous.node('alarm-name').textContent, 'alarm_ringing · A');
simultaneous.dispatch('click'); simultaneous.dispatch('click');
assert.ok(!simultaneous.ringing());
const silent = browser();
silent.reply([alarm(silent, 'Quiet', 'silent')]); silent.advance(1000); silent.tick();
assert.ok(silent.ringing()); assert.deepEqual(silent.sound.played, []);
silent.node('alarm-motion').checked = false; silent.node('alarm-motion').onchange();
assert.ok(silent.node('body').classList.items.has('alarm-steady'));
silent.reply([]);
assert.ok(!silent.ringing(), 'management disable/delete stops the active alarm');

const volumes = browser();
volumes.reply([{...alarm(volumes, 'Muted'), volume: 0}, {...alarm(volumes, 'Soft', 'chime'), volume: 25}]);
volumes.node('alarm-bell').onclick();
volumes.advance(1000); volumes.tick();
assert.ok(volumes.ringing());
assert.deepEqual(volumes.sound.played, ['chime'], 'a muted alarm must not block a simultaneous audible alarm');
assert.deepEqual(volumes.sound.volumes, [25]);
const muted = browser();
muted.reply([{...alarm(muted), volume: 0}]);
assert.equal(muted.node('alarm-status').textContent, '');
muted.advance(1000); muted.tick();
assert.ok(muted.ringing(), 'zero volume keeps the visual reminder');
assert.deepEqual(muted.sound.played, []);
for (const volume of [-1, 101, 2.5, null, '25']) {
    const invalid = browser();
    invalid.reply([{...alarm(invalid), volume}]);
    assert.equal(invalid.node('alarm-status').textContent, 'alarm_sync_error');
}

const late = browser();
late.reply([alarm(late)]); late.advance(61000); late.tick();
assert.ok(!late.ringing(), 'suspended pages must not replay stale alarms');
const offline = browser();
offline.reply([alarm(offline)]); offline.poll(); offline.requests.at(-1).onerror();
offline.advance(1000); offline.tick();
assert.ok(offline.ringing(), 'already loaded next occurrence survives a temporary network failure');
offline.window.serverUrl = 'http://other.example'; offline.tick();
assert.ok(!offline.ringing(), 'switching servers drops the previous server alarm');
const stale = browser();
const oldRequest = stale.requests[0];
stale.poll(); stale.reply([]); stale.reply([alarm(stale)], oldRequest);
stale.advance(2000); stale.tick();
assert.ok(!stale.ringing(), 'old responses cannot restore a deleted alarm');

const monotonic = browser({}, true);
const serverStart = monotonic.now();
const monotonicDue = alarm(monotonic);
monotonic.reply([monotonicDue]); monotonic.node('alarm-bell').onclick();
monotonic.adjustClock(-120000);
monotonic.advance(1000); monotonic.tick();
assert.ok(monotonic.ringing(), 'device clock corrections must not delay the server alarm');
assert.deepEqual(monotonic.sound.played, ['bell']);
monotonic.poll(); monotonic.reply([monotonicDue], undefined, [monotonicDue.id], serverStart + 1000);
monotonic.advance(2000); monotonic.tick();
assert.deepEqual(monotonic.sound.played, ['bell', 'bell'], 'sound repeats after a backward clock correction and server resync');
monotonic.dispatch('touchend'); monotonic.adjustClock(600000); monotonic.dispatch('click');
assert.ok(monotonic.ringing(), 'clock corrections must not turn a generated click into a second tap');
monotonic.advance(150); monotonic.dispatch('touchend'); monotonic.dispatch('click');
assert.ok(!monotonic.ringing());
assert.equal(monotonic.sound.unlocked, 1);

let created = 0, starts = 0, stops = 0, context;
const peaks = [], frequencies = [], waves = [];
function LegacyAudioContext() {
    ++created; context = this; this.currentTime = 0; this.destination = {};
    this.createOscillator = () => ({frequency: {}, connect() {}, disconnect() {},
        start() { ++starts; frequencies.push(this.frequency.value); waves.push(this.type); }, stop() { ++stops; }});
    this.createGain = () => ({gain: {setValueAtTime() {}, linearRampToValueAtTime(value) { if (value) peaks.push(value); }}, connect() {}, disconnect() {}});
}
const legacyWindow = {webkitAudioContext: LegacyAudioContext};
vm.runInNewContext(audioScript, {window: legacyWindow});
assert.equal(legacyWindow.AlarmAudio.play('bell'), false);
assert.equal(legacyWindow.AlarmAudio.unlock('bell'), true);
assert.equal(starts, 2);
assert.equal(legacyWindow.AlarmAudio.isReady(), true, 'old contexts without state/resume work');
assert.equal(legacyWindow.AlarmAudio.play('digital'), true);
assert.equal(starts, 5); assert.equal(created, 1);
context.state = 'interrupted';
assert.equal(legacyWindow.AlarmAudio.isReady(), false);
assert.equal(legacyWindow.AlarmAudio.play('beep'), false);
context.resume = () => { context.state = 'running'; };
assert.equal(legacyWindow.AlarmAudio.unlock('beep'), true);
assert.equal(starts, 6); assert.equal(created, 1);
legacyWindow.AlarmAudio.stop(); assert.ok(stops >= starts);
peaks.length = 0;
legacyWindow.AlarmAudio.play('bell', 25);
assert.deepEqual(peaks, [0.035, 0.035], 'ringing uses a quarter of full gain at 25%');
peaks.length = 0;
legacyWindow.AlarmAudio.unlock('bell', 25);
assert.deepEqual(peaks, [0.035, 0.035], 'preview and actual ringing use the same volume');
const beforeMute = starts;
legacyWindow.AlarmAudio.play('bell', 0);
assert.equal(starts, beforeMute, 'muting must not create oscillators');
const signatures = new Set();
for (const sound of ['bell', 'beep', 'digital', 'chime', 'melody', 'pulse', 'sonar']) {
    frequencies.length = waves.length = 0;
    assert.equal(legacyWindow.AlarmAudio.play(sound, 100), true);
    assert.ok(frequencies.length);
    signatures.add(JSON.stringify([frequencies, waves]));
}
assert.equal(signatures.size, 7, 'each audible style has a distinct pattern');
const unsupported = {};
vm.runInNewContext(audioScript, {window: unsupported});
assert.equal(unsupported.AlarmAudio.unlock('bell'), false);
console.log('Alarm checks passed: ES5/webkit audio, unlock, scheduling, holidays via server, touch deduplication, dismissal, stale/offline data and motion control.');
