/* User-opened, same-origin enrollment. No codes or credentials enter storage. */
(function () {
    'use strict';
    var session = window.WebClockDeviceSession, openButton = document.getElementById('device-join-open');
    var panel = document.getElementById('device-join-panel'), form = document.getElementById('device-join-form');
    var input = document.getElementById('device-join-code'), status = document.getElementById('device-join-status');
    var submit = document.getElementById('device-join-submit'), retry = document.getElementById('device-join-retry');
    var cancel = document.getElementById('device-join-cancel'), attempt = null, epoch = 0, opened = false, busy = false;
    var labels = window.WebClockEnrollmentTranslations || {}, statusKey = 'join_intro';
    var connection = document.getElementById('connection-panel');
    if (!session || !openButton || !panel || !form) return;
    function text(key) {
        var language = typeof window.currentLanguage === 'string' ? window.currentLanguage : document.documentElement.lang;
        var pack = labels[language] || labels['zh-TW'] || {};
        return pack[key] || key;
    }
    function render() {
        var nodes = document.querySelectorAll('[data-enrollment-i18n]');
        for (var i = 0; i < nodes.length; i++) nodes[i].textContent = text(nodes[i].getAttribute('data-enrollment-i18n'));
        status.textContent = text(statusKey);
        submit.disabled = busy || !attempt;
        retry.disabled = busy;
        input.disabled = busy || !attempt;
    }
    function show(key) { statusKey = key; render(); }
    function errorKey(error) {
        if (!error) return 'join_retry_hint';
        if (error.code === 'invalid_invitation') return 'join_invalid';
        if (error.code === 'rate_limited') return 'join_rate_limited';
        if (error.code === 'same_origin_required') return 'join_same_origin';
        if (error.code === 'cookie_unconfirmed') return 'join_cookie';
        if (error.code === 'join_attempt_conflict') return 'join_conflict';
        return 'join_retry_hint';
    }
    function prepare() {
        var current = ++epoch;
        attempt = null; input.value = ''; busy = true; show('join_preparing');
        session.prepare(function (error, result) {
            if (!opened || current !== epoch) return;
            busy = false;
            if (error) { show(errorKey(error)); return; }
            attempt = result.attempt_id; show('join_enter_code');
            try { input.focus(); } catch (failure) {}
        });
    }
    openButton.onclick = function () {
        opened = true; panel.style.display = 'block'; input.value = '';
        if (connection) connection.scrollTop = Math.max(0, panel.offsetTop - 8);
        var state = session.getState();
        if (!state.sameOrigin) { attempt = null; busy = false; show('join_same_origin'); return; }
        if (state.phase === 'active') { attempt = null; busy = false; show('join_connected'); return; }
        prepare();
    };
    cancel.onclick = function () {
        opened = false; epoch += 1; session.cancelJoin(); attempt = null; busy = false;
        input.value = ''; panel.style.display = 'none';
        try { openButton.focus(); } catch (failure) {}
    };
    retry.onclick = function () {
        if (busy) return;
        if (session.getState().phase === 'active') { attempt = null; show('join_connected'); return; }
        prepare();
    };
    form.onsubmit = function (event) {
        if (event && event.preventDefault) event.preventDefault();
        if (!attempt || busy) return false;
        var code = String(input.value || '').replace(/\s/g, '').toUpperCase();
        if (!/^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6}$/.test(code)) { show('join_invalid'); return false; }
        var current = ++epoch;
        input.value = ''; busy = true; show('join_submitting');
        session.join(attempt, code, function (error) {
            code = '';
            if (!opened || current !== epoch) return;
            busy = false;
            if (error) {
                if (error.code === 'join_attempt_conflict' || error.code === 'cookie_unconfirmed' || error.status === 401 || error.status === 403) attempt = null;
                show(errorKey(error)); return;
            }
            attempt = null; show('join_connected');
        });
        return false;
    };
    session.subscribe(function (event) {
        if (!opened) return;
        if (event.type === 'source' || (event.type === 'revoked' && !busy) || (event.type === 'identity' && event.state.phase === 'unknown')) {
            epoch += 1; session.cancelJoin(); attempt = null; busy = false; input.value = ''; show('join_conflict');
        }
    });
    window.WebClockEnrollmentRefresh = render;
    render();
}());
