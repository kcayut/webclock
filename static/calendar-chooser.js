/* Shared calendar selection for management pages; clock bootstrap stays separate. */
(function () {
    'use strict';
    const copy = value => JSON.parse(JSON.stringify(value));
    const targetKey = target => JSON.stringify([target.source_id, target.uid, target.scope, target.recurrence_id || '']);
    function visibleChoice(choice) {
        if (choice.input.disabled) return false;
        let child = choice.input;
        for (let parent = child.parentNode; parent; child = parent, parent = parent.parentNode) {
            if (parent.hidden || (String(parent.tagName || parent.tag || '').toLowerCase() === 'details' && !parent.open &&
                String(child.tagName || child.tag || '').toLowerCase() !== 'summary')) return false;
        }
        return !choice.input.getClientRects || choice.input.getClientRects().length > 0;
    }

    function createRange() {
        const anchors = new Map();
        return {
            clear() { anchors.clear(); },
            select(peer, choices, choice, shift) {
                if (!visibleChoice(choice)) return [];
                const visible = choices.filter(visibleChoice);
                const first = visible.indexOf(anchors.get(peer)), last = visible.indexOf(choice);
                if (!shift || first < 0) anchors.set(peer, choice);
                return shift && first >= 0 && last >= 0 ? visible.slice(Math.min(first, last), Math.max(first, last) + 1) : [choice];
            }
        };
    }
    // loadEvents returns the existing {events} catalog. Selection contains only
    // source_ids, targets and optional group exclusions; the caller owns drafts.
    function create(options) {
        const t = options.t, fmt = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, name) => values[name]);
        const choices = new Map(), calendarTrees = new Map(), calendarLoads = new Map(), rangePeers = new Map();
        const range = createRange();
        let sources = [], selection = {source_ids: [], targets: []}, open = new Set(), exclusionsEnabled = false;
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
        function setChoice(content, choice, checked) {
            if (choice.field === 'calendar_source_ids') {
                content.source_ids = content.source_ids.filter(id => id !== choice.item.id);
                if (checked) {
                    content.source_ids.push(choice.item.id);
                    content.targets = content.targets.filter(target => target.source_id !== choice.item.id || target.display_window);
                    if (exclusionsEnabled) content.exclusions = content.exclusions.filter(target => target.source_id !== choice.item.id);
                }
            } else {
                const target = choice.item, existing = content.targets.find(item => targetKey(item) === targetKey(target));
                content.targets = content.targets.filter(item => targetKey(item) !== targetKey(target) &&
                    !(checked && target.scope === 'series' && item.source_id === target.source_id && item.uid === target.uid && !item.display_window));
                if (checked) content.targets.push(copy(existing || target));
                if (exclusionsEnabled) {
                    const sameSeries = item => item.source_id === target.source_id && item.uid === target.uid;
                    content.exclusions = content.exclusions.filter(item => targetKey(item) !== targetKey(target) && !(checked && target.scope === 'series' && sameSeries(item)));
                    if (!checked && target.scope === 'series') content.targets = content.targets.filter(item => !sameSeries(item));
                    if (!checked && choice.covered) content.exclusions.push(copy(target));
                }
            }
        }
        function selectChoice(choice, shift) {
            const selected = range.select(choice.peer, rangePeers.get(choice.peer) || [], choice, shift);
            if (!selected.length) return;
            const next = copy(selection);
            selected.forEach(item => setChoice(next, item, choice.input.checked));
            if (JSON.stringify(next) !== JSON.stringify(selection)) {
                selection = next;
                options.onChange(copy(next));
            }
            renderCurrent();
        }
        function place(parent, element, index) {
            if (parent.children[index] !== element) parent.insertBefore(element, parent.children[index] || null);
        }
        function renderChoice(key, field, item, peer, parent, index, text, checked, disabled = false, partial = false, covered = false) {
            let choice = choices.get(key);
            if (!choice) {
                const label = node('label', undefined, 'group-choice'), input = node('input'), span = node('span');
                input.type = 'checkbox'; input.setAttribute('data-group-content', key);
                label.append(input, span);
                choice = {label, input, text: span}; choices.set(key, choice);
                // Native mouse and keyboard activation both produce click then change.
                input.addEventListener('click', event => { choice.shift = !!event.shiftKey; });
                input.addEventListener('change', () => { const shift = choice.shift; choice.shift = false; selectChoice(choice, shift); });
            }
            Object.assign(choice, {field, item, peer, covered, live: true});
            choice.input.checked = checked; choice.input.disabled = disabled; choice.input.indeterminate = partial;
            choice.text.textContent = text;
            if (!rangePeers.has(peer)) rangePeers.set(peer, []);
            rangePeers.get(peer).push(choice);
            place(parent, choice.label, index);
            return choice;
        }
        function tree(key, source, parent, index, isSource) {
            let result = calendarTrees.get(key);
            if (!result) {
                const details = node('details', undefined, 'group-calendar-node'), summary = node('summary');
                const children = node('div', undefined, 'group-calendar-children'), items = node('div', undefined, 'group-calendar-items');
                result = {details, summary, items, source};
                if (isSource) {
                    const tools = node('div', undefined, 'group-calendar-tools'), status = node('span', undefined, 'help');
                    const refresh = labelNode('button', 'group_calendar_refresh'); refresh.type = 'button';
                    status.setAttribute('role', 'status');
                    refresh.addEventListener('click', () => loadCalendar(source.id));
                    tools.append(status, refresh); children.append(tools); Object.assign(result, {status, refresh});
                }
                children.append(items); details.append(summary, children);
                details.addEventListener('toggle', () => {
                    if (details.open) open.add(key); else open.delete(key);
                    if (isSource && details.open && !result.source.missing && !calendarLoads.get(source.id)?.attempted) loadCalendar(source.id);
                });
                calendarTrees.set(key, result);
            }
            result.source = source; result.live = true;
            if (result.details.open !== open.has(key)) result.details.open = open.has(key);
            place(parent, result.details, index);
            return result;
        }
        async function loadCalendar(sourceId) {
            const state = calendarLoads.get(sourceId) || {events: [], attempted: false};
            if (state.loading) return;
            state.loading = true; state.attempted = true; state.error = false; calendarLoads.set(sourceId, state);
            renderCurrent();
            try {
                const result = await options.loadEvents(sourceId);
                if (calendarLoads.get(sourceId) !== state) return;
                if (!Array.isArray(result.events)) throw new Error('Invalid calendar catalog');
                state.events = result.events.filter(event => event.source_id === sourceId);
            } catch (error) { if (calendarLoads.get(sourceId) === state) state.error = true; }
            finally { state.loading = false; if (calendarLoads.get(sourceId) === state) renderCurrent(); }
        }
        function renderCalendar() {
            const targets = selection.targets, exclusions = selection.exclusions || [], items = sources.slice();
            [...selection.source_ids, ...targets.map(target => target.source_id), ...exclusions.map(target => target.source_id)].forEach(id => {
                if (!items.some(source => source.id === id)) items.push({id, missing: true});
            });
            items.forEach((source, sourceIndex) => {
                const full = selection.source_ids.includes(source.id), selectedTargets = targets.filter(target => target.source_id === source.id);
                const excludedTargets = exclusions.filter(target => target.source_id === source.id), hasExceptions = excludedTargets.length > 0;
                const root = tree('source:' + source.id, source, options.container, sourceIndex, true);
                const name = source.missing ? fmt('group_missing_content', {id: source.id}) : source.name;
                renderChoice('calendar_source_ids:' + source.id, 'calendar_source_ids', source, 'calendar_sources', root.summary, 0,
                    name + ' · ' + t('group_calendar_all'), full && !hasExceptions, false, full && hasExceptions || !full && selectedTargets.length > 0);
                const state = calendarLoads.get(source.id) || {events: []};
                root.refresh.disabled = !!state.loading || !!source.missing;
                root.refresh.textContent = t('group_calendar_refresh');
                root.status.textContent = state.loading ? t('group_calendar_loading') : state.error ? t('group_calendar_failed') :
                    state.attempted && !state.events.length ? t('group_calendar_empty') : '';
                const entries = [], series = new Map(), known = new Set();
                function seriesOf(uid, title, missing) {
                    if (!series.has(uid)) {
                        const item = {uid, title, missing, occurrences: []}; series.set(uid, item); entries.push(item);
                    }
                    return series.get(uid);
                }
                (source.missing ? [] : state.events).forEach(event => {
                    const target = {source_id: source.id, uid: event.uid, scope: 'occurrence', recurrence_id: event.recurrence_id || '',
                        title: (event.text || t('calendar_untitled')).slice(0, 500)};
                    const key = targetKey(target);
                    if (known.has(key)) return;
                    known.add(key);
                    const item = {target, event};
                    if (event.recurring) seriesOf(event.uid, target.title, false).occurrences.push(item); else entries.push(item);
                });
                [...selectedTargets, ...excludedTargets].forEach(target => {
                    if (target.scope === 'series') seriesOf(target.uid, target.title || target.uid, true);
                    else if (!known.has(targetKey(target))) {
                        const item = {target, missing: true}; known.add(targetKey(target));
                        if (target.recurrence_id || series.has(target.uid)) seriesOf(target.uid, target.title || target.uid, true).occurrences.push(item);
                        else entries.push(item);
                    }
                });
                function occurrence(item, parent, index, peer, inherited, disabled) {
                    const target = item.target, event = item.event;
                    const excluded = excludedTargets.some(entry => targetKey(entry) === targetKey(target));
                    const chosen = selectedTargets.some(entry => targetKey(entry) === targetKey(target));
                    let text = target.title || target.uid;
                    if (item.missing) text = fmt('group_calendar_unlisted', {id: text});
                    else if (event?.starts_at) text += ' · ' + (event.all_day ? new Date(event.starts_at).toLocaleDateString(document.documentElement.lang,
                        {timeZone: 'Asia/Taipei'}) + ' · ' + t('calendar_all_day') : new Date(event.starts_at).toLocaleString(document.documentElement.lang, {timeZone: 'Asia/Taipei'}));
                    renderChoice('calendar_targets:' + targetKey(target), 'calendar_targets', target, peer, parent, index, text,
                        !excluded && (inherited || chosen), disabled, false, inherited);
                }
                entries.forEach((item, index) => {
                    const peer = 'source:' + source.id;
                    if (!item.occurrences) { occurrence(item, root.items, index, peer, full, full && !hasExceptions); return; }
                    const target = {source_id: source.id, uid: item.uid, scope: 'series', recurrence_id: '', title: item.title};
                    const key = targetKey(target), chosen = selectedTargets.some(item => targetKey(item) === key);
                    const denied = excludedTargets.some(item => targetKey(item) === key);
                    const childDenies = excludedTargets.some(item => item.uid === target.uid && item.scope === 'occurrence');
                    const allowed = !denied && (full || chosen);
                    const childAllows = selectedTargets.some(item => item.uid === target.uid && item.scope === 'occurrence' && !excludedTargets.some(excluded => targetKey(excluded) === targetKey(item)));
                    const branch = tree('series:' + key, source, root.items, index, false);
                    renderChoice('calendar_targets:' + key, 'calendar_targets', target, peer, branch.summary, 0,
                        (item.missing ? fmt('group_calendar_unlisted', {id: item.title}) : item.title) + ' · ' + t('group_calendar_series'), allowed && !childDenies, full && !hasExceptions,
                        allowed && childDenies || !allowed && childAllows, full);
                    item.occurrences.forEach((child, index) => occurrence(child, branch.items, index, 'series:' + key, allowed, allowed && !childDenies && !hasExceptions));
                });
            });
            return items.length;
        }

        function renderCurrent() {
            rangePeers.clear();
            choices.forEach(choice => { choice.live = false; });
            calendarTrees.forEach(tree => { tree.live = false; });
            const count = renderCalendar();
            choices.forEach((choice, key) => { if (!choice.live) { choice.label.remove(); choices.delete(key); } });
            calendarTrees.forEach((tree, key) => { if (!tree.live) { tree.details.remove(); calendarTrees.delete(key); } });
            return count;
        }
        return {
            render(nextSources, nextSelection, nextOpen) {
                sources = nextSources;
                selection = {source_ids: nextSelection.source_ids || [], targets: nextSelection.targets || []};
                exclusionsEnabled = nextSelection.exclusions !== undefined;
                if (exclusionsEnabled) selection.exclusions = nextSelection.exclusions || [];
                open = nextOpen || open;
                return renderCurrent();
            },
            invalidate(sourceIds) {
                sourceIds.forEach(id => {
                    calendarLoads.delete(id);
                    if (open.has('source:' + id) && sources.some(source => source.id === id)) loadCalendar(id);
                });
                renderCurrent();
            },
            clearAnchors() { range.clear(); }
        };
    }
    window.WebClockCalendarChooser = {create, createRange, targetKey};
}());
