// Run with: node tests/test_clock.js (Node.js standard library only).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const nodes = {time: {}, 'date-part': {}, 'day-part': {}};
const timers = [];
const listeners = {};
let now = Date.parse('2026-09-14T00:05:00Z');
class DeviceDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
}
const context = vm.createContext({
    Date: DeviceDate,
    document: {
        getElementById: id => nodes[id],
        addEventListener: (event, callback) => { listeners[event] = callback; },
    },
    window: {addEventListener: (event, callback) => { listeners[event] = callback; }},
    setInterval: (callback, delay) => timers.push({callback, delay}),
    // Any accidental server, external time or stored-settings dependency must fail.
    XMLHttpRequest: () => assert.fail('public clock must not use a server'),
    fetch: () => assert.fail('public clock must not fetch data'),
    Intl: undefined,
    Promise: undefined,
});
vm.runInContext('Number.isFinite = undefined;', context);
vm.runInContext(fs.readFileSync(path.join(root, 'static/time-format.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'static/clock.js'), 'utf8'), context);
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
for (const [, script] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
    vm.runInContext(script, context);
}
assert.equal(timers.length, 1);
assert.equal(timers[0].delay, 1000);

for (const [zone, instant, time, date, day] of [
    ['Asia/Taipei', '2026-09-14T00:05:00Z', '08:05', '9/14', '星期一'],
    ['America/Los_Angeles', '2026-09-14T00:05:00Z', '17:05', '9/13', '星期日'],
    ['Asia/Kathmandu', '2026-09-14T00:05:00Z', '05:50', '9/14', '星期一'],
    ['America/New_York', '2026-03-08T06:59:00Z', '01:59', '3/8', '星期日'],
    ['America/New_York', '2026-03-08T07:00:00Z', '03:00', '3/8', '星期日'],
    ['UTC', '2026-12-31T23:59:00Z', '23:59', '12/31', '星期四'],
    ['UTC', '2027-01-01T00:00:00Z', '00:00', '1/1', '星期五'],
]) {
    process.env.TZ = zone;
    now = Date.parse(instant);
    timers[0].callback();
    assert.deepEqual(Object.values(nodes).map(node => node.textContent), [time, date, day]);
}
now = Date.parse('2027-01-01T12:34:00Z');
listeners.visibilitychange();
assert.equal(nodes.time.textContent, '12:34');
now += 60000;
listeners.pageshow();
assert.equal(nodes.time.textContent, '12:35');

// The server's explicit timezone and language must override the device timezone.
context.renderClock(Date.parse('2026-09-14T20:00:00Z'), 8,
    ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']);
assert.deepEqual(Object.values(nodes).map(node => node.textContent), ['04:00', '9/15', 'Tue']);
nodes['time-period'] = {style: {}};
for (const [instant, language, time, period] of [
    ['2026-10-01T00:05:00Z', 'zh-TW', '12:05', '上午'],
    ['2026-10-01T12:05:00Z', 'zh-TW', '12:05', '下午'],
    ['2026-10-01T23:59:00Z', 'en', '11:59', 'PM'],
    ['2026-10-01T01:05:00Z', 'ja', '01:05', '午前'],
]) {
    context.renderClock(Date.parse(instant), 0, ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], '12h', language);
    assert.equal(nodes.time.textContent, time);
    assert.equal(nodes['time-period'].textContent, period);
    assert.equal(nodes['time-period'].style.display, 'block');
}
context.renderClock(Date.parse('2026-10-01T23:59:00Z'), 0, ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']);
assert.equal(nodes.time.textContent, '23:59');
assert.equal(nodes['time-period'].style.display, 'none');
console.log('Clock checks passed: device timezone, DST, date rollover, resume, server override, no network.');

// Night mode follows configured wall time; it restores the user's daytime value.
const settings = {mode: 'normal', brightness: 80, night: {enabled: true, start: '22:00', end: '07:00', brightness: 12, black: false}};
for (const [instant, brightness] of [
    ['2026-09-17T13:59:59Z', 80], ['2026-09-17T14:00:00Z', 12],
    ['2026-09-17T22:59:59Z', 12], ['2026-09-17T23:00:00Z', 80],
]) assert.equal(context.clockDisplaySettings(settings, Date.parse(instant), 8).brightness, brightness);
settings.night.black = true;
assert.equal(context.clockDisplaySettings(settings, Date.parse('2026-09-17T14:00:00Z'), 8).mode, 'black');
settings.mode = 'black';
assert.equal(context.clockDisplaySettings(settings, Date.parse('2026-09-17T23:00:00Z'), 8).mode, 'black');
settings.mode = 'normal';
settings.night.start = '10:00'; settings.night.end = '12:00';
assert.equal(context.clockDisplaySettings(settings, Date.parse('2026-09-17T03:00:00Z'), 8).brightness, 12);
assert.equal(context.clockDisplaySettings(settings, Date.parse('2026-09-17T04:00:00Z'), 8).brightness, 80);
console.log('Night schedule boundaries, manual override and daytime restoration checks passed.');

// Run the self-hosted page with the APIs available to an old, offline browser.
const template = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const serverScript = template.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace('{{ translations | tojson }}', JSON.stringify({'zh-TW': {
        weekdays: ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
        server_unavailable: 'Server unavailable', server_timeout: 'Server timed out',
        status_parse_failed: 'Unreadable response', page_error: 'Page error',
    }}))
    .replace('{{ language | tojson }}', '"zh-TW"');
function checkLegacyPage(failOptionalEditor) {
    const elements = {};
    const ticks = [];
    const requests = [];
    const storage = {};
    let storageAvailable = false;
    function makeNode() {
        const classes = new Set();
        return {
            style: {}, children: [],
            classList: {
                add: name => classes.add(name), remove: name => classes.delete(name),
                toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
                contains: name => classes.has(name),
            },
            appendChild(child) { this.children.push(child); },
            removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
            querySelectorAll(selector) { return this.children.filter(child => selector === '.event-row' && child.className === 'event-row'); },
            querySelector: () => null,
            setAttribute() {}, getAttribute: () => '',
        };
    }
    const node = id => elements[id] || (elements[id] = makeNode());
    const legacy = vm.createContext({
        Date: DeviceDate, Intl: undefined, Promise: undefined, fetch: undefined,
        navigator: {},
        document: {
            body: node('body'), documentElement: {},
            getElementById(id) {
                assert.notEqual(id, 'next-event', 'clock must not render a countdown outside reminder display windows');
                if (failOptionalEditor && id === 'local-events-list') throw new Error('optional editor failed');
                return node(id);
            },
            createElement: makeNode,
            addEventListener() {}, querySelectorAll: () => [], querySelector: () => null,
        },
        window: {
            location: {origin: 'http://clock.example'}, addEventListener() {},
            localStorage: {
                getItem(key) { if (!storageAvailable) throw new Error('storage unavailable'); return storage[key] || null; },
                setItem(key, value) { storage[key] = value; },
            },
        },
        setInterval: (callback, delay) => ticks.push({callback, delay}),
        setTimeout() {}, clearTimeout() {},
        XMLHttpRequest: function () {
            this.open = (method, url) => {
                assert.match(node('time').textContent, /^\d\d:\d\d$/);
                assert.equal(method, 'GET');
                assert.match(url, /^http:\/\/clock\.example\/api\/status\?nocache=\d+$/);
                requests.push(this);
            };
            this.send = () => {}; // A stalled request must never hold up the clock.
        },
    });
    vm.runInContext('Number.isFinite = undefined;', legacy);
    vm.runInContext(fs.readFileSync(path.join(root, 'static/time-format.js'), 'utf8'), legacy);
    vm.runInContext(fs.readFileSync(path.join(root, 'static/clock.js'), 'utf8'), legacy);
    if (failOptionalEditor) assert.throws(() => vm.runInContext(serverScript, legacy), /optional editor failed/);
    else vm.runInContext(serverScript, legacy);
    const tick = ticks.find(timer => timer.delay === 1000);
    assert.ok(tick, 'clock timer starts before optional initialization');
    const before = node('time').textContent;
    now += 60000;
    tick.callback();
    assert.notEqual(node('time').textContent, before);
    if (!failOptionalEditor) {
        assert.deepEqual(ticks.map(timer => timer.delay), [1000, 5000], 'clock only polls its own status server');
        assert.equal(requests.length, 1, 'startup makes one status request and no external time request');
        function reply(xhr, data, status = 200) {
            Object.assign(xhr, {readyState: 4, status, responseText: typeof data === 'string' ? data : JSON.stringify(data)});
            xhr.onreadystatechange();
        }
        function newRequest() {
            legacy.fetchStatus();
            return requests[requests.length - 1];
        }
        let serverNow = Date.parse('2026-10-01T00:00:00Z');
        now = serverNow + 2 * 3600000; // The device clock is deliberately two hours fast.
        reply(requests[0], {events: [], server_timestamp: serverNow});
        assert.equal(legacy.getClockUtcMs(), serverNow);
        assert.equal(node('time').textContent, '08:00');
        now += 30000;
        serverNow += 120000;
        reply(newRequest(), {events: [], server_timestamp: serverNow});
        assert.equal(legacy.getClockUtcMs(), serverNow, 'every status reply replaces the previous time base');
        assert.equal(node('time').textContent, '08:02');
        for (const [fail, message] of [
            [xhr => reply(xhr, '', 503), 'Server unavailable'],
            [xhr => xhr.onerror(), 'Server unavailable'],
            [xhr => xhr.ontimeout(), 'Server timed out'],
            [xhr => reply(xhr, '{broken'), 'Unreadable response'],
        ]) {
            fail(newRequest());
            assert.equal(node('notice').style.display, 'block');
            assert.equal(node('notice-text').textContent, message);
            const offlineTime = legacy.getClockUtcMs();
            now += 60000;
            tick.callback();
            assert.equal(legacy.getClockUtcMs(), offlineTime + 60000, 'the corrected clock advances while disconnected');
            legacy.hideNotice(true);
            assert.equal(node('notice').style.display, 'none');
            serverNow += 60000;
            reply(newRequest(), {events: [], server_timestamp: serverNow});
            assert.equal(node('notice').style.display, 'none', 'recovery clears the connection warning');
            assert.equal(legacy.lastNoticeKey, '');
            assert.equal(legacy.noticeMutedUntil, 0);
            fail(newRequest());
            assert.equal(node('notice').style.display, 'block', 'a new failure after recovery is not muted');
            assert.equal(node('notice-text').textContent, message);
            reply(newRequest(), {events: [], server_timestamp: serverNow});
            assert.equal(node('notice').style.display, 'none', 'recovery also clears a visible connection warning');
        }
        legacy.window.onerror();
        assert.equal(node('notice-text').textContent, 'Page error');
        reply(newRequest(), {events: [], server_timestamp: serverNow});
        assert.equal(node('notice').style.display, 'block', 'status recovery preserves unrelated page errors');
        assert.equal(node('notice-text').textContent, 'Page error');
        for (const invalid of [NaN, Infinity, -Infinity, '123', null, undefined, 0, -1]) {
            legacy.enterServerMode({events: [], server_timestamp: invalid});
            assert.equal(legacy.getClockUtcMs(), serverNow, 'invalid timestamps must not replace the corrected time base');
        }
        legacy.enterServerMode({events: [], settings: {brightness: 35},
            next_event: {text: 'Meeting', starts_at: now + 300000}});
        assert.equal(node('clock-container').style.opacity, 0.35);
        assert.equal(node('list-container').style.opacity, 0.35);
        assert.equal(node('list-container').style.display, 'none');
        assert.equal(node('body').classList.contains('has-events'), false);
        assert.equal(elements['next-event'], undefined);
        legacy.enterServerMode({events: [{text: 'Visible reminder', time: '08:10'}]});
        assert.equal(node('list-container').style.display, 'block');
        assert.equal(node('body').classList.contains('has-events'), true);
        assert.equal(node('event-counter').textContent, '1 / 1');
        assert.deepEqual(node('list-container').children[0].children[0].children.map(child => child.textContent),
            ['08:10', 'Visible reminder']);
        legacy.enterServerMode({events: [{text: 'Visible reminder', time: '08:10'}],
            settings: {time_format: '12h', language: 'zh-TW', timezone_offset: 8},
            server_timestamp: Date.parse('2026-10-01T04:00:00Z')});
        assert.equal(node('time').textContent, '12:00');
        assert.equal(node('time-period').textContent, '下午');
        assert.equal(node('body').classList.contains('uses-12-hour'), true);
        assert.equal(node('list-container').children[0].children[0].children[0].textContent, '上午 08:10',
            'unchanged events redraw when the display format changes');
        assert.equal(JSON.parse(storage['webclock.settings']).time_format, '12h');
        storageAvailable = true;
        legacy.saveLocalEvents([{id: 1, text: 'Offline reminder', time: '13:10'}]);
        legacy.enterStandaloneMode();
        assert.equal(node('time-period').textContent, '下午', 'offline mode keeps the saved display format');
        assert.equal(node('local-events-list').children[0].children[0].textContent, '下午 01:10 Offline reminder');
        assert.equal(node('list-container').children[0].children[0].children[0].textContent, '下午 01:10');
        assert.equal(JSON.parse(storage['webclock.localEvents'])[0].time, '13:10', 'formatting never changes stored reminder time');
        legacy.saveLocalEvents([]);
        const reminderForm = node('local-event-form');
        const reminderText = node('local-event-text');
        const reminderTime = node('local-event-time');
        let validTime = false, focusedInvalid = 0, reportedInvalid = 0;
        reminderForm.checkValidity = () => validTime;
        reminderForm.querySelector = selector => {
            assert.equal(selector, ':invalid');
            return {focus() { focusedInvalid += 1; }};
        };
        reminderText.value = 'Keep this draft';
        reminderTime.value = '13:10'; // A partial proxy edit retains the last valid canonical time.
        legacy.addLocalEvent();
        assert.equal(focusedInvalid, 1, 'old browsers focus the invalid field without reportValidity');
        reminderForm.reportValidity = () => { reportedInvalid += 1; };
        legacy.addLocalEvent();
        assert.equal(reportedInvalid, 1);
        assert.equal(JSON.parse(storage['webclock.localEvents']).length, 0, 'incomplete time must not save the previous valid time');
        assert.equal(reminderText.value, 'Keep this draft');
        assert.equal(reminderTime.value, '13:10');
        validTime = true;
        reminderTime.value = '14:25';
        legacy.addLocalEvent();
        assert.equal(JSON.parse(storage['webclock.localEvents'])[0].time, '14:25');
        assert.equal(reminderText.value, '');
        assert.equal(reminderTime.value, '');
        legacy.saveLocalEvents([]);
        tick.callback();
        assert.equal(node('list-container').style.display, 'none');
        assert.equal(node('body').classList.contains('has-events'), false);
        assert.equal(node('list-container').children.length, 0);
        assert.equal(elements['next-event'], undefined);
    }
    vm.runInContext(fs.readFileSync(path.join(root, 'static/offline.js'), 'utf8'), legacy);
    assert.match(node('time').textContent, /^\d\d:\d\d$/);
}
checkLegacyPage(false);
checkLegacyPage(true);
for (const page of [html, template]) {
    assert.doesNotMatch(page, /id="next-event"/);
    assert.ok(page.indexOf('offline.js') > page.indexOf('setInterval(update'), 'optional offline script loads after clock startup');
}
assert.match(template, /<form id="local-event-form"[^>]*onsubmit="addLocalEvent\(\); return false;">[\s\S]*?<button type="submit">Add<\/button>[\s\S]*?<\/form>/,
    'the real Add action uses native form validation for the time input proxies');
console.log('Legacy startup checks passed: no modern APIs/storage/network response, optional UI failure, brightness and reminders without countdown.');
console.log('Server time checks passed: no external time API, repeated calibration, offline ticking, invalid timestamps and connection-warning recovery.');
