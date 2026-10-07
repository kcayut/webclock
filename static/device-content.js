/* Management-only content assignments; drafts never leave this page before saving. */
(function () {
    'use strict';
    const copy = value => JSON.parse(JSON.stringify(value));
    const calendarFields = ['calendar_source_ids', 'calendar_targets', 'calendar_exclusions'];
    const fields = [
        ['calendar_source_ids', 'calendar_sources', 'name', 'group_calendars', 'calendar'],
        ['manual_note_ids', 'manual_notes', 'text', 'group_notes', 'manual_note_ids'],
        ['schedule_ids', 'schedules', 'name', 'group_schedules', 'schedule_ids']
    ];
    function create({t, request, loadCatalog, loadEvents, onBusy}) {
        const editors = new Map();
        let catalog = null, catalogLoading = false, catalogFailed = false;
        const format = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, name) => values[name]);
        function node(tag, className) {
            const element = document.createElement(tag);
            if (className) element.className = className;
            return element;
        }
        function changed(state) {
            state.dirty = true; state.sequence++; state.message = ''; state.error = false;
        }
        function build(device) {
            const info = device.content_settings;
            const state = {id: device.id, info, base: info.revision, overrides: copy(info.content_overrides),
                dirty: false, busy: false, sequence: 0, message: '', error: false, conflict: false,
                sections: [], open: new Set()};
            state.root = node('details', 'device-content-settings group-section');
            state.root.setAttribute('data-device-content', state.id);
            state.summary = node('summary'); state.hint = node('p', 'help'); state.form = node('form');
            state.catalogStatus = node('p', 'error'); state.catalogStatus.setAttribute('role', 'status');
            state.root.append(state.summary, state.hint, state.catalogStatus, state.form);
            fields.forEach(([key, collection, title, labelKey, sourceKey]) => {
                const section = node('section', 'device-content-section'), label = node('label');
                const policy = node('select'), inherit = node('option'), custom = node('option');
                policy.id = 'device-content-' + state.id + '-' + key;
                label.htmlFor = policy.id; inherit.value = 'inherit'; custom.value = 'custom'; policy.append(inherit, custom);
                const options = node('fieldset', 'device-content-options'), legend = node('legend');
                const list = node('div', 'group-content-options'), empty = node('p', 'help');
                options.append(legend, list, empty);
                const current = node('p', 'help'), preview = node('ul', 'device-content-preview');
                section.append(label, policy, current, preview, options); state.form.append(section);
                const row = {key, collection, title, labelKey, sourceKey, label, policy, inherit, custom,
                    options, legend, list, empty, current, preview, choices: new Map()};
                state.sections.push(row);
                policy.addEventListener('change', () => {
                    (key === 'calendar_source_ids' ? calendarFields : [key]).forEach(field => {
                        if (policy.value === 'inherit') delete state.overrides[field];
                        else state.overrides[field] = copy(state.info.inherited_content[field] || []);
                    });
                    changed(state); paint(state);
                });
                if (key === 'calendar_source_ids') row.chooser = window.WebClockCalendarChooser.create({
                    container: list, t, loadEvents,
                    onChange(selection) {
                        if (!(key in state.overrides)) return;
                        state.overrides.calendar_source_ids = selection.source_ids;
                        state.overrides.calendar_targets = selection.targets;
                        state.overrides.calendar_exclusions = selection.exclusions;
                        changed(state); paintActions(state);
                    }
                });
            });
            state.status = node('p', 'help'); state.status.setAttribute('role', 'status'); state.status.setAttribute('aria-live', 'polite');
            const actions = node('div', 'actions'); state.save = node('button', 'primary'); state.save.type = 'submit';
            state.reload = node('button'); state.reload.type = 'button'; actions.append(state.save, state.reload);
            state.form.append(state.status, actions);
            state.form.addEventListener('submit', event => { event.preventDefault(); return save(state); });
            state.reload.addEventListener('click', () => reload(state));
            return state;
        }
        function paintActions(state) {
            const conflict = state.conflict || state.dirty && state.base !== state.info.revision;
            state.save.textContent = t('device_content_save'); state.reload.textContent = t('device_content_reload');
            state.save.disabled = state.busy || state.locked || !state.dirty || conflict;
            state.reload.disabled = state.busy || state.locked;
            state.status.textContent = t(state.busy ? 'loading' : conflict ? 'device_content_conflict' :
                state.message || (state.dirty ? 'group_unsaved' : ''));
            state.status.className = state.error || conflict ? 'error' : 'help';
        }
        function itemName(collection, title, id) {
            if (!catalog) return String(id);
            const item = catalog && catalog[collection].find(item => item.id === id);
            return item ? item[title] || String(id) : format('group_missing_content', {id});
        }
        function paintPreview(state, row) {
            const content = state.info.effective_content;
            row.current.textContent = format('device_content_current', {source: t('device_display_source_' + state.info.sources[row.sourceKey])});
            const names = (content[row.key] || []).map(id => itemName(row.collection, row.title, id));
            if (row.key === 'calendar_source_ids') {
                ['calendar_targets', 'calendar_exclusions'].forEach(key => (content[key] || []).forEach(target => {
                    names.push((key === 'calendar_exclusions' ? t('device_content_excluded') + ' · ' : '') +
                        itemName('calendar_sources', 'name', target.source_id) + ' · ' + (target.title || target.uid) +
                        ' · ' + t('calendar_scope_' + target.scope) + (target.recurrence_id ? ' · ' + target.recurrence_id : ''));
                }));
            }
            row.preview.replaceChildren();
            (names.length ? names : [t('none')]).forEach(name => {
                const item = node('li'); item.textContent = name; row.preview.append(item);
            });
        }
        function paintChoices(state, row) {
            const custom = row.key in state.overrides, content = custom ? state.overrides : state.info.inherited_content;
            row.options.hidden = !custom;
            if (!catalog) return;
            if (row.chooser) {
                row.empty.hidden = row.chooser.render(catalog.calendar_sources, {
                    source_ids: content.calendar_source_ids, targets: content.calendar_targets || [],
                    exclusions: content.calendar_exclusions || []
                }, state.open) > 0;
                return;
            }
            const ids = content[row.key] || [], items = catalog[row.collection].slice(), live = new Set();
            ids.forEach(id => { if (!items.some(item => item.id === id)) items.push({id}); });
            items.forEach((item, index) => {
                live.add(item.id);
                let choice = row.choices.get(item.id);
                if (!choice) {
                    const label = node('label', 'group-choice'), input = node('input'), text = node('span');
                    input.type = 'checkbox'; input.setAttribute('data-device-content-choice', row.key + ':' + item.id);
                    label.append(input, text); choice = {label, input, text}; row.choices.set(item.id, choice);
                    input.addEventListener('change', () => {
                        if (!(row.key in state.overrides)) return;
                        state.overrides[row.key] = state.overrides[row.key].filter(id => id !== item.id);
                        if (input.checked) state.overrides[row.key].push(item.id);
                        changed(state); paintActions(state);
                    });
                }
                choice.input.checked = ids.includes(item.id);
                choice.text.textContent = item[row.title] || format('group_missing_content', {id: item.id});
                if (row.list.children[index] !== choice.label) row.list.insertBefore(choice.label, row.list.children[index] || null);
            });
            row.choices.forEach((choice, id) => { if (!live.has(id)) { choice.label.remove(); row.choices.delete(id); } });
            row.empty.hidden = items.length > 0;
        }
        function paint(state) {
            state.summary.textContent = t('device_content_title'); state.hint.textContent = t('device_content_hint');
            state.catalogStatus.textContent = catalogFailed ? t('device_content_catalog_failed') : !catalog ? t('loading') : '';
            state.sections.forEach(row => {
                row.label.textContent = row.legend.textContent = t(row.labelKey);
                row.policy.value = row.key in state.overrides ? 'custom' : 'inherit';
                row.policy.disabled = !!state.locked;
                row.inherit.textContent = t('device_display_inherit'); row.custom.textContent = t('group_override');
                row.empty.textContent = t('group_content_empty'); row.options.disabled = !!state.locked;
                paintChoices(state, row); paintPreview(state, row);
            });
            paintActions(state);
        }
        async function refreshCatalog() {
            if (catalogLoading) return;
            catalogLoading = true;
            try {
                const result = await loadCatalog();
                if (!fields.every(([, collection]) => Array.isArray(result[collection]))) throw new Error('Invalid content catalog');
                catalog = result; catalogFailed = false;
            } catch (_) { catalogFailed = true; }
            finally { catalogLoading = false; editors.forEach(paint); }
        }
        async function save(state) {
            if (state.busy || state.locked || !state.dirty || state.conflict || state.base !== state.info.revision) return;
            const sequence = state.sequence, data = {revision: state.base, content_overrides: copy(state.overrides)};
            state.busy = true; paintActions(state); onBusy();
            try {
                const result = await request(state.id, 'PATCH', data);
                state.info = result; state.base = result.revision; state.error = false;
                if (sequence === state.sequence) { state.overrides = copy(result.content_overrides); state.dirty = false; state.message = 'saved'; }
                else state.message = 'group_saved_more_drafts';
            } catch (error) {
                state.error = true; state.message = 'group_save_failed';
                if (error.code === 'content_settings_changed') {
                    state.conflict = true;
                    try { state.info = await request(state.id, 'GET'); } catch (_) { /* Preserve the draft and last successful preview. */ }
                }
            } finally { state.busy = false; paint(state); onBusy(); }
        }
        async function reload(state) {
            if (state.busy || state.locked || state.dirty && !window.confirm(t('device_content_reload_confirm'))) return;
            const sequence = state.sequence;
            state.busy = true; paintActions(state); onBusy(); refreshCatalog();
            try {
                const result = await request(state.id, 'GET'); state.info = result;
                if (sequence === state.sequence) {
                    state.overrides = copy(result.content_overrides); state.base = result.revision;
                    state.dirty = state.conflict = state.error = false; state.message = '';
                }
            } catch (_) { state.message = 'group_save_failed'; state.error = true; }
            finally { state.busy = false; paint(state); onBusy(); }
        }
        return {
            refreshCatalog,
            busy: id => !!editors.get(id)?.busy,
            forget: id => editors.delete(id),
            render(device, locked = false) {
                if (!device.content_settings) return null;
                if (!editors.has(device.id)) editors.set(device.id, build(device));
                const state = editors.get(device.id); state.info = device.content_settings; state.locked = locked;
                if (!state.dirty && !state.busy) { state.overrides = copy(state.info.content_overrides); state.base = state.info.revision; }
                paint(state); return state.root;
            }
        };
    }
    window.WebClockDeviceContent = {create};
}());
