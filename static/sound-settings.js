(function () {
    'use strict';
    var form = document.getElementById('alarm-effects');
    var sample = document.getElementById('effects-sample');
    var edge = document.getElementById('sample-edge');
    var flash = document.getElementById('alarm_flash');
    var vibration = document.getElementById('alarm_vibration');
    var volume = document.getElementById('preview-volume');
    var toneResult = document.getElementById('tone-result');
    var stopButton = document.getElementById('stop-tone');
    var activeTone = null, customPreview = null, repeatTimer;
    var effectResult = document.getElementById('effects-result');
    var timer, vibrating = false;

    function status(node, key) {
        node.setAttribute('data-i18n', key);
        node.textContent = t(key);
    }

    function endPreview() {
        clearTimeout(timer);
        sample.hidden = true;
        if (vibrating) window.AlarmAudio.vibrate(0);
        vibrating = false;
    }

    function stopTone(message) {
        clearTimeout(repeatTimer);
        var previous = customPreview;
        customPreview = null;
        if (previous && previous.cancel) previous.cancel();
        if (activeTone) {
            window.AlarmAudio.stop();
            activeTone.setAttribute('aria-pressed', 'false');
            activeTone.querySelector('.tone-icon').textContent = '▶';
            activeTone = null;
        }
        stopButton.disabled = true;
        if (message) status(toneResult, message);
    }

    volume.addEventListener('input', function () {
        document.getElementById('preview-volume-value').textContent = volume.value + '%';
        if (activeTone && Number(volume.value) === 0) stopTone('sound_silent');
    });
    stopButton.addEventListener('click', function () {
        if (activeTone) activeTone.focus();
        stopTone('sounds_stopped');
    });
    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-preview-tone]');
        if (!button) return;
        var sound = button.getAttribute('data-preview-tone');
        if (activeTone === button) {
            stopTone('sounds_stopped');
            return;
        }
        stopTone();
        document.dispatchEvent(new Event('webclock:stop-trim-preview'));
        if (sound === 'silent' || Number(volume.value) === 0) {
            status(toneResult, 'sound_silent');
            return;
        }
        var audio = window.AlarmAudio;
        var custom = audio.isRingtoneId(sound);
        if (!audio.unlock(custom ? 'silent' : sound, Number(volume.value))) {
            status(toneResult, custom ? 'ringtone_preview_unavailable' : 'audio_unavailable');
            return;
        }
        activeTone = button;
        button.setAttribute('aria-pressed', 'true');
        button.querySelector('.tone-icon').textContent = '■';
        stopButton.disabled = false;
        status(toneResult, custom ? 'loading' : 'sounds_playing');
        if (custom) {
            var preview = {};
            customPreview = preview;
            preview.cancel = audio.loadRingtone(sound, 'management', function (buffer) {
                function repeat() {
                    if (customPreview !== preview) return;
                    var played = audio.playRingtone(buffer, Number(volume.value), function () {
                        repeatTimer = setTimeout(repeat, 350);
                    });
                    if (!played) stopTone('ringtone_preview_unavailable');
                    else status(toneResult, 'sounds_playing');
                }
                repeat();
            }, function () { return customPreview === preview; });
        } else {
            // The clock repeats on every second 1-second alarm tick.
            repeatTimer = setTimeout(function repeat() {
                if (!audio.play(sound, Number(volume.value))) stopTone('audio_unavailable');
                else repeatTimer = setTimeout(repeat, 2000);
            }, 2000);
        }
    });
    document.getElementById('preview-effects').addEventListener('click', function () {
        endPreview();
        edge.hidden = flash.value === 'off';
        edge.setAttribute('data-alarm-flash', flash.value);
        sample.hidden = false;
        vibrating = vibration.checked && window.AlarmAudio.vibrate();
        status(effectResult, vibration.checked && !vibrating ? 'sounds_vibration_unavailable' : 'sounds_previewed');
        timer = setTimeout(endPreview, 2000);
    });
    form.addEventListener('submit', function (event) {
        event.preventDefault();
        var button = form.querySelector('[type="submit"]');
        button.disabled = true;
        postSettings({alarm_flash: flash.value, alarm_vibration: vibration.checked}).then(function (result) {
            status(effectResult, result ? 'saved' : (settingsConflict ? 'settings_conflict' : 'settings_save_error'));
            button.disabled = false;
        });
    });
    function stop() {
        endPreview();
        if (activeTone) stopTone('sounds_stopped');
    }
    window.addEventListener('hashchange', stop);
    window.addEventListener('pagehide', stop);
    document.addEventListener('webclock:stop-audio-preview', function () {
        if (activeTone) stopTone('sounds_stopped');
    });
    document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); });
}());
