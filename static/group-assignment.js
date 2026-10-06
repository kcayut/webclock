/* Shared, independently saved group assignments for management editors. */
(function () {
    'use strict';
    const copy = value => JSON.parse(JSON.stringify(value));
    const itemKey = item => JSON.stringify(item.kind === 'calendar' ? [item.kind, item.target.source_id, item.target.uid, item.target.scope, item.target.recurrence_id || ''] : [item.kind, item.id]);
    function create(options) {
        const t = options.t, editors = new Set(), summaries = new Map();
        let data = null, loading = null, failed = false, epoch = 0;
        const empty = () => ({group_ids: [], partial_group_ids: []});
        async function request(method, body) {
            const init = {method, credentials: 'same-origin', cache: 'no-store', headers: {}};
            if (body) {
                init.headers['Content-Type'] = 'application/json';
                init.headers['X-CSRF-Token'] = document.getElementById('csrf-token').content;
                init.body = JSON.stringify(body);
            }
            const url = window.webclockUrl ? window.webclockUrl('/api/v1/groups/assignments') : '/api/v1/groups/assignments';
            const response = await fetch(url, init), result = await response.json();
            if (!response.ok) throw new Error('Assignment request failed');
            return result;
        }
        function valid(assignment) {
            return assignment && Array.isArray(assignment.group_ids) && Array.isArray(assignment.partial_group_ids);
        }
        function node(tag, className) {
            const result = document.createElement(tag); if (className) result.className = className; return result;
        }
        function summary(element, assignment) {
            summaries.set(element, assignment);
            const names = new Map((data?.groups || []).map(group => [group.id, group.name]));
            element.textContent = !data || !valid(assignment) ? t(failed ? 'assignment_load_failed' : 'assignment_loading') :
                [...assignment.group_ids.map(id => names.get(id) || id), ...assignment.partial_group_ids.map(id => (names.get(id) || id) + ' · ' + t('assignment_partial'))].join(' · ') || t('assignment_none');
        }
        function render() {
            summaries.forEach((assignment, element) => summary(element, assignment));
            editors.forEach(editor => editor.render());
        }
        function changed() { render(); if (options.onChange) options.onChange(); }
        async function load() {
            if (loading) return loading;
            const version = epoch;
            failed = false;
            loading = request('GET').then(result => {
                if (version !== epoch) return;
                if (!Array.isArray(result.groups) || !result.manual_notes || !result.schedules) throw new Error('Invalid assignments');
                data = result; failed = false;
            }).catch(() => { if (version === epoch) failed = true; }).finally(() => { loading = null; changed(); });
            render();
            return loading;
        }
        function get(kind, id) { return data ? data[kind === 'manual_note' ? 'manual_notes' : 'schedules'][String(id)] || empty() : null; }
        function createEditor(container) {
            const drafts = new Map(), choices = new Map();
            const title = node('strong'), allLabel = node('label', 'group-choice'), all = node('input'), allText = node('span');
            const list = node('div'), hint = node('p', 'help'), status = node('p', 'help'), actions = node('div', 'actions');
            const save = node('button'), retry = node('button'); save.type = retry.type = 'button'; all.type = 'checkbox';
            all.setAttribute('data-assignment-all', ''); status.setAttribute('role', 'status');
            container.className += ' content-group-editor'; allLabel.append(all, allText); actions.append(save, retry);
            container.append(title, allLabel, list, hint, actions, status);
            let item = null, current = null;
            function mark() { current.dirty = true; current.message = 'assignment_pending'; current.sequence++; renderEditor(); }
            all.addEventListener('change', () => {
                if (!current || !data) return;
                current.value = {group_ids: all.checked ? data.groups.map(group => group.id) : [], partial_group_ids: []}; mark();
            });
            function renderEditor() {
                container.hidden = !item;
                if (!item || !current) return;
                title.textContent = t('assignment_title'); allText.textContent = t('assignment_all'); hint.textContent = t('assignment_independent');
                save.textContent = t('assignment_save'); retry.textContent = t('assignment_retry');
                all.disabled = save.disabled = current.busy || !data || !current.ready;
                retry.hidden = !failed; retry.disabled = !!loading;
                const groups = data?.groups || [], value = current.value;
                const count = groups.filter(group => value.group_ids.includes(group.id)).length;
                all.checked = groups.length > 0 && count === groups.length && !value.partial_group_ids.length;
                all.indeterminate = !all.checked && (count > 0 || value.partial_group_ids.length > 0);
                if (!groups.length) all.disabled = true;
                const live = new Set();
                groups.forEach((group, index) => {
                    live.add(group.id);
                    let choice = choices.get(group.id);
                    if (!choice) {
                        const label = node('label', 'group-choice'), input = node('input'), text = node('span'); input.type = 'checkbox';
                        input.setAttribute('data-assignment-group', group.id); label.append(input, text); choice = {label, input, text}; choices.set(group.id, choice);
                        input.addEventListener('change', () => {
                            current.value.group_ids = current.value.group_ids.filter(id => id !== group.id);
                            current.value.partial_group_ids = current.value.partial_group_ids.filter(id => id !== group.id);
                            if (input.checked) current.value.group_ids.push(group.id); mark();
                        });
                    }
                    choice.text.textContent = group.name;
                    choice.input.checked = value.group_ids.includes(group.id);
                    choice.input.indeterminate = value.partial_group_ids.includes(group.id);
                    choice.input.disabled = current.busy || !current.ready;
                    if (list.children[index] !== choice.label) list.insertBefore(choice.label, list.children[index] || null);
                });
                choices.forEach((choice, id) => { if (!live.has(id)) { choice.label.remove(); choices.delete(id); } });
                const message = failed ? 'assignment_load_failed' : current.message || (!data || !current.ready ? 'assignment_loading' : !groups.length ? 'assignment_empty' : '');
                status.textContent = message ? t(message) : '';
                status.className = current.message === 'assignment_failed' || failed ? 'form-error' : 'help';
            }
            save.addEventListener('click', async () => {
                if (!item || !data || !current.ready || current.busy) return;
                const draft = current, sentItem = copy(item), sequence = draft.sequence;
                const body = {item: sentItem, group_ids: draft.value.group_ids.slice()};
                if (draft.value.partial_group_ids.length) body.keep_partial_group_ids = draft.value.partial_group_ids.slice();
                draft.busy = true; draft.message = 'loading'; ++epoch; renderEditor();
                try {
                    const result = await request('PUT', body);
                    if (!valid(result.assignment)) throw new Error('Invalid assignment');
                    failed = false;
                    if (Array.isArray(result.groups)) data.groups = result.groups;
                    if (sentItem.kind !== 'calendar') data[sentItem.kind === 'manual_note' ? 'manual_notes' : 'schedules'][String(sentItem.id)] = result.assignment;
                    if (draft.sequence === sequence) { draft.value = copy(result.assignment); draft.dirty = false; draft.message = 'saved'; }
                    else draft.message = 'assignment_pending';
                    if (options.onSaved) options.onSaved(sentItem, result.assignment);
                } catch (error) { draft.message = 'assignment_failed'; }
                finally { ++epoch; draft.busy = false; changed(); }
            });
            retry.addEventListener('click', load);
            const editor = {
                set(nextItem, assignment) {
                    item = nextItem;
                    if (item) {
                        const key = itemKey(item);
                        if (!drafts.has(key)) drafts.set(key, {value: empty(), ready: false, dirty: false, busy: false, sequence: 0, message: ''});
                        current = drafts.get(key);
                        if (!current.dirty && !current.busy && valid(assignment)) { current.value = copy(assignment); current.ready = true; }
                    }
                    renderEditor();
                },
                render: renderEditor,
                remove() { editors.delete(editor); }
            };
            editors.add(editor); return editor;
        }
        return {load, get, summary, createEditor, groups() { return data ? data.groups.slice() : null; }, applyLanguage: render, removeSummary(element) { summaries.delete(element); }};
    }
    window.WebClockAssignments = {create};
}());
