/* Native audio only: keep this file parseable by iOS 9 Safari. */
(function () {
    'use strict';
    var context = null, unlocked = false, nodes = [], ringtone = null;
    var ringtoneRoutes = {management: '/api/ringtones/', self: '/api/v1/ringtones/', device: '/api/v2/device/ringtones/'};
    var tones = {
        bell: {notes: [880, 1320], duration: 0.45},
        beep: {notes: [880], duration: 0.16},
        digital: {notes: [660, 880, 660], duration: 0.16, wave: 'square', gain: 0.06},
        chime: {notes: [523.25, 659.25, 783.99], duration: 0.35},
        melody: {notes: [523.25, 659.25, 783.99, 659.25, 1046.5], duration: 0.18, wave: 'triangle'},
        pulse: {notes: [740, 740, 740, 740], duration: 0.09, wave: 'square', gain: 0.06},
        sonar: {notes: [440, 880], duration: 0.5}
    };

    function stop() {
        if (ringtone) ringtone.stop();
        for (var i = 0; i < nodes.length; i++) {
            try { nodes[i].stop(); } catch (error) {}
            try { nodes[i].disconnect(); } catch (error) {}
        }
        nodes = [];
    }

    function isReady() {
        return !!(context && unlocked && (!context.state || context.state === 'running'));
    }

    function normalizedVolume(volume) {
        return typeof volume === 'number' && isFinite(volume) ? Math.max(0, Math.min(100, volume)) / 100 : 1;
    }

    function tone(sound, fromGesture, volume) {
        stop();
        volume = normalizedVolume(volume);
        if (sound === 'silent' || volume === 0) return true;
        if (!context || (!fromGesture && !isReady())) return false;
        var pattern = tones[sound] || tones.bell;
        var notes = pattern.notes, duration = pattern.duration;
        try {
            for (var i = 0; i < notes.length; i++) {
                var start = context.currentTime + i * (duration + 0.08);
                var oscillator = context.createOscillator();
                var gain = context.createGain();
                oscillator.type = pattern.wave || 'sine';
                oscillator.frequency.value = notes[i];
                gain.gain.setValueAtTime(0, start);
                gain.gain.linearRampToValueAtTime((pattern.gain || 0.14) * volume, start + 0.01);
                gain.gain.linearRampToValueAtTime(0, start + duration);
                oscillator.connect(gain);
                gain.connect(context.destination);
                oscillator.onended = (function (node, envelope) {
                    return function () { node.disconnect(); envelope.disconnect(); };
                }(oscillator, gain));
                nodes.push(oscillator);
                oscillator.start(start);
                oscillator.stop(start + duration + 0.01);
            }
            return true;
        } catch (error) {
            stop();
            unlocked = false;
            return false;
        }
    }

    function unlock(sound, volume) {
        try {
            var Constructor = window.AudioContext || window.webkitAudioContext;
            if (!Constructor) return false;
            if (!context) context = new Constructor();
            if (typeof context.resume === 'function' && context.state !== 'running') {
                var resumed = context.resume();
                if (resumed && typeof resumed.catch === 'function') {
                    resumed.catch(function () { unlocked = false; });
                }
            }
            unlocked = true;
            // Play within the original tap, not after an asynchronous request.
            return tone(sound || 'bell', true, volume);
        } catch (error) {
            unlocked = false;
            return false;
        }
    }

    function isRingtoneId(id) {
        return typeof id === 'string' && id.length === 32 && /^[a-f0-9]+$/.test(id);
    }

    function loadRingtone(id, audience, callback, allowed) {
        var xhr, finished = false;
        var maxSeconds = 300;
        var maxBytes = 44 + 2 * 16000 * maxSeconds;
        function complete(buffer) {
            if (finished) return;
            finished = true;
            xhr = null;
            if (!allowed || allowed()) callback(buffer);
        }
        function cancel() {
            finished = true;
            if (xhr) {
                xhr.abort();
                xhr = null;
            }
        }
        try {
            if (!isRingtoneId(id) || !Object.prototype.hasOwnProperty.call(ringtoneRoutes, audience) ||
                    !context || typeof context.decodeAudioData !== 'function' || (allowed && !allowed())) {
                complete(null);
                return cancel;
            }
            var url = (window.webclockBase || window.location.origin) + ringtoneRoutes[audience] + id;
            xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.withCredentials = false;
            xhr.responseType = 'arraybuffer';
            xhr.timeout = 30000;
            xhr.setRequestHeader('Cache-Control', 'no-cache');
            xhr.onprogress = function (event) {
                if (event.loaded > maxBytes) {
                    var request = xhr;
                    complete(null);
                    if (request) request.abort();
                }
            };
            xhr.onerror = xhr.ontimeout = function () { complete(null); };
            xhr.onload = function () {
                if (finished || (allowed && !allowed())) return;
                var request = xhr;
                if (request.status !== 200 || (request.responseURL && request.responseURL !== url) ||
                        !request.response || !request.response.byteLength || request.response.byteLength > maxBytes) {
                    complete(null);
                    return;
                }
                try {
                    var decoded = context.decodeAudioData(request.response, function (buffer) {
                        complete(buffer && buffer.duration > 0 && buffer.duration <= maxSeconds ? buffer : null);
                    }, request.onerror);
                    if (decoded && typeof decoded.catch === 'function') decoded.catch(request.onerror);
                } catch (error) { complete(null); }
            };
            xhr.send();
        } catch (error) { complete(null); }
        return cancel;
    }

    function playRingtone(buffer, volume, onEnded) {
        volume = normalizedVolume(volume);
        if (!buffer || !isReady() || !volume) return false;
        stop();
        var clip, gain;
        function release() {
            if (ringtone !== playback) return false;
            ringtone = null;
            try { clip.disconnect(); } catch (error) {}
            try { gain.disconnect(); } catch (error) {}
            return true;
        }
        var playback = {stop: function () {
            release();
            if (clip) {
                try { clip.stop(); } catch (error) {}
            }
        }};
        try {
            clip = context.createBufferSource();
            gain = context.createGain();
            ringtone = playback;
            clip.buffer = buffer;
            gain.gain.value = volume;
            clip.connect(gain);
            gain.connect(context.destination);
            clip.onended = function () { if (release() && onEnded) onEnded(); };
            clip.start();
            return true;
        } catch (error) { playback.stop(); return false; }
    }

    function vibrate(duration) {
        if (!window.navigator || typeof window.navigator.vibrate !== 'function') return false;
        try {
            return window.navigator.vibrate(duration === 0 ? 0 : [160, 100, 160]);
        } catch (error) {
            return false;
        }
    }

    window.AlarmAudio = {unlock: unlock, play: function (sound, volume) { return tone(sound, false, volume); },
                         stop: stop, isReady: isReady, vibrate: vibrate, isRingtoneId: isRingtoneId,
                         loadRingtone: loadRingtone, playRingtone: playRingtone,
                         isRingtonePlaying: function () { return !!ringtone; }};
}());
