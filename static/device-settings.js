/* Management-only display overrides. Drafts stay in this page, never localStorage. */
(function () {
    'use strict';
    const fields = [
        ['brightness', 'group_brightness', 'number', 0, 100],
        ['mode', 'group_mode', [['normal', 'group_normal'], ['black', 'group_black']]],
        ['timezone_offset', 'group_timezone', 'number', -12, 14],
        ['time_format', 'group_time_format', [['24h', 'group_24h'], ['12h', 'group_12h']]],
        ['language', 'group_display_language', [['zh-TW', '繁體中文'], ['en', 'English'], ['ja', '日文']]],
        ['night.enabled', 'group_night_enabled', 'boolean'],
        ['night.start', 'group_night_start', 'time'], ['night.end', 'group_night_end', 'time'],
        ['night.brightness', 'group_night_brightness', 'number', 0, 100],
        ['night.black', 'group_night_black', 'boolean']
    ];
    const copy = value => JSON.parse(JSON.stringify(value));
    const at = (value, path) => path.split('.').reduce((row, key) => row[key], value);
    function create({t, request, onBusy}) {
        const editors = new Map();
        const text = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, name) => values[name]);
        function node(tag, className) {
            const element = document.createElement(tag);
            if (className) element.className = className;
            return element;
        }
        function valueText(field, value) {
            if (field[2] === 'boolean') return t(value ? 'enabled' : 'disabled');
            const choice = Array.isArray(field[2]) && field[2].find(row => row[0] === String(value));
            return choice ? t(choice[1]) : String(value);
        }
        function inputValue(field, input) {
            if (field[2] === 'boolean') return input.value === 'true';
            return field[2] === 'number' && /^-?\d+$/.test(input.value) ? Number(input.value) : input.value;
        }
        function dirty(state) {
            state.dirty = true; state.sequence++; state.message = ''; state.error = false;
        }
        function build(device) {
            const state = {id: device.id, info: device.display_settings, base: device.display_settings.revision,
                overrides: copy(device.display_settings.display_overrides), dirty: false, busy: false,
                sequence: 0, message: '', error: false, controls: [], policies: new Map()};
            state.root = node('details', 'device-display-settings group-section');
            state.root.setAttribute('data-device-settings', device.id);
            state.summary = node('summary'); state.hint = node('p', 'help'); state.form = node('form');
            state.root.append(state.summary, state.hint, state.form);
            function policy(key, parent, labelKey) {
                const select = node('select'); select.id = 'device-' + device.id + '-' + key + '-policy';
                const inherit = node('option'); inherit.value = 'inherit';
                const custom = node('option'); custom.value = 'custom'; select.append(inherit, custom);
                parent.append(select); state.policies.set(key, {select, inherit, custom, labelKey});
                select.addEventListener('change', () => {
                    if (select.value === 'inherit') delete state.overrides[key];
                    else state.overrides[key] = copy(state.info.inherited_settings[key]);
                    dirty(state); paint(state);
                });
                return select;
            }
            const night = node('fieldset', 'device-night-settings'), legend = node('legend');
            state.nightLabel = legend; night.append(legend);
            policy('night', night, 'device_night_settings');
            fields.forEach(field => {
                const [path, labelKey, type, low, high] = field;
                const key = path.split('.')[0], row = node('div', 'device-display-row');
                const label = node('label'), input = node(Array.isArray(type) || type === 'boolean' ? 'select' : 'input');
                input.id = 'device-' + device.id + '-' + path.replace('.', '-'); label.htmlFor = input.id;
                const choices = [];
                if (Array.isArray(type) || type === 'boolean') {
                    (type === 'boolean' ? [['true', 'enabled'], ['false', 'disabled']] : type).forEach(([value, title]) => {
                        const option = node('option'); option.value = value; input.append(option); choices.push({option, title});
                    });
                } else {
                    input.type = type; input.required = true;
                    if (type === 'number') { input.min = low; input.max = high; input.step = '1'; }
                }
                row.append(label);
                if (key !== 'night') policy(key, row, labelKey);
                const current = node('p', 'help device-setting-current');
                current.id = input.id + '-current'; input.setAttribute('aria-describedby', current.id);
                row.append(input, current); (key === 'night' ? night : state.form).append(row);
                state.controls.push({field, label, input, choices, current});
                const changed = () => {
                    const next = inputValue(field, input);
                    if (key === 'night') {
                        if (!state.overrides.night || state.overrides.night[path.split('.')[1]] === next) return;
                        state.overrides.night[path.split('.')[1]] = next;
                    } else {
                        if (state.overrides[key] === next) return;
                        state.overrides[key] = next;
                    }
                    dirty(state); paintActions(state);
                };
                input.addEventListener('input', changed); input.addEventListener('change', changed);
            });
            state.form.append(night);
            state.status = node('p', 'help'); state.status.setAttribute('role', 'status'); state.status.setAttribute('aria-live', 'polite');
            const actions = node('div', 'actions'); state.save = node('button', 'primary'); state.save.type = 'submit';
            state.reload = node('button'); state.reload.type = 'button'; actions.append(state.save, state.reload);
            state.form.append(state.status, actions);
            state.form.addEventListener('submit', event => { event.preventDefault(); return save(state); });
            state.reload.addEventListener('click', () => reload(state));
            return state;
        }
        function paintActions(state) {
            const conflict = state.dirty && state.base !== state.info.revision;
            state.save.textContent = t('device_display_save'); state.reload.textContent = t('device_display_reload');
            state.save.disabled = state.busy || state.locked || !state.dirty || conflict;
            state.reload.disabled = state.busy || state.locked;
            state.status.textContent = t(state.busy ? 'loading' : conflict ? 'device_display_conflict' :
                state.message || (state.dirty ? 'group_unsaved' : ''));
            state.status.className = state.error || conflict ? 'error' : 'help';
        }
        function paint(state) {
            state.summary.textContent = t('device_display_title'); state.hint.textContent = t('device_display_hint');
            state.nightLabel.textContent = t('device_night_settings');
            state.policies.forEach(({select, inherit, custom, labelKey}, key) => {
                select.value = key in state.overrides ? 'custom' : 'inherit';
                select.setAttribute('aria-label', t(labelKey) + ' · ' + t('group_setting_source'));
                inherit.textContent = t('device_display_inherit'); custom.textContent = t('group_override');
            });
            state.controls.forEach(({field, label, input, choices, current}) => {
                const path = field[0], key = path.split('.')[0], custom = key in state.overrides;
                label.textContent = t(field[1]); choices.forEach(({option, title}) => { option.textContent = t(title); });
                const value = at(custom ? state.overrides : state.info.inherited_settings, path);
                if (input.value !== String(value)) input.value = String(value);
                input.disabled = !custom;
                current.textContent = text('device_display_current', {
                    value: valueText(field, at(state.info.effective_settings, path)),
                    source: t('device_display_source_' + state.info.sources[path])
                });
            });
            paintActions(state);
        }
        async function save(state) {
            if (state.busy || state.locked || !state.dirty || state.base !== state.info.revision || !state.form.reportValidity()) return;
            const sequence = state.sequence, data = {revision: state.base, display_overrides: copy(state.overrides)};
            state.busy = true; paintActions(state); onBusy();
            try {
                const result = await request(state.id, 'PATCH', data);
                state.info = result; state.base = result.revision; state.error = false;
                if (state.sequence === sequence) { state.overrides = copy(result.display_overrides); state.dirty = false; state.message = 'saved'; }
                else state.message = 'group_saved_more_drafts';
            } catch (error) {
                state.error = true; state.message = error.code === 'display_settings_changed' ? 'device_display_conflict' : 'group_save_failed';
                if (error.code === 'display_settings_changed') {
                    try { state.info = await request(state.id, 'GET'); } catch (_) { /* Keep the draft and last successful values. */ }
                }
            } finally { state.busy = false; paint(state); onBusy(); }
        }
        async function reload(state) {
            if (state.busy || state.locked || (state.dirty && !window.confirm(t('device_display_reload_confirm')))) return;
            const sequence = state.sequence;
            state.busy = true; paintActions(state); onBusy();
            try {
                const result = await request(state.id, 'GET'); state.info = result;
                // Typing during a slow reload keeps the new draft, requiring review.
                if (sequence === state.sequence) {
                    state.overrides = copy(result.display_overrides); state.base = result.revision;
                    state.dirty = false; state.message = ''; state.error = false;
                }
            } catch (_) { state.message = 'group_save_failed'; state.error = true; }
            finally { state.busy = false; paint(state); onBusy(); }
        }
        return {
            busy: id => !!editors.get(id)?.busy,
            forget: id => editors.delete(id),
            render(device, locked = false) {
                if (!device.display_settings) return null;
                if (!editors.has(device.id)) editors.set(device.id, build(device));
                const state = editors.get(device.id); state.locked = locked; state.info = device.display_settings;
                if (!state.dirty && !state.busy) { state.overrides = copy(state.info.display_overrides); state.base = state.info.revision; }
                paint(state); return state.root;
            }
        };
    }
    window.WebClockDeviceSettings = {fields, create};
}());
