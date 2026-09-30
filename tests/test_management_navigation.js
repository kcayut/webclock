// Run with node tests/test_management_navigation.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/management.js'), 'utf8');
function checkNavigation(initial, names) {
    function element(name, attribute) {
        const attrs = {[attribute]: name, href: '/admin#' + (name === 'calendar' ? 'calendar-title' : name)};
        const handlers = {};
        const classes = new Set();
        return {hidden: false, draft: 'keep unsaved input', classes, handlers,
            addEventListener: (type, handler) => { handlers[type] = handler; },
            getAttribute: key => attrs[key], setAttribute: (key, value) => { attrs[key] = value; },
            removeAttribute: key => { delete attrs[key]; },
            classList: {toggle: (key, on) => { if (on) classes.add(key); else classes.delete(key); }}};
    }
    const panels = names.map(name => element(name, 'data-management-panel'));
    const links = ['display', 'calendar', 'alarms', 'devices', 'backup'].map(name => element(name, 'data-management-link'));
    const events = {};
    let scrollY = 110;
    const frames = [];
    const window = {location: {hash: ''}, addEventListener: (name, fn) => { events[name] = fn; },
        requestAnimationFrame: fn => frames.push(fn), scrollTo(x, y) { scrollY = y; }};
    const context = {window, document: {body: {getAttribute: () => initial},
        querySelectorAll: selector => selector === '[data-management-panel]' ? panels : links}};
    vm.runInNewContext(source, context);
    function selected(name) {
        assert.equal(panels.find(panel => !panel.hidden).getAttribute('data-management-panel'), name);
        assert.equal(panels.filter(panel => !panel.hidden).length, 1);
        assert.equal(links.find(link => link.getAttribute('aria-current')).getAttribute('data-management-link'), name);
        assert.ok(panels.every(panel => panel.draft === 'keep unsaved input'));
    }
    selected(initial);
    events.load();
    scrollY = 110; // The browser resolves a direct hash after the load handler.
    frames.shift()();
    assert.equal(scrollY, 0);
    // Same-document links must preserve invalid POST drafts even when the URL is /add.
    for (const link of links) {
        let prevented = false;
        link.handlers.click.call(link, {preventDefault: () => { prevented = true; }});
        const target = link.getAttribute('data-management-link');
        assert.equal(prevented, names.includes(target));
        if (prevented) {
            // Match the browser's leading # normalization on location.hash assignment.
            window.location.hash = '#' + window.location.hash.replace(/^#/, '');
            events.hashchange();
            selected(target);
        }
    }
    for (const name of names) {
        window.location.hash = '#' + (name === 'calendar' ? 'calendar-title' : name);
        events.hashchange();
        selected(name);
    }
    window.location.hash = '#management-main'; events.hashchange(); selected(names[names.length - 1]);
    window.location.hash = '#unknown'; events.hashchange(); selected(initial);
    window.location.hash = ''; events.hashchange(); selected(initial);
}
checkNavigation('display', ['display', 'calendar', 'backup']);
checkNavigation('calendar', ['display', 'calendar', 'backup']); // Invalid reminder submission.
checkNavigation('alarms', ['alarms', 'devices']);
console.log('Management navigation: direct links, back/forward, errors and retained drafts passed.');
