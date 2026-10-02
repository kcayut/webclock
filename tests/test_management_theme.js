// Run with node tests/test_management_theme.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/management.js'), 'utf8');
const boot = fs.readFileSync(path.join(__dirname, '../templates/management_nav.html'), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

for (const saved of [null, 'dark', 'light', 'invalid', 'unavailable']) {
    let theme, stored = saved;
    const buttons = ['light', 'dark'].map(value => {
        const attrs = {'data-theme': value};
        let click;
        return {
            getAttribute: name => attrs[name],
            setAttribute: (name, value) => { attrs[name] = String(value); },
            addEventListener: (event, handler) => { assert.equal(event, 'click'); click = handler; },
            click() { assert.equal(typeof click, 'function'); click.call(this); }
        };
    });
    const group = {querySelectorAll: selector => { assert.equal(selector, 'button'); return buttons; }};
    const document = {documentElement: {
        getAttribute: () => theme, setAttribute: (name, value) => { theme = value; }
    }, body: {getAttribute: () => 'display'}, querySelectorAll: () => [],
    getElementById: id => id === 'management-theme-toggle' ? group : null};
    const window = {location: {hash: ''}, scrollTo() {}, addEventListener() {}, localStorage: {
        getItem() { if (saved === 'unavailable') throw new Error('storage denied'); return stored; },
        setItem(key, value) { assert.equal(key, 'webclock-management-theme');
            if (saved === 'unavailable') throw new Error('storage denied'); stored = value; }
    }};
    const context = {document, window};
    vm.runInNewContext(boot, context);
    vm.runInNewContext(source, context);
    function checkPressed(selected) {
        for (const button of buttons) {
            assert.equal(button.getAttribute('aria-pressed'), String(button.getAttribute('data-theme') === selected));
        }
        assert.equal(buttons.filter(button => button.getAttribute('aria-pressed') === 'true').length, 1);
    }
    checkPressed(saved === 'dark' ? 'dark' : 'light');
    for (const next of ['dark', 'light', 'light']) {
        buttons.find(button => button.getAttribute('data-theme') === next).click();
        assert.equal(theme, next);
        checkPressed(next);
        if (saved !== 'unavailable') assert.equal(stored, next);
    }
}
console.log('Management light/dark buttons, exclusive pressed state and unavailable storage checks passed.');
