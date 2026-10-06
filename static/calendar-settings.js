/* Calendar management stays separate from the lightweight clock page. */
(function () {
    'use strict';
    var saved = null, busy = false, rows = [], serial = 0, sourcesSaved = false;
    var selection = {source_ids: [], targets: []}, displayDirty = false, treeOpen = new Set();
    var chooser = null, localChoice = null, treeContainer = null;
    var cards = new Map(), listGeneration = 0;
    var noteAssignments = [];
    var assignments = window.WebClockAssignments ? window.WebClockAssignments.create({t: t, onChange: refreshAssignments,
        onSaved: function (item, assignment) {
            if (item.kind === 'calendar') {
                cards.forEach(function (card) {
                    if (targetKey(card.item.target) === targetKey(item.target)) card.item.assignment = assignment;
                    if (card.item.series_target && targetKey(card.item.series_target) === targetKey(item.target)) card.item.series_assignment = assignment;
                });
                refreshList();
            }
        }
    }) : null;
    var providers = ['apple', 'google', 'ics'];
    var addButtons = document.querySelectorAll('[data-calendar-add]');
    function $(id) { return document.getElementById(id); }
    function t(key) { return window.t(key); }
    function copy(value) { return JSON.parse(JSON.stringify(value)); }
    function targetKey(target) { return window.WebClockCalendarChooser.targetKey(target); }
    function node(tag, text, className) {
        var element = document.createElement(tag);
        if (text !== undefined) element.textContent = text;
        if (className) element.className = className;
        return element;
    }
    function label(key, tag) {
        var element = node(tag || 'span', t(key));
        element.setAttribute('data-i18n', key);
        return element;
    }
    function status(id, key, failed) {
        var element = $(id);
        element.textContent = key ? t(key) : '';
        if (key) element.setAttribute('data-i18n', key);
        else element.removeAttribute('data-i18n');
        element.className = failed ? 'form-error' : '';
    }
    function controls() {
        $('calendar-source-fields').disabled = busy || !saved;
        $('calendar-display-fields').disabled = busy || !saved;
        cards.forEach(function (card) { card.fields.disabled = busy || !saved; });
        for (var i = 0; i < addButtons.length; i++) addButtons[i].disabled = rows.length >= 20;
    }
    function validState(data) {
        if (!data || !Array.isArray(data.sources) || data.sources.length > 20 || typeof data.local_display_enabled !== 'boolean' ||
            (data.calendar_targets !== undefined && !Array.isArray(data.calendar_targets))) return false;
        var ids = Object.create(null);
        return data.sources.every(function (source) {
            if (!source || typeof source.id !== 'string' || !source.id || ids[source.id] ||
                typeof source.name !== 'string' || !source.name.trim() || typeof source.url !== 'string' || !source.url.trim() ||
                providers.indexOf(source.provider) < 0 || typeof source.display_enabled !== 'boolean') return false;
            ids[source.id] = true;
            return true;
        });
    }
    function send(method, url, payload, done) {
        var xhr = new XMLHttpRequest();
        var finished = false;
        xhr.open(method, window.webclockUrl ? window.webclockUrl(url) : url, true);
        xhr.timeout = 15000;
        function finish(ok, data) {
            if (finished) return;
            finished = true;
            done(ok, data || {});
        }
        xhr.onload = function () {
            var data;
            try { data = JSON.parse(xhr.responseText); } catch (error) { finish(false); return; }
            finish(xhr.status >= 200 && xhr.status < 300, data);
        };
        xhr.onerror = xhr.ontimeout = function () { finish(false); };
        if (payload) {
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.setRequestHeader('X-CSRF-Token', $('csrf-token').content);
            xhr.send(JSON.stringify(payload));
        } else xhr.send();
    }
    function request(method, payload, done) {
        busy = true;
        if (method !== 'GET') { listGeneration++; status('calendar-list-status', ''); }
        controls();
        send(method, '/api/calendar', payload, function (ok, data) {
            busy = false;
            done(ok && validState(data), data);
            controls();
        });
    }
    function visibilityDraft() {
        var values = Object.create(null);
        saved.sources.forEach(function (source) { values[source.id] = selection.source_ids.indexOf(source.id) >= 0; });
        return {values: values, local: localChoice.input.checked, targets: copy(selection.targets)};
    }
    function applyLanguage() {
        $('calendar-source-summary').textContent = saved ? (sourcesSaved ? t('saved') + ' · ' : '') + t('calendar_source_count').replace('{count}', saved.sources.length) : t('calendar_not_loaded');
        if (localChoice) localChoice.text.textContent = t('calendar_local');
        renderTree();
        cards.forEach(updateCardText);
        if (assignments) assignments.applyLanguage();
        var errors = [];
        if (saved && Array.isArray(saved.errors)) saved.errors.forEach(function (error) {
            if (!error || typeof error.id !== 'string') return;
            var source = saved.sources.filter(function (source) { return source.id === error.id; })[0];
            if (!source) return;
            var key = ['fetch_failed', 'invalid_feed', 'event_limit'].indexOf(error.error) >= 0 ? 'calendar_' + error.error : 'calendar_fetch_failed';
            errors.push(source.name + ': ' + t(key));
        });
        $('calendar-source-errors').textContent = errors.join(' · ');
    }
    function renderTree() {
        if (!chooser || !saved) return;
        chooser.render(saved.sources.map(function (source) {
            return {id: source.id, name: source.name + ' · ' + t('calendar_provider_' + source.provider)};
        }), selection, treeOpen);
    }
    function renderDisplay(draft) {
        if (!localChoice) {
            var container = node('label', undefined, 'check');
            var input = node('input');
            input.type = 'checkbox';
            input.setAttribute('data-calendar-source', 'local');
            input.addEventListener('change', function () { displayDirty = true; status('calendar-display-status', 'calendar_display_pending'); });
            var text = node('span');
            container.appendChild(input);
            container.appendChild(text);
            $('calendar-display-list').appendChild(container);
            localChoice = {input: input, text: text};
            treeContainer = node('div', undefined, 'group-calendar-choices');
            $('calendar-display-list').appendChild(treeContainer);
            chooser = window.WebClockCalendarChooser.create({container: treeContainer, t: t,
                loadEvents: function (id) {
                    return new Promise(function (resolve, reject) {
                        send('GET', '/api/v1/calendar-events?source_id=' + encodeURIComponent(id), null, function (ok, data) {
                            if (ok) resolve(data); else reject(new Error('Calendar catalog unavailable'));
                        });
                    });
                },
                onChange: function (next) { selection = next; displayDirty = true; status('calendar-display-status', 'calendar_display_pending'); }
            });
        }
        localChoice.input.checked = draft ? draft.local : saved.local_display_enabled;
        selection = {source_ids: saved.sources.filter(function (source) {
            return draft && Object.prototype.hasOwnProperty.call(draft.values, source.id) ? draft.values[source.id] : source.display_enabled;
        }).map(function (source) { return source.id; }), targets: copy(draft ? draft.targets : saved.calendar_targets || [])};
        selection.targets = selection.targets.filter(function (target) { return saved.sources.some(function (source) { return source.id === target.source_id; }); });
        applyLanguage();
    }
    function offsetHours() { return Number($('timezone-select').value) || 0; }
    function localTime(milliseconds, allDay) {
        if (typeof milliseconds !== 'number' || !isFinite(milliseconds)) return '';
        var value = new Date(milliseconds + offsetHours() * 3600000).toISOString().slice(0, allDay ? 10 : 16);
        return window.WebClockTime ? window.WebClockTime.format(value, $('time-format-select').value, document.documentElement.lang) : value.replace('T', ' ');
    }
    function manualTime(element) {
        var value = element.getAttribute('data-sort-time') || '';
        if (!/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?$/.test(value)) return Infinity;
        return Date.parse(value.replace(' ', 'T') + (value.length === 10 ? 'T00:00:00Z' : ':00Z')) - offsetHours() * 3600000;
    }
    function sortList() {
        var list = $('calendar-current-list');
        var focused = document.activeElement;
        var entries = Array.from(list.children).filter(function (item) { return item.getAttribute('data-note-id') !== undefined && item.getAttribute('data-note-id') !== null; })
            .map(function (element) { return {element: element, time: manualTime(element)}; });
        cards.forEach(function (card) { entries.push({element: card.element, time: typeof card.item.starts_at === 'number' ? card.item.starts_at : Infinity, calendar: true}); });
        entries.sort(function (left, right) { return left.time - right.time; });
        // Move calendar cards only: existing note forms keep their DOM and focus.
        var before = null;
        for (var i = entries.length - 1; i >= 0; i--) {
            if (entries[i].calendar) {
                var children = Array.from(list.children), index = children.indexOf(entries[i].element);
                if (index < 0 || (children[index + 1] || null) !== before) list.insertBefore(entries[i].element, before);
            }
            before = entries[i].element;
        }
        if ($('calendar-current-empty')) $('calendar-current-empty').hidden = entries.length > 0;
        if (focused && document.activeElement !== focused && list.contains(focused)) focused.focus();
    }
    function cardTarget(card, scope) {
        return scope === 'series' ? card.item.series_target || card.item.target : card.item.target;
    }
    function windowDraft(target) {
        var setting = target.display_window || {mode: 'day'}, minutes = setting.before_minutes || 0;
        var unit = minutes && minutes % 1440 === 0 ? 1440 : minutes && minutes % 60 === 0 ? 60 : 1;
        return {mode: setting.mode, value: String(minutes / unit), unit: String(unit), end: setting.mode === 'relative' ? setting.end : 'day_end', start: setting.start || '', finish: setting.end && setting.mode === 'absolute' ? setting.end : '', dirty: false};
    }
    function readEditor(card) {
        return {mode: card.mode.value, value: card.value.value, unit: card.unit.value, end: card.end.value,
            start: card.start.value, finish: card.finish.value, dirty: true};
    }
    function showEditor(card) {
        card.relative.hidden = card.mode.value !== 'relative';
        card.absolute.hidden = card.mode.value !== 'absolute';
        card.value.required = card.mode.value === 'relative';
        card.start.required = card.finish.required = card.mode.value === 'absolute';
        card.value.disabled = card.unit.disabled = card.end.disabled = card.mode.value !== 'relative';
        card.start.disabled = card.finish.disabled = card.mode.value !== 'absolute';
        card.absoluteOption.disabled = card.scope.value === 'series';
        card.hint.hidden = card.scope.value !== 'series';
    }
    function fillEditor(card) {
        var scope = card.scope.value, draft = card.drafts[scope] || windowDraft(cardTarget(card, scope));
        card.drafts[scope] = draft;
        card.mode.value = draft.mode; card.value.value = draft.value; card.unit.value = draft.unit;
        card.end.value = draft.end; card.start.value = draft.start; card.finish.value = draft.finish;
        showEditor(card);
    }
    function updateCardText(card) {
        card.labels.forEach(function (entry) { entry.element.textContent = t(entry.key); });
        var item = card.item;
        card.title.textContent = item.text || t('calendar_untitled');
        card.meta.textContent = [item.source_name, localTime(item.starts_at, item.all_day), item.all_day ? t('calendar_all_day') : '',
            item.target.scope === 'series' ? t('group_calendar_series') : ''].filter(Boolean).join(' · ');
        card.missing.textContent = item.status === 'missing' ? t('group_calendar_unlisted').replace('{id}', item.text || item.target.uid) : '';
        card.missing.hidden = item.status !== 'missing';
        if (card.messageKey) card.message.textContent = t(card.messageKey);
    }
    function cardStatus(card, key, failed) {
        card.messageKey = key;
        card.message.textContent = key ? t(key) : '';
        card.message.className = failed ? 'form-error' : 'help calendar-window-status';
    }
    function refreshCardAssignment(card) {
        if (!assignments) return;
        assignments.summary(card.groupSummary, card.item.assignment);
        var target = copy(cardTarget(card, card.scope.value)); delete target.display_window;
        card.groupEditor.set({kind: 'calendar', target: target}, card.scope.value === card.item.target.scope ? card.item.assignment : card.item.series_assignment);
    }
    function refreshAssignments() {
        if (!assignments) return;
        noteAssignments.forEach(function (entry) {
            var value = assignments.get('manual_note', entry.id);
            assignments.summary(entry.summary, value); entry.editor.set({kind: 'manual_note', id: entry.id}, value);
        });
        cards.forEach(refreshCardAssignment);
    }
    function newCard(item) {
        var card = {item: item, labels: [], drafts: {}, element: node('li', undefined, 'note-card calendar-entry')};
        card.element.setAttribute('data-calendar-item', item.id);
        card.title = node('strong'); card.meta = node('p', undefined, 'help'); card.missing = node('p', undefined, 'help');
        var details = node('details'), summary = node('summary');
        card.labels.push({element: summary, key: 'display_window'});
        card.form = node('form', undefined, 'calendar-entry-window'); card.fields = node('fieldset');
        function field(key, type, parent) {
            var wrapper = node('label', undefined, 'field'), caption = node('span'), input = node(type === 'select' ? 'select' : 'input');
            input.setAttribute('data-calendar-window', key);
            if (type !== 'select') input.type = type;
            wrapper.appendChild(caption); wrapper.appendChild(input); (parent || card.fields).appendChild(wrapper);
            card.labels.push({element: caption, key: key});
            return input;
        }
        function option(select, value, key) {
            var result = node('option'); result.value = value; select.appendChild(result);
            card.labels.push({element: result, key: key}); return result;
        }
        card.scope = field('calendar_window_scope', 'select');
        if (item.target.scope !== 'series') option(card.scope, 'occurrence', 'calendar_window_occurrence');
        if (item.series_target || item.target.scope === 'series') option(card.scope, 'series', 'group_calendar_series');
        card.scope.value = item.target.scope;
        card.mode = field('calendar_window_mode', 'select');
        option(card.mode, 'day', 'calendar_window_day'); option(card.mode, 'relative', 'calendar_window_relative');
        card.absoluteOption = option(card.mode, 'absolute', 'calendar_window_absolute');
        card.relative = node('div', undefined, 'fields calendar-window-relative'); card.fields.appendChild(card.relative);
        card.value = field('calendar_window_before', 'number', card.relative); card.value.min = '0'; card.value.step = 'any';
        card.unit = field('calendar_window_unit', 'select', card.relative);
        option(card.unit, '1', 'calendar_window_minutes'); option(card.unit, '60', 'calendar_window_hours'); option(card.unit, '1440', 'calendar_window_days');
        card.end = field('calendar_window_end', 'select', card.relative);
        option(card.end, 'day_end', 'calendar_window_day_end'); option(card.end, 'event_end', 'calendar_window_event_end');
        card.absolute = node('div', undefined, 'fields calendar-window-absolute'); card.fields.appendChild(card.absolute);
        card.start = field('display_start', 'datetime-local', card.absolute); card.finish = field('display_end', 'datetime-local', card.absolute);
        card.hint = node('p', undefined, 'help'); card.labels.push({element: card.hint, key: 'calendar_window_series_hint'});
        card.fields.appendChild(card.hint);
        var save = node('button'); save.type = 'submit'; card.labels.push({element: save, key: 'save'}); card.fields.appendChild(save);
        card.message = node('p', undefined, 'help calendar-window-status'); card.message.setAttribute('role', 'status');
        card.form.appendChild(card.fields); card.form.appendChild(card.message); details.appendChild(summary); details.appendChild(card.form);
        card.element.appendChild(card.title); card.element.appendChild(card.meta); card.element.appendChild(card.missing); card.element.appendChild(details);
        if (assignments) {
            card.groupSummary = node('span', undefined, 'content-group-summary'); card.element.appendChild(card.groupSummary);
            var groups = node('div'); details.appendChild(groups); card.groupEditor = assignments.createEditor(groups);
        }
        card.scope.addEventListener('change', function () { fillEditor(card); refreshCardAssignment(card); });
        [card.mode, card.value, card.unit, card.end, card.start, card.finish].forEach(function (input) {
            function changed() { card.drafts[card.scope.value] = readEditor(card); showEditor(card); cardStatus(card, 'calendar_window_pending'); }
            input.addEventListener('input', changed); input.addEventListener('change', changed);
        });
        card.form.addEventListener('submit', function (event) { event.preventDefault(); saveWindow(card); });
        fillEditor(card); updateCardText(card); refreshCardAssignment(card);
        return card;
    }
    function windowValue(card) {
        if (card.mode.value === 'day') return {mode: 'day'};
        if (card.mode.value === 'relative') {
            var minutes = Number(card.value.value) * Number(card.unit.value);
            if (card.value.value.trim() === '' || !Number.isInteger(minutes) || minutes < 0 || minutes > 525600) return null;
            return {mode: 'relative', before_minutes: minutes, end: card.end.value};
        }
        if (card.mode.value === 'absolute' && card.scope.value === 'occurrence' &&
            /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(card.start.value) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(card.finish.value) && card.start.value < card.finish.value) {
            return {mode: 'absolute', start: card.start.value, end: card.finish.value};
        }
        return null;
    }
    function saveWindow(card) {
        if (busy || !saved) return;
        var setting = windowValue(card);
        if (!setting) { cardStatus(card, 'calendar_window_failed', true); return; }
        var scope = card.scope.value, target = copy(cardTarget(card, scope)); target.display_window = setting;
        var targets = copy(saved.calendar_targets || []).filter(function (entry) { return targetKey(entry) !== targetKey(target); });
        targets.push(target);
        var submitted = readEditor(card);
        cardStatus(card, 'calendar_saving');
        request('PATCH', {calendar_targets: targets}, function (ok, data) {
            if (!ok) { cardStatus(card, 'calendar_window_failed', true); return; }
            saved = data;
            // Apply the saved timing to a pending tree draft only if that draft
            // still selects this target (directly or through its parent).
            var covered = selection.source_ids.indexOf(target.source_id) >= 0 || selection.targets.some(function (entry) {
                return targetKey(entry) === targetKey(target) || targetKey(entry) === targetKey(card.item.target) ||
                    entry.source_id === target.source_id && entry.uid === target.uid && entry.scope === 'series';
            });
            if (!displayDirty) renderDisplay();
            else if (covered) {
                selection.targets = selection.targets.filter(function (entry) { return targetKey(entry) !== targetKey(target); });
                selection.targets.push(copy(target)); renderTree();
            }
            submitted.dirty = false; card.drafts[scope] = submitted;
            cardStatus(card, 'saved');
            refreshList();
        });
    }
    function renderList(items) {
        var present = new Set();
        items.forEach(function (item) {
            present.add(item.id);
            var card = cards.get(item.id);
            if (!card) { card = newCard(item); cards.set(item.id, card); }
            else {
                card.item = item;
                Object.keys(card.drafts).forEach(function (scope) { if (!card.drafts[scope].dirty) delete card.drafts[scope]; });
                if (!card.drafts[card.scope.value]) fillEditor(card);
                updateCardText(card);
                refreshCardAssignment(card);
            }
        });
        cards.forEach(function (card, id) { if (!present.has(id)) {
            if (assignments) { assignments.removeSummary(card.groupSummary); card.groupEditor.remove(); }
            card.element.remove(); cards.delete(id);
        } });
        sortList(); controls();
    }
    function refreshList() {
        if (!saved) return;
        if (assignments) assignments.load();
        var generation = ++listGeneration;
        status('calendar-list-status', 'calendar_list_loading');
        send('GET', '/api/calendar/display-items', null, function (ok, data) {
            if (generation !== listGeneration) return;
            if (!ok || !Array.isArray(data.items) || !data.items.every(function (item) { return item && typeof item.id === 'string' && item.target && typeof item.target.source_id === 'string'; })) {
                status('calendar-list-status', 'calendar_list_failed', true); return;
            }
            renderList(data.items); status('calendar-list-status', '');
        });
    }
    function addSource(source) {
        var key = String(++serial), card = node('div', undefined, 'calendar-source-row');
        card.setAttribute('data-calendar-source-id', source.id || '');
        var fields = node('div', undefined, 'fields');
        function field(kind, value, title, limit) {
            var container = node('div', undefined, 'field');
            var caption = label(title, 'label');
            var input = node('input');
            input.id = 'calendar-' + kind + '-' + key;
            caption.setAttribute('for', input.id);
            input.type = kind === 'url' ? 'password' : 'text';
            input.value = value;
            input.maxLength = limit;
            input.required = true;
            input.autocomplete = 'off';
            container.appendChild(caption);
            fields.appendChild(container);
            return {container: container, input: input};
        }
        var name = field('name', source.name, 'calendar_source_name', 100);
        name.container.appendChild(name.input);
        var url = field('url', source.url, 'calendar_url', 4096);
        url.input.setAttribute('autocapitalize', 'none');
        url.input.spellcheck = false;
        var urlRow = node('div', undefined, 'calendar-url-row');
        var eye = node('button');
        eye.type = 'button';
        eye.setAttribute('aria-pressed', 'false');
        eye.setAttribute('aria-controls', url.input.id);
        eye.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
        var eyeText = label('calendar_show');
        eye.appendChild(eyeText);
        eye.addEventListener('click', function () {
            var visible = url.input.type === 'password';
            url.input.type = visible ? 'text' : 'password';
            eye.setAttribute('aria-pressed', String(visible));
            var key = visible ? 'calendar_hide' : 'calendar_show';
            eyeText.setAttribute('data-i18n', key);
            eyeText.textContent = t(key);
        });
        urlRow.appendChild(url.input);
        urlRow.appendChild(eye);
        url.container.appendChild(urlRow);
        var remove = label('calendar_remove_source', 'button');
        remove.type = 'button';
        remove.className = 'danger';
        var row = {id: source.id, provider: source.provider, name: name.input, url: url.input, element: card};
        remove.addEventListener('click', function () {
            rows = rows.filter(function (item) { return item !== row; });
            card.parentNode.removeChild(card);
            controls();
            status('calendar-status', 'calendar_sources_pending');
        });
        card.appendChild(fields);
        card.appendChild(remove);
        card.addEventListener('input', function () { status('calendar-status', 'calendar_sources_pending'); });
        $('calendar-sources-' + source.provider).appendChild(card);
        rows.push(row);
        return row;
    }
    function renderSources() {
        rows = [];
        providers.forEach(function (provider) { $('calendar-sources-' + provider).textContent = ''; });
        saved.sources.forEach(addSource);
        controls();
    }
    function load() {
        if (busy || saved) return;
        $('calendar-retry').hidden = true;
        status('calendar-display-status', 'loading');
        request('GET', null, function (ok, data) {
            if (!ok) {
                status('calendar-display-status', 'calendar_load_error', true);
                $('calendar-retry').hidden = false;
                applyLanguage();
                return;
            }
            saved = data;
            renderSources();
            renderDisplay();
            status('calendar-display-status', '');
            refreshList();
        });
    }
    function failure(data) {
        return data.error === 'invalid_settings' || data.error === 'invalid_url' ? 'calendar_invalid_settings' : 'calendar_save_error';
    }
    $('calendar-form').addEventListener('submit', function (event) {
        event.preventDefault();
        if (busy || !saved) return;
        var old = Object.create(null), sources = [], draft = visibilityDraft();
        saved.sources.forEach(function (source) { old[source.id] = source; });
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            if (!row.name.value.trim() || !row.url.value.trim()) {
                status('calendar-status', 'calendar_required', true);
                (!row.name.value.trim() ? row.name : row.url).focus();
                return;
            }
            var source = {name: row.name.value.trim(), provider: row.provider, url: row.url.value.trim(), display_enabled: row.id ? old[row.id].display_enabled : true};
            if (row.id) source.id = row.id;
            sources.push(source);
        }
        status('calendar-status', 'calendar_saving');
        request('POST', {sources: sources, local_display_enabled: saved.local_display_enabled}, function (ok, data) {
            if (!ok) { status('calendar-status', failure(data), true); return; }
            var changedSources = data.sources.filter(function (source) { return !old[source.id] || old[source.id].url !== source.url; }).map(function (source) { return source.id; });
            saved = data;
            sourcesSaved = true;
            renderSources();
            renderDisplay(draft);
            chooser.invalidate(changedSources);
            status('calendar-status', 'calendar_saved');
            $('calendar-source-settings').open = false;
            refreshList();
        });
    });
    $('calendar-display-form').addEventListener('submit', function (event) {
        event.preventDefault();
        if (busy || !saved) return;
        var values = visibilityDraft();
        var payload = {local_display_enabled: values.local, calendar_targets: values.targets, sources: saved.sources.map(function (source) {
            return {id: source.id, display_enabled: values.values[source.id]};
        })};
        status('calendar-display-status', 'calendar_saving');
        request('PATCH', payload, function (ok, data) {
            if (!ok) { status('calendar-display-status', failure(data), true); return; }
            saved = data;
            displayDirty = false;
            renderDisplay();
            status('calendar-display-status', 'calendar_display_saved');
            refreshList();
        });
    });
    for (var i = 0; i < addButtons.length; i++) addButtons[i].addEventListener('click', function () {
        if (busy || !saved || rows.length >= 20) return;
        var provider = this.getAttribute('data-calendar-add');
        var count = rows.filter(function (row) { return row.provider === provider; }).length + 1;
        var row = addSource({provider: provider, name: t('calendar_provider_' + provider) + ' ' + count, url: ''});
        controls();
        status('calendar-status', 'calendar_sources_pending');
        row.url.focus();
    });
    $('calendar-retry').addEventListener('click', load);
    if (assignments) {
        Array.from(document.querySelectorAll('[data-note-group-editor]')).forEach(function (container) {
            var id = Number(container.getAttribute('data-note-group-editor'));
            var summary = document.querySelector('[data-note-group-summary="' + id + '"]');
            if (summary) noteAssignments.push({id: id, summary: summary, editor: assignments.createEditor(container)});
        });
        refreshAssignments();
    }
    $('calendar-list-refresh').addEventListener('click', refreshList);
    $('timezone-select').addEventListener('change', function () { cards.forEach(updateCardText); sortList(); });
    $('time-format-select').addEventListener('change', function () { cards.forEach(updateCardText); });
    window.CalendarSettings = {applyLanguage: applyLanguage};
    applyLanguage();
    load();
}());
