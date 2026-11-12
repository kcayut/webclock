// Run with node tests/test_management_tabs.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/management.js'), 'utf8');

function element(name, attribute, group) {
    const attrs = {[attribute]: name, 'data-tab-group': group};
    const classes = new Set();
    const handlers = {};
    return {
        hidden: false, classes,
        addEventListener(type, handler) { handlers[type] = handler; },
        getAttribute(key) { return attrs[key]; },
        setAttribute(key, value) { attrs[key] = String(value); },
        removeAttribute(key) { delete attrs[key]; },
        focus() { this.focused = true; },
        trigger(type, event = {}) { return handlers[type].call(this, {preventDefault() {}, ...event}); },
        classList: {
            toggle(key, on) { if (on) classes.add(key); else classes.delete(key); },
            contains(key) { return classes.has(key); }
        }
    };
}

const tabs = [
    element('one', 'data-management-tab', 'sample'),
    element('two', 'data-management-tab', 'sample'),
    element('other', 'data-management-tab', 'second')
];
const panels = [
    element('one', 'data-management-tab-panel', 'sample'),
    element('two', 'data-management-tab-panel', 'sample'),
    element('other', 'data-management-tab-panel', 'second')
];
const window = {location: {hash: ''}, addEventListener() {}, requestAnimationFrame() {}, scrollTo() {}};
const document = {
    body: {getAttribute: () => 'display'},
    documentElement: {setAttribute() {}, getAttribute() { return 'light'; }},
    getElementById: () => null,
    querySelectorAll(selector) {
        if (selector === '[data-management-tab]') return tabs;
        if (selector === '[data-management-tab-panel]') return panels;
        return [];
    }
};
vm.runInNewContext(source, {window, document});

tabs[0].trigger('click');
assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
assert.equal(tabs[0].getAttribute('tabindex'), '0');
assert.equal(tabs[1].getAttribute('aria-selected'), 'false');
assert.equal(tabs[1].getAttribute('tabindex'), '-1');
assert.equal(panels[0].hidden, false);
assert.equal(panels[1].hidden, true);
assert.equal(tabs[2].getAttribute('aria-selected'), undefined, 'Tabs in another group must not be touched.');

tabs[1].trigger('click');
assert.equal(panels[0].hidden, true);
assert.equal(panels[1].hidden, false);
assert.equal(tabs[1].getAttribute('aria-selected'), 'true');

let prevented = false;
tabs[0].trigger('keydown', {key: 'ArrowRight', preventDefault() { prevented = true; }});
assert.equal(prevented, true);
assert.equal(tabs[1].focused, true);
assert.equal(tabs[1].getAttribute('aria-selected'), 'true');
assert.equal(panels[1].hidden, false);

tabs[1].trigger('keydown', {key: 'Home', preventDefault() {}});
assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
assert.equal(panels[0].hidden, false);
console.log('Management tabs switch panels, keep groups independent and support keyboard navigation.');
