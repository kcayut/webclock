/* Optional ES5 device authorization. Private snapshots live in memory only. */
(function () {
    'use strict';
    var origin = window.webclockBase || window.location.origin || (window.location.protocol + '//' + window.location.host);
    var source = '', mode = 'unknown', identity = null, group = null, pending = null, phase = 'unknown';
    var generation = 0, sequence = 0, handled = {}, listeners = [], joining = 0, enrolling = false;
    var resources = {}, bound = false, checked = false, checking = false, lastIdentityCheck = 0;
    var applied = {display: 0, alarms: 0}, revisions = {}, commands = [], reporting = false, lastReport = 0;
    var MAX_LEASE = 300000;
    function wall() { return new Date().getTime(); }
    function mono() { return window.performance && typeof window.performance.now === 'function' ? window.performance.now() : wall(); }
    function number(value) { return typeof value === 'number' && isFinite(value); }
    function object(value) { return value && typeof value === 'object' && !Array.isArray(value); }
    function sameOrigin() { return source === origin; }
    function validIdentity(value) {
        var fields = ['device_id', 'owner_id', 'group_id', 'identity_revision'];
        if (!object(value)) return false;
        for (var i = 0; i < fields.length; i++) if (typeof value[fields[i]] !== 'string' || !value[fields[i]] || value[fields[i]].length > 256) return false;
        return number(value.credential_generation) && value.credential_generation >= 1 && Math.floor(value.credential_generation) === value.credential_generation &&
            number(value.assignment_revision) && value.assignment_revision >= 1 && Math.floor(value.assignment_revision) === value.assignment_revision;
    }
    function identityKey(value) {
        return value ? [value.device_id, value.owner_id, value.group_id, value.credential_generation,
            value.assignment_revision, value.identity_revision].join('|') : '';
    }
    function scope() { return source + '|' + (identity ? identityKey(identity) : 'public'); }
    function storageKey() { return 'webclock.deviceBound.' + source; }
    function markBound() {
        bound = true;
        try { window.localStorage.setItem(storageKey(), '1'); } catch (error) {}
    }
    function notify(type, resource) {
        var state = getState();
        for (var i = 0; i < listeners.length; i++) {
            try { listeners[i]({type: type, resource: resource || 'all', state: state}); } catch (error) {}
        }
    }
    function clear(reason, forget) {
        generation += 1;
        handled = {}; resources = {}; commands = []; revisions = {}; applied = {display: 0, alarms: 0};
        reporting = false;
        if (forget) { identity = null; group = null; pending = null; }
        notify(reason || 'clear');
    }
    function getState() {
        return {source: source, mode: mode, phase: phase, identity: identity, group: group, scope: scope(),
            sameOrigin: sameOrigin(), attempt_id: pending ? pending.attempt_id : null,
            generation: generation, shared: mode === 'self' && checked && (!sameOrigin() || phase === 'unpaired') && !bound && !identity && !pending};
    }
    function setSource(value, bootMode) {
        value = String(value || '').replace(/\/+$/, '');
        if (value !== origin && !/^https?:\/\/[A-Za-z0-9.\-:\[\]]+$/.test(value)) value = '';
        if (value === source) return;
        source = value; mode = sameOrigin() && (bootMode === 'self' || bootMode === 'managed') ? bootMode : 'unknown';
        identity = null; pending = null; phase = 'unknown'; checked = false; checking = false; joining += 1; enrolling = false;
        try { bound = window.localStorage.getItem(storageKey()) === '1'; } catch (error) { bound = true; }
        clear('source', true);
    }
    function ticket(channel) { return {source: source, generation: generation, sequence: ++sequence, channel: channel, wall: wall(), mono: mono()}; }
    function current(request) { return request.source === source && request.generation === generation; }
    function finish(request) {
        if (!current(request) || request.sequence <= (handled[request.channel] || 0)) return false;
        handled[request.channel] = request.sequence;
        return true;
    }
    function request(method, path, body, channel, callback, headers) {
        var stamp = ticket(channel), xhr = new XMLHttpRequest(), done = false;
        headers = headers || {};
        if (!source || (method !== 'GET' && !sameOrigin())) { callback({code: 'same_origin_required'}); return; }
        function complete(error) {
            if (done) return;
            done = true;
            if (!finish(stamp)) return;
            if (error) { callback(error, null, xhr, stamp); return; }
            if (xhr.status === 401 || xhr.status === 403) {
                var denial = null;
                try { denial = JSON.parse(xhr.responseText); } catch (invalidDenial) {}
                callback({code: denial && denial.code || 'device_authentication_required', status: xhr.status}, null, xhr, stamp); return;
            }
            var data = null;
            if (xhr.status !== 304) {
                try { data = JSON.parse(xhr.responseText); } catch (failure) { callback({code: 'invalid_response'}, null, xhr, stamp); return; }
            }
            if (xhr.status < 200 || (xhr.status >= 300 && xhr.status !== 304)) {
                callback({code: data && data.code || 'request_failed', status: xhr.status}, data, xhr, stamp);
            } else callback(null, data, xhr, stamp);
        }
        try {
            xhr.open(method, source + path, true);
            xhr.withCredentials = false; // Default same-origin cookies; never credentials to another origin.
            xhr.timeout = 8000;
            if (body !== null) xhr.setRequestHeader('Content-Type', 'application/json');
            for (var key in headers) if (Object.prototype.hasOwnProperty.call(headers, key)) xhr.setRequestHeader(key, headers[key]);
            xhr.onload = function () { complete(); };
            xhr.onerror = function () { complete({code: 'network_error'}); };
            xhr.ontimeout = function () { complete({code: 'timeout'}); };
            xhr.send(body === null ? null : JSON.stringify(body));
        } catch (error) { complete({code: 'network_error'}); }
    }
    function post(path, body, channel, callback) {
        if (!sameOrigin()) { callback({code: 'same_origin_required'}); return; }
        request('GET', '/api/csrf', null, channel + '-csrf', function (error, data) {
            if (error || !data || typeof data.csrf_token !== 'string') { callback(error || {code: 'invalid_response'}); return; }
            request('POST', path, body, channel, callback, {'X-CSRF-Token': data.csrf_token});
        });
    }
    function unauthorized(error) {
        if (error && (error.status === 401 || error.status === 403)) {
            if (error.code === 'csrf_failed') { phase = 'unknown'; checked = false; clear('authorization-check', true); checkIdentity(); return true; }
            markBound(); phase = 'revoked'; checked = true; checking = false; clear('revoked', true);
            return true;
        }
        return false;
    }
    function useIdentity(value, membership) {
        if (!validIdentity(value)) return false;
        var changed = identityKey(value) !== identityKey(identity);
        identity = value; pending = null; phase = 'active'; checked = true; markBound();
        group = object(membership) && membership.id === value.group_id && typeof membership.name === 'string' ?
            {id: membership.id, name: membership.name} : null;
        if (changed) clear('identity', false);
        return true;
    }
    function checkIdentity(callback) {
        callback = callback || function () {};
        if (!sameOrigin()) { checked = true; callback({code: 'same_origin_required'}); return; }
        checking = true; lastIdentityCheck = wall();
        request('GET', '/api/v2/device/identity', null, 'identity', function (error, data) {
            checking = false;
            if (error) {
                checked = error.status === 401 || error.status === 403 || error.status === 404;
                if ((error.status === 401 || error.status === 404) && !bound && mode === 'self' && !identity) {
                    phase = 'unpaired'; pending = null; notify('identity');
                } else unauthorized(error);
                callback(error); return;
            }
            if (data && data.status === 'active' && useIdentity(data.identity, data.group)) { callback(null, data); return; }
            if (data && data.status === 'pending' && typeof data.attempt_id === 'string' && number(data.expires_at) && data.expires_at > 0) {
                identity = null; group = null; pending = data; phase = 'pending'; checked = true; clear('pending', false);
                callback(null, data); return;
            }
            callback({code: 'invalid_response'});
        });
    }
    function discover(callback) {
        if (mode !== 'unknown') { callback(); return; }
        request('GET', '/api/health', null, 'health', function (error, data) {
            if (!error && data && data.status === 'ok' && (data.deployment_mode === 'self' || data.deployment_mode === 'managed')) {
                mode = data.deployment_mode; if (!sameOrigin()) checked = true;
            }
            callback(error);
        });
    }
    function checkLease(kind) {
        var item = resources[kind];
        if (!item) return false;
        var currentWall = wall(), currentMono = mono();
        var elapsed = Math.max(0, currentWall - item.wall, currentMono - item.mono);
        if (currentWall < item.lastWall || currentMono < item.lastMono || elapsed >= item.duration) {
            delete resources[kind]; notify('expired', kind); return false;
        }
        item.lastWall = currentWall; item.lastMono = currentMono;
        return true;
    }
    function expire() { checkLease('display'); checkLease('alarms'); }
    function leaseValue(data, stamp) {
        if (!data || !number(data.server_timestamp) || data.server_timestamp <= 0 || !object(data.lease) || !number(data.lease.issued_at) || !number(data.lease.expires_at)) return null;
        var duration = data.lease.expires_at - data.server_timestamp;
        if (duration <= 0 || duration > MAX_LEASE || data.lease.expires_at - data.lease.issued_at > MAX_LEASE || data.lease.issued_at > data.server_timestamp) return null;
        var elapsed = Math.max(0, wall() - stamp.wall, mono() - stamp.mono);
        if (elapsed >= duration) return null;
        return {wall: stamp.wall, mono: stamp.mono, lastWall: wall(), lastMono: mono(), duration: duration};
    }
    function header(xhr, key) { return typeof xhr.getResponseHeader === 'function' ? xhr.getResponseHeader(key) : null; }
    function fetchPrivate(kind, accept, failure) {
        expire();
        var old = resources[kind], currentIdentity = identityKey(identity);
        var headers = old && old.etag ? {'If-None-Match': old.etag} : {};
        request('GET', '/api/v2/device/' + (kind === 'alarms' ? 'browser-alarms' : 'display'), null, kind, function (error, data, xhr, stamp) {
            if (error) { unauthorized(error); expire(); failure(error); return; }
            if (!identity || identityKey(identity) !== currentIdentity) return;
            if (xhr.status === 304) {
                var renewalScope = header(xhr, 'X-WebClock-Identity-Revision');
                if (renewalScope && renewalScope !== identity.identity_revision) { phase = 'unknown'; checked = false; clear('identity', true); checkIdentity(); return; }
                if (!old || resources[kind] !== old || !checkLease(kind) || header(xhr, 'X-WebClock-Identity-Revision') !== identity.identity_revision) { failure({code: 'invalid_response'}); return; }
                data = {server_timestamp: Number(header(xhr, 'X-WebClock-Server-Timestamp')),
                    lease: {issued_at: Number(header(xhr, 'X-WebClock-Server-Timestamp')), expires_at: Number(header(xhr, 'X-WebClock-Lease-Expires-At'))}};
                var renewal = leaseValue(data, stamp);
                if (renewal) { renewal.etag = old.etag; resources[kind] = renewal; applied[kind] += 1; report(); }
                return;
            }
            if (!data || data.schema_version !== 3 || !validIdentity(data.identity)) { failure({code: 'invalid_response'}); return; }
            if (identityKey(data.identity) !== currentIdentity) { phase = 'unknown'; checked = false; clear('identity', true); checkIdentity(); return; }
            var lease = leaseValue(data, stamp);
            if (!lease) { failure({code: 'invalid_response'}); return; }
            try { if (accept(data, true) === false) throw new Error('Invalid snapshot'); }
            catch (invalid) { failure({code: 'invalid_response'}); return; }
            lease.etag = header(xhr, 'ETag'); resources[kind] = lease;
            applied[kind] += 1;
            if (kind === 'display') {
                ['config_revision', 'schedule_revision', 'holiday_revision'].forEach(function (key) { if (typeof data[key] === 'string') revisions[key] = data[key]; });
            }
            report();
        }, headers);
    }
    function publicTime(accept, failure) {
        request('GET', '/api/time', null, 'time', function (error, data) {
            if (error || !data || !number(data.server_timestamp) || data.server_timestamp <= 0) { failure(error || {code: 'invalid_response'}); return; }
            try { accept({server_timestamp: data.server_timestamp, events: [], public_time_only: true}, false); }
            catch (invalid) { failure({code: 'invalid_response'}); }
        });
    }
    function fetchData(kind, accept, failure) {
        failure = failure || function () {};
        if (enrolling) { if (kind === 'display') publicTime(accept, failure); return; }
        discover(function (error) {
            if (error) { if (kind === 'display') publicTime(accept, failure); else failure(error); return; }
            if (sameOrigin() && (!checked || (!identity && (wall() < lastIdentityCheck || wall() - lastIdentityCheck >= 15000)))) {
                if (!checking) checkIdentity(function () {
                    if (checked) fetchData(kind, accept, failure);
                    else if (kind === 'display') publicTime(accept, failure);
                    else failure({code: 'identity_unavailable'});
                });
                return;
            }
            if (identity && sameOrigin()) { fetchPrivate(kind, accept, failure); return; }
            if (!getState().shared) {
                if (kind === 'display') publicTime(accept, failure);
                else failure({code: 'device_authentication_required'});
                return;
            }
            request('GET', kind === 'alarms' ? '/api/v1/browser-alarms' : '/api/status?nocache=' + wall(), null, kind, function (error, data) {
                if (error) { failure(error); return; }
                try { if (accept(data, false) === false) throw new Error('Invalid snapshot'); }
                catch (invalid) { failure({code: 'invalid_response'}); }
            });
        });
    }
    function report() {
        if (!identity || !applied.display || reporting) return;
        var acknowledgements = [];
        for (var i = 0; i < commands.length; i++) if (applied.display > commands[i].display && applied.alarms > commands[i].alarms) acknowledgements.push(commands[i].id);
        if (!acknowledgements.length && wall() - lastReport < 30000) return;
        reporting = true; lastReport = wall();
        var body = {device_type: 'browser', capabilities: {display: true}};
        if (window.AlarmAudio && typeof window.AlarmAudio.isReady === 'function' && window.AlarmAudio.isReady()) body.capabilities.audio = true;
        for (var key in revisions) if (Object.prototype.hasOwnProperty.call(revisions, key)) body[key] = revisions[key];
        if (acknowledgements.length) body.acknowledged_commands = acknowledgements;
        post('/api/v2/device/status', body, 'report', function (error, data) {
            reporting = false;
            if (error) { unauthorized(error); return; }
            if (!data || !validIdentity(data.identity) || identityKey(data.identity) !== identityKey(identity)) { phase = 'unknown'; checked = false; clear('identity', true); return; }
            commands = commands.filter(function (command) { return acknowledgements.indexOf(command.id) < 0; });
            var added = false;
            if (Array.isArray(data.commands)) for (var i = 0; i < data.commands.length; i++) {
                var command = data.commands[i], known = false;
                for (var j = 0; j < commands.length; j++) if (commands[j].id === command.id) known = true;
                if (!known && command.action === 'sync' && typeof command.id === 'string') { commands.push({id: command.id, display: applied.display, alarms: applied.alarms}); added = true; }
            }
            if (added) notify('sync');
        });
    }
    function prepare(callback) {
        var attemptGeneration = ++joining, completed = callback;
        enrolling = true; checking = false; checked = false; clear('prepare', true);
        callback = function (error, data) { enrolling = false; completed(error, data); };
        post('/api/v2/device/join/prepare', {}, 'prepare', function (error, data) {
            if (attemptGeneration !== joining) return;
            if (error || !data || typeof data.attempt_id !== 'string' || !number(data.expires_at)) { unauthorized(error); callback(error || {code: 'invalid_response'}); return; }
            var expected = data.attempt_id;
            checkIdentity(function (checkError, result) {
                if (attemptGeneration !== joining) return;
                if (checkError || !result || result.status !== 'pending' || result.attempt_id !== expected) { callback({code: 'cookie_unconfirmed'}); return; }
                callback(null, result);
            });
        });
    }
    function join(attemptId, code, callback) {
        var attemptGeneration = ++joining, completed = callback;
        enrolling = true;
        callback = function (error, data) { enrolling = false; completed(error, data); };
        checkIdentity(function (error, before) {
            if (attemptGeneration !== joining) return;
            if (error || !before || (before.status === 'pending' && before.attempt_id !== attemptId)) { callback({code: 'join_attempt_conflict'}); return; }
            post('/api/v2/device/join', {attempt_id: attemptId, code: code}, 'join', function (joinError, joined) {
                code = '';
                if (attemptGeneration !== joining) return;
                if (joinError || !joined || joined.schema_version !== 3 || !validIdentity(joined.identity)) { unauthorized(joinError); callback(joinError || {code: 'invalid_response'}); return; }
                checkIdentity(function (checkError, after) {
                    if (attemptGeneration !== joining) return;
                    if (checkError || !after || after.status !== 'active' || identityKey(after.identity) !== identityKey(joined.identity)) { callback({code: 'cookie_unconfirmed'}); return; }
                    try { window.localStorage.setItem('webclock.deviceChanged.' + source, String(wall()) + '.' + sequence); } catch (failure) {}
                    callback(null, after); notify('joined');
                });
            });
        });
    }
    function leave(callback) {
        if (!sameOrigin() || !identity) { callback({code: 'device_authentication_required'}); return; }
        var attemptGeneration = ++joining;
        enrolling = true; checking = false; phase = 'leaving';
        clear('leaving', false);
        post('/api/v2/device/leave', {}, 'leave', function (error, data) {
            if (attemptGeneration !== joining) return;
            enrolling = false;
            if (error || !data || data.status !== 'left') {
                phase = 'active'; unauthorized(error);
                callback(error || {code: 'invalid_response'}); return;
            }
            phase = 'unpaired'; checked = true; clear('left', true);
            try { window.localStorage.setItem('webclock.deviceChanged.' + source, String(wall()) + '.' + sequence); } catch (failure) {}
            callback(null, data);
        });
    }
    function resume() { expire(); if (sameOrigin() && !enrolling && !checking) checkIdentity(); }
    window.WebClockDeviceSession = {setSource: setSource, getState: getState, checkIdentity: checkIdentity,
        prepare: prepare, join: join, leave: leave, cancelJoin: function () { joining += 1; enrolling = false; checked = false; generation += 1; handled = {}; reporting = false; },
        fetchDisplay: function (accept, failure) { fetchData('display', accept, failure); },
        fetchAlarms: function (accept, failure) { fetchData('alarms', accept, failure); },
        hasLease: checkLease, expire: expire, subscribe: function (callback) { listeners.push(callback); }};
    document.addEventListener('visibilitychange', function () { if (!document.hidden) resume(); });
    window.addEventListener('pageshow', resume);
    window.addEventListener('storage', function (event) {
        if (event.key === 'webclock.deviceChanged.' + source || event.key === storageKey()) {
            phase = 'unknown'; checked = false; joining += 1; enrolling = false; clear('identity', true); checkIdentity();
        }
    });
    setInterval(expire, 1000);
}());
