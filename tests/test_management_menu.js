'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/management.js'), 'utf8');

const attributes = {}, listeners = {};
const sidebar = {
    setAttribute: (key, value) => { attributes[key] = String(value); },
    getAttribute: key => attributes[key],
    querySelectorAll: () => links
};
const toggle = {
    attributes: {}, focused: false,
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key]; },
    addEventListener(type, handler) { this.handler = handler; },
    focus() { this.focused = true; }
};
const links = [0, 1].map(index => ({
    index,
    addEventListener(type, handler) { this.handler = handler; }
}));
const documentListeners = {};
const document = {
    body: {getAttribute: () => 'display'},
    documentElement: {lang: 'zh-TW'},
    getElementById: id => id === 'management-menu-toggle' ? toggle : null,
    querySelector: selector => selector === '.management-sidebar' ? sidebar : null,
    querySelectorAll: () => [],
    addEventListener(type, handler) { documentListeners[type] = handler; }
};
const window = {
    location: {hash: ''},
    addEventListener() {},
    requestAnimationFrame(callback) { callback(); },
    scrollTo() {}
};
vm.runInNewContext(source, {window, document});

assert.equal(sidebar.getAttribute('data-menu-open'), 'false');
assert.equal(toggle.getAttribute('aria-expanded'), 'false');
toggle.handler.call(toggle);
assert.equal(sidebar.getAttribute('data-menu-open'), 'true');
assert.equal(toggle.getAttribute('aria-expanded'), 'true');
links[0].handler.call(links[0]);
assert.equal(sidebar.getAttribute('data-menu-open'), 'false');
assert.equal(toggle.getAttribute('aria-expanded'), 'false');

toggle.handler.call(toggle);
assert.equal(toggle.getAttribute('aria-expanded'), 'true');
documentListeners.keydown({key: 'Escape'});
assert.equal(toggle.getAttribute('aria-expanded'), 'false');
assert.equal(toggle.focused, true, 'Escape returns focus to the menu button');
console.log('Mobile management menu opens, closes on navigation and Escape, and keeps aria-expanded in sync.');
