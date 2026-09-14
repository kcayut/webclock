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
});
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
