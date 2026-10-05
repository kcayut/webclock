// Run with node tests/test_device_enrollment.js. No browser libraries required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const sessionCode = fs.readFileSync(path.join(root, 'static/device-session.js'), 'utf8');
const panelCode = fs.readFileSync(path.join(root, 'static/device-enrollment.js'), 'utf8');
for (const code of [sessionCode, panelCode]) assert.doesNotMatch(code, /\b(?:const|let|async)\b|=>|\?\./, 'optional scripts must be ES5');
function browser(mode = 'managed', storageWorks = true) {
    let now = 1800000000000, elapsed = 0;
    const requests = [], timers = [], changes = [], stored = {}, handlers = {}, nodes = {};
    const node = id => nodes[id] || (nodes[id] = {style: {}, value: '', textContent: '', disabled: false, focus() { this.focused = true; }});
    const listen = (name, callback) => (handlers[name] || (handlers[name] = [])).push(callback);
    const window = {location: {origin: 'https://clock.example'}, performance: {now: () => elapsed}, addEventListener: listen, confirm: () => true,
        localStorage: {getItem(key) { if (!storageWorks) throw Error('storage unavailable'); return stored[key] || null; },
            setItem(key, value) { if (!storageWorks) throw Error('storage unavailable'); stored[key] = value; }},
        WebClockEnrollmentTranslations: {'zh-TW': {}}, currentLanguage: 'zh-TW'};
    const context = vm.createContext({window, document: {hidden: false, documentElement: {lang: 'zh-TW'},
        getElementById: node, querySelectorAll: () => [], addEventListener: listen},
        Date: function () { this.getTime = () => now; },
        setInterval: (callback, delay) => timers.push({callback, delay}),
        XMLHttpRequest: function () {
            this.headers = {}; this.responseHeaders = {};
            this.open = (method, url) => { this.method = method; this.url = url; };
            this.setRequestHeader = (key, value) => { this.headers[key] = value; };
            this.getResponseHeader = key => this.responseHeaders[key] || null;
            this.send = value => { this.body = value; requests.push(this); };
        }, Promise: undefined, fetch: undefined, Intl: undefined});
    vm.runInContext(sessionCode, context);
    const session = window.WebClockDeviceSession;
    session.subscribe(change => changes.push(change));
    session.setSource(window.location.origin, mode);
    function pending(suffix) {
        const found = [...requests].reverse().find(request => !request.replied && request.url.endsWith(suffix));
        assert.ok(found, 'Expected request: ' + suffix + '\n' + requests.map(r => r.method + ' ' + r.url).join('\n'));
        return found;
    }
    function reply(request, data, status = 200, headers = {}) {
        request.replied = true; request.status = status; request.responseHeaders = headers;
        request.responseText = typeof data === 'string' ? data : JSON.stringify(data); request.onload();
    }
    function respond(suffix, data, status, headers) { reply(pending(suffix), data, status, headers); }
    function csrf() { respond('/api/csrf', {csrf_token: 'test-csrf'}); }
    const identity = {device_id: 'device-a', owner_id: 'owner', group_id: 'group-a', credential_generation: 1, assignment_revision: 1, identity_revision: 'scope-a'};
    function activate() {
        session.checkIdentity(); respond('/identity', {status: 'active', identity, group: {id: identity.group_id, name: 'Living room'}});
    }
    function snapshot(extra = {}, who = identity) {
        return {schema_version: 3, identity: who, server_timestamp: now, lease: {issued_at: now, expires_at: now + 300000},
            settings: {mode: 'black', brightness: 0, timezone_offset: 8, language: 'zh-TW', time_format: '24h'},
            events: [{text: 'PRIVATE EVENT'}], next_event: null, config_revision: 'c1', schedule_revision: 's1', holiday_revision: 'h1', ...extra};
    }
    return {window, context, session, requests, stored, changes, node, identity, pending, reply, respond, csrf, activate, snapshot,
        panel() { vm.runInContext(panelCode, context); }, now: () => now,
        advance(ms) { now += ms; elapsed += ms; }, rollback(ms) { now -= ms; },
        dispatch(name, event = {}) { (handlers[name] || []).forEach(fn => fn(event)); }};
}
const page = browser();
assert.equal(page.requests.length, 0, 'loading the clock never creates an attempt');
page.panel();
assert.equal(page.requests.length, 0, 'loading enrollment is also passive');
page.node('device-join-open').onclick();
page.csrf();
assert.deepEqual(JSON.parse(page.pending('/join/prepare').body), {});
page.respond('/join/prepare', {attempt_id: 'attempt-a', expires_at: page.now() + 600000}, 201);
assert.equal(page.node('device-join-submit').disabled, true, 'cookie roundtrip is required');
page.respond('/identity', {status: 'pending', attempt_id: 'attempt-a', expires_at: page.now() + 600000});
assert.equal(page.node('device-join-submit').disabled, false);
page.node('device-join-code').value = 'abc234';
page.node('device-join-form').onsubmit({preventDefault() {}});
assert.equal(page.node('device-join-code').value, '', 'code removed from input immediately');
page.respond('/identity', {status: 'pending', attempt_id: 'attempt-a', expires_at: page.now() + 600000});
page.csrf();
assert.deepEqual(JSON.parse(page.pending('/join').body), {attempt_id: 'attempt-a', code: 'ABC234'});
assert.equal(page.pending('/join').headers['X-CSRF-Token'], 'test-csrf');
page.respond('/join', {schema_version: 3, identity: page.identity, server_timestamp: page.now()}, 201);
assert.equal(page.node('device-join-status').textContent, 'join_submitting', 'join response is not yet cookie confirmation');
page.respond('/identity', {status: 'active', identity: page.identity, group: {id: page.identity.group_id, name: 'Living room'}});
assert.equal(page.node('device-join-status').textContent, 'join_connected');
assert.equal(page.node('device-join-fields').style.display, 'none', 'joined devices hide the code fields');
assert.equal(page.node('device-join-open').style.display, 'none', 'joined devices hide the join entry');
assert.equal(page.node('device-group-name').textContent, 'Living room');
assert.equal(page.node('device-group-leave').style.display, '');
assert.ok(!JSON.stringify(page.stored).includes('ABC234'));
assert.ok(!JSON.stringify(page.stored).includes('attempt-a'));
let applied = [];
page.session.fetchDisplay(data => { applied.push(data.events[0].text); return true; });
page.respond('/display', page.snapshot(), 200, {ETag: '"display-a"'});
assert.deepEqual(applied, ['PRIVATE EVENT']);
assert.equal(page.session.hasLease('display'), true);
assert.ok(!JSON.stringify(page.stored).includes('PRIVATE EVENT'));
page.advance(299000);
page.session.fetchDisplay(() => assert.fail('304 must not reapply stale content'));
page.respond('/display', null, 304);
page.advance(1001); page.session.expire();
assert.equal(page.session.hasLease('display'), false, '304 without explicit scoped renewal cannot extend a lease');
assert.ok(page.changes.some(event => event.type === 'expired' && event.resource === 'display'));

