/* Native audio only: keep this file parseable by iOS 9 Safari. */
(function () {
    'use strict';
    var context = null, unlocked = false, nodes = [];
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
        for (var i = 0; i < nodes.length; i++) {
            try { nodes[i].stop(); } catch (error) {}
            try { nodes[i].disconnect(); } catch (error) {}
        }
        nodes = [];
    }

    function isReady() {
        return !!(context && unlocked && (!context.state || context.state === 'running'));
    }

    function tone(sound, fromGesture, volume) {
        stop();
        volume = typeof volume === 'number' && isFinite(volume) ? Math.max(0, Math.min(100, volume)) / 100 : 1;
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

    window.AlarmAudio = {unlock: unlock, play: function (sound, volume) { return tone(sound, false, volume); },
                         stop: stop, isReady: isReady};
}());
