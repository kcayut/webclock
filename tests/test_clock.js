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
assert.equal(context.clockCountdown({text: '$& meeting', starts_at: 900000}, 0, '{text} in {minutes} minutes'), '$& meeting in 15 minutes');
assert.equal(context.clockCountdown({text: 'meeting', starts_at: 900000}, 899999, '{minutes}'), '1');
assert.equal(context.clockCountdown({text: 'meeting', starts_at: 900000}, 900000, '{minutes}'), '');
assert.equal(context.clockCountdown(null, 0, '{minutes}'), '');
for (const starts_at of ['900000', null, NaN, Infinity]) {
    assert.equal(context.clockCountdown({text: 'invalid', starts_at}, 0, '{minutes}'), '');
}
console.log('Night schedule boundaries, manual override, daytime restoration and countdown checks passed.');

// Run the self-hosted page with the APIs available to an old, offline browser.
const template = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const serverScript = template.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace('{{ translations | tojson }}', JSON.stringify({'zh-TW': {
        weekdays: ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
        countdown: '{text}：{minutes} 分鐘',
    }}))
    .replace('{{ language | tojson }}', '"zh-TW"');
function checkLegacyPage(failOptionalEditor) {
    const elements = {};
    const ticks = [];
    const node = id => elements[id] || (elements[id] = {
        style: {}, classList: {add() {}, remove() {}, toggle() {}},
        querySelectorAll: () => [], querySelector: () => null,
        setAttribute() {}, getAttribute: () => '',
    });
    const legacy = vm.createContext({
        Date: DeviceDate, Intl: undefined, Promise: undefined, fetch: undefined,
        navigator: {},
        document: {
            body: node('body'), documentElement: {},
            getElementById(id) {
                if (failOptionalEditor && id === 'local-events-list') throw new Error('optional editor failed');
                return node(id);
            },
            addEventListener() {}, querySelectorAll: () => [], querySelector: () => null,
        },
        window: {
            location: {origin: 'http://clock.example'}, addEventListener() {},
            localStorage: {getItem() { throw new Error('storage unavailable'); }, setItem() {}},
        },
        setInterval: (callback, delay) => ticks.push({callback, delay}),
        setTimeout() {}, clearTimeout() {},
        XMLHttpRequest: function () {
            this.open = () => assert.match(node('time').textContent, /^\d\d:\d\d$/);
            this.send = () => {}; // A stalled request must never hold up the clock.
        },
    });
    vm.runInContext('Number.isFinite = undefined;', legacy);
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
        legacy.enterServerMode({events: [], settings: {brightness: 35},
            next_event: {text: 'Meeting', starts_at: now + 300000}});
        assert.equal(node('clock-container').style.opacity, 0.35);
        assert.equal(node('list-container').style.opacity, 0.35);
        assert.equal(node('next-event').textContent, 'Meeting：5 分鐘');
        legacy.enterStandaloneMode();
        tick.callback();
    }
    vm.runInContext(fs.readFileSync(path.join(root, 'static/offline.js'), 'utf8'), legacy);
    assert.match(node('time').textContent, /^\d\d:\d\d$/);
}
checkLegacyPage(false);
checkLegacyPage(true);
for (const page of [html, template]) {
    assert.ok(page.indexOf('offline.js') > page.indexOf('setInterval(update'), 'optional offline script loads after clock startup');
}
console.log('Legacy startup checks passed: no modern APIs/storage/network response, optional UI failure, brightness and countdown.');