const denial = browser(); denial.activate();
denial.session.fetchDisplay(() => true); denial.respond('/display', denial.snapshot());
denial.session.fetchDisplay(() => assert.fail('stale success must not revive revoked content'));
const old = denial.pending('/display');
denial.session.fetchDisplay(() => true); denial.respond('/display', '<html>denied</html>', 403);
assert.equal(denial.session.getState().phase, 'revoked', '403 clears even with non-JSON body');
assert.equal(denial.session.hasLease('display'), false);
denial.reply(old, denial.snapshot());
assert.equal(denial.session.getState().identity, null);
assert.ok(!denial.requests.some(request => request.url.includes('/api/status')));

// Host-managed moves and temporary suspension keep the credential, while each
// assignment revision partitions all private responses and cached snapshots.
const moved = browser(); moved.activate();
moved.session.fetchDisplay(() => true); moved.respond('/display', moved.snapshot());
moved.session.fetchAlarms(() => true); moved.respond('/browser-alarms', moved.snapshot());
moved.session.fetchAlarms(() => assert.fail('the former group cannot reappear'));
const oldGroupAlarms = moved.pending('/browser-alarms');
const movedIdentity = {...moved.identity, group_id: 'group-b', assignment_revision: 2, identity_revision: 'scope-b'};
moved.session.fetchDisplay(() => assert.fail('new group content waits for identity confirmation'));
moved.respond('/display', moved.snapshot({}, movedIdentity));
assert.equal(moved.session.hasLease('display'), false); assert.equal(moved.session.hasLease('alarms'), false);
moved.respond('/identity', {status: 'active', identity: movedIdentity, group: {id: 'group-b', name: 'New room'}});
assert.equal(moved.session.getState().group.name, 'New room');
moved.reply(oldGroupAlarms, moved.snapshot());
assert.equal(moved.session.hasLease('alarms'), false);
let restoredDisplays = 0;
moved.session.fetchDisplay(() => { restoredDisplays++; return true; }); moved.respond('/display', moved.snapshot({}, movedIdentity));
moved.session.fetchAlarms(() => true); moved.respond('/browser-alarms', moved.snapshot({}, movedIdentity));
moved.session.fetchDisplay(() => assert.fail('disabled content is not accepted'));
moved.respond('/display', {code: 'device_disabled'}, 403);
assert.equal(moved.session.hasLease('display'), false); assert.equal(moved.session.hasLease('alarms'), false);
assert.equal(moved.session.getState().shared, false, 'Temporary suspension never falls back to shared content');
const resumedIdentity = {...movedIdentity, assignment_revision: 4, identity_revision: 'scope-restored'};
moved.advance(15000);
moved.session.fetchDisplay(() => { restoredDisplays++; return true; });
moved.respond('/identity', {status: 'active', identity: resumedIdentity, group: {id: 'group-b', name: 'New room'}});
moved.respond('/display', moved.snapshot({}, resumedIdentity));
assert.equal(restoredDisplays, 2, 'A restored authorization resumes with the existing cookie on the identity poll');
assert.equal(moved.session.getState().identity.credential_generation, 1);
assert.ok(!moved.requests.some(request => /\/join(?:\/prepare)?$/.test(request.url)), 'Moving and resuming never create a join attempt');

