/* Teams-like range picker for optional display windows. */
(function () {
    'use strict';
    var roots = document.querySelectorAll('[data-range-picker]');
    if (!roots.length) return;
    var SLOT = 30;

    function pad(value) { return (value < 10 ? '0' : '') + value; }
    function language() { return document.documentElement.lang || 'zh-TW'; }
    function label(key) {
        var packs = window.I18N, pack = packs && (packs[window.currentLanguage] || packs['zh-TW']);
        return pack && pack[key] || key;
    }
    function dayKey(date) {
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
    }
    function valueOf(date) {
        return dayKey(date) + 'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }
    function parseValue(value) {
        var match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value || '');
        if (!match) return null;
        return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]),
            Number(match[4]), Number(match[5]));
    }
    function parseDay(value) {
        var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
        return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
    }
    function parseTime(value) {
        var match = /^(\d{2}):(\d{2})$/.exec(value || '');
        return match ? Number(match[1]) * 60 + Number(match[2]) : null;
    }
    function startOfDay(date) { return new Date(date.getFullYear(), date.getMonth(), date.getDate()); }
    function addDays(date, amount) { return new Date(date.getFullYear(), date.getMonth(), date.getDate() + amount); }
    function addMonths(date, amount) { return new Date(date.getFullYear(), date.getMonth() + amount, 1); }
    function startOfWeek(date) {
        var result = startOfDay(date), offset = (result.getDay() + 6) % 7;
        return addDays(result, -offset);
    }
    function withTime(date, minutes) {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate(),
            Math.floor(minutes / 60), minutes % 60);
    }
    function timeOf(date) { return date ? pad(date.getHours()) + ':' + pad(date.getMinutes()) : ''; }
    function formatDate(date, options) { return new Intl.DateTimeFormat(language(), options).format(date); }
    function formatValue(date) {
        if (!date) return '';
        var value = valueOf(date);
        return window.WebClockTime
            ? window.WebClockTime.format(value, window.currentTimeFormat || '24h', language())
            : value.replace('T', ' ');
    }
    function rangeText(start, end) {
        return start && end ? formatValue(start) + ' → ' + formatValue(end) : label('range_none');
    }
    function sameDay(left, right) { return left && right && dayKey(left) === dayKey(right); }
    var tooltip = null;
    function ensureTooltip(host) {
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.className = 'range-picker-tooltip';
            tooltip.setAttribute('aria-hidden', 'true');
            tooltip.hidden = true;
        }
        if (tooltip.parentNode !== host) host.appendChild(tooltip);
        return tooltip;
    }
    function positionTooltip(event) {
        if (!tooltip || tooltip.hidden) return;
        var width = tooltip.offsetWidth, height = tooltip.offsetHeight;
        var left = event.clientX + 14, top = event.clientY + 16;
        if (left + width > window.innerWidth - 8) left = event.clientX - width - 14;
        if (top + height > window.innerHeight - 8) top = event.clientY - height - 16;
        tooltip.style.left = Math.max(8, left) + 'px';
        tooltip.style.top = Math.max(8, top) + 'px';
    }
    function hideTooltip() { if (tooltip) tooltip.hidden = true; }
    function tooltipText(start, end, view) {
        if (!start || !end) return '';
        if (view !== 'week') {
            return formatDate(start, {year: 'numeric', month: 'numeric', day: 'numeric'}) + ' → ' +
                formatDate(end, {year: 'numeric', month: 'numeric', day: 'numeric'});
        }
        var hour12 = window.currentTimeFormat === '12h';
        var sameYear = start.getFullYear() === end.getFullYear();
        var startOptions = {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: hour12};
        if (!sameYear) startOptions.year = 'numeric';
        var endOptions = {hour: '2-digit', minute: '2-digit', hour12: hour12};
        if (!sameDay(start, end)) {
            endOptions = {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: hour12};
            if (!sameYear) endOptions.year = 'numeric';
        }
        return new Intl.DateTimeFormat(language(), startOptions).format(start) + ' → ' +
            new Intl.DateTimeFormat(language(), endOptions).format(end);
    }
    function timeControl(root) {
        if (!window.WebClockTimeInputs) return;
        window.WebClockTimeInputs.refresh(root, window.currentTimeFormat || '24h', language());
    }

    function create(root) {
        var fieldset = root.closest('fieldset');
        var startInput = fieldset.querySelector('input[name="display_start"]');
        var endInput = fieldset.querySelector('input[name="display_end"]');
        var toggle = root.querySelector('[data-range-toggle]');
        var panel = root.querySelector('[data-range-panel]');
        var summary = root.querySelector('[data-range-summary]');
        var labelNode = root.querySelector('[data-range-label]');
        var monthView = root.querySelector('[data-range-view-panel="month"]');
        var weekView = root.querySelector('[data-range-view-panel="week"]');
        var yearView = root.querySelector('[data-range-view-panel="year"]');
        var startTime = root.querySelector('[data-range-time="start"]');
        var endTime = root.querySelector('[data-range-time="end"]');
        var startDate = root.querySelector('[data-range-date-field="start"]');
        var endDate = root.querySelector('[data-range-date-field="end"]');
        var viewButtons = root.querySelectorAll('[data-range-view]');
        var state = {view: 'month', cursor: startOfDay(new Date()), start: null, end: null,
            selecting: false, anchor: null, lastPointer: 0, container: null};

        function syncTimes() {
            startTime.value = timeOf(state.start);
            endTime.value = timeOf(state.end);
            timeControl(root);
        }
        function syncDates() {
            startDate.value = state.start ? dayKey(state.start) : '';
            endDate.value = state.end ? dayKey(state.end) : '';
        }
        function paintSummary() {
            summary.textContent = state.start && state.end ? rangeText(state.start, state.end) : '';
            summary.hidden = !(state.start && state.end);
            if (state.selecting && tooltip && !tooltip.hidden) {
                tooltip.textContent = tooltipText(state.start, state.end, state.view);
            }
        }
        function showTooltip(event) {
            ensureTooltip(root.closest('dialog[open]') || document.body);
            tooltip.hidden = false;
            tooltip.textContent = tooltipText(state.start, state.end, state.view);
            positionTooltip(event);
        }
        function readInputs() {
            state.start = parseValue(startInput.value);
            state.end = parseValue(endInput.value);
            if (state.start) state.cursor = startOfDay(state.start);
            paintSummary();
            syncTimes();
            syncDates();
        }
        function commit() {
            startInput.value = state.start ? valueOf(state.start) : '';
            endInput.value = state.end ? valueOf(state.end) : '';
            [startInput, endInput].forEach(function (input) {
                ['input', 'change'].forEach(function (name) {
                    input.dispatchEvent(new Event(name, {bubbles: true}));
                });
            });
            paintSummary();
            syncTimes();
            syncDates();
        }
        function responseTimes() {
            return {
                start: state.start ? state.start.getHours() * 60 + state.start.getMinutes() : 0,
                end: state.end ? state.end.getHours() * 60 + state.end.getMinutes() : 1439
            };
        }
        function setLabel() {
            if (!labelNode) return;
            if (state.view === 'year') labelNode.textContent = String(state.cursor.getFullYear());
            else if (state.view === 'week') {
                var first = startOfWeek(state.cursor), last = addDays(first, 6);
                labelNode.textContent = formatDate(first, {month: 'short', day: 'numeric'}) + ' – ' +
                    formatDate(last, {month: 'short', day: 'numeric'});
            } else labelNode.textContent = formatDate(state.cursor, {year: 'numeric', month: 'long'});
        }
        function setView(view) {
            state.view = view;
            for (var i = 0; i < viewButtons.length; i++) {
                var active = viewButtons[i].getAttribute('data-range-view') === view;
                viewButtons[i].setAttribute('aria-selected', String(active));
            }
            monthView.hidden = view !== 'month';
            weekView.hidden = view !== 'week';
            yearView.hidden = view !== 'year';
            render();
        }
        function paintDaySelection(container) {
            if (!state.start || !state.end) return;
            var first = startOfDay(state.start) <= startOfDay(state.end) ? startOfDay(state.start) : startOfDay(state.end);
            var last = startOfDay(state.start) <= startOfDay(state.end) ? startOfDay(state.end) : startOfDay(state.start);
            container.querySelectorAll('[data-range-date]').forEach(function (cell) {
                var date = parseDay(cell.getAttribute('data-range-date'));
                var selected = date && date >= first && date <= last;
                cell.classList.toggle('is-selected', !!selected);
                cell.classList.toggle('is-start', !!selected && sameDay(date, state.start));
                cell.classList.toggle('is-end', !!selected && sameDay(date, state.end));
            });
        }
        function paintMonthSelection() { paintDaySelection(monthView); }
        function paintYearSelection() {
            paintDaySelection(yearView);
            var year = state.cursor.getFullYear();
            yearView.querySelectorAll('[data-range-year-month]').forEach(function (card) {
                var month = Number(card.getAttribute('data-range-year-month'));
                var first = new Date(year, month, 1), next = new Date(year, month + 1, 1);
                card.classList.toggle('is-selected', !!(state.start && state.end && state.end >= first && state.start < next));
            });
        }
        function weekRange() {
            return {start: 0, end: 24};
        }
        function weekMinutes(event, column) {
            var grid = weekView.querySelector('[data-week-grid]');
            var startHour = Number(grid.getAttribute('data-week-start-hour'));
            var endHour = Number(grid.getAttribute('data-week-end-hour'));
            var rect = column.getBoundingClientRect();
            var raw = startHour * 60 + (event.clientY - rect.top) / Math.max(1, rect.height) * (endHour - startHour) * 60;
            var snapped = Math.round(raw / SLOT) * SLOT;
            return Math.max(startHour * 60, Math.min(endHour * 60, snapped));
        }
        function paintWeekSelection() {
            var grid = weekView.querySelector('[data-week-grid]');
            if (!grid) return;
            weekView.querySelectorAll('[data-week-selection]').forEach(function (overlay) { overlay.hidden = true; });
            if (!state.start || !state.end) return;
            var startHour = Number(grid.getAttribute('data-week-start-hour'));
            var endHour = Number(grid.getAttribute('data-week-end-hour'));
            var row = Number(grid.getAttribute('data-week-row-height')) || 34;
            var gridHeight = (endHour - startHour) * row;
            var selected = [];
            weekView.querySelectorAll('[data-week-column]').forEach(function (column) {
                var date = parseDay(column.getAttribute('data-range-date'));
                if (!date) return;
                var dayStart = withTime(date, 0), dayEnd = withTime(addDays(date, 1), 0);
                var start = Math.max(state.start.getTime(), dayStart.getTime());
                var end = Math.min(state.end.getTime(), dayEnd.getTime());
                if (end > start) selected.push({column: column, date: date, start: start, end: end});
            });
            if (!selected.length) return;
            selected.forEach(function (item) {
                var overlay = item.column.querySelector('[data-week-selection]');
                if (!overlay) return;
                var top = ((item.start - withTime(item.date, 0).getTime()) / 60000 / 60 - startHour) * row;
                var height = ((item.end - item.start) / 60000 / 60) * row;
                top = Math.max(0, Math.min(gridHeight - 6, top));
                height = Math.max(6, Math.min(gridHeight - top, height));
                overlay.style.top = top + 'px';
                overlay.style.height = height + 'px';
                overlay.hidden = false;
            });
        }
        function renderMonth() {
            var year = state.cursor.getFullYear(), month = state.cursor.getMonth();
            var gridStart = startOfWeek(new Date(year, month, 1));
            var html = '<div class="range-weekdays">';
            for (var d = 0; d < 7; d++) html += '<span>' + formatDate(addDays(gridStart, d), {weekday: 'short'}) + '</span>';
            html += '</div><div class="range-month-grid">';
            for (var i = 0; i < 42; i++) {
                var date = addDays(gridStart, i);
                var classes = ['range-day'];
                if (date.getMonth() !== month) classes.push('is-outside');
                if (sameDay(date, new Date())) classes.push('is-today');
                html += '<button type="button" class="' + classes.join(' ') + '" data-range-date="' + dayKey(date) +
                    '" aria-label="' + formatDate(date, {dateStyle: 'full'}) + '"><span>' + date.getDate() + '</span></button>';
            }
            monthView.innerHTML = html + '</div>';
            paintMonthSelection();
        }
        function renderWeek() {
            var first = startOfWeek(state.cursor), range = weekRange(), row = 34;
            var html = '<div class="range-week-head"><span></span>';
            for (var d = 0; d < 7; d++) {
                var day = addDays(first, d);
                html += '<span class="' + (sameDay(day, new Date()) ? 'is-today' : '') + '">' +
                    formatDate(day, {weekday: 'short', day: 'numeric'}) + '</span>';
            }
            html += '</div><div class="range-week-body"><div class="range-time-axis">';
            for (var hour = range.start; hour < range.end; hour++) {
                html += '<span>' + pad(hour) + ':00</span>';
            }
            html += '</div><div class="range-week-grid" data-week-grid data-week-start-hour="' + range.start +
                '" data-week-end-hour="' + range.end + '" data-week-row-height="' + row + '">';
            for (var dayIndex = 0; dayIndex < 7; dayIndex++) {
                var columnDate = addDays(first, dayIndex);
                html += '<div class="range-week-column' + (sameDay(columnDate, new Date()) ? ' is-today' : '') +
                    '" data-week-column data-range-date="' + dayKey(columnDate) + '">';
                for (var cell = range.start; cell < range.end; cell++) html += '<div class="range-week-hour"></div>';
                html += '<div class="range-week-selection" data-week-selection hidden></div></div>';
            }
            weekView.innerHTML = html + '</div></div>';
            paintWeekSelection();
        }
        function renderYear() {
            var year = state.cursor.getFullYear(), html = '<div class="range-year-grid">';
            for (var month = 0; month < 12; month++) {
                var first = new Date(year, month, 1), start = startOfWeek(first);
                html += '<div class="range-year-month" data-range-year-month="' + month + '">' +
                    '<button type="button" class="range-year-title" data-range-month="' + month + '"><strong>' +
                    formatDate(first, {month: 'long'}) + '</strong></button><span class="range-mini-week">';
                for (var w = 0; w < 7; w++) html += '<i>' + formatDate(addDays(start, w), {weekday: 'narrow'}) + '</i>';
                html += '</span><span class="range-mini-days">';
                for (var i = 0; i < 42; i++) {
                    var day = addDays(start, i);
                    var classes = ['range-year-day'];
                    if (day.getMonth() !== month) classes.push('is-outside');
                    if (sameDay(day, new Date())) classes.push('is-today');
                    html += '<button type="button" class="' + classes.join(' ') + '" data-range-date="' + dayKey(day) +
                        '" aria-label="' + formatDate(day, {dateStyle: 'full'}) + '">' + day.getDate() + '</button>';
                }
                html += '</span></div>';
            }
            yearView.innerHTML = html + '</div>';
            paintYearSelection();
        }
        function render() {
            setLabel();
            if (state.view === 'month') renderMonth();
            else if (state.view === 'week') renderWeek();
            else renderYear();
        }
        function finishSelection(event) {
            if (!state.selecting) return;
            if (event && typeof event.clientX === 'number' && typeof event.clientY === 'number') updateSelection(event);
            state.selecting = false;
            state.container = null;
            hideTooltip();
            if (state.start && state.end) commit();
        }
        root.addEventListener('pointerdown', function (event) {
            if (event.button > 0) return;
            var day = event.target.closest('[data-range-date]');
            if (!day) return;
            var container = monthView.contains(day) ? monthView : (yearView.contains(day) ? yearView : null);
            if (!container) return;
            var date = parseDay(day.getAttribute('data-range-date'));
            if (!date) return;
            event.preventDefault();
            state.lastPointer = Date.now();
            state.anchor = date;
            state.container = container;
            var times = responseTimes();
            state.start = withTime(date, times.start);
            state.end = withTime(date, times.end);
            state.selecting = true;
            if (container === monthView) paintMonthSelection(); else paintYearSelection();
            paintSummary();
            showTooltip(event);
        });
        function updateSelection(event) {
            if (!state.selecting || !state.anchor || !state.container) return;
            positionTooltip(event);
            var element = document.elementFromPoint(event.clientX, event.clientY);
            if (state.container === weekView) {
                var column = element && element.closest ? element.closest('[data-week-column]') : null;
                if (!column || !weekView.contains(column)) return;
                var currentDate = parseDay(column.getAttribute('data-range-date'));
                if (!currentDate) return;
                var currentMinute = weekMinutes(event, column);
                var current = withTime(currentDate, currentMinute);
                if (current < state.anchor) {
                    state.start = current;
                    state.end = new Date(state.anchor.getTime() + SLOT * 60000);
                } else if (current > state.anchor) {
                    state.start = state.anchor;
                    state.end = current;
                } else {
                    state.start = state.anchor;
                    state.end = new Date(state.anchor.getTime() + SLOT * 60000);
                }
                paintWeekSelection();
                paintSummary();
                return;
            }
            var day = element && element.closest ? element.closest('[data-range-date]') : null;
            if (!day || !state.container.contains(day)) return;
            var date = parseDay(day.getAttribute('data-range-date'));
            if (!date) return;
            var times = responseTimes();
            if (date < state.anchor) {
                state.start = withTime(date, times.start);
                state.end = withTime(state.anchor, times.end);
            } else {
                state.start = withTime(state.anchor, times.start);
                state.end = withTime(date, times.end);
            }
            if (state.container === monthView) paintMonthSelection(); else paintYearSelection();
            paintSummary();
        }
        document.addEventListener('pointermove', updateSelection);
        document.addEventListener('pointerup', finishSelection);
        document.addEventListener('pointercancel', function () { finishSelection(); });
        weekView.addEventListener('pointerdown', function (event) {
            if (event.button > 0) return;
            var column = event.target.closest('[data-week-column]');
            if (!column || !weekView.contains(column)) return;
            var date = parseDay(column.getAttribute('data-range-date'));
            if (!date) return;
            event.preventDefault();
            state.lastPointer = Date.now();
            state.anchor = withTime(date, weekMinutes(event, column));
            state.start = state.anchor;
            state.end = new Date(state.anchor.getTime() + SLOT * 60000);
            state.selecting = true;
            state.container = weekView;
            paintWeekSelection();
            paintSummary();
            showTooltip(event);
        });
        monthView.addEventListener('click', function (event) {
            var day = event.target.closest('[data-range-date]');
            if (!day || state.selecting || Date.now() - state.lastPointer < 400) return;
            var date = parseDay(day.getAttribute('data-range-date'));
            if (!date) return;
            var times = responseTimes();
            state.start = withTime(date, times.start);
            state.end = withTime(date, times.end);
            commit();
            paintMonthSelection();
        });
        yearView.addEventListener('click', function (event) {
            var month = event.target.closest('[data-range-month]');
            if (month) {
                state.cursor = new Date(state.cursor.getFullYear(), Number(month.getAttribute('data-range-month')), 1);
                setView('month');
                return;
            }
            var day = event.target.closest('[data-range-date]');
            if (!day || state.selecting || Date.now() - state.lastPointer < 400) return;
            var date = parseDay(day.getAttribute('data-range-date'));
            if (!date) return;
            var times = responseTimes();
            state.start = withTime(date, times.start);
            state.end = withTime(date, times.end);
            commit();
            paintYearSelection();
        });
        viewButtons.forEach(function (button) {
            button.addEventListener('click', function () { setView(button.getAttribute('data-range-view')); });
        });
        root.querySelector('[data-range-prev]').addEventListener('click', function () {
            state.cursor = state.view === 'year' ? new Date(state.cursor.getFullYear() - 1, 0, 1) :
                state.view === 'week' ? addDays(state.cursor, -7) : addMonths(state.cursor, -1);
            render();
        });
        root.querySelector('[data-range-next]').addEventListener('click', function () {
            state.cursor = state.view === 'year' ? new Date(state.cursor.getFullYear() + 1, 0, 1) :
                state.view === 'week' ? addDays(state.cursor, 7) : addMonths(state.cursor, 1);
            render();
        });
        root.querySelector('[data-range-today]').addEventListener('click', function () {
            state.cursor = startOfDay(new Date());
            render();
        });
        root.querySelector('[data-range-clear]').addEventListener('click', function () {
            state.start = state.end = null;
            commit();
            render();
        });
        function openPanel() {
            panel.hidden = false;
            toggle.setAttribute('aria-expanded', 'true');
            readInputs();
            render();
        }
        root.querySelector('[data-range-done]').addEventListener('click', function () {
            panel.hidden = true;
            toggle.setAttribute('aria-expanded', 'false');
        });
        toggle.addEventListener('click', function () {
            if (panel.hidden) openPanel();
            else {
                panel.hidden = true;
                toggle.setAttribute('aria-expanded', 'false');
            }
        });
        function applyTimes() {
            var startMinutes = parseTime(startTime.value), endMinutes = parseTime(endTime.value);
            if (startMinutes === null || endMinutes === null) return;
            var startDay = parseDay(startDate.value) || state.start || state.cursor;
            var endDay = parseDay(endDate.value) || state.end || state.cursor;
            state.start = withTime(startDay, startMinutes);
            state.end = withTime(endDay, endMinutes);
            if (state.end <= state.start) state.end = new Date(state.start.getTime() + SLOT * 60000);
            commit();
            render();
        }
        function applyDates(changed) {
            var startDay = parseDay(startDate.value), endDay = parseDay(endDate.value);
            if (!startDay && !endDay) {
                state.start = state.end = null;
                commit();
                render();
                return;
            }
            if (!startDay) startDay = endDay;
            if (!endDay) endDay = startDay;
            if (endDay < startDay) {
                if (changed === 'end') startDay = endDay;
                else endDay = startDay;
            }
            var times = responseTimes();
            state.start = withTime(startDay, times.start);
            state.end = withTime(endDay, times.end);
            if (state.end <= state.start) {
                if (changed === 'end') state.start = new Date(state.end.getTime() - SLOT * 60000);
                else state.end = new Date(state.start.getTime() + SLOT * 60000);
            }
            state.cursor = startOfDay(state.start);
            commit();
            render();
        }
        startTime.addEventListener('change', applyTimes);
        endTime.addEventListener('change', applyTimes);
        startDate.addEventListener('change', function () { applyDates('start'); });
        endDate.addEventListener('change', function () { applyDates('end'); });
        readInputs();
        if (!panel.hidden) render();
        return {
            refresh: function () { readInputs(); if (!panel.hidden) render(); },
            open: openPanel,
            applyLanguage: function () { paintSummary(); if (!panel.hidden) render(); }
        };
    }

    roots.forEach(function (root) { root._rangePicker = create(root); });
    function resolvePicker(element) {
        return element && element.matches && element.matches('[data-range-picker]') ? element :
            element && element.querySelector ? element.querySelector('[data-range-picker]') : null;
    }
    window.WebClockRangePicker = {
        refresh: function (element) {
            var root = resolvePicker(element);
            if (root && root._rangePicker) root._rangePicker.refresh();
        },
        open: function (element) {
            var root = resolvePicker(element);
            if (root && root._rangePicker) root._rangePicker.open();
        },
        applyLanguage: function () {
            roots.forEach(function (root) { if (root._rangePicker) root._rangePicker.applyLanguage(); });
        }
    };
}());
