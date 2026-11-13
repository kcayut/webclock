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
        var viewButtons = root.querySelectorAll('[data-range-view]');
        var state = {view: 'month', cursor: startOfDay(new Date()), start: null, end: null,
            selecting: false, anchor: null, lastPointer: 0, container: null};

        function syncTimes() {
            startTime.value = timeOf(state.start);
            endTime.value = timeOf(state.end);
            timeControl(root);
        }
        function paintSummary() {
            summary.textContent = state.start && state.end ? rangeText(state.start, state.end) : '';
            summary.hidden = !(state.start && state.end);
        }
        function readInputs() {
            state.start = parseValue(startInput.value);
            state.end = parseValue(endInput.value);
            if (state.start) state.cursor = startOfDay(state.start);
            paintSummary();
            syncTimes();
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
            var start = 8, end = 22;
            if (state.start && state.end && sameDay(state.start, state.end)) {
                start = Math.min(start, Math.floor((state.start.getHours() * 60 + state.start.getMinutes()) / 60));
                end = Math.max(end, Math.ceil((state.end.getHours() * 60 + state.end.getMinutes()) / 60));
            }
            start = Math.max(0, Math.min(23, start));
            end = Math.max(start + 1, Math.min(24, end));
            return {start: start, end: end};
        }
        function weekMinutes(event, column) {
            var grid = weekView.querySelector('[data-week-grid]');
            var startHour = Number(grid.getAttribute('data-week-start-hour'));
            var endHour = Number(grid.getAttribute('data-week-end-hour'));
            var row = Number(grid.getAttribute('data-week-row-height')) || 34;
            var rect = column.getBoundingClientRect();
            var slot = Math.floor((event.clientY - rect.top) / (row / 2));
            slot = Math.max(0, Math.min((endHour - startHour) * 2 - 1, slot));
            return startHour * 60 + slot * SLOT;
        }
        function paintWeekSelection() {
            var grid = weekView.querySelector('[data-week-grid]');
            if (!grid) return;
            var overlay = grid.querySelector('[data-week-selection]');
            if (!overlay) return;
            if (!state.start || !state.end) { overlay.hidden = true; return; }
            var columns = grid.querySelectorAll('[data-week-column]');
            var firstIndex = -1, lastIndex = -1, first = startOfWeek(state.cursor);
            for (var i = 0; i < 7; i++) {
                var date = addDays(first, i);
                var dayStart = withTime(date, 0), dayEnd = withTime(addDays(date, 1), 0);
                if (state.end > dayStart && state.start < dayEnd) {
                    if (firstIndex < 0) firstIndex = i;
                    lastIndex = i;
                }
            }
            if (firstIndex < 0 || !columns[firstIndex] || !columns[lastIndex]) { overlay.hidden = true; return; }
            var startHour = Number(grid.getAttribute('data-week-start-hour'));
            var endHour = Number(grid.getAttribute('data-week-end-hour'));
            var row = Number(grid.getAttribute('data-week-row-height')) || 34;
            var gridHeight = (endHour - startHour) * row;
            var top, bottom;
            if (firstIndex === lastIndex) {
                top = (state.start.getHours() * 60 + state.start.getMinutes() - startHour * 60) / 60 * row;
                bottom = (state.end.getHours() * 60 + state.end.getMinutes() - startHour * 60) / 60 * row;
            } else if (state.start.getHours() * 60 + state.start.getMinutes() <
                       state.end.getHours() * 60 + state.end.getMinutes()) {
                top = (state.start.getHours() * 60 + state.start.getMinutes() - startHour * 60) / 60 * row;
                bottom = (state.end.getHours() * 60 + state.end.getMinutes() - startHour * 60) / 60 * row;
            } else {
                top = 0;
                bottom = gridHeight;
            }
            top = Math.max(0, Math.min(gridHeight, top));
            bottom = Math.max(top + 6, Math.min(gridHeight, bottom));
            var left = columns[firstIndex].offsetLeft;
            var right = columns[lastIndex].offsetLeft + columns[lastIndex].offsetWidth;
            overlay.style.left = left + 'px';
            overlay.style.top = top + 'px';
            overlay.style.width = (right - left) + 'px';
            overlay.style.height = (bottom - top) + 'px';
            overlay.hidden = false;
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
                html += '</div>';
            }
            weekView.innerHTML = html + '<div class="range-week-selection" data-week-selection hidden></div></div></div>';
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
        function finishSelection() {
            if (!state.selecting) return;
            state.selecting = false;
            state.container = null;
            if (state.start && state.end) commit();
        }
        root.addEventListener('pointerdown', function (event) {
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
        });
        document.addEventListener('pointermove', function (event) {
            if (!state.selecting || !state.anchor || !state.container) return;
            var element = document.elementFromPoint(event.clientX, event.clientY);
            if (state.container === weekView) {
                var column = element && element.closest ? element.closest('[data-week-column]') : null;
                if (!column || !weekView.contains(column)) return;
                var currentDate = parseDay(column.getAttribute('data-range-date'));
                if (!currentDate) return;
                var currentMinute = weekMinutes(event, column);
                var current = withTime(currentDate, currentMinute);
                var start = current < state.anchor ? current : state.anchor;
                var end = current < state.anchor ? state.anchor : current;
                state.start = start;
                state.end = new Date(end.getTime() + SLOT * 60000);
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
        });
        document.addEventListener('pointerup', finishSelection);
        document.addEventListener('pointercancel', finishSelection);
        weekView.addEventListener('pointerdown', function (event) {
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
        root.querySelector('[data-range-done]').addEventListener('click', function () {
            panel.hidden = true;
            toggle.setAttribute('aria-expanded', 'false');
        });
        toggle.addEventListener('click', function () {
            var open = panel.hidden;
            panel.hidden = !open;
            toggle.setAttribute('aria-expanded', String(open));
            if (open) {
                readInputs();
                render();
            }
        });
        function applyTimes() {
            var startMinutes = parseTime(startTime.value), endMinutes = parseTime(endTime.value);
            if (startMinutes === null || endMinutes === null) return;
            var startDate = state.start || state.cursor;
            var endDate = state.end || state.cursor;
            state.start = withTime(startDate, startMinutes);
            state.end = withTime(endDate, endMinutes);
            if (state.end <= state.start) state.end = new Date(state.start.getTime() + SLOT * 60000);
            commit();
            render();
        }
        startTime.addEventListener('change', applyTimes);
        endTime.addEventListener('change', applyTimes);
        readInputs();
        return {
            refresh: function () { readInputs(); if (!panel.hidden) render(); },
            applyLanguage: function () { paintSummary(); if (!panel.hidden) render(); }
        };
    }

    roots.forEach(function (root) { root._rangePicker = create(root); });
    window.WebClockRangePicker = {
        refresh: function (element) {
            var root = element && element.matches && element.matches('[data-range-picker]') ? element :
                element && element.querySelector ? element.querySelector('[data-range-picker]') : null;
            if (root && root._rangePicker) root._rangePicker.refresh();
        },
        applyLanguage: function () {
            roots.forEach(function (root) { if (root._rangePicker) root._rangePicker.applyLanguage(); });
        }
    };
}());