const renewal = browser(); renewal.activate();
renewal.session.fetchAlarms(() => true); renewal.respond('/browser-alarms', renewal.snapshot(), 200, {ETag: '"alarm-a"'});
renewal.advance(250000); renewal.session.fetchAlarms(() => true);
renewal.respond('/browser-alarms', null, 304, {'X-WebClock-Identity-Revision': 'scope-a',
    'X-WebClock-Server-Timestamp': String(renewal.now()), 'X-WebClock-Lease-Expires-At': String(renewal.now() + 300000)});
renewal.advance(60000); assert.equal(renewal.session.hasLease('alarms'), true);
renewal.rollback(1); renewal.session.expire();
assert.equal(renewal.session.hasLease('alarms'), false, 'wall clock rollback cannot lengthen a lease');

const change = browser(); change.activate();
change.session.fetchDisplay(() => assert.fail('old-source data accepted'));
const oldSource = change.pending('/display');
change.session.setSource('https://other.example', 'self');
change.reply(oldSource, change.snapshot());
change.session.fetchDisplay(() => true);
change.respond('/api/health', {status: 'ok', deployment_mode: 'self'});
const shared = change.requests[change.requests.length - 1];
assert.ok(shared.url.includes('/api/status?'));
assert.equal(shared.withCredentials, false);
assert.ok(!change.requests.some(request => request.url.startsWith('https://other.example/api/v2')));

const loss = browser(); loss.panel(); loss.node('device-join-open').onclick(); loss.csrf();
loss.respond('/join/prepare', {attempt_id: 'pending', expires_at: loss.now() + 600000});
loss.respond('/identity', {code: 'device_authentication_required'}, 401);
assert.equal(loss.node('device-join-submit').disabled, true);
assert.equal(loss.node('device-join-status').textContent, 'join_cookie');

const conflict = browser(); conflict.panel(); conflict.node('device-join-open').onclick(); conflict.csrf();
conflict.respond('/join/prepare', {attempt_id: 'first-tab', expires_at: conflict.now() + 600000});
conflict.respond('/identity', {status: 'pending', attempt_id: 'second-tab', expires_at: conflict.now() + 600000});
assert.equal(conflict.node('device-join-submit').disabled, true);
conflict.node('device-join-cancel').onclick();
assert.equal(conflict.node('device-join-panel').style.display, 'none');
assert.equal(conflict.node('device-join-open').style.display, '', 'cancel restores the join entry immediately');

