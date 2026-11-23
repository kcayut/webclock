(function () {
    'use strict';

    const form = document.getElementById('ringtone-editor');
    if (!form) return;

    const sampleRate = 16000;
    const maxFileBytes = 8 * 1024 * 1024;
    const maxSourceSeconds = 300;
    const maxWaveBytes = 44 + 2 * sampleRate * maxSourceSeconds;
    const input = document.getElementById('ringtone-file');
    const fields = document.getElementById('ringtone-clip');
    const name = document.getElementById('ringtone-name');
    const start = document.getElementById('ringtone-start');
    const end = document.getElementById('ringtone-end');
    const startSlider = document.getElementById('ringtone-start-slider');
    const endSlider = document.getElementById('ringtone-end-slider');
    const timeline = document.getElementById('ringtone-timeline');
    const playhead = document.getElementById('ringtone-playhead');
    let previewFrame;
    const sourceDuration = document.getElementById('ringtone-source-duration');
    const clipDuration = document.getElementById('ringtone-clip-duration');
    const rangeLabel = document.getElementById('ringtone-range-label');
    const preview = document.getElementById('ringtone-preview');
    const save = document.getElementById('ringtone-save');
    const cancelEdit = document.getElementById('ringtone-cancel-edit');
    let trimOrigin;
    const result = document.getElementById('ringtone-editor-result');
    const manageResult = document.getElementById('ringtone-manage-result');
    const volume = document.getElementById('preview-volume');
    const addToggle = document.getElementById('ringtone-add');
    const selectBoxes = Array.from(document.querySelectorAll('[data-select-ringtone]'));
    const deleteSelected = document.getElementById('ringtone-delete-selected');
    const disclosures = document.querySelectorAll('.ringtone-disclosure');
    const actionControls = document.querySelectorAll('.ringtone-options input, .ringtone-options button');
    const deleteButtons = document.querySelectorAll('[data-delete-ringtone]');
    const copyButtons = document.querySelectorAll('[data-copy-ringtone]');
    const csrfToken = document.getElementById('csrf-token').content;
    const OfflineContext = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const controlCharacter = /\p{C}/u;
    let audio, player, playing, gain;

    function status(key, output = result) {
        if (key) output.setAttribute('data-i18n', key);
        else output.removeAttribute('data-i18n');
        output.textContent = key ? t(key) : '';
    }

    function setBusy(busy) {
        input.disabled = busy;
        fields.disabled = busy || !audio;
        preview.disabled = save.disabled = busy || !selectedClip();
        cancelEdit.disabled = busy;
        addToggle.disabled = busy;
        for (const control of [...actionControls, ...selectBoxes, ...disclosures]) control.disabled = busy;
        updateSelection(busy);
    }

    function updateSelection(busy = false) {
        if (!deleteSelected) return;
        const count = selectBoxes.filter(box => box.checked).length;
        document.getElementById('ringtone-selected-count').textContent = String(count);
        deleteSelected.disabled = busy || count === 0;
    }

    function showEditor(open) {
        form.hidden = !open;
        addToggle.setAttribute('aria-expanded', String(open));
        if (!open) stopPreview();
    }
    function cancelDraft() {
        const origin = trimOrigin || addToggle;
        trimOrigin = null;
        stopPreview();
        audio = null;
        form.reset();
        fields.hidden = true;
        setBusy(false);
        input.closest('.field').hidden = false;
        status('ringtone_save', save);
        status('');
        showEditor(false);
        const panel = origin.closest('.ringtone-options');
        (panel?.hidden ? panel.parentNode.querySelector('.ringtone-disclosure') : origin).focus();
    }
    cancelEdit.addEventListener('click', cancelDraft);
    addToggle.addEventListener('click', () => {
        if (trimOrigin) { cancelDraft(); return; }
        showEditor(form.hidden);
        if (!form.hidden) input.focus();
    });
    disclosures.forEach(button => button.addEventListener('click', () => {
        const open = button.getAttribute('aria-expanded') !== 'true';
        disclosures.forEach(other => {
            const expanded = other === button && open;
            other.setAttribute('aria-expanded', String(expanded));
            document.getElementById(other.getAttribute('aria-controls')).hidden = !expanded;
        });
    }));
    selectBoxes.forEach(box => box.addEventListener('change', () => updateSelection()));

    function returnToSounds(id) {
        const target = new URL(form.dataset.returnUrl, window.location.href);
        if (target.pathname === window.location.pathname) {
            window.history.replaceState(id ? {ringtoneFocus: id} : null, '', target.href);
            window.location.reload();
        } else {
            window.location.assign(target.href);
        }
    }

    window.addEventListener('pageshow', () => {
        const id = window.history.state?.ringtoneFocus;
        if (!id || location.hash !== '#sounds') return;
        window.history.replaceState(null, '');
        requestAnimationFrame(() => document.getElementById('tone-label-' + id)?.closest('button').focus());
    });

    async function responseCode(response) {
        const payload = await response.json().catch(function () { return {}; });
        return payload.code || payload.error;
    }

    function setPreviewing(active) {
        if (!active) {
            cancelAnimationFrame(previewFrame);
            playhead.hidden = true;
        }
        const key = active ? 'ringtone_stop_preview' : 'ringtone_preview';
        preview.setAttribute('data-i18n', key);
        preview.setAttribute('aria-pressed', String(active));
        preview.textContent = t(key);
    }

    function stopPreview() {
        if (!playing) return;
        playing.onended = null;
        playing.stop();
        playing.disconnect();
        playing = null;
        setPreviewing(false);
    }

    function fileFormat(file, bytes) {
        const header = new Uint8Array(bytes, 0, Math.min(12, bytes.byteLength));
        const signature = String.fromCharCode(...header);
        if (/\.wav$/i.test(file.name)) {
            return signature.startsWith('RIFF') && signature.slice(8) === 'WAVE' ? 'audio/wav' : '';
        }
        if (/\.m4[ar]$/i.test(file.name)) {
            return signature.slice(4, 8) === 'ftyp' ? 'audio/mp4' : '';
        }
        if (/\.ogg$/i.test(file.name)) {
            return signature.startsWith('OggS') && header[4] === 0 ? 'audio/ogg' : '';
        }
        if (!/\.mp3$/i.test(file.name)) return '';
        const frame = header[0] === 0xff && (header[1] & 0xe0) === 0xe0 &&
            (header[1] & 0x18) !== 0x08 && (header[1] & 0x06) === 0x02 &&
            (header[2] & 0xf0) !== 0xf0 && (header[2] & 0x0c) !== 0x0c;
        return signature.startsWith('ID3') || (header.length >= 4 && frame) ? 'audio/mpeg' : '';
    }

    function readDuration(file, format) {
        // shortcut: the browser estimates MP3 metadata duration; enforce the decoded length too.
        return new Promise(function (resolve, reject) {
            const media = document.createElement('video');
            const url = URL.createObjectURL(file.slice(0, file.size, format));
            const timer = setTimeout(function () { finish(NaN); }, 10000);
            function finish(duration) {
                clearTimeout(timer);
                media.onloadedmetadata = media.onerror = null;
                media.removeAttribute('src');
                media.load();
                URL.revokeObjectURL(url);
                if (Number.isFinite(duration) && duration > 0) resolve(duration);
                else reject(new Error('Audio metadata unavailable'));
            }
            media.onloadedmetadata = function () { finish(media.videoWidth || media.videoHeight ? NaN : media.duration); };
            media.onerror = function () { finish(NaN); };
            media.preload = 'metadata';
            media.src = url;
        });
    }

    function selectedClip() {
        if (!audio) return null;
        const startSeconds = start.valueAsNumber;
        const endSeconds = end.valueAsNumber;
        const first = Math.round(startSeconds * sampleRate);
        const last = Math.round(endSeconds * sampleRate);
        if (!(startSeconds >= 0 && endSeconds <= audio.duration && first < last)) return null;
        return {first: first, length: last - first};
    }

    function updateClip() {
        stopPreview();
        if (Number.isFinite(start.valueAsNumber)) startSlider.value = start.value;
        if (Number.isFinite(end.valueAsNumber)) endSlider.value = end.value;
        const clip = selectedClip();
        timeline.style.setProperty('--clip-start', (100 * startSlider.valueAsNumber / audio.duration) + '%');
        timeline.style.setProperty('--clip-end', (100 * endSlider.valueAsNumber / audio.duration) + '%');
        const key = clip ? 'ringtone_clip_duration' : 'ringtone_range_error';
        rangeLabel.setAttribute('data-i18n', key);
        rangeLabel.textContent = t(key);
        clipDuration.textContent = clip ? (clip.length / sampleRate).toFixed(3) : '';
        preview.disabled = save.disabled = !clip;
    }

    function moveSlider() {
        const seconds = this.valueAsNumber;
        const position = seconds === audio.duration ? audio.length : Math.round(seconds * 100) * (sampleRate / 100);
        if (this === startSlider) {
            const last = Math.max(1, Math.round(endSlider.valueAsNumber * sampleRate));
            start.value = String(Math.min(position, last - 1) / sampleRate);
            end.value = String(last / sampleRate);
        } else {
            const first = Math.min(audio.length - 1, Math.round(startSlider.valueAsNumber * sampleRate));
            end.value = String(Math.min(audio.length, Math.max(position, first + 1)) / sampleRate);
            start.value = String(first / sampleRate);
        }
        updateClip();
    }

    function setSource(buffer, label, suffix = '') {
        audio = buffer;
        name.value = Array.from(label).slice(0, 60 - Array.from(suffix).length).join('') + suffix;
        start.max = end.max = startSlider.max = endSlider.max = String(audio.duration);
        start.value = '0';
        end.value = String(audio.duration);
        sourceDuration.textContent = audio.duration.toFixed(3);
        fields.hidden = false;
        updateClip();
    }

    input.addEventListener('change', async function () {
        const file = input.files[0];
        stopPreview();
        audio = null;
        fields.hidden = fields.disabled = true;
        status('');
        if (!file) return;
        if (!file.size || file.size > maxFileBytes) {
            input.value = '';
            status('ringtone_size_error');
            return;
        }
        setBusy(true);
        cancelEdit.disabled = false;
        status('ringtone_reading');
        try {
            const bytes = await file.arrayBuffer();
            if (input.files[0] !== file) return;
            const format = fileFormat(file, bytes);
            if (!format) {
                status('ringtone_type_error');
                return;
            }
            const duration = await readDuration(file, format);
            if (input.files[0] !== file) return;
            if (duration > maxSourceSeconds) {
                status('ringtone_duration_error');
                return;
            }
            const decoder = new OfflineContext(1, 1, sampleRate);
            const decoded = await decoder.decodeAudioData(bytes);
            if (input.files[0] !== file) return;
            if (decoded.duration > maxSourceSeconds) {
                status('ringtone_duration_error');
                return;
            }
            setSource(decoded, file.name.replace(/\.[^.]+$/, '').trim());
            status('');
        } catch (error) {
            if (input.files[0] === file) status('ringtone_decode_error');
        } finally {
            if (input.files[0] === file) {
                setBusy(false);
                if (!audio) input.value = '';
            }
        }
    });
    start.addEventListener('input', updateClip);
    end.addEventListener('input', updateClip);
    startSlider.addEventListener('input', moveSlider);
    endSlider.addEventListener('input', moveSlider);

    preview.addEventListener('click', function () {
        if (playing) {
            stopPreview();
            return;
        }
        const clip = selectedClip();
        if (!clip) return;
        document.dispatchEvent(new Event('webclock:stop-audio-preview'));
        try {
            if (!player) {
                const Context = window.AudioContext || window.webkitAudioContext;
                player = new Context();
                gain = player.createGain();
                gain.channelCount = 1;
                gain.channelCountMode = 'explicit';
                gain.connect(player.destination);
            }
            const resumed = player.resume();
            gain.gain.value = Number(volume.value) / 100;
            const source = player.createBufferSource();
            source.buffer = audio;
            source.connect(gain);
            const startedAt = player.currentTime;
            source.start(startedAt, clip.first / sampleRate, clip.length / sampleRate);
            playing = source;
            function showPosition() {
                const elapsed = Math.min(clip.length / sampleRate, player.currentTime - startedAt);
                playhead.style.left = (100 * (clip.first / sampleRate + elapsed) / audio.duration) + '%';
                previewFrame = requestAnimationFrame(showPosition);
            }
            playhead.hidden = false;
            showPosition();
            source.onended = function () {
                source.disconnect();
                playing = null;
                setPreviewing(false);
            };
            setPreviewing(true);
            resumed.catch(function () {
                if (playing !== source) return;
                stopPreview();
                status('audio_unavailable');
            });
        } catch (error) {
            status('audio_unavailable');
        }
    });
    volume.addEventListener('input', function () {
        if (gain) gain.gain.value = Number(volume.value) / 100;
    });
    document.addEventListener('webclock:stop-trim-preview', stopPreview);
    window.addEventListener('hashchange', stopPreview);
    window.addEventListener('pagehide', stopPreview);
    document.addEventListener('visibilitychange', function () { if (document.hidden) stopPreview(); });

    function encodeWave(buffer) {
        const samples = buffer.getChannelData(0);
        const bytes = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(bytes);
        function tag(offset, value) {
            for (let index = 0; index < value.length; index++) {
                view.setUint8(offset + index, value.charCodeAt(index));
            }
        }
        tag(0, 'RIFF');
        view.setUint32(4, bytes.byteLength - 8, true);
        tag(8, 'WAVE');
        tag(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        tag(36, 'data');
        view.setUint32(40, samples.length * 2, true);
        for (let index = 0; index < samples.length; index++) {
            const value = Math.max(-1, Math.min(1, samples[index]));
            view.setInt16(44 + index * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
        }
        return bytes;
    }

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        const clip = selectedClip();
        const label = name.value.trim();
        if (fields.disabled || !clip) return;
        if (!label || Array.from(label).length > 60 || controlCharacter.test(name.value)) {
            status('ringtone_name_error');
            name.focus();
            return;
        }
        stopPreview();
        setBusy(true);
        status('ringtone_uploading');
        try {
            const renderer = new OfflineContext(1, clip.length, sampleRate);
            const source = renderer.createBufferSource();
            source.buffer = audio;
            source.connect(renderer.destination);
            source.start(0, clip.first / sampleRate, clip.length / sampleRate);
            const wav = encodeWave(await renderer.startRendering());
            const response = await fetch(window.webclockUrl('/api/ringtones'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'audio/wav',
                    'X-Ringtone-Name': encodeURIComponent(label),
                    'X-CSRF-Token': csrfToken
                },
                body: wav
            });
            if (response.status !== 201) {
                const code = await responseCode(response);
                if (code === 'ringtone_upload_busy' || code === 'ringtone_quota' || code === 'ringtone_storage_full') {
                    status(code);
                } else if (code === 'invalid_ringtone_name') {
                    status('ringtone_name_error');
                } else {
                    status('ringtone_upload_error');
                }
                return;
            }
            returnToSounds((await response.json()).id);
        } catch (error) {
            status('ringtone_upload_error');
        } finally {
            setBusy(false);
        }
    });

    copyButtons.forEach(function (button) {
        button.addEventListener('click', async function () {
            stopPreview();
            document.dispatchEvent(new Event('webclock:stop-audio-preview'));
            setBusy(true);
            const feedback = button.closest('.ringtone-options').querySelector('.ringtone-action-result');
            status('ringtone_reading', feedback);
            try {
                const response = await fetch(window.webclockUrl('/api/ringtones/' + encodeURIComponent(button.dataset.copyRingtone)), {
                    cache: 'no-store'
                });
                if (!response.ok || response.headers.get('Content-Type') !== 'audio/wav' ||
                    Number(response.headers.get('Content-Length')) > maxWaveBytes) {
                    throw new Error('Invalid ringtone response');
                }
                const bytes = await response.arrayBuffer();
                if (bytes.byteLength <= 44 || bytes.byteLength > maxWaveBytes) throw new Error('Invalid WAV size');
                const decoder = new OfflineContext(1, 1, sampleRate);
                const decoded = await decoder.decodeAudioData(bytes);
                if (!decoded.length || decoded.duration > maxSourceSeconds || decoded.numberOfChannels !== 1) {
                    throw new Error('Invalid ringtone audio');
                }
                input.value = '';
                trimOrigin = button;
                input.closest('.field').hidden = true;
                status('ringtone_save_copy', save);
                setSource(decoded, button.dataset.ringtoneName, t('ringtone_copy_suffix'));
                showEditor(true);
                status('', feedback);
                status('ringtone_copy_ready');
            } catch (error) {
                status('ringtone_copy_error', feedback);
                return;
            } finally {
                setBusy(false);
            }
            name.focus();
        });
    });

    async function changeLibrary(path, method, body, feedback, fallback) {
        setBusy(true);
        status('', feedback);
        stopPreview();
        document.dispatchEvent(new Event('webclock:stop-audio-preview'));
        try {
            const response = await fetch(window.webclockUrl('/api/ringtones' + path), {
                method,
                headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken},
                body: JSON.stringify(body)
            });
            if (response.ok) {
                returnToSounds(response.status === 204 ? null : (await response.json()).id);
                return;
            }
            const error = await response.json().catch(() => ({}));
            if (error.code === 'ringtone_in_use' && Array.isArray(error.ids)) {
                const names = error.ids.map(id => document.getElementById('tone-label-' + id)?.textContent);
                feedback.removeAttribute('data-i18n');
                feedback.textContent = t('ringtone_delete_blocked').replace('{names}', () => names.filter(Boolean).join(', '));
            } else if (error.code === 'invalid_ringtone_name') {
                status('ringtone_name_error', feedback);
            } else {
                status(['ringtone_quota', 'ringtone_storage_full'].includes(error.code) ? error.code : fallback, feedback);
            }
        } catch (error) {
            status(fallback, feedback);
        } finally {
            setBusy(false);
        }
    }

    document.querySelectorAll('[data-rename-ringtone]').forEach(rename => {
        rename.addEventListener('submit', event => {
            event.preventDefault();
            const field = rename.querySelector('input');
            changeLibrary('/' + rename.dataset.renameRingtone, 'PATCH', {name: field.value},
                rename.parentNode.querySelector('.ringtone-action-result'), 'ringtone_change_error');
        });
    });
    document.querySelectorAll('[data-duplicate-draft]').forEach(draft => {
        const panel = draft.closest('.ringtone-options');
        const button = panel.querySelector('[data-duplicate-ringtone]');
        const rename = panel.querySelector('[data-rename-ringtone]');
        const actions = button.parentNode;
        const field = draft.querySelector('input');
        const feedback = panel.querySelector('.ringtone-action-result');
        function showDraft(open) {
            draft.hidden = !open;
            rename.hidden = actions.hidden = open;
            status('', feedback);
            if (open) {
                const suffix = t('ringtone_copy_suffix');
                field.value = Array.from(button.dataset.ringtoneName).slice(0, 60 - Array.from(suffix).length).join('') + suffix;
                field.focus();
                field.select();
            } else {
                draft.reset();
                button.focus();
            }
        }
        button.addEventListener('click', () => showDraft(true));
        draft.querySelector('[data-cancel-duplicate]').addEventListener('click', () => showDraft(false));
        draft.addEventListener('submit', event => {
            event.preventDefault();
            changeLibrary('/' + draft.dataset.duplicateDraft + '/copy', 'POST', {name: field.value},
                feedback, 'ringtone_change_error');
        });
    });
    deleteButtons.forEach(button => button.addEventListener('click', () => {
        if (window.confirm(t('ringtone_delete_confirm').replace('{name}', () => button.dataset.ringtoneName))) {
            changeLibrary('/' + button.dataset.deleteRingtone, 'DELETE', undefined,
                button.closest('.ringtone-options').querySelector('.ringtone-action-result'), 'ringtone_delete_error');
        }
    }));
    if (deleteSelected) deleteSelected.addEventListener('click', () => {
        const checked = selectBoxes.filter(box => box.checked);
        const names = checked.map(box => box.parentNode.textContent.trim()).join('、');
        if (checked.length && window.confirm(t('ringtone_bulk_confirm').replace('{names}', () => names))) {
            changeLibrary('', 'DELETE', {ids: checked.map(box => box.value)}, manageResult, 'ringtone_delete_error');
        }
    });
}());
