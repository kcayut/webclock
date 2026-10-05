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
    assert.equal(nodes['time-period'].style.display, 'inline-block');
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
const clockLabels = {};
for (const language of ['zh-TW', 'en', 'ja']) {
    const pack = clockLabels[language] = {
        weekdays: ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
        server_unavailable: 'Server unavailable', server_timeout: 'Server timed out',
        status_parse_failed: 'Unreadable response', page_error: 'Page error',
    };
    for (const key of ['delete', 'offline_ready', 'offline_unavailable', 'offline_failed',
        'connection_connecting', 'connection_connected', 'connection_saved', 'connection_standalone',
        'connection_unreadable', 'connection_unavailable', 'connection_timeout',
        ...Array.from(template.matchAll(/data-clock-i18n="([^"]+)"/g), match => match[1])]) {
        pack[key] = language + ':' + key + (['connection_connected', 'connection_saved'].includes(key) ? ' {url}' : '');
    }
}
const inlineScripts = Array.from(template.matchAll(/<script>([\s\S]*?)<\/script>/g), match => match[1]);
const coreScript = inlineScripts.find(script => script.includes('WebClockCore.start'))
    .replace('{{ translations[language].weekdays | tojson }}', JSON.stringify(clockLabels['zh-TW'].weekdays))
    .replace('{{ language | tojson }}', '"zh-TW"');
const serverScript = inlineScripts.find(script => script.includes('var I18N ='))
    .replace('{{ translations | tojson }}', JSON.stringify(clockLabels))
    .replace('{{ language | tojson }}', '"zh-TW"');
function checkLegacyPage(failOptionalEditor, bootSettings) {
    const elements = {};
    const ticks = [];
    const requests = [];
    const storage = bootSettings ? {'webclock.settings': bootSettings.raw} : {};
    let storageAvailable = !!bootSettings;
    let storageWritable = true;
    let failNextSend = false;
    function makeNode() {
        const classes = new Set();
        const attributes = {};
        return {
            style: {}, children: [],
            classList: {
                add: name => classes.add(name), remove: name => classes.delete(name),
                toggle(name, on) {
                    if (arguments.length < 2) on = !classes.has(name);
                    if (on) classes.add(name); else classes.delete(name);
                    return on;
                },
                contains: name => classes.has(name),
            },
            appendChild(child) { this.children.push(child); },
            removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
            querySelectorAll(selector) { return this.children.filter(child => selector === '.event-row' && child.className === 'event-row'); },
            querySelector: () => null,
            setAttribute(name, value) { attributes[name] = value; },
            getAttribute: name => attributes[name] || '',
        };
    }
    const node = id => elements[id] || (elements[id] = makeNode());
    node('body').setAttribute('data-deployment-mode', 'self');
    const labels = Array.from(template.matchAll(/<[^>]+data-clock-i18n="([^"]+)"[^>]*>/g), ([tag, key]) => {
        const id = (tag.match(/\bid="([^"]+)"/) || [])[1];
        const label = id ? node(id) : makeNode();
        label.setAttribute('data-clock-i18n', key);
        label.setAttribute('data-clock-attribute', (tag.match(/data-clock-attribute="([^"]+)"/) || [])[1] || '');
        return label;
    });
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
            addEventListener() {},
            querySelectorAll: selector => selector === '[data-clock-i18n]' ? labels : [],
            querySelector: () => null,
        },
        window: {
            location: {origin: 'http://clock.example'}, addEventListener() {},
            localStorage: {
                getItem(key) { if (!storageAvailable) throw new Error('storage unavailable'); return storage[key] || null; },
                setItem(key, value) { if (!storageWritable) throw new Error('storage unavailable'); storage[key] = value; },
            },
        },
        setInterval: (callback, delay) => ticks.push({callback, delay}),
        setTimeout() {}, clearTimeout() {},
        XMLHttpRequest: function () {
            this.open = (method, url) => {
                assert.match(node('time').textContent, /^\d\d:\d\d$/);
                assert.equal(method, 'GET');
                assert.match(url, /^http:\/\/[^/]+\/api\/(?:status\?nocache=\d+|time)$/);
                this.url = url;
                requests.push(this);
            };
            this.send = () => {
                if (failNextSend) {
                    failNextSend = false;
                    throw new Error('send failed');
                }
            }; // A stalled request must never hold up the clock.
        },
    });
    vm.runInContext('Number.isFinite = undefined;', legacy);
    vm.runInContext(fs.readFileSync(path.join(root, 'static/time-format.js'), 'utf8'), legacy);
    vm.runInContext(fs.readFileSync(path.join(root, 'static/clock.js'), 'utf8'), legacy);
    vm.runInContext(coreScript, legacy);
    if (failOptionalEditor) assert.throws(() => vm.runInContext(serverScript, legacy), /optional editor failed/);
    else vm.runInContext(serverScript, legacy);
    assert.equal(elements.notice, undefined, 'optional failures never create a main-screen notice');
    assert.equal(node('connection-panel').classList.contains('open'), false,
        'optional initialization never opens the connection panel');
    const tick = ticks.find(timer => timer.delay === 1000);
    assert.ok(tick, 'clock timer starts before optional initialization');
    const before = node('time').textContent;
    now += 60000;
    tick.callback();
    assert.notEqual(node('time').textContent, before);
    if (bootSettings) {
        assert.equal(legacy.activeSettings.brightness, bootSettings.brightness);
        assert.equal(legacy.activeSettings.timezone_offset, 8);
        assert.equal(legacy.activeSettings.night.enabled, false);
        assert.equal(legacy.activeSettings.night.start, '22:00');
        assert.equal(legacy.activeSettings.time_format, '24h');
        assert.match(node('time').textContent, /^\d\d:\d\d$/);
        assert.match(node('date-part').textContent, /^\d{1,2}\/\d{1,2}$/);
        assert.ok(node('day-part').textContent);
        assert.equal(node('clock-container').style.opacity, bootSettings.brightness / 100);
        assert.equal(node('body').classList.contains('force-black'), false);
        assert.equal(storage['webclock.settings'], bootSettings.raw,
            'startup does not overwrite an unreadable or legacy cache');
        return;
    }
    if (!failOptionalEditor) {
        assert.deepEqual(ticks.map(timer => timer.delay), [1000, 5000], 'clock only polls its own status server');
        assert.equal(requests.length, 1, 'startup makes one status request and no external time request');
        assert.equal(node('connection-toggle').textContent, '...', 'the connection entry stays neutral while connecting');
        assert.equal(node('connection-toggle').title, clockLabels['zh-TW'].connection_settings);
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

        storage['webclock.localEvents'] = JSON.stringify([{id: 900, text: 'Keep local reminder', time: '09:00'}]);
        const localEventsBeforeRaces = storage['webclock.localEvents'];

        const slowRequest = newRequest();
        const nextPoll = newRequest();
        serverNow += 60000;
        reply(slowRequest, {events: [{text: 'Slow response', time: '08:03'}], server_timestamp: serverNow});
        assert.equal(legacy.getClockUtcMs(), serverNow,
            'an older in-flight request can calibrate after a newer poll has only been issued');
        serverNow += 60000;
        reply(nextPoll, {events: [{text: 'Next response', time: '08:04'}], server_timestamp: serverNow});
        assert.equal(legacy.getClockUtcMs(), serverNow);

        const oldSuccess = newRequest();
        const newSuccess = newRequest();
        serverNow += 60000;
        reply(newSuccess, {events: [{text: 'Newest state', time: '08:05'}], settings: {brightness: 44},
            server_timestamp: serverNow});
        const newestClock = legacy.getClockUtcMs();
        reply(oldSuccess, {events: [{text: 'Stale state', time: '07:00'}], settings: {brightness: 10},
            server_timestamp: serverNow - 3600000});
        assert.equal(legacy.getClockUtcMs(), newestClock, 'an older success cannot replace a newer response');
        assert.equal(legacy.activeSettings.brightness, 44);
        assert.equal(node('list-container').children[0].children[0].children[1].textContent, 'Newest state');

        for (const fail of [
            xhr => reply(xhr, '{broken'),
            xhr => { reply(xhr, '', 0); xhr.onerror(); },
            xhr => { reply(xhr, '', 0); xhr.ontimeout(); },
            xhr => reply(xhr, '', 503),
        ]) {
            const oldFailure = newRequest();
            const newBeforeFailure = newRequest();
            serverNow += 60000;
            reply(newBeforeFailure, {events: [{text: 'Still current', time: '08:06'}], server_timestamp: serverNow});
            const savedSettings = storage['webclock.settings'];
            fail(oldFailure);
            assert.equal(legacy.connectionMode, 'server',
                'each older failure independently cannot undo a newer success');
            assert.equal(legacy.lastServerStatus, 'connection_connected');
            assert.equal(legacy.getClockUtcMs(), serverNow);
            assert.equal(storage['webclock.settings'], savedSettings);
            assert.equal(node('list-container').children[0].children[0].children[1].textContent, 'Still current');
        }

        const duplicate = newRequest();
        serverNow += 60000;
        reply(duplicate, {events: [{text: 'Only terminal state', time: '08:07'}], server_timestamp: serverNow});
        const duplicateClock = legacy.getClockUtcMs();
        duplicate.onerror();
        duplicate.ontimeout();
        reply(duplicate, {events: [{text: 'Duplicate callback', time: '01:00'}],
            server_timestamp: serverNow - 3600000});
        assert.equal(legacy.getClockUtcMs(), duplicateClock, 'one request is applied only once');
        assert.equal(legacy.connectionMode, 'server');
        assert.equal(node('list-container').children[0].children[0].children[1].textContent, 'Only terminal state');

        const oldSource = newRequest();
        node('server-url-input').value = 'http://second.example';
        assert.equal(legacy.saveServerUrl(), true);
        reply(oldSource, {events: [{text: 'Old source', time: '01:00'}], settings: {brightness: 12},
            server_timestamp: serverNow - 7200000});
        assert.equal(legacy.activeSettings.brightness, 44, 'switching servers invalidates the previous source');
        const secondSource = newRequest();
        assert.match(secondSource.url, /^http:\/\/second\.example\/api\/time/);
        serverNow += 60000;
        reply(secondSource, {events: [{text: 'Second server', time: '08:08'}], settings: {brightness: 46},
            server_timestamp: serverNow});

        const beforeSameUrlReconnect = newRequest();
        node('server-url-input').value = 'http://second.example';
        legacy.reconnectNow();
        const afterSameUrlReconnect = requests[requests.length - 1];
        beforeSameUrlReconnect.onerror();
        assert.equal(legacy.lastServerStatus, 'connection_connecting',
            'reconnect rejects old callbacks even before its first response');
        serverNow += 60000;
        reply(afterSameUrlReconnect, {events: [{text: 'Reconnected', time: '08:09'}], server_timestamp: serverNow});
        beforeSameUrlReconnect.onerror();
        reply(beforeSameUrlReconnect, {events: [{text: 'Before reconnect', time: '01:00'}],
            server_timestamp: serverNow - 7200000});
        assert.equal(legacy.connectionMode, 'standalone');
        assert.ok(!legacy.currentEventsJson.includes('Reconnected'),
            'without the optional session module another source only supplies public time');

        node('server-url-input').value = 'http://clock.example';
        legacy.reconnectNow();
        const firstARequest = requests[requests.length - 1];
        node('server-url-input').value = 'http://second.example';
        legacy.reconnectNow();
        const staleBRequest = requests[requests.length - 1];
        node('server-url-input').value = 'http://clock.example';
        legacy.reconnectNow();
        const currentARequest = requests[requests.length - 1];
        reply(firstARequest, {events: [{text: 'First A', time: '01:00'}], settings: {brightness: 13},
            server_timestamp: serverNow - 7200000});
        staleBRequest.ontimeout();
        assert.equal(legacy.activeSettings.brightness, 44,
            'the first A generation stays invalid before the current A responds');
        assert.equal(legacy.lastServerStatus, 'connection_connecting');
        serverNow += 60000;
        reply(currentARequest, {events: [{text: 'Current A', time: '08:10'}], settings: {brightness: 48},
            server_timestamp: serverNow});
        assert.equal(legacy.serverUrl, 'http://clock.example');
        assert.equal(legacy.activeSettings.brightness, 48,
            'A to B to A does not make the first A generation current again');
        assert.equal(node('list-container').children[0].children[0].children[1].textContent, 'Current A');
        assert.equal(storage['webclock.localEvents'], localEventsBeforeRaces,
            'request races and source switches do not delete local reminders');
        delete storage['webclock.localEvents'];

        failNextSend = true;
        const sendFailure = newRequest();
        assert.equal(legacy.connectionMode, 'standalone', 'a synchronous send failure uses the offline fallback');
        sendFailure.onerror();
        assert.equal(legacy.lastServerStatus, 'connection_unavailable',
            'a later callback cannot terminate a synchronous send failure twice');

        for (const [fail, statusKey] of [
            [xhr => reply(xhr, '', 503), 'connection_unavailable'],
            [xhr => reply(xhr, '', 401), 'connection_unavailable'],
            [xhr => reply(xhr, '', 403), 'connection_unavailable'],
            [xhr => xhr.onerror(), 'connection_unavailable'],
            [xhr => { reply(xhr, '', 0); xhr.onerror(); }, 'connection_unavailable'],
            [xhr => xhr.ontimeout(), 'connection_timeout'],
            [xhr => { reply(xhr, '', 0); xhr.ontimeout(); }, 'connection_timeout'],
            [xhr => reply(xhr, '<!doctype html><title>Login</title>'), 'connection_unreadable'],
            [xhr => reply(xhr, '{broken'), 'connection_unreadable'],
        ]) {
            fail(newRequest());
            assert.equal(elements.notice, undefined, 'network failures stay off the main clock');
            assert.equal(node('connection-panel').classList.contains('open'), false);
            assert.equal(node('connection-toggle').textContent, '...', 'failure does not turn the entry into a warning symbol');
            assert.equal(node('connection-toggle').title, clockLabels['zh-TW'].connection_settings);
            assert.equal(node('connection-status').textContent, clockLabels['zh-TW'][statusKey]);
            const offlineTime = legacy.getClockUtcMs();
            now += 60000;
            tick.callback();
            assert.equal(legacy.getClockUtcMs(), offlineTime + 60000, 'the corrected clock advances while disconnected');
            serverNow += 60000;
            reply(newRequest(), {events: [], server_timestamp: serverNow});
            assert.equal(elements.notice, undefined);
            assert.equal(node('connection-panel').classList.contains('open'), false);
            assert.equal(node('connection-toggle').textContent, '...');
            fail(newRequest());
            assert.equal(elements.notice, undefined, 'a new failure after recovery is also quiet');
            assert.equal(node('connection-panel').classList.contains('open'), false);
            assert.equal(node('connection-toggle').textContent, '...');
            reply(newRequest(), {events: [], server_timestamp: serverNow});
        }
        assert.equal(legacy.window.location.origin, 'http://clock.example',
            'authentication and parse failures never redirect the clock');
        assert.equal(legacy.window.onerror, undefined, 'runtime errors do not install a main-screen notice handler');
        legacy.toggleConnectionPanel();
        assert.equal(node('connection-panel').classList.contains('open'), true,
            'the user can still open the connection panel');
        assert.equal(node('server-url-input').value, legacy.serverUrl);
        assert.equal(node('connection-status').textContent,
            clockLabels['zh-TW'].connection_connected.replace('{url}', legacy.serverUrl));
        legacy.toggleConnectionPanel();
        assert.equal(node('connection-panel').classList.contains('open'), false);
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
        const validSettings = JSON.stringify(legacy.activeSettings);
        const savedValidSettings = storage['webclock.settings'];
        for (const invalidSettings of [
            {brightness: null}, {brightness: ''}, {brightness: ' '}, {brightness: NaN}, {brightness: 101},
            {timezone_offset: null}, {timezone_offset: 'bad'}, {timezone_offset: Infinity}, {timezone_offset: 15},
            {mode: 'invisible'}, {language: 'unknown'}, {language: ['en'], brightness: 0}, {time_format: 'invalid'},
            {night: null}, {night: {enabled: true, start: 'bad'}},
            {night: {enabled: true, start: '22:00', end: '22:00'}}, {unknown: true},
            {constructor: true, brightness: 0}, {toString: true, brightness: 0},
            JSON.parse('{"__proto__": {}, "brightness": 0}'),
            {night: {toString: true}, brightness: 0},
        ]) {
            legacy.enterServerMode({events: [], settings: invalidSettings});
            assert.equal(JSON.stringify(legacy.activeSettings), validSettings,
                'invalid settings retain the last valid display state');
            assert.equal(storage['webclock.settings'], savedValidSettings,
                'invalid settings are not persisted');
            assert.match(node('time').textContent, /^\d\d:\d\d$/);
            assert.doesNotMatch(node('time').textContent + node('date-part').textContent, /NaN/);
            assert.match(node('date-part').textContent, /^\d{1,2}\/\d{1,2}$/);
            assert.ok(node('day-part').textContent);
            assert.ok(Number(node('clock-container').style.opacity) > 0,
                'invalid settings cannot hide the basic clock');
            assert.notEqual(node('clock-container').style.display, 'none');
            assert.notEqual(node('clock-container').style.visibility, 'hidden');
            assert.equal(node('body').classList.contains('force-black'), false,
                'invalid settings cannot trigger black mode');
        }
        legacy.enterServerMode({
            settings: {brightness: 0, timezone_offset: 'bad'},
            server_timestamp: Date.parse('2026-10-01T01:23:00Z'),
            events: [{text: 'Valid event with invalid settings', time: '09:23'}],
        });
        assert.equal(JSON.stringify(legacy.activeSettings), validSettings);
        assert.equal(node('time').textContent, '09:23',
            'invalid settings do not reject the valid server time in the same reply');
        assert.equal(node('list-container').children[0].children[0].children[1].textContent,
            'Valid event with invalid settings');

        storageAvailable = false;
        legacy.enterStandaloneMode();
        assert.equal(JSON.stringify(legacy.activeSettings), validSettings,
            'unavailable storage retains the current valid settings');
        storageAvailable = true;
        const corruptLocalEvents = JSON.stringify([null, false, {text: 'Invalid time', time: 123},
            {text: 'Invalid date', date: []}, {text: 45}, {text: 'Valid local reminder', time: '09:00'}]);
        storage['webclock.localEvents'] = corruptLocalEvents;
        legacy.enterServerMode({events: [{text: 'Private reminder', time: '10:00'}]});
        assert.doesNotThrow(() => legacy.enterStandaloneMode(),
            'malformed local reminders cannot prevent private content from clearing');
        assert.equal(node('list-container').children[0].children[0].children[1].textContent,
            'Valid local reminder');
        assert.equal(node('event-counter').textContent, '1 / 1');
        assert.equal(storage['webclock.localEvents'], corruptLocalEvents,
            'filtering local reminders never rewrites the saved source');
        delete storage['webclock.localEvents'];
        storage['webclock.settings'] = '{broken';
        legacy.enterStandaloneMode();
        assert.equal(JSON.stringify(legacy.activeSettings), validSettings,
            'malformed stored JSON retains the current valid settings');
        storage['webclock.settings'] = JSON.stringify({brightness: null, timezone_offset: 'bad'});
        legacy.enterStandaloneMode();
        assert.equal(JSON.stringify(legacy.activeSettings), validSettings,
            'invalid stored settings retain the current valid settings');
        storage['webclock.settings'] = savedValidSettings;
        storageWritable = false;
        legacy.enterServerMode({events: [], settings: {brightness: 45}});
        assert.equal(legacy.activeSettings.brightness, 45,
            'a storage write failure does not reject an otherwise valid live setting');
        assert.equal(node('clock-container').style.opacity, 0.45);
        assert.equal(storage['webclock.settings'], savedValidSettings,
            'a storage write failure leaves the previous stored settings intact');
        legacy.enterStandaloneMode();
        assert.equal(legacy.activeSettings.brightness, 45,
            'disconnecting after a failed save must not restore stale cached settings');
        assert.equal(node('clock-container').style.opacity, 0.45);
        const beforeWriteFailureTick = node('time').textContent;
        now += 60000;
        tick.callback();
        assert.notEqual(node('time').textContent, beforeWriteFailureTick,
            'the clock keeps advancing after a storage write failure');
        storageWritable = true;

        legacy.enterServerMode({events: [], settings: {brightness: 0}});
        assert.equal(node('clock-container').style.opacity, 0,
            'an explicit zero brightness remains a valid user setting');
        legacy.enterServerMode({events: [], settings: {brightness: 35, mode: 'black'}});
        assert.equal(node('body').classList.contains('force-black'), true,
            'manual black mode remains valid');
        const beforeBlackTick = node('time').textContent;
        now += 60000;
        tick.callback();
        assert.notEqual(node('time').textContent, beforeBlackTick,
            'the underlying clock keeps advancing during intentional black mode');
        legacy.enterServerMode({events: [], settings: {
            mode: 'normal', brightness: 35,
            night: {enabled: true, start: '22:00', end: '07:00', brightness: 0, black: false},
        }, server_timestamp: Date.parse('2026-10-01T15:59:00Z')});
        assert.equal(node('clock-container').style.opacity, 0,
            'zero night brightness remains valid independently of black mode');
        assert.equal(node('body').classList.contains('force-black'), false);
        legacy.enterServerMode({events: [], settings: {night: {black: true}}});
        assert.equal(node('body').classList.contains('force-black'), true,
            'a valid active night black setting remains supported');
        const beforeNightDate = node('date-part').textContent;
        const beforeNightDay = node('day-part').textContent;
        now += 60000;
        tick.callback();
        assert.equal(node('time').textContent, '00:00');
        assert.notEqual(node('date-part').textContent, beforeNightDate);
        assert.notEqual(node('day-part').textContent, beforeNightDay,
            'time, date and weekday keep updating while intentionally black');
        now += 7 * 3600000;
        tick.callback();
        assert.equal(node('time').textContent, '07:00');
        assert.equal(node('body').classList.contains('force-black'), false,
            'night mode ends automatically without another server response');
        assert.equal(node('clock-container').style.opacity, 0.35,
            'night end restores the last valid daytime brightness');
        legacy.enterServerMode({events: [], settings: {
            night: {enabled: false}, mode: 'normal', brightness: 35,
        }});
        assert.equal(node('body').classList.contains('force-black'), false);
        assert.equal(node('clock-container').style.opacity, 0.35);
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
        legacy.serverUrl = 'http://clock.example/$&';
        legacy.setConnectionStatus('connection_saved', false);
        assert.equal(node('connection-status').textContent, 'zh-TW:connection_saved http://clock.example/$&');
        legacy.serverUrl = 'http://clock.example';
        const savedEvents = storage['webclock.localEvents'];
        node('local-event-text').value = 'Unsent reminder';
        node('local-event-time').value = '14:25';
        node('server-url-input').value = 'http://unsent.example';
        for (const language of ['en', 'ja', 'zh-TW']) {
            const settings = {time_format: '12h', language, timezone_offset: 8};
            legacy.saveSettings(settings);
            legacy.applySettings(settings);
            for (const label of labels) {
                const key = label.getAttribute('data-clock-i18n');
                const attribute = label.getAttribute('data-clock-attribute');
                assert.equal(attribute ? label.getAttribute(attribute) : label.textContent, clockLabels[language][key]);
            }
            assert.equal(node('local-events-list').children.at(-1).children[1].textContent, clockLabels[language].delete);
            legacy.enterServerMode({events: []});
            assert.equal(node('connection-status').textContent, clockLabels[language].connection_connected.replace('{url}', 'http://clock.example'));
            for (const [fail, key] of [
                [xhr => xhr.onerror(), 'connection_unavailable'],
                [xhr => xhr.ontimeout(), 'connection_timeout'],
                [xhr => reply(xhr, '{broken'), 'connection_unreadable'],
            ]) {
                fail(newRequest());
                assert.equal(node('connection-status').textContent, clockLabels[language][key]);
            }
            for (const state of ['ready', 'unavailable', 'failed']) {
                node('offline-status').setAttribute('data-state', state);
                legacy.setLanguage(language === 'en' ? 'ja' : 'en');
                legacy.setLanguage(language);
                assert.equal(node('offline-status').textContent, clockLabels[language]['offline_' + state]);
            }
            assert.equal(node('local-event-text').value, 'Unsent reminder');
            assert.equal(node('local-event-time').value, '14:25');
            assert.equal(node('server-url-input').value, 'http://unsent.example');
            assert.equal(storage['webclock.localEvents'], savedEvents, 'language changes preserve stored local reminders');
            assert.equal(legacy.activeSettings.time_format, '12h');
        }
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
for (const bootSettings of [
    {raw: '{broken', brightness: 100},
    {raw: JSON.stringify({brightness: null, mode: 'black'}), brightness: 100},
    {raw: JSON.stringify({language: ['en'], brightness: 0}), brightness: 100},
    {raw: JSON.stringify({brightness: '65', night: {enabled: false}}), brightness: 65},
]) checkLegacyPage(false, bootSettings);
// A separately parsed optional script can be missing or contain invalid syntax
// without preventing the already-started clock from crossing midnight.
{
    const isolatedNodes = {'time': {}, 'time-period': {style: {}}, 'date-part': {}, 'day-part': {}};
    const isolatedTimers = [];
    const isolated = vm.createContext({
        Date: DeviceDate,
        document: {
            getElementById: id => isolatedNodes[id],
            addEventListener() {},
        },
        window: {addEventListener() {}},
        setInterval: (callback, delay) => isolatedTimers.push({callback, delay}),
    });
    vm.runInContext(fs.readFileSync(path.join(root, 'static/clock.js'), 'utf8'), isolated);
    vm.runInContext(coreScript, isolated);
    assert.throws(() => vm.runInContext('var optionalFeature = ;', isolated), /Unexpected token/);
    isolated.window.WebClockCore.useUpdater(function () { throw new Error('optional updater failed'); });
    now = Date.parse('2026-12-31T23:59:00Z');
    isolatedTimers[0].callback();
    const beforeDate = isolatedNodes['date-part'].textContent;
    now += 60000;
    isolatedTimers[0].callback();
    assert.notEqual(isolatedNodes['date-part'].textContent, beforeDate);
    assert.equal(isolatedNodes.time.textContent, '00:00');
}
for (const page of [html, template]) {
    assert.doesNotMatch(page, /id="next-event"/);
    assert.doesNotMatch(page, /id="notice(?:-text|-close)?"|showNotice\(|window\.onerror/,
        'the clock has no automatic system-error notice surface');
    assert.ok(page.indexOf('offline.js') > page.indexOf('WebClockCore.start'), 'optional offline script loads after clock startup');
}
assert.doesNotMatch(template, /id="alarm-status"/, 'alarm synchronization failures stay off the main clock');
assert.match(template, /<form id="local-event-form"[^>]*onsubmit="addLocalEvent\(\); return false;">[\s\S]*?<button type="submit" data-clock-i18n="add">[\s\S]*?<\/button>[\s\S]*?<\/form>/,
    'the real Add action uses native form validation for the time input proxies');
console.log('Legacy startup checks passed: no modern APIs/storage/network response, optional UI failure, brightness and reminders without countdown.');
console.log('Server time checks passed: no external time API, repeated calibration, offline ticking, invalid timestamps and connection-warning recovery.');