for (const mode of ['managed', 'self']) {
    const blocked = browser(mode, false);
    blocked.session.fetchDisplay(() => assert.fail('unconfirmed storage/cookie must not share private data'));
    blocked.respond('/identity', {code: 'device_authentication_required'}, 401);
    assert.ok(!blocked.requests.some(request => request.url.includes('/api/status')));
}
const network = browser('self');
network.session.fetchDisplay(() => assert.fail('network failure cannot prove unpaired self mode'));
network.pending('/identity').onerror();
assert.equal(network.session.getState().shared, false);
const tab = browser(); tab.activate();
tab.session.fetchDisplay(() => true); tab.respond('/display', tab.snapshot());
tab.dispatch('storage', {key: 'webclock.deviceChanged.https://clock.example'});
assert.equal(tab.session.hasLease('display'), false);
assert.equal(tab.session.getState().identity, null);
console.log('Device enrollment/session checks passed: ES5, manual intent, cookie roundtrip, CSRF, lease, revocation, source isolation, storage failure and multiple tabs.');

// Unpaired managed displays still receive public server time, never shared data.
const publicClock = browser();
let calibration;
publicClock.session.fetchDisplay(data => { calibration = data; });
publicClock.respond('/identity', {code: 'device_authentication_required'}, 401);
publicClock.respond('/api/time', {server_timestamp: publicClock.now()});
assert.equal(calibration.public_time_only, true);
assert.deepEqual(Array.from(calibration.events), []);
assert.ok(!publicClock.requests.some(request => request.url.includes('/api/status') || request.url.includes('/join')));

// A 304 is an authorization renewal and a successful sync application.
const sync = browser(); sync.activate();
sync.session.fetchDisplay(() => true); sync.respond('/display', sync.snapshot(), 200, {ETag: '"stable-display"'});
sync.session.fetchAlarms(() => true); sync.respond('/browser-alarms', sync.snapshot(), 200, {ETag: '"stable-alarms"'});
sync.csrf();
assert.equal(JSON.parse(sync.pending('/status').body).capabilities.display, true);
sync.respond('/status', {identity: sync.identity, commands: [{id: 'command-1', action: 'sync'}]});
function renew(page, endpoint) {
    page.respond(endpoint, null, 304, {'X-WebClock-Identity-Revision': page.identity.identity_revision,
        'X-WebClock-Server-Timestamp': String(page.now()), 'X-WebClock-Lease-Expires-At': String(page.now() + 300000)});
}
sync.session.fetchDisplay(() => assert.fail('304 reapplied display')); renew(sync, '/display');
assert.ok(!sync.requests.some(request => !request.replied && request.url.endsWith('/api/csrf')), 'display alone cannot ACK both snapshots');
sync.session.fetchAlarms(() => assert.fail('304 reapplied alarms')); renew(sync, '/browser-alarms');
sync.csrf();
assert.deepEqual(JSON.parse(sync.pending('/status').body).acknowledged_commands, ['command-1']);
sync.respond('/status', {identity: sync.identity, commands: []});
sync.advance(31000); sync.session.fetchDisplay(() => true); renew(sync, '/display');
sync.csrf();
assert.ok(sync.pending('/status'), 'unchanged snapshots continue heartbeats');
sync.respond('/status', {identity: sync.identity, commands: []});

const recoverCsrf = browser(); recoverCsrf.activate();
recoverCsrf.session.fetchDisplay(() => true); recoverCsrf.respond('/display', recoverCsrf.snapshot());
recoverCsrf.csrf(); recoverCsrf.respond('/status', {code: 'csrf_failed'}, 403);
assert.equal(recoverCsrf.session.hasLease('display'), false, '403 clears private data immediately while identity is rechecked');
recoverCsrf.respond('/identity', {status: 'active', identity: recoverCsrf.identity});
assert.equal(recoverCsrf.session.getState().phase, 'active', 'management CSRF rotation does not revoke the independent device');

const malformed = browser(); malformed.activate();
malformed.session.fetchDisplay(() => true); malformed.respond('/display', malformed.snapshot());
malformed.session.fetchDisplay(() => assert.fail('HTML accepted'));
malformed.respond('/display', '<html>login</html>');
assert.equal(malformed.session.hasLease('display'), true, 'bad payload only retains the already-authorized lease');
malformed.session.fetchDisplay(() => true);
malformed.pending('/display').ontimeout();
malformed.advance(300001); malformed.dispatch('pageshow');
assert.equal(malformed.session.hasLease('display'), false, 'resume expires stale content before identity network response');

