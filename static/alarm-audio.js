/* Native audio only: keep this file parseable by iOS 9 Safari. */
(function () {
    'use strict';
    var context = null, unlocked = false, nodes = [];

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

    function tone(sound, fromGesture) {
        stop();
        if (sound === 'silent') return true;
        if (!context || (!fromGesture && !isReady())) return false;
        var notes = sound === 'digital' ? [660, 880, 660] : sound === 'beep' ? [880] : [880, 1320];
        var duration = sound === 'bell' ? 0.45 : 0.16;
        try {
            for (var i = 0; i < notes.length; i++) {
                var start = context.currentTime + i * (duration + 0.08);
                var oscillator = context.createOscillator();
                var gain = context.createGain();
                oscillator.type = sound === 'digital' ? 'square' : 'sine';
                oscillator.frequency.value = notes[i];
                gain.gain.setValueAtTime(0, start);
                gain.gain.linearRampToValueAtTime(sound === 'digital' ? 0.06 : 0.14, start + 0.01);
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

    function unlock(sound) {
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
            return tone(sound || 'bell', true);
        } catch (error) {
            unlocked = false;
            return false;
        }
    }

    window.AlarmAudio = {unlock: unlock, play: function (sound) { return tone(sound, false); },
                         stop: stop, isReady: isReady};
}());
