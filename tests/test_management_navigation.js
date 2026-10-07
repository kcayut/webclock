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
    const context = {window, document: {body: {getAttribute: () => initial}, getElementById: () => null,
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
    if (names.includes('calendar')) {
        window.location.hash = '#announcements-title'; events.hashchange(); selected('calendar');
    }
    window.location.hash = '#unknown'; events.hashchange(); selected(initial);
    window.location.hash = ''; events.hashchange(); selected(initial);
}
checkNavigation('display', ['display', 'calendar', 'backup']);
checkNavigation('calendar', ['display', 'calendar', 'backup']); // Invalid reminder submission.
checkNavigation('alarms', ['alarms', 'devices']);

async function checkLanguage() {
    let handler, request, reloads = 0, failure = false, alerts = 0, timeRefreshes = 0, calendarRefreshes = 0;
    const attrs = {'data-error': 'save failed'};
    const select = {value: 'en', disabled: false,
        addEventListener: (name, callback) => { if (name === 'change') handler = callback; },
        getAttribute: key => attrs[key], setAttribute: (key, value) => { attrs[key] = value; }};
    const label = {textContent: '語言', getAttribute: () => 'language'};
    const weekday = {textContent: '一', getAttribute: () => '1'};
    const draft = {note: 'unsaved reminder', nightStart: '22:30', privateUrl: 'https://private.example/draft.ics'};
    const before = JSON.stringify(draft);
    const packs = {en: {language: 'Language', admin_title: 'Settings', weekdays: ['Sun', 'Mon'], settings_save_error: 'Save failed'},
        'zh-TW': {language: '語言', admin_title: '設定', weekdays: ['日', '一'], settings_save_error: '儲存失敗'}};
    const window = {location: {hash: '', reload: () => { reloads++; }}, addEventListener() {},
        CalendarSettings: {applyLanguage: () => { calendarRefreshes++; }},
        requestAnimationFrame: callback => callback(), scrollTo() {}, alert() { alerts++; }};
    const context = {window, I18N: packs, currentLanguage: 'zh-TW', currentTimeFormat: '12h', settingsMessage: '',
        applyTimeFormat: format => { assert.equal(format, '12h'); timeRefreshes++; },
        document: {documentElement: {lang: 'zh-TW'}, body: {getAttribute: () => 'display'},
            getElementById: id => id === 'management-language-select' ? select : id === 'management-i18n' ? {textContent: JSON.stringify(packs)} : id === 'csrf-token' ? {content: 'language-csrf-token'} : id === 'settings-status' ? {textContent: ''} : null,
            querySelectorAll: selector => selector === '[data-i18n]' ? [label] : selector === '[data-weekday]' ? [weekday] : []},
        fetch(url, options) { request = {url, options}; return failure === 'network' ? Promise.reject(new Error('offline')) : Promise.resolve({ok: !failure}); }};
    vm.createContext(context);
    const admin = fs.readFileSync(require('node:path').join(__dirname, '../templates/admin.html'), 'utf8');
    vm.runInContext(admin.slice(admin.indexOf('function t(key)'), admin.indexOf('function setWindowMode(')), context);
    vm.runInContext(source, context);
    handler.call(select);
    assert.equal(select.disabled, true);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(select.disabled, false);
    assert.equal(request.url, '/api/management/language');
    assert.equal(request.options.headers['X-CSRF-Token'], 'language-csrf-token');
    assert.deepEqual(JSON.parse(request.options.body), {language: 'en'});
    assert.equal(context.currentLanguage, 'en');
    assert.equal(context.document.documentElement.lang, 'en');
    assert.equal(context.document.title, 'Settings');
    assert.equal(label.textContent, 'Language');
    assert.equal(weekday.textContent, 'Mon');
    assert.equal(timeRefreshes, 1); assert.equal(calendarRefreshes, 1);
    for (const fail of [true, 'network']) {
        failure = fail; select.value = 'zh-TW'; handler.call(select);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(select.disabled, false);
        assert.equal(select.value, 'en');
        assert.equal(context.document.documentElement.lang, 'en');
    }
    assert.equal(alerts, 2);
    assert.equal(reloads, 0, 'Successful and failed language changes must never reload away drafts');
    assert.equal(JSON.stringify(draft), before);
}

async function checkBackup() {
    const admin = fs.readFileSync(require('node:path').join(__dirname, '../templates/admin.html'), 'utf8');
    const backup = {version: 1, settings: {language: 'en'}, notes: []};
    const fields = {
        'csrf-token': {content: 'backup-csrf-token'},
        'backup-file': {files: [{size: 100, text: async () => JSON.stringify(backup)}]},
        'backup-status': {textContent: ''}, 'backup-submit': {disabled: false}
    };
    let request, reloaded = false, ok = false;
    const context = vm.createContext({document: {getElementById: id => fields[id]}, t: key => key,
        window: {confirm: () => true, location: {reload() { reloaded = true; }}},
        fetch: async (url, options) => { request = {url, options}; return {ok}; }});
    vm.runInContext(admin.slice(admin.indexOf('async function importBackup('), admin.indexOf('function setMode(')), context);
    await context.importBackup();
    assert.equal(request.url, '/api/backup');
    assert.equal(request.options.headers['X-CSRF-Token'], 'backup-csrf-token');
    assert.equal(request.options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(request.options.body), backup);
    assert.equal(reloaded, false, 'Rejected imports must preserve the current page');
    assert.equal(fields['backup-status'].textContent, 'backup_error');
    assert.equal(fields['backup-submit'].disabled, false);
    ok = true;
    await context.importBackup();
    assert.equal(reloaded, true);
    assert.equal(fields['backup-status'].textContent, 'backup_done');
}

Promise.all([checkLanguage(), checkBackup()]).then(() => console.log('Management navigation, CSRF headers, backup imports and in-place language changes passed.'))
    .catch(error => { console.error(error); process.exitCode = 1; });