const wrongScope = browser(); wrongScope.activate();
wrongScope.session.fetchDisplay(() => true); wrongScope.respond('/display', wrongScope.snapshot(), 200, {ETag: '"a"'});
wrongScope.session.fetchDisplay(() => true);
wrongScope.respond('/display', null, 304, {'X-WebClock-Identity-Revision': 'other-scope'});
assert.equal(wrongScope.session.hasLease('display'), false, 'changed 304 scope clears private content immediately');
assert.equal(wrongScope.session.getState().identity, null);
console.log('Public calibration, valid 304 heartbeat/sync ACK, CSRF recovery, invalid payload and resume expiry checks passed.');

const canceled = browser(); canceled.panel(); canceled.node('device-join-open').onclick();
canceled.node('device-join-cancel').onclick(); canceled.csrf();
assert.ok(!canceled.requests.some(request => request.url.endsWith('/join/prepare')), 'canceling before CSRF returns prevents a later prepare write');
console.log('Canceled enrollment cannot send a delayed write.');

const membership = browser(); membership.activate(); membership.panel();
assert.equal(membership.node('device-join-panel').style.display, 'block', 'reload restores membership without opening enrollment');
assert.equal(membership.node('device-join-code').disabled, true);
membership.node('device-join-retry').onclick();
const checksBeforeResume = membership.requests.length;
membership.dispatch('pageshow');
assert.equal(membership.requests.length, checksBeforeResume, 'resume cannot supersede a manual recheck and strand its callback');
membership.respond('/identity', {status: 'active', identity: membership.identity, group: {id: membership.identity.group_id, name: 'Renamed room'}});
assert.equal(membership.node('device-join-retry').disabled, false);
assert.equal(membership.node('device-group-name').textContent, 'Renamed room', 'recheck fetches the current group name');
assert.ok(!membership.requests.some(request => request.url.endsWith('/join/prepare')), 'rechecking membership never starts another join');
membership.session.fetchDisplay(() => true); membership.respond('/display', membership.snapshot());
membership.session.fetchAlarms(() => true); membership.respond('/browser-alarms', membership.snapshot());
membership.session.fetchDisplay(() => assert.fail('in-flight private display revived after leave'));
const lateDisplay = membership.pending('/display');
membership.stored.localReminder = 'keep me';
membership.window.confirm = () => false;
membership.node('device-group-leave').onclick();
assert.equal(membership.session.hasLease('display'), true, 'canceling leave does not change membership');
membership.window.confirm = () => true;
membership.node('device-group-leave').onclick();
assert.equal(membership.session.hasLease('display'), false);
assert.equal(membership.session.hasLease('alarms'), false, 'leaving immediately clears both private leases');
membership.csrf();
assert.deepEqual(JSON.parse(membership.pending('/leave').body), {});
membership.respond('/leave', {status: 'left'});
membership.reply(lateDisplay, membership.snapshot());
assert.equal(membership.session.getState().identity, null);
assert.equal(membership.session.getState().group, null);
assert.equal(membership.node('device-group-name').textContent, '');
assert.equal(membership.node('device-join-panel').style.display, 'none');
assert.equal(membership.node('device-join-open').style.display, '');
assert.equal(membership.stored.localReminder, 'keep me');
assert.ok(membership.stored['webclock.deviceChanged.https://clock.example'], 'other tabs are told to discard their old identity');
assert.equal(membership.session.getState().shared, false, 'leaving cannot fall back to anonymous private data');
membership.node('device-join-open').onclick(); membership.csrf();
assert.ok(membership.pending('/join/prepare'), 'a new manual join remains available');

for (const failure of ['network', 'storage']) {
    const failed = browser(); failed.activate(); failed.panel();
    failed.node('device-group-leave').onclick(); failed.csrf();
    if (failure === 'network') failed.pending('/leave').onerror();
    else failed.respond('/leave', {code: 'storage_failure'}, 500);
    assert.equal(failed.node('device-join-status').textContent, 'join_leave_failed');
    assert.equal(failed.session.getState().identity.device_id, failed.identity.device_id, 'failed leave is never shown as successful');
    assert.equal(failed.node('device-group-leave').disabled, false);
    failed.node('device-join-retry').onclick();
    failed.respond('/identity', {status: 'active', identity: failed.identity, group: {id: failed.identity.group_id, name: 'Still joined'}});
    assert.equal(failed.node('device-group-name').textContent, 'Still joined');
}
console.log('Membership UI checks passed: restore, real recheck, hidden code, confirmed leave, stale responses, local reminders and failed leave.');
