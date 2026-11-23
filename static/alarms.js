/* Optional self-hosted alarms. The clock starts before this ES5 script loads. */
(function () {
    'use strict';
    var bell = document.getElementById('alarm-bell');
    if (!bell) return;
    var message = document.getElementById('alarm-message');
    var session = window.WebClockDeviceSession, privateData = false;
    var source = '', queue = [], active = [], handled = {}, dismissed = [];
    var cachedRingtone = null;
    var enabled = 0, confirmed = false, vibrating = false;
    var baseTime = null, baseElapsedTime = 0, requestNumber = 0, lastTouch = -1000, lastTone = -1600;
    var RING_LIMIT = 60 * 60 * 1000;

    function text(node, value) {
        if (node.textContent !== value) node.textContent = value;
    }
    function deviceNow() { return new Date().getTime(); }
    function elapsedNow() {
        return window.performance && typeof window.performance.now === 'function' ? window.performance.now() : deviceNow();
    }
    function now() { return baseTime === null ? deviceNow() : baseTime + elapsedNow() - baseElapsedTime; }
    function sourceUrl() { return window.serverUrl || window.webclockBase || window.location.origin; }
    function sourceScope() { return session ? session.getState().scope : sourceUrl(); }
    function storageKey() { return 'webclock.dismissedAlarms.' + source; }
    function ready() { return !!(window.AlarmAudio && window.AlarmAudio.isReady()); }
    function audible() {
        for (var i = 0; i < queue.length; i++) if (isAudible(queue[i])) return true;
        return false;
    }
    function isAudible(item) { return item.sound !== 'silent' && item.volume !== 0; }
    function ringingAlarm() {
        for (var i = 0; i < active.length; i++) if (isAudible(active[i])) return active[i];
        return null;
    }
    function clearRingtone() {
        var previous = cachedRingtone;
        cachedRingtone = null;
        if (previous && previous.cancel) previous.cancel();
    }
    function prepareRingtone(ringing, instant) {
        var audio = window.AlarmAudio;
        var local = window.webclockBase || window.location.origin;
        if (!ready() || sourceUrl() !== local || !audio.loadRingtone) { clearRingtone(); return; }
        var next = ringing;
        if (!next) {
            for (var i = 0; i < queue.length; i++) {
                var item = queue[i];
                if (item.starts_at > instant && (!next || item.starts_at < next.starts_at) &&
                        isAudible(item) && audio.isRingtoneId(item.custom_sound)) next = item;
            }
        }
        var id = next && next.custom_sound;
        if (!audio.isRingtoneId(id)) { clearRingtone(); return; }
        if (cachedRingtone && cachedRingtone.id === id && elapsedNow() < cachedRingtone.retryAt) return;
        var audience = privateData ? 'device' : 'self', scope = source;
        if (audience === 'self' && document.body.getAttribute('data-deployment-mode') !== 'self') return;
        clearRingtone();
        var entry = {id: id, retryAt: Infinity, buffer: null};
        cachedRingtone = entry;
        entry.cancel = audio.loadRingtone(id, audience, function (buffer) {
            entry.buffer = buffer;
            if (!buffer) entry.retryAt = elapsedNow() + 15000;
        }, function () {
            return cachedRingtone === entry && sourceScope() === scope && sourceUrl() === local &&
                (!privateData || session.hasLease('alarms'));
        });
    }
    function render() {
        bell.style.display = enabled || active.length ? 'block' : 'none';
        var label = t('alarm_set');
        if (active.length) label = t(confirmed ? 'alarm_second_tap' : 'alarm_first_tap');
        else if (audible()) label += ' · ' + t(ready() ? 'alarm_sound_ready' : 'alarm_enable_sound');
        bell.setAttribute('aria-label', label);
        bell.title = label;
        bell.className = ready() ? 'sound-ready' : '';
        message.style.display = active.length ? 'block' : 'none';
        if (active.length) {
            text(document.getElementById('alarm-name'), t('alarm_ringing') + ' · ' + active[0].name +
                (active.length > 1 ? ' (+' + (active.length - 1) + ')' : ''));
            text(document.getElementById('alarm-prompt'), t(confirmed ? 'alarm_second_tap' : 'alarm_first_tap'));
        }
        text(document.getElementById('alarm-help'), t('alarm_sound_hint'));
        text(document.getElementById('alarm-manage'), t('alarm_manage'));
    }
    function stopRing(save) {
        if (save) {
            for (var i = 0; i < active.length; i++) {
                dismissed.push({id: active[i].occurrence_id, starts_at: active[i].starts_at});
            }
            dismissed = dismissed.filter(function (item) { return item.starts_at > now() - 60000; });
            if (!privateData) writeStoredJson(storageKey(), dismissed);
        }
        if (vibrating) window.AlarmAudio.vibrate(0);
        vibrating = false;
        active = [];
        clearRingtone();
        text(document.getElementById('alarm-name'), '');
        text(document.getElementById('alarm-prompt'), '');
        confirmed = false;
        document.body.classList.remove('alarm-ringing');
        if (window.AlarmAudio) window.AlarmAudio.stop();
        render();
    }
    function expireRings(instant) {
        if (!active.length) return;
        var ringing = ringingAlarm();
        var expired = [], remaining = [];
        for (var i = 0; i < active.length; i++) {
            if (instant - active[i].starts_at >= RING_LIMIT) {
                expired.push(active[i]);
                handled[active[i].occurrence_id] = instant;
            } else {
                remaining.push(active[i]);
            }
        }
        if (!expired.length) return;
        active = remaining;
        if (!active.length) {
            stopRing(false);
            return;
        }
        if (ringing !== ringingAlarm()) {
            if (window.AlarmAudio) window.AlarmAudio.stop();
            lastTone = -1600;
        }
        render();
    }
    function accept(data) {
        if (!data || !Array.isArray(data.alarms) || data.alarms.length > 1000 ||
                !Array.isArray(data.enabled_ids) || data.enabled_ids.length > 1000 ||
                typeof data.server_timestamp !== 'number' || !isFinite(data.server_timestamp) ||
                typeof data.enabled_count !== 'number' || data.enabled_count < 0 || data.enabled_count > 1000) {
            throw new Error('Invalid alarm response');
        }
        for (var i = 0; i < data.alarms.length; i++) {
            var item = data.alarms[i];
            if (!item || typeof item.id !== 'string' || typeof item.occurrence_id !== 'string' || typeof item.name !== 'string' ||
                    typeof item.starts_at !== 'number' || !isFinite(item.starts_at) ||
                    ['bell', 'beep', 'digital', 'chime', 'melody', 'pulse', 'sonar', 'silent'].indexOf(item.sound) < 0 ||
                    (item.volume !== undefined && (typeof item.volume !== 'number' || !isFinite(item.volume) ||
                     item.volume < 0 || item.volume > 100 || Math.floor(item.volume) !== item.volume))) {
                throw new Error('Invalid alarm occurrence');
            }
        }
        queue = data.alarms;
        enabled = data.enabled_count;
        baseTime = data.server_timestamp;
        baseElapsedTime = elapsedNow();
        var ringingCount = active.length;
        var ringing = ringingAlarm();
        active = active.filter(function (item) { return data.enabled_ids.indexOf(item.id) >= 0; });
        if (ringing !== ringingAlarm() && window.AlarmAudio) window.AlarmAudio.stop();
        if (ringingCount && !active.length) stopRing(false);
        for (var key in handled) if (handled[key] < now() - 60000) delete handled[key];
        tick();
    }
    function reset() {
        requestNumber += 1;
        queue = []; enabled = 0; handled = {}; dismissed = []; baseTime = null;
        stopRing(false);
    }
    function poll() {
        var target = sourceUrl();
        var nextScope = sourceScope();
        if (nextScope !== source) {
            stopRing(false);
            source = nextScope;
            privateData = !!(session && session.getState().identity);
            queue = [];
            enabled = 0;
            baseTime = null;
            handled = {};
            dismissed = privateData ? [] : readStoredJson(storageKey(), []);
            if (!Array.isArray(dismissed)) dismissed = [];
            dismissed = dismissed.filter(function (item) {
                return item && typeof item.id === 'string' && typeof item.starts_at === 'number';
            }).slice(-1000);
            for (var i = 0; i < dismissed.length; i++) handled[dismissed[i].id] = dismissed[i].starts_at;
        }
        if (session) {
            session.fetchAlarms(function (data, isPrivate) {
                if (source !== sourceScope()) { reset(); source = sourceScope(); }
                privateData = isPrivate;
                accept(data);
                return true;
            });
            return;
        }
        if (!document.body.getAttribute || document.body.getAttribute('data-deployment-mode') !== 'self') return;
        if (target !== (window.webclockBase || window.location.origin)) return;
        var sequence = ++requestNumber;
        var xhr = new XMLHttpRequest();
        xhr.open('GET', target + '/api/v1/browser-alarms', true);
        xhr.timeout = 8000;
        xhr.withCredentials = false;
        function failure() {
            /* Alarm polling faults stay quiet; loaded alarms and the clock keep running. */
        }
        xhr.onload = function () {
            if (sequence !== requestNumber || target !== sourceUrl()) return;
            if (xhr.status !== 200) { failure(); return; }
            try { accept(JSON.parse(xhr.responseText)); } catch (error) { failure(); }
        };
        xhr.onerror = xhr.ontimeout = failure;
        try { xhr.send(); } catch (error) { failure(); }
    }
    function tick() {
        if (session) session.expire();
        if (source !== sourceScope()) { poll(); return; }
        if (privateData && !session.hasLease('alarms')) return;
        var instant = now();
        expireRings(instant);
        for (var i = 0; i < queue.length; i++) {
            var item = queue[i];
            // Never replay an alarm missed while the page was suspended for a minute or longer.
            if (item.starts_at <= instant && instant - item.starts_at < 60000 &&
                    !Object.prototype.hasOwnProperty.call(handled, item.occurrence_id)) {
                handled[item.occurrence_id] = item.starts_at;
                if (!active.length && window.activeSettings && window.activeSettings.alarm_vibration && window.AlarmAudio) {
                    vibrating = window.AlarmAudio.vibrate();
                }
                active.push(item);
                document.body.classList.add('alarm-ringing');
            }
        }
        var ringing = ringingAlarm(), audio = window.AlarmAudio;
        prepareRingtone(ringing, instant);
        if (ringing && audio && elapsedNow() - lastTone >= 1600 &&
                (!audio.isRingtonePlaying || !audio.isRingtonePlaying())) {
            var volume = ringing.volume === undefined ? 100 : ringing.volume;
            var buffer = cachedRingtone && cachedRingtone.id === ringing.custom_sound && cachedRingtone.buffer;
            if (!buffer || !audio.playRingtone(buffer, volume)) {
                audio.play(ringing.sound, volume);
            }
            lastTone = elapsedNow();
        }
        render();
    }
    function tap(event) {
        if (event.type === 'click' && elapsedNow() - lastTouch < 800) {
            event.preventDefault();
            event.stopPropagation();
            if (event.stopImmediatePropagation) event.stopImmediatePropagation();
            return;
        }
        if (!active.length) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.stopImmediatePropagation) event.stopImmediatePropagation();
        if (event.type === 'touchend') lastTouch = elapsedNow();
        if (confirmed) stopRing(true);
        else { confirmed = true; render(); }
    }
    bell.onclick = function () {
        if (window.AlarmAudio) window.AlarmAudio.unlock('bell');
        tick();
    };
    document.addEventListener('touchend', tap, true);
    document.addEventListener('click', tap, true);
    document.addEventListener('keydown', function (event) {
        if (!event.repeat && (event.keyCode === 13 || event.keyCode === 32)) tap(event);
    }, true);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { tick(); poll(); } });
    window.addEventListener('pageshow', function () { tick(); poll(); });
    window.addEventListener('pagehide', function () {
        clearRingtone();
        if (window.AlarmAudio) window.AlarmAudio.stop();
    });
    if (session) session.subscribe(function (event) {
        if (event.type === 'sync' || event.type === 'joined') { poll(); return; }
        if (event.resource === 'alarms' || event.resource === 'all') { reset(); source = sourceScope(); privateData = !!event.state.identity; }
    });
    setInterval(tick, 1000);
    setInterval(poll, 15000);
    poll();
}());
