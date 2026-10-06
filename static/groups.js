/* Group management only; no invitations or drafts are stored in browser storage. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    if (!$('group-manager')) return;
    const packs = JSON.parse($('schedule-i18n').textContent);
    const copy = value => JSON.parse(JSON.stringify(value));
    const t = key => (packs[document.documentElement.lang] || packs['zh-TW'])[key] || key;
    const fmt = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, key) => values[key]);
    const NEW = '__new';
    const fields = window.WebClockDeviceSettings.fields;
    const contentFields = [
        ['calendar_source_ids', 'calendar_sources', 'name'],
        ['manual_note_ids', 'manual_notes', 'text'], ['schedule_ids', 'schedules', 'name']
    ];
    let rows = [], selected = '', catalog = null, readVersion = 0, mutationVersion = 0;
    let refreshing = false, stale = false, initializing = false, panelVersion = 0;
    const drafts = new Map(), controls = new Map(), choices = new Map(), invitationBusy = new Set();
    const invitations = new Map(), members = new Map(), panelErrors = new Set();
    const rangePeers = new Map();
    // A code is tied to this one response and selection; changing groups erases it.
    let visibleCode = null;

    function node(tag, text, className) {
        const result = document.createElement(tag);
        if (text !== undefined) result.textContent = text;
        if (className) result.className = className;
        return result;
    }
    function labelNode(tag, key) {
        const result = node(tag, t(key));
        result.setAttribute('data-group-i18n', key);
        return result;
    }
    async function request(url, method = 'GET', data) {
        const options = {method, cache: 'no-store', credentials: 'same-origin', headers: {}};
        if (data !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
        if (method !== 'GET') options.headers['X-CSRF-Token'] = $('csrf-token').content;
        const response = await fetch(window.webclockUrl ? window.webclockUrl(url) : url, options);
        const result = await response.json();
        if (!response.ok) {
            const error = new Error(t(result.code === 'group_has_members' ? 'group_has_members' : 'group_request_failed'));
            error.code = result.code;
            throw error;
        }
        return result;
    }
    const api = (path, method, data) => request('/api/v1/groups' + path, method, data);
    function dataOf(row) {
        return {name: row.name, enabled: row.enabled, display_overrides: copy(row.display_overrides), content: copy(row.content)};
    }
    function createDraft(data) {
        return {data: copy(data), dirty: false, sequence: 0, busy: false, message: '', error: false, capacity: '5', open: new Set()};
    }
    function current() { return drafts.get(selected); }
    function at(value, path) {
        const parts = path.split('.');
        return parts.length === 1 ? value[parts[0]] : (value[parts[0]] || {})[parts[1]];
    }
    function setOverride(value, path, next) {
        const parts = path.split('.');
        if (parts.length === 1) {
            if (next === undefined) delete value[path]; else value[path] = next;
        } else {
            if (!value[parts[0]]) value[parts[0]] = {};
            if (next === undefined) delete value[parts[0]][parts[1]]; else value[parts[0]][parts[1]] = next;
            if (!Object.keys(value[parts[0]]).length) delete value[parts[0]];
        }
    }
    function changeDraft(change) {
        const draft = current();
        if (!draft) return;
        change(draft.data);
        draft.sequence++;
        draft.dirty = true;
        draft.message = '';
        draft.error = false;
        renderActions();
    }
    function displayValue(field, value) {
        if (value === undefined) return t('unknown');
        if (field[2] === 'boolean') return t(value ? 'enabled' : 'disabled');
        if (Array.isArray(field[2])) {
            const option = field[2].find(item => item[0] === String(value));
            return option ? t(option[1]) : String(value);
        }
        return String(value);
    }
    function inputValue(field, input) {
        if (field[2] === 'boolean') return input.value === 'true';
        // Keep incomplete numeric drafts as text until a valid submit.
        return field[2] === 'number' && /^-?\d+$/.test(input.value) ? Number(input.value) : input.value;
    }
    function buildFields() {
        fields.forEach(field => {
            const [path, key, type, minimum, maximum] = field;
            const row = node('div', undefined, 'group-setting');
            const id = 'group-' + path.replace('.', '-');
            const label = labelNode('label', key);
            label.htmlFor = id;
            const policy = node('select');
            policy.id = id + '-policy';
            policy.setAttribute('aria-label', t(key) + ' · ' + t('group_setting_source'));
            const inherit = node('option'); inherit.value = 'inherit';
            const custom = labelNode('option', 'group_override'); custom.value = 'custom';
            policy.append(inherit, custom);
            const input = node(Array.isArray(type) || type === 'boolean' ? 'select' : 'input');
            input.id = id;
            if (Array.isArray(type) || type === 'boolean') {
                (type === 'boolean' ? [['true', 'enabled'], ['false', 'disabled']] : type).forEach(([value, text]) => {
                    const option = labelNode('option', text); option.value = value; input.append(option);
                });
            } else {
                input.type = type;
                input.required = true;
                if (type === 'number') { input.min = minimum; input.max = maximum; input.step = '1'; }
            }
            const values = node('div', undefined, 'group-setting-values'); values.append(policy, input);
            row.append(label, values);
            $('group-settings').append(row);
            controls.set(path, {field, policy, inherit, input});
            policy.addEventListener('change', () => {
                changeDraft(data => setOverride(data.display_overrides, path,
                    policy.value === 'inherit' ? undefined : inputValue(field, input)));
                renderValues();
            });
            input.addEventListener('input', () => changeDraft(data => setOverride(data.display_overrides, path, inputValue(field, input))));
            input.addEventListener('change', () => {
                const next = inputValue(field, input);
                if (at(current().data.display_overrides, path) !== next) changeDraft(data => setOverride(data.display_overrides, path, next));
            });
        });
    }

    const range = window.WebClockCalendarChooser.createRange();
    const notesAll = node('input'), notesAllLabel = node('label', undefined, 'group-choice');
    notesAll.type = 'checkbox'; notesAll.setAttribute('data-group-select-all', 'manual_note_ids');
    notesAllLabel.append(notesAll, labelNode('span', 'group_notes_select_all'));
    notesAll.addEventListener('change', () => {
        if (!current() || !catalog || !catalog.manual_notes.length) return;
        const available = new Set(catalog.manual_notes.map(item => item.id));
        changeDraft(data => {
            data.content.manual_note_ids = data.content.manual_note_ids.filter(id => !available.has(id));
            if (notesAll.checked) data.content.manual_note_ids.push(...available);
        });
        renderChoices();
    });
    const calendarChooser = window.WebClockCalendarChooser.create({
        container: $('group-calendar_source_ids'), t,
        loadEvents: id => request('/api/v1/calendar-events?source_id=' + encodeURIComponent(id)),
        onChange(selection) {
            changeDraft(data => {
                data.content.calendar_source_ids = selection.source_ids;
                if (selection.targets.length) data.content.calendar_targets = selection.targets;
                else delete data.content.calendar_targets;
                if (selection.exclusions.length) data.content.calendar_exclusions = selection.exclusions;
                else delete data.content.calendar_exclusions;
            });
        }
    });
    function selectChoice(choice, shift) {
        if (!current()) return;
        const selected = range.select(choice.peer, rangePeers.get(choice.peer) || [], choice, shift);
        if (!selected.length) return;
        changeDraft(data => selected.forEach(item => {
            const ids = data.content[item.field].filter(id => id !== item.item.id);
            if (choice.input.checked) ids.push(item.item.id);
            data.content[item.field] = ids;
        }));
        renderChoices();
    }
    function renderChoice(key, field, item, parent, index, text, checked) {
        let choice = choices.get(key);
        if (!choice) {
            const label = node('label', undefined, 'group-choice'), input = node('input'), span = node('span');
            input.type = 'checkbox'; input.setAttribute('data-group-content', key);
            label.append(input, span);
            choice = {label, input, text: span}; choices.set(key, choice);
            input.addEventListener('click', event => { choice.shift = !!event.shiftKey; });
            input.addEventListener('change', () => { const shift = choice.shift; choice.shift = false; selectChoice(choice, shift); });
        }
        Object.assign(choice, {field, item, peer: field, live: true});
        choice.input.checked = checked; choice.input.disabled = false;
        choice.text.textContent = text;
        if (!rangePeers.has(field)) rangePeers.set(field, []);
        rangePeers.get(field).push(choice);
        if (parent.children[index] !== choice.label) parent.insertBefore(choice.label, parent.children[index] || null);
    }
    function renderChoices() {
        const draft = current();
        if (!draft || !catalog) return;
        rangePeers.clear(); choices.forEach(choice => { choice.live = false; });
        contentFields.filter(([field]) => field !== 'calendar_source_ids').forEach(([field, key, title]) => {
            const container = $('group-' + field), selectedIds = draft.data.content[field];
            const items = catalog[key].slice();
            let offset = 0;
            if (field === 'manual_note_ids') {
                const count = items.filter(item => selectedIds.includes(item.id)).length;
                notesAll.checked = items.length > 0 && count === items.length;
                notesAll.indeterminate = count > 0 && count < items.length;
                notesAll.disabled = items.length === 0;
                if (container.children[0] !== notesAllLabel) container.insertBefore(notesAllLabel, container.children[0] || null);
                offset = 1;
            }
            selectedIds.forEach(id => {
                if (!items.some(item => item.id === id)) items.push({id, missing: true});
            });
            items.forEach((item, index) => {
                const choiceId = field + ':' + item.id;
                renderChoice(choiceId, field, item, container, index + offset,
                    item.missing ? fmt('group_missing_content', {id: item.id}) : (item[title] || String(item.id)), selectedIds.includes(item.id));
            });
            $('group-' + field + '-empty').hidden = items.length > 0;
        });
        $('group-calendar_source_ids-empty').hidden = calendarChooser.render(catalog.calendar_sources,
            {source_ids: draft.data.content.calendar_source_ids, targets: draft.data.content.calendar_targets || [], exclusions: draft.data.content.calendar_exclusions || []}, draft.open) > 0;
        choices.forEach((choice, key) => { if (!choice.live) { choice.label.remove(); choices.delete(key); } });
    }
    function renderSelector() {
        const value = selected;
        $('group-select').replaceChildren();
        const empty = node('option', t('group_choose')); empty.value = ''; $('group-select').append(empty);
        rows.forEach(row => {
            const option = node('option', row.name + (drafts.get(row.id)?.dirty ? ' *' : ''));
            option.value = row.id; $('group-select').append(option);
        });
        if (value && value !== NEW && !rows.some(row => row.id === value) && drafts.has(value)) {
            const option = node('option', drafts.get(value).data.name + ' *'); option.value = value; $('group-select').append(option);
        }
        if (drafts.has(NEW)) { const option = node('option', t('group_new')); option.value = NEW; $('group-select').append(option); }
        $('group-select').value = value;
        $('group-initialize').hidden = rows.some(row => row.is_default);
        $('group-initialize').disabled = initializing || !catalog;
        $('group-add').disabled = !catalog;
    }
    function renderActions() {
        const draft = current(), existing = selected && selected !== NEW;
        $('group-form').hidden = !draft;
        $('group-access').hidden = !existing;
        $('group-save').disabled = !draft || draft.busy;
        $('group-delete').hidden = !existing;
        $('group-delete').disabled = !draft || draft.busy || invitationBusy.has(selected);
        $('group-form-status').textContent = draft ? t(draft.message || (draft.dirty ? 'group_unsaved' : '')) : '';
        $('group-form-status').className = draft?.error ? 'error' : 'help';
        $('group-refresh-status').textContent = stale ? t('group_stale') : '';
        const busy = invitationBusy.has(selected);
        const row = rows.find(item => item.id === selected);
        $('group-invite-create').disabled = !existing || busy || !row?.enabled;
        $('group-invite-close').disabled = !existing || busy || !invitations.get(selected) || invitations.get(selected).status === 'closed';
    }
    function renderValues() {
        const draft = current();
        renderActions();
        if (!draft || !catalog) return;
        if ($('group-name').value !== draft.data.name) $('group-name').value = draft.data.name;
        $('group-enabled').checked = draft.data.enabled;
        if ($('group-invite-capacity').value !== draft.capacity) $('group-invite-capacity').value = draft.capacity;
        controls.forEach(({field, input, policy, inherit}, path) => {
            const override = at(draft.data.display_overrides, path), inherited = override === undefined;
            const value = inherited ? at(catalog.defaults, path) : override;
            policy.value = inherited ? 'inherit' : 'custom';
            input.disabled = inherited;
            if (input.value !== String(value)) input.value = String(value);
            inherit.textContent = fmt('group_inherit_value', {value: displayValue(field, at(catalog.defaults, path))});
            policy.setAttribute('aria-label', t(field[1]) + ' · ' + t('group_setting_source'));
        });
        renderChoices();
    }
    function renderAccess() {
        const info = invitations.get(selected);
        $('group-invite-status').textContent = info ? fmt('group_invite_details', {
            state: t('group_invite_' + info.status), remaining: info.remaining, capacity: info.capacity,
            expires: new Date(info.expires_at).toLocaleString(document.documentElement.lang)
        }) : t('group_invite_none');
        $('group-access-status').textContent = panelErrors.has(selected) ? t('group_access_stale') : '';
        const show = visibleCode && visibleCode.groupId === selected && info && info.status === 'active' && info.id === visibleCode.inviteId;
        $('group-code-box').hidden = !show;
        $('group-code').textContent = show ? visibleCode.code : '';
        if (!show) visibleCode = null;
        const list = $('group-members'); list.replaceChildren();
        const memberRows = members.get(selected) || [];
        memberRows.forEach(member => {
            const li = node('li', undefined, 'group-member');
            li.append(node('strong', member.name || member.id || member.device_id));
            const status = member.status || (member.enabled ? 'active' : 'disabled');
            const online = typeof member.online === 'boolean' ? t(member.online ? 'online' : 'offline') : t('unknown');
            const permission = member.group_enabled === false ? t('group_invite_disabled') : t('group_member_' + status);
            li.append(node('span', permission + ' · ' + online, 'help'));
            if (member.last_seen) li.append(node('span', t('last_seen') + ': ' + new Date(member.last_seen).toLocaleString(document.documentElement.lang), 'help'));
            list.append(li);
        });
        if (!memberRows.length) list.append(node('li', t('group_members_empty'), 'empty'));
        renderActions();
    }
    async function loadAccess() {
        const id = selected, version = ++panelVersion, epoch = mutationVersion;
        if (!id || id === NEW) return;
        try {
            const [invitation, result] = await Promise.all([
                api('/' + encodeURIComponent(id) + '/invite'), api('/' + encodeURIComponent(id) + '/members')
            ]);
            if (version !== panelVersion || epoch !== mutationVersion) return;
            invitations.set(id, invitation.invite); members.set(id, result.members); panelErrors.delete(id);
        } catch (error) { if (version === panelVersion) panelErrors.add(id); }
        if (id === selected) renderAccess();
    }
    function choose(id) {
        selected = id; visibleCode = null; range.clear(); calendarChooser.clearAnchors(); ++panelVersion;
        if (id && !drafts.has(id)) {
            const row = rows.find(item => item.id === id);
            if (row) drafts.set(id, createDraft(dataOf(row)));
        }
        renderSelector(); renderValues(); renderAccess(); loadAccess();
    }
    async function refresh() {
        if (refreshing) return;
        refreshing = true;
        const version = ++readVersion, epoch = mutationVersion;
        try {
            const [result, available] = await Promise.all([api(''), api('/catalog')]);
            if (version !== readVersion || epoch !== mutationVersion) return;
            rows = result.groups; catalog = available; stale = false;
            const focused = $('group-form').contains(document.activeElement);
            rows.forEach(row => {
                const draft = drafts.get(row.id);
                if (!draft) drafts.set(row.id, createDraft(dataOf(row)));
                else if (!draft.dirty && !draft.busy && !(selected === row.id && focused)) draft.data = dataOf(row);
            });
            if (!selected && rows.length) selected = rows[0].id;
            // A remotely removed group keeps its unsaved draft visible for review.
            if (selected && selected !== NEW && !rows.some(row => row.id === selected)) {
                const draft = current();
                if (draft?.dirty) { draft.message = 'group_removed'; draft.error = true; }
                else selected = '';
            }
            renderSelector(); renderValues();
            await loadAccess();
        } catch (error) { if (version === readVersion) { stale = true; renderActions(); } }
        finally { refreshing = false; }
    }
    async function save(event) {
        event.preventDefault();
        const draft = current(), id = selected;
        if (!draft || draft.busy) return;
        if ($('group-form').reportValidity && !$('group-form').reportValidity()) return;
        const sent = copy(draft.data), sequence = draft.sequence;
        // Group content PATCH merges fields; omission must not retain old targets.
        if (id !== NEW && !sent.content.calendar_targets) sent.content.calendar_targets = [];
        if (id !== NEW && !sent.content.calendar_exclusions) sent.content.calendar_exclusions = [];
        draft.busy = true; draft.message = 'group_saving'; draft.error = false; ++mutationVersion; renderActions();
        try {
            const row = await api(id === NEW ? '' : '/' + encodeURIComponent(id), id === NEW ? 'POST' : 'PATCH', sent);
            ++mutationVersion;
            rows = rows.filter(item => item.id !== row.id); rows.push(row);
            if (draft.sequence === sequence) { draft.data = dataOf(row); draft.dirty = false; draft.message = 'saved'; }
            else draft.message = 'group_saved_more_drafts';
            if (id === NEW) {
                drafts.delete(NEW); drafts.set(row.id, draft);
                if (selected === NEW) selected = row.id;
            }
        } catch (error) { draft.message = 'group_save_failed'; draft.error = true; }
        finally {
            draft.busy = false; ++mutationVersion;
            renderSelector(); renderValues(); if (selected !== NEW) loadAccess();
        }
    }
    async function invite(method) {
        const id = selected;
        if (!id || id === NEW || invitationBusy.has(id)) return;
        const capacity = Number($('group-invite-capacity').value);
        if (method === 'POST' && (!Number.isInteger(capacity) || capacity < 1 || capacity > 100)) {
            $('group-access-status').textContent = t('group_capacity_error'); return;
        }
        invitationBusy.add(id); visibleCode = null; ++mutationVersion; ++panelVersion; renderAccess();
        try {
            const result = await api('/' + encodeURIComponent(id) + '/invite', method, method === 'POST' ? {capacity} : undefined);
            const info = method === 'POST' ? result : result.invite;
            if (method === 'POST' && selected === id) visibleCode = {groupId: id, inviteId: result.id, code: result.code};
            if (info) delete info.code;
            invitations.set(id, info); panelErrors.delete(id);
        } catch (error) { panelErrors.add(id); }
        finally { ++mutationVersion; invitationBusy.delete(id); if (selected === id) renderAccess(); }
    }
    $('group-select').addEventListener('change', () => choose($('group-select').value));
    $('group-add').addEventListener('click', () => {
        if (!drafts.has(NEW)) drafts.set(NEW, createDraft({name: '', enabled: true, display_overrides: {},
            content: {calendar_source_ids: [], manual_note_ids: [], schedule_ids: []}}));
        choose(NEW); $('group-name').focus();
    });
    $('group-name').addEventListener('input', () => changeDraft(data => { data.name = $('group-name').value; }));
    $('group-enabled').addEventListener('change', () => changeDraft(data => { data.enabled = $('group-enabled').checked; }));
    $('group-form').addEventListener('submit', save);
    $('group-refresh').addEventListener('click', refresh);
    $('group-invite-create').addEventListener('click', () => invite('POST'));
    $('group-invite-close').addEventListener('click', () => invite('DELETE'));
    $('group-invite-capacity').addEventListener('input', () => { if (current()) current().capacity = $('group-invite-capacity').value; });
    $('group-delete').addEventListener('click', async () => {
        const id = selected, draft = current();
        if (!draft || draft.busy || id === NEW || !window.confirm(fmt('group_delete_confirm', {name: draft.data.name}))) return;
        draft.busy = true; ++mutationVersion; renderActions();
        try {
            await api('/' + encodeURIComponent(id), 'DELETE');
            rows = rows.filter(row => row.id !== id); drafts.delete(id); invitations.delete(id); members.delete(id);
            if (selected === id) choose(rows[0]?.id || '');
        } catch (error) { draft.message = error.code === 'group_has_members' ? 'group_has_members' : 'group_save_failed'; draft.error = true; }
        finally { draft.busy = false; ++mutationVersion; renderSelector(); renderActions(); loadAccess(); }
    });
    $('group-initialize').addEventListener('click', async () => {
        if (initializing || !window.confirm(t('group_initialize_confirm'))) return;
        initializing = true; ++mutationVersion; renderSelector();
        try {
            const row = await api('/initialize', 'POST', {name: t('group_default_name')});
            rows = rows.filter(item => item.id !== row.id); rows.push(row);
            drafts.set(row.id, createDraft(dataOf(row))); choose(row.id);
        } catch (error) { stale = true; }
        finally { initializing = false; ++mutationVersion; renderSelector(); renderActions(); loadAccess(); }
    });
    function applyLanguage() {
        document.querySelectorAll('[data-group-i18n]').forEach(element => { element.textContent = t(element.getAttribute('data-group-i18n')); });
        renderSelector(); renderValues(); renderAccess();
    }
    function memberRemoved(id) {
        ++mutationVersion; ++panelVersion;
        members.forEach((rows, groupId) => members.set(groupId, rows.filter(member => (member.id || member.device_id) !== id)));
        renderAccess();
        loadAccess();
    }
    window.WebClockGroups = {applyLanguage, refresh, memberRemoved};
    buildFields(); applyLanguage(); refresh();
    setInterval(refresh, 15000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}());
