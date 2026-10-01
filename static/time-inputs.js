/* Native time inputs follow the OS locale, so use explicit fields with a canonical hidden value. */
(function (root) {
    'use strict';
    function make(tag, className, parent) {
        var element = document.createElement(tag);
        element.className = className;
        parent.appendChild(element);
        return element;
    }
    function attach(input) {
        var group = document.createElement('div');
        group.className = 'time-input-control';
        group.setAttribute('role', 'group');
        input.parentNode.insertBefore(group, input.nextSibling);
        var state = {group: group, label: document.querySelector('label[for="' + input.id + '"]')};
        state.date = make('input', 'time-input-date', group);
        state.date.type = 'date';
        state.hour = make('input', 'time-input-hour', group);
        state.hour.type = 'number';
        state.hour.id = input.id + '-hour';
        state.hour.setAttribute('inputmode', 'numeric');
        state.hour.placeholder = '00';
        state.hour.step = '1';
        make('span', 'time-input-separator', group).textContent = ':';
        state.minute = make('input', 'time-input-minute', group);
        state.minute.type = 'number';
        state.minute.setAttribute('inputmode', 'numeric');
        state.minute.placeholder = '00';
        state.minute.min = '0';
        state.minute.max = '59';
        state.minute.step = '1';
        state.period = make('select', 'time-input-period', group);
        make('option', '', state.period).value = 'am';
        make('option', '', state.period).value = 'pm';
        if (state.label) state.label.htmlFor = state.hour.id;
        function sync() {
            var hour = state.hour.value, minute = state.minute.value, date = state.date.value;
            var any = hour !== '' || minute !== '' || (state.type === 'datetime-local' && date !== '');
            state.hour.required = state.minute.required = state.date.required = input.required || any;
            var valid = hour !== '' && minute !== '' && state.hour.validity.valid && state.minute.validity.valid;
            if (state.type === 'datetime-local') valid = valid && date !== '' && state.date.validity.valid;
            state.invalid = any && !valid;
            if (valid) {
                var h = Number(hour);
                if (state.format === '12h') h = h % 12 + (state.period.value === 'pm' ? 12 : 0);
                input.value = (state.type === 'datetime-local' ? date + 'T' : '') + root.WebClockTime.pad(h) + ':' + root.WebClockTime.pad(Number(minute));
            } else if (!any) input.value = '';
            state.value = input.value;
        }
        [state.date, state.hour, state.minute, state.period].forEach(function (field) {
            ['input', 'change'].forEach(function (name) {
                field.addEventListener(name, function () {
                    sync();
                    var event = document.createEvent('Event');
                    event.initEvent(name, true, false);
                    input.dispatchEvent(event);
                });
            });
        });
        state.sync = sync;
        if (input.form) input.form.addEventListener('reset', function () { state.value = null; state.invalid = false; });
        input._clockTimeControl = state;
        return state;
    }
    function refresh(container, format, language) {
        if (!root.WebClockTime) return;
        var inputs = container.querySelectorAll('input[type="time"], input[type="datetime-local"], input[data-clock-time-type]');
        for (var i = 0; i < inputs.length; i++) {
            var input = inputs[i];
            var type = input.type === 'hidden' ? input.getAttribute('data-clock-time-type') : input.type;
            var state = input._clockTimeControl || attach(input);
            var preservePartial = state.invalid && state.value === input.value && state.type === type;
            var unchanged = state.value === input.value && state.format === format && state.type === type;
            state.type = type;
            input.setAttribute('data-clock-time-type', type);
            input.type = 'hidden';
            var words = root.WebClockTime.labels(language);
            var label = state.label ? state.label.textContent.trim() : input.getAttribute('aria-label') || '';
            state.group.setAttribute('aria-label', label);
            state.hour.setAttribute('aria-label', label + ' · ' + words.hour);
            state.minute.setAttribute('aria-label', label + ' · ' + words.minute);
            state.date.setAttribute('aria-label', label + ' · ' + words.date);
            state.period.setAttribute('aria-label', label + ' · ' + words.period);
            state.period.options[0].textContent = words.am;
            state.period.options[1].textContent = words.pm;
            state.date.hidden = type !== 'datetime-local';
            state.date.disabled = input.disabled || state.date.hidden;
            state.hour.disabled = state.minute.disabled = input.disabled;
            state.period.hidden = format !== '12h';
            state.period.disabled = input.disabled || state.period.hidden;
            state.hour.min = format === '12h' ? '1' : '0';
            state.hour.max = format === '12h' ? '12' : '23';
            state.hour.placeholder = format === '12h' ? '12' : '00';
            if (preservePartial && state.format !== format && state.hour.value !== '') {
                var draftHour = Number(state.hour.value);
                if (draftHour >= (state.format === '12h' ? 1 : 0) && draftHour <= (state.format === '12h' ? 12 : 23)) {
                    if (state.format === '12h') draftHour = draftHour % 12 + (state.period.value === 'pm' ? 12 : 0);
                    state.hour.value = root.WebClockTime.pad(format === '12h' ? draftHour % 12 || 12 : draftHour);
                    state.period.value = draftHour < 12 ? 'am' : 'pm';
                }
            }
            if (!unchanged && !preservePartial) {
                var parts = /^(?:(\d{4}-\d{2}-\d{2})T)?(\d{2}):(\d{2})$/.exec(input.value);
                var hour = parts ? Number(parts[2]) : 0;
                state.date.value = parts && parts[1] || '';
                state.hour.value = parts ? root.WebClockTime.pad(format === '12h' ? hour % 12 || 12 : hour) : '';
                state.minute.value = parts ? parts[3] : '';
                state.period.value = hour < 12 ? 'am' : 'pm';
            }
            state.format = format;
            state.sync();
        }
    }
    root.WebClockTimeInputs = {refresh: refresh};
}(window));
