/* Optional self-hosted alarms. The clock starts before this ES5 script loads. */
(function () {
    'use strict';
    var bell = document.getElementById('alarm-bell');
    if (!bell) return;
    var hint = document.getElementById('alarm-status');
    var message = document.getElementById('alarm-message');
    var motion = document.getElementById('alarm-motion');
    var source = '', queue = [], active = [], handled = {}, dismissed = [];
    var enabled = 0, confirmed = false, failed = false, holidayKnown = true, attemptedSound = false;
    var baseTime = null, baseElapsedTime = 0, requestNumber = 0, lastTouch = -1000, lastTone = -1600;

    function text(node, value) {
        if (node.textContent !== value) node.textContent = value;
    }
    function deviceNow() { return new Date().getTime(); }
    function elapsedNow() {
        return window.performance && typeof window.performance.now === 'function' ? window.performance.now() : deviceNow();
    }
    function now() { return baseTime === null ? deviceNow() : baseTime + elapsedNow() - baseElapsedTime; }
    function sourceUrl() { return window.serverUrl || window.location.origin; }
    function storageKey() { return 'webclock.dismissedAlarms.' + source; }
    function ready() { return !!(window.AlarmAudio && window.AlarmAudio.isReady()); }
    function audible() {
        for (var i = 0; i < queue.length; i++) if (queue[i].sound !== 'silent' && queue[i].volume !== 0) return true;
        return false;
    }
    function render() {
        bell.style.display = enabled || active.length ? 'block' : 'none';
        var label = t('alarm_set');
        if (active.length) label = t(confirmed ? 'alarm_second_tap' : 'alarm_first_tap');
        else if (audible()) label += ' · ' + t(ready() ? 'alarm_sound_ready' : 'alarm_enable_sound');
        bell.setAttribute('aria-label', label);
        bell.title = label;
        bell.className = ready() ? 'sound-ready' : '';
        var status = failed ? t('alarm_sync_error') : !holidayKnown ? t('alarm_unknown_holiday') : '';
        if (!status && enabled && audible() && !ready()) {
            status = t(attemptedSound ? 'alarm_sound_unavailable' : 'alarm_enable_sound');
        }
        text(hint, status);
        hint.style.display = status ? 'block' : 'none';
        message.style.display = active.length ? 'block' : 'none';
        if (active.length) {
            text(document.getElementById('alarm-name'), t('alarm_ringing') + ' · ' + active[0].name +
                (active.length > 1 ? ' (+' + (active.length - 1) + ')' : ''));
            text(document.getElementById('alarm-prompt'), t(confirmed ? 'alarm_second_tap' : 'alarm_first_tap'));
        }
        text(document.getElementById('alarm-motion-label'), t('alarm_flash'));
        text(document.getElementById('alarm-help'), t('alarm_sound_hint'));
        text(document.getElementById('alarm-manage'), t('alarm_manage'));
    }
    function stopRing(save) {
        if (save) {
            for (var i = 0; i < active.length; i++) {
                dismissed.push({id: active[i].occurrence_id, starts_at: active[i].starts_at});
            }
            dismissed = dismissed.filter(function (item) { return item.starts_at > now() - 60000; });
            writeStoredJson(storageKey(), dismissed);
        }
        active = [];
        confirmed = false;
        document.body.classList.remove('alarm-ringing');
        if (window.AlarmAudio) window.AlarmAudio.stop();
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
        holidayKnown = data.holiday_known !== false;
        baseTime = data.server_timestamp;
        baseElapsedTime = elapsedNow();
        failed = false;
        var ringingCount = active.length;
        active = active.filter(function (item) { return data.enabled_ids.indexOf(item.id) >= 0; });
        if (active.length !== ringingCount && window.AlarmAudio) window.AlarmAudio.stop();
        if (ringingCount && !active.length) stopRing(false);
        for (var key in handled) if (handled[key] < now() - 60000) delete handled[key];
        tick();
    }
    function poll() {
        var target = sourceUrl();
        if (target !== source) {
            stopRing(false);
            source = target;
            queue = [];
            enabled = 0;
            baseTime = null;
            handled = {};
            dismissed = readStoredJson(storageKey(), []);
            if (!Array.isArray(dismissed)) dismissed = [];
            dismissed = dismissed.filter(function (item) {
                return item && typeof item.id === 'string' && typeof item.starts_at === 'number';
            }).slice(-1000);
            for (var i = 0; i < dismissed.length; i++) handled[dismissed[i].id] = dismissed[i].starts_at;
        }
        var sequence = ++requestNumber;
        var xhr = new XMLHttpRequest();
        xhr.open('GET', target + '/api/v1/browser-alarms', true);
        xhr.timeout = 8000;
        function failure() {
            if (sequence !== requestNumber || target !== sourceUrl()) return;
            failed = true;
            render();
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
        if (source !== sourceUrl()) { poll(); return; }
        var instant = now();
        for (var i = 0; i < queue.length; i++) {
            var item = queue[i];
            // Never replay an alarm missed while the page was suspended for a minute or longer.
            if (item.starts_at <= instant && instant - item.starts_at < 60000 &&
                    !Object.prototype.hasOwnProperty.call(handled, item.occurrence_id)) {
                handled[item.occurrence_id] = item.starts_at;
                active.push(item);
                document.body.classList.add('alarm-ringing');
            }
        }
        if (active.length && elapsedNow() - lastTone >= 1600) {
            for (var j = 0; j < active.length; j++) {
                if (active[j].sound !== 'silent' && active[j].volume !== 0) {
                    if (window.AlarmAudio) window.AlarmAudio.play(active[j].sound, active[j].volume === undefined ? 100 : active[j].volume);
                    break;
                }
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
        attemptedSound = true;
        if (window.AlarmAudio) window.AlarmAudio.unlock('bell');
        render();
    };
    motion.checked = readStoredValue('webclock.alarmFlash', 'on') !== 'off';
    function setMotion() {
        document.body.classList.toggle('alarm-steady', !motion.checked);
        writeStoredValue('webclock.alarmFlash', motion.checked ? 'on' : 'off');
    }
    motion.onchange = setMotion;
    setMotion();
    document.addEventListener('touchend', tap, true);
    document.addEventListener('click', tap, true);
    document.addEventListener('keydown', function (event) {
        if (!event.repeat && (event.keyCode === 13 || event.keyCode === 32)) tap(event);
    }, true);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { tick(); poll(); } });
    window.addEventListener('pageshow', function () { tick(); poll(); });
    setInterval(tick, 1000);
    setInterval(poll, 15000);
    poll();
}());
