/* User-opened, same-origin enrollment. No codes or credentials enter storage. */
(function () {
    'use strict';
    var session = window.WebClockDeviceSession, openButton = document.getElementById('device-join-open');
    var panel = document.getElementById('device-join-panel'), form = document.getElementById('device-join-form');
    var input = document.getElementById('device-join-code'), status = document.getElementById('device-join-status');
    var submit = document.getElementById('device-join-submit'), retry = document.getElementById('device-join-retry');
    var fields = document.getElementById('device-join-fields'), groupName = document.getElementById('device-group-name');
    var leave = document.getElementById('device-group-leave'), title = document.getElementById('device-join-title');
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
        var state = session.getState(), joined = !!state.identity;
        var nodes = document.querySelectorAll('[data-enrollment-i18n]');
        for (var i = 0; i < nodes.length; i++) nodes[i].textContent = text(nodes[i].getAttribute('data-enrollment-i18n'));
        openButton.style.display = opened || joined ? 'none' : '';
        panel.style.display = opened || joined ? 'block' : 'none';
        fields.style.display = submit.style.display = joined ? 'none' : '';
        cancel.style.display = joined ? 'none' : '';
        groupName.style.display = leave.style.display = joined ? '' : 'none';
        title.textContent = text(joined ? 'join_group_title' : 'join_title');
        groupName.textContent = joined ? (state.group ? state.group.name : text('join_group_unknown')) : '';
        status.textContent = text(joined && statusKey === 'join_intro' ? 'join_connected' : statusKey);
        submit.disabled = busy || !attempt;
        retry.disabled = leave.disabled = busy;
        input.disabled = joined || busy || !attempt;
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
        render();
        try { openButton.focus(); } catch (failure) {}
    };
    retry.onclick = function () {
        if (busy) return;
        if (session.getState().identity) {
            var current = ++epoch;
            busy = true; show('join_checking');
            session.checkIdentity(function (error, result) {
                if (current !== epoch) return;
                busy = false;
                show(error || !result || result.status !== 'active' ? 'join_check_failed' : 'join_connected');
            });
            return;
        }
        prepare();
    };
    leave.onclick = function () {
        if (busy || !session.getState().identity || !window.confirm(text('join_leave_confirm'))) return;
        var current = ++epoch;
        busy = true; input.value = ''; show('join_leaving');
        session.leave(function (error) {
            if (current !== epoch) return;
            busy = false; attempt = null;
            if (error) { show('join_leave_failed'); return; }
            opened = false; statusKey = 'join_intro'; render();
            try { openButton.focus(); } catch (failure) {}
        });
    };
    form.onsubmit = function (event) {
        if (event && event.preventDefault) event.preventDefault();
        if (!attempt || busy || session.getState().identity) return false;
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
        if (event.type === 'source' || event.type === 'authorization-check' || (event.type === 'revoked' && !busy) || (event.type === 'identity' && event.state.phase === 'unknown')) {
            epoch += 1; attempt = null; busy = false; input.value = ''; show('join_conflict');
        } else {
            if (event.state.identity && !busy) { attempt = null; input.value = ''; statusKey = 'join_connected'; }
            render();
        }
    });
    window.WebClockEnrollmentRefresh = render;
    render();
}());
