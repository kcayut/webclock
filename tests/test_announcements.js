// Run with node tests/test_announcements.js (standard library only).
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/announcements.js'), 'utf8');
assert.doesNotMatch(source, /\b(?:const|let|async)\b|=>|\?\.|localStorage|sessionStorage/);
let wall = 1800000000000, mono = 1000, sequence = 0;
const timers = new Map(), classes = new Set();
function element() {
    let text = '';
    const result = {style: {}, children: [], appendChild(child) { this.children.push(child); }};
    Object.defineProperty(result, 'textContent', {
        get() { return text + this.children.map(child => child.textContent).join(''); },
        set(value) { text = value; this.children = []; }
    });
    Object.defineProperty(result, 'innerHTML', {set() { assert.fail('Announcements must never use HTML'); }});
    return result;
}
const container = element();
const window = {performance: {now: () => mono}};
const context = vm.createContext({window, Date: function () { this.getTime = () => wall; },
    document: {getElementById: () => container, createElement: element,
        body: {classList: {toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }}}},
    setTimeout(callback, delay) { const id = ++sequence; timers.set(id, {callback, delay}); return id; },
    clearTimeout(id) { timers.delete(id); }, Promise: undefined, fetch: undefined, Intl: undefined});
vm.runInContext(source, context);
const announcements = window.WebClockAnnouncements;
const serverTime = wall - 7200000; // Device wall time is wrong by two hours.
const rows = [{id: 1, text: '<b>Silent announcement</b>', visible_until: serverTime + 5000},
    {id: 2, text: 'Later', visible_until: serverTime + 9000}];
announcements.set(rows, serverTime, 2000);
assert.equal(container.textContent, '<b>Silent announcement</b>Later');
assert.equal(classes.has('has-announcements'), true);
assert.equal([...timers.values()][0].delay, 3000, 'Network delay is deducted before setting a local deadline');
wall += 2999; mono += 2999; announcements.tick(); assert.equal(container.children.length, 2);
wall++; mono++; [...timers.values()][0].callback();
assert.equal(container.textContent, 'Later', 'The earliest announcement is removed at its own deadline');
assert.equal([...timers.values()][0].delay, 4000);
wall += 4000; mono += 4000; announcements.tick();
assert.equal(container.style.display, 'none'); assert.equal(timers.size, 0); assert.equal(container.textContent, '');
announcements.set(rows, serverTime, 9000);
assert.equal(container.textContent, '', 'A response arriving after expiry never flashes expired text');
announcements.set(rows, serverTime); wall -= 1; announcements.tick();
assert.equal(container.textContent, '', 'A wall clock rollback cannot extend private content');
announcements.set(rows, serverTime); mono -= 1; announcements.tick();
assert.equal(container.textContent, '', 'A monotonic clock reset clears private content');
announcements.set(rows, serverTime); wall += 10000; announcements.tick();
assert.equal(container.textContent, '', 'A suspended monotonic clock still expires from elapsed wall time');
announcements.set(rows, serverTime); announcements.clear();
assert.equal(container.textContent, ''); assert.equal(classes.has('has-announcements'), false); assert.equal(timers.size, 0);
announcements.set([{text: 'Invalid', visible_until: 'later'}, null], serverTime);
assert.equal(container.textContent, '');
announcements.set(rows, undefined); assert.equal(container.textContent, '');

// Switching reminder type changes visibility, preserving every entered value.
const admin = fs.readFileSync(path.join(__dirname, '../templates/admin.html'), 'utf8');
const functionSource = admin.match(/        function setAnnouncementMode\(select\) \{[\s\S]*?\n        \}/)[0];
const fields = {hidden: true, disabled: true, expiry: '2030-01-02T12:30', ids: ['device-a']};
const groups = {hidden: false};
const select = {value: '1', form: {querySelector: selector => selector === '[data-announcement-options]' ? fields : groups}};
const management = vm.createContext({}); vm.runInContext(functionSource, management);
management.setAnnouncementMode(select);
assert.equal(fields.hidden, false); assert.equal(fields.disabled, false); assert.equal(groups.hidden, true);
select.value = ''; management.setAnnouncementMode(select);
assert.equal(fields.hidden, true); assert.equal(fields.disabled, true); assert.equal(groups.hidden, false);
select.value = '1'; management.setAnnouncementMode(select);
assert.equal(fields.expiry, '2030-01-02T12:30'); assert.deepEqual(fields.ids, ['device-a']);
console.log('Announcements: ES5, safe text, request latency, exact deadlines, clock rollback, clearing and retained form drafts passed.');
