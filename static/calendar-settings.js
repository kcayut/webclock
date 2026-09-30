/* Calendar management stays separate from the lightweight clock page. */
(function () {
    'use strict';
    var saved = null, busy = false, rows = [], displayRows = [], serial = 0, sourcesSaved = false;
    var providers = ['apple', 'google', 'ics'];
    var addButtons = document.querySelectorAll('[data-calendar-add]');
    function $(id) { return document.getElementById(id); }
    function t(key) { return window.t(key); }
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
        for (var i = 0; i < addButtons.length; i++) addButtons[i].disabled = rows.length >= 20;
    }
    function validState(data) {
        if (!data || !Array.isArray(data.sources) || data.sources.length > 20 || typeof data.local_display_enabled !== 'boolean') return false;
        var ids = Object.create(null);
        return data.sources.every(function (source) {
            if (!source || typeof source.id !== 'string' || !source.id || ids[source.id] ||
                typeof source.name !== 'string' || !source.name.trim() || typeof source.url !== 'string' || !source.url.trim() ||
                providers.indexOf(source.provider) < 0 || typeof source.display_enabled !== 'boolean') return false;
            ids[source.id] = true;
            return true;
        });
    }
    function request(method, payload, done) {
        busy = true;
        controls();
        var xhr = new XMLHttpRequest();
        xhr.open(method, '/api/calendar', true);
        xhr.timeout = 15000;
        function finish(ok, data) {
            busy = false;
            controls();
            done(ok, data || {});
        }
        xhr.onload = function () {
            var data;
            try { data = JSON.parse(xhr.responseText); } catch (error) { finish(false); return; }
            finish(xhr.status >= 200 && xhr.status < 300 && validState(data), data);
        };
        xhr.onerror = xhr.ontimeout = function () { finish(false); };
        if (payload) {
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(JSON.stringify(payload));
        } else xhr.send();
    }
    function visibilityDraft() {
        var values = Object.create(null);
        displayRows.forEach(function (row) { values[row.id] = row.input.checked; });
        return values;
    }
    function applyLanguage() {
        $('calendar-source-summary').textContent = saved ? (sourcesSaved ? t('saved') + ' · ' : '') + t('calendar_source_count').replace('{count}', saved.sources.length) : t('calendar_not_loaded');
        displayRows.forEach(function (row) {
            row.text.textContent = row.source ? row.source.name + ' · ' + t('calendar_provider_' + row.source.provider) : t('calendar_local');
        });
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
    function renderDisplay(draft) {
        $('calendar-display-list').textContent = '';
        displayRows = [];
        function add(id, enabled, source) {
            var container = node('label', undefined, 'check');
            var input = node('input');
            input.type = 'checkbox';
            input.setAttribute('data-calendar-source', id);
            input.checked = draft && Object.prototype.hasOwnProperty.call(draft, id) ? draft[id] : enabled;
            input.addEventListener('change', function () { status('calendar-display-status', 'calendar_display_pending'); });
            var text = node('span');
            container.appendChild(input);
            container.appendChild(text);
            $('calendar-display-list').appendChild(container);
            displayRows.push({id: id, input: input, text: text, source: source});
        }
        add('local', saved.local_display_enabled, null);
        saved.sources.forEach(function (source) { add(source.id, source.display_enabled, source); });
        applyLanguage();
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
            saved = data;
            sourcesSaved = true;
            renderSources();
            renderDisplay(draft);
            status('calendar-status', 'calendar_saved');
            $('calendar-source-settings').open = false;
        });
    });
    $('calendar-display-form').addEventListener('submit', function (event) {
        event.preventDefault();
        if (busy || !saved) return;
        var values = visibilityDraft();
        var payload = {local_display_enabled: values.local, sources: saved.sources.map(function (source) {
            return {id: source.id, display_enabled: values[source.id]};
        })};
        status('calendar-display-status', 'calendar_saving');
        request('PATCH', payload, function (ok, data) {
            if (!ok) { status('calendar-display-status', failure(data), true); return; }
            saved = data;
            renderDisplay();
            status('calendar-display-status', 'calendar_display_saved');
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
    window.CalendarSettings = {applyLanguage: applyLanguage};
    applyLanguage();
    load();
}());
