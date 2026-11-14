/*
 * Optional clock renderers for flip, segment and paper.  This file never reads
 * the clock, never creates a timer and never owns display settings.  It uses
 * the single snapshot passed by WebClockCore; if it is missing or fails, #time
 * remains the visible and accessible fallback.
 */
(function (root) {
    'use strict';
    var STYLE_IDS = ['classic', 'flip', 'segment', 'paper'];
    var SEGMENTS = {
        '0': 'abcdef',
        '1': 'bc',
        '2': 'abged',
        '3': 'abgcd',
        '4': 'fgbc',
        '5': 'afgcd',
        '6': 'afgedc',
        '7': 'abc',
        '8': 'abcdefg',
        '9': 'abcdfg'
    };
    var segmentOrder = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];
    var state = {
        style: null,
        nodes: null,
        update: null,
        surface: null,
        bodyClasses: [],
        last: null,
        stylesheetReady: false
    };

    function indexOf(list, value) {
        for (var i = 0; i < list.length; i++) {
            if (list[i] === value) return i;
        }
        return -1;
    }

    function create(doc, tag, className) {
        var node = doc.createElement(tag);
        if (className) node.className = className;
        return node;
    }

    function append(parent, child) {
        parent.appendChild(child);
        return child;
    }

    function setText(node, value) {
        value = String(value);
        if (node && node.textContent !== value) node.textContent = value;
    }

    function hasClass(node, name) {
        return (' ' + (node.className || '') + ' ').indexOf(' ' + name + ' ') >= 0;
    }

    function addClass(node, name) {
        if (!hasClass(node, name)) node.className = (node.className ? node.className + ' ' : '') + name;
    }

    function removeClass(node, name) {
        var values = (node.className || '').split(/\s+/), kept = [];
        for (var i = 0; i < values.length; i++) {
            if (values[i] && values[i] !== name) kept.push(values[i]);
        }
        node.className = kept.join(' ');
    }

    function stylesheetReady(doc) {
        if (state.stylesheetReady) return true;
        var sheets = doc.styleSheets;
        if (!sheets) return true;
        for (var i = 0; i < sheets.length; i++) {
            var href = sheets[i].href || '';
            if (href.indexOf('clock-styles.css') < 0) continue;
            try {
                if (!sheets[i].cssRules || sheets[i].cssRules.length > 0) {
                    state.stylesheetReady = true;
                    return true;
                }
            } catch (error) {
                /* Cross-origin sheets still count as loaded; this one is same-origin. */
                state.stylesheetReady = true;
                return true;
            }
        }
        return false;
    }

    function reset(doc) {
        doc = doc || root.document;
        var body = doc && doc.body;
        if (body) {
            for (var i = 0; i < state.bodyClasses.length; i++) removeClass(body, state.bodyClasses[i]);
        }
        state.bodyClasses = [];
        if (state.surface) {
            state.surface.style.display = 'none';
            while (state.surface.firstChild) state.surface.removeChild(state.surface.firstChild);
        }
        state.style = null;
        state.nodes = null;
        state.update = null;
        state.last = null;
    }

    function ensureSurface(doc, style) {
        var container = doc.getElementById('clock-container');
        if (!container) throw new Error('Clock container is unavailable');
        var surface = doc.getElementById('clock-style-surface');
        if (!surface) {
            surface = create(doc, 'div', 'clock-deco');
            surface.id = 'clock-style-surface';
            surface.setAttribute('aria-hidden', 'true');
            container.insertBefore(surface, container.firstChild || null);
        } else if (container.firstChild !== surface) {
            container.insertBefore(surface, container.firstChild || null);
        }
        while (surface.firstChild) surface.removeChild(surface.firstChild);
        surface.className = 'clock-deco clock-deco-' + style;
        surface.style.display = '';
        state.surface = surface;
        return surface;
    }

    function periodNode(doc) {
        var node = create(doc, 'div', 'clock-period');
        node.setAttribute('aria-hidden', 'true');
        return node;
    }

    function timeParts(doc, className) {
        var wrap = create(doc, 'span', className || 'style-time');
        var hour = create(doc, 'span', 'style-hour');
        var colon = create(doc, 'span', 'style-colon');
        colon.textContent = ':';
        var minute = create(doc, 'span', 'style-minute');
        append(wrap, hour);
        append(wrap, colon);
        append(wrap, minute);
        return {wrap: wrap, hour: hour, minute: minute};
    }

    function secondsNode(doc, className) {
        var wrap = create(doc, 'span', 'clock-seconds ' + (className || 'style-seconds'));
        var value = create(doc, 'span', 'style-seconds-value');
        append(wrap, value);
        return {wrap: wrap, value: value};
    }

    function buildFlip(doc, surface) {
        var period = periodNode(doc);
        var row = create(doc, 'div', 'flip-row');
        var main = create(doc, 'div', 'flip-main');
        var hourPanel = create(doc, 'div', 'flip-panel');
        var hour = create(doc, 'span', 'flip-digits');
        var colon = create(doc, 'span', 'flip-colon');
        var minutePanel = create(doc, 'div', 'flip-panel');
        var minute = create(doc, 'span', 'flip-digits');
        var seconds = secondsNode(doc, 'flip-seconds');
        append(colon, create(doc, 'i', 'flip-dot'));
        append(colon, create(doc, 'i', 'flip-dot'));
        append(hourPanel, hour);
        append(minutePanel, minute);
        append(main, hourPanel);
        append(main, colon);
        append(main, minutePanel);
        append(row, main);
        append(row, seconds.wrap);
        append(surface, period);
        append(surface, row);
        state.nodes = {period: period, hour: hour, minute: minute, seconds: seconds.value,
                       hourPanel: hourPanel, minutePanel: minutePanel};
        state.update = function (data) {
            setText(state.nodes.hour, data.hourText);
            setText(state.nodes.minute, data.minuteText);
            setText(state.nodes.period, data.periodText);
            if (data.settings.show_seconds) setText(state.nodes.seconds, data.secondText);
            var changed = state.last && (state.last.hourText !== data.hourText ||
                state.last.minuteText !== data.minuteText);
            if (changed && !doc.hidden && !hasClass(doc.body, 'night-active') &&
                    !hasClass(doc.body, 'force-black') && !reducedMotion()) {
                state.nodes.minutePanel.className = 'flip-panel';
                if (state.nodes.minutePanel.offsetWidth !== undefined) state.nodes.minutePanel.offsetWidth;
                state.nodes.minutePanel.className = 'flip-panel flip-tick';
            }
        };
    }

    function segmentDigit(doc) {
        var digit = create(doc, 'span', 'segment-digit');
        var nodes = {};
        for (var i = 0; i < segmentOrder.length; i++) {
            var name = segmentOrder[i];
            nodes[name] = append(digit, create(doc, 'span', 'segment segment-' + name));
        }
        return {root: digit, nodes: nodes, value: null};
    }

    function setSegmentDigit(node, value) {
        value = String(value);
        if (node.value === value) return;
        node.value = value;
        var on = SEGMENTS[value] || '';
        for (var i = 0; i < segmentOrder.length; i++) {
            var name = segmentOrder[i];
            node.nodes[name].className = 'segment segment-' + name +
                (on.indexOf(name) >= 0 ? ' on' : '');
        }
    }

    function buildSegment(doc, surface) {
        var period = periodNode(doc);
        var row = create(doc, 'div', 'segment-row');
        var digits = [];
        for (var i = 0; i < 4; i++) {
            var digit = segmentDigit(doc);
            digits.push(digit);
            append(row, digit.root);
            if (i === 1) {
                var colon = create(doc, 'span', 'segment-colon');
                append(colon, create(doc, 'i', 'segment-dot'));
                append(colon, create(doc, 'i', 'segment-dot'));
                append(row, colon);
            }
        }
        var seconds = create(doc, 'span', 'clock-seconds segment-seconds');
        var secondTens = segmentDigit(doc), secondOnes = segmentDigit(doc);
        digits.push(secondTens, secondOnes);
        append(seconds, secondTens.root);
        append(seconds, secondOnes.root);
        append(row, seconds);
        append(surface, period);
        append(surface, row);
        state.nodes = {period: period, digits: digits};
        state.update = function (data) {
            var text = data.hourText + data.minuteText;
            for (var index = 0; index < 4; index++) setSegmentDigit(state.nodes.digits[index], text.charAt(index));
            setText(state.nodes.period, data.periodText);
            if (data.settings.show_seconds) {
                setSegmentDigit(state.nodes.digits[4], data.secondText.charAt(0));
                setSegmentDigit(state.nodes.digits[5], data.secondText.charAt(1));
            }
        };
    }

    function buildPaper(doc, surface) {
        var period = periodNode(doc);
        var main = create(doc, 'div', 'paper-time');
        var parts = timeParts(doc, 'paper-time-main');
        var seconds = secondsNode(doc, 'paper-seconds');
        append(main, period);
        append(main, parts.wrap);
        append(main, seconds.wrap);
        append(surface, main);
        state.nodes = {period: period, hour: parts.hour, minute: parts.minute, seconds: seconds.value};
        state.update = function (data) {
            setText(state.nodes.hour, data.hourText);
            setText(state.nodes.minute, data.minuteText);
            setText(state.nodes.period, data.periodText);
            if (data.settings.show_seconds) setText(state.nodes.seconds, data.secondText);
        };
    }

    function reducedMotion() {
        try {
            return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
        } catch (error) {
            return false;
        }
    }

    function build(doc, style) {
        var surface = ensureSurface(doc, style);
        state.style = style;
        state.last = null;
        if (style === 'flip') buildFlip(doc, surface);
        else if (style === 'segment') buildSegment(doc, surface);
        else if (style === 'paper') buildPaper(doc, surface);
        else throw new Error('Unknown clock style');
    }

    function applyBodyClasses(doc, style) {
        var body = doc.body, i;
        for (i = 0; i < state.bodyClasses.length; i++) removeClass(body, state.bodyClasses[i]);
        state.bodyClasses = ['clock-style-' + style, 'clock-style-enhanced'];
        for (i = 0; i < state.bodyClasses.length; i++) addClass(body, state.bodyClasses[i]);
    }

    function render(data, doc) {
        doc = doc || root.document;
        if (!doc || !doc.body) return 'classic';
        if (doc.hidden) state.last = null;
        var requested = data && data.style ? data.style : 'classic';
        if (indexOf(STYLE_IDS, requested) < 0) {
            reset(doc);
            return 'classic';
        }
        if (requested === 'classic' || !stylesheetReady(doc)) {
            reset(doc);
            return 'classic';
        }
        try {
            var rebuilt = false;
            if (state.style !== requested || !state.nodes) {
                build(doc, requested);
                rebuilt = true;
            }
            if (rebuilt || !hasClass(doc.body, 'clock-style-enhanced')) {
                applyBodyClasses(doc, requested);
            }
            state.update(data);
            state.last = {
                hourText: data.hourText,
                minuteText: data.minuteText,
                secondText: data.secondText,
                showSeconds: !!data.settings.show_seconds
            };
            return requested;
        } catch (error) {
            reset(doc);
            return 'classic';
        }
    }

    function segmentPattern(value) {
        return SEGMENTS[String(value)] || '';
    }

    if (root.addEventListener) {
        root.addEventListener('pageshow', function () {
            state.last = null;
        });
    }

    root.WebClockStyles = {
        ids: STYLE_IDS,
        render: render,
        reset: reset,
        segmentPattern: segmentPattern
    };
}(window));
