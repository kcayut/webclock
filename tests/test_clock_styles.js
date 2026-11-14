// Run with: node tests/test_clock_styles.js (Node.js standard library only).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const rendererSource = fs.readFileSync(path.join(root, 'static/clock-styles.js'), 'utf8');
const clockSource = fs.readFileSync(path.join(root, 'static/clock.js'), 'utf8');
const previewSource = fs.readFileSync(path.join(root, 'templates/clock_preview.html'), 'utf8');
const indexSource = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');

class FakeNode {
    constructor(tag, doc) {
        this.tagName = tag;
        this.ownerDocument = doc;
        this.children = [];
        this.parentNode = null;
        this.className = '';
        this.id = '';
        this.style = {};
        this.attributes = {};
        this.textContent = '';
        this.ownerSVGElement = null;
    }
    appendChild(child) {
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.children.push(child);
        return child;
    }
    insertBefore(child, before) {
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        const index = before ? this.children.indexOf(before) : this.children.length;
        this.children.splice(index < 0 ? this.children.length : index, 0, child);
        return child;
    }
    removeChild(child) {
        const index = this.children.indexOf(child);
        if (index >= 0) this.children.splice(index, 1);
        child.parentNode = null;
        return child;
    }
    get firstChild() { return this.children[0] || null; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    createSVGPoint() { return {}; }
}

function fakeDocument(styleSheetLoaded = true) {
    const doc = {
        hidden: false,
        styleSheets: styleSheetLoaded
            ? [{href: 'http://clock.test/static/clock-styles.css', cssRules: [{}]}]
            : [],
        body: null,
        createElement: tag => new FakeNode(tag, doc),
        createElementNS: (namespace, tag) => new FakeNode(tag, doc),
        getElementById(id) {
            if (doc.elements[id]) return doc.elements[id];
            for (const rootNode of Object.values(doc.elements)) {
                const found = find(rootNode, id);
                if (found) return found;
            }
            return null;
        },
        elements: {}
    };
    function find(node, id) {
        if (node.id === id) return node;
        for (const child of node.children) {
            const found = find(child, id);
            if (found) return found;
        }
        return null;
    }
    doc.body = new FakeNode('body', doc);
    const container = new FakeNode('div', doc);
    container.id = 'clock-container';
    doc.elements['clock-container'] = container;
    return doc;
}

function runtime(doc, supports = true) {
    const window = {
        document: doc,
        matchMedia: () => ({matches: false}),
        CSS: {supports: () => supports}
    };
    doc.defaultView = window;
    const context = vm.createContext({window, document: doc, Math, Object, Array, String, Number, isFinite});
    vm.runInContext(rendererSource, context);
    return {window, context};
}

function snapshot(style, hour, minute, second, options = {}) {
    const settings = Object.assign({
        clock_style: style,
        show_seconds: true,
        show_date: true,
        show_weekday: true
    }, options);
    const hourText = String(hour).padStart(2, '0');
    const minuteText = String(minute).padStart(2, '0');
    const secondText = String(second).padStart(2, '0');
    return {
        style,
        hourText,
        minuteText,
        secondText,
        periodText: options.periodText || '',
        daySeconds: hour * 3600 + minute * 60 + second,
        settings
    };
}

function styleSurface(doc) {
    return doc.getElementById('clock-style-surface');
}

// Flip: panels replace one value at a time and never create a second surface.
{
    const doc = fakeDocument();
    const {window} = runtime(doc);
    const api = window.WebClockStyles;
    assert.equal(api.render(snapshot('flip', 9, 59, 58), doc), 'flip');
    const surface = styleSurface(doc);
    assert.ok(surface, 'flip creates a decoration surface');
    assert.equal(surface.className.includes('clock-deco-flip'), true);
    assert.equal(doc.body.className.includes('clock-style-enhanced'), true);
    assert.equal(surface.children[1].children[0].children[0].children[0].textContent, '09');
    assert.equal(surface.children[1].children[0].children[2].children[0].textContent, '59');
    api.render(snapshot('flip', 10, 0, 1), doc);
    assert.equal(surface.children[1].children[0].children[0].children[0].textContent, '10');
    assert.equal(surface.children[1].children[0].children[2].children[0].textContent, '00');
    assert.equal(surface.children[1].children[1].children[0].textContent, '01');
    assert.equal(doc.getElementById('clock-container').children.filter(child => child.id === 'clock-style-surface').length, 1);
}

// Segment: all digits exist once, values change by class state, seconds freeze when disabled.
{
    const doc = fakeDocument();
    const {window} = runtime(doc);
    const api = window.WebClockStyles;
    api.render(snapshot('segment', 23, 59, 59), doc);
    const surface = styleSurface(doc);
    const digits = surface.children[1].children.filter(child => child.className === 'segment-digit');
    assert.equal(digits.length, 4, 'four hour/minute digits');
    assert.equal(surface.children[1].children.filter(child => child.className.indexOf('segment-seconds') >= 0).length, 1);
    assert.equal(digits[0].children.filter(child => child.className.includes(' on')).length, 5, '2 uses five segments');
    assert.equal(digits[1].children.filter(child => child.className.includes(' on')).length, 5, '3 uses five segments');
    api.render(snapshot('segment', 11, 11, 11, {show_seconds: true}), doc);
    assert.equal(digits[0].children.filter(child => child.className.includes(' on')).length, 2, '1 uses two segments');
    assert.equal(digits[1].children.filter(child => child.className.includes(' on')).length, 2, '1 stays distinguishable');
    api.render(snapshot('segment', 20, 8, 9, {show_seconds: true}), doc);
    assert.equal(digits[0].children.filter(child => child.className.includes(' on')).length, 5, '2 uses five segments');
    const secondDigits = surface.children[1].children.find(child => child.className.indexOf('segment-seconds') >= 0).children;
    assert.equal(secondDigits[0].children.filter(child => child.className.includes(' on')).length, 6);
    assert.equal(secondDigits[1].children.filter(child => child.className.includes(' on')).length, 6);
    api.render(snapshot('segment', 20, 8, 59, {show_seconds: false}), doc);
    assert.equal(secondDigits[1].children.filter(child => child.className.includes(' on')).length, 6,
        'seconds are not updated when the setting is off');
    for (const digit of '0123456789') {
        const pattern = api.segmentPattern(digit);
        assert.ok(pattern.length >= 2 && pattern.length <= 7, digit + ' has a seven-segment pattern');
    }
}

// Paper: static content and only the shared clock data.
{
    const doc = fakeDocument();
    const {window} = runtime(doc);
    const api = window.WebClockStyles;
    api.render(snapshot('paper', 10, 28, 36), doc);
    assert.equal(styleSurface(doc).children[0].className, 'paper-time');
    assert.equal(doc.body.className.includes('clock-style-paper'), true);
}

// Invalid or unavailable styles always return to the visible #time fallback.
{
    const doc = fakeDocument();
    const {window} = runtime(doc);
    window.WebClockStyles.render(snapshot('flip', 10, 28, 36), doc);
    assert.equal(window.WebClockStyles.render(snapshot('unknown-style', 10, 28, 36), doc), 'classic');
    assert.equal(doc.body.className, '');
    assert.equal(styleSurface(doc).style.display, 'none');

    const noCss = fakeDocument(false);
    const noCssRuntime = runtime(noCss);
    assert.equal(noCssRuntime.window.WebClockStyles.render(snapshot('flip', 10, 28, 36), noCss), 'classic');
    assert.equal(noCss.body.className, '');
}

// Twenty style changes keep one timer-free surface and no accumulated body classes.
{
    const doc = fakeDocument();
    const {window} = runtime(doc);
    const api = window.WebClockStyles;
    const styles = ['flip', 'segment', 'paper', 'classic'];
    for (let index = 0; index < 20; index++) api.render(snapshot(styles[index % styles.length], 10, 28, 36), doc);
    const surfaces = doc.getElementById('clock-container').children.filter(child => child.id === 'clock-style-surface');
    assert.equal(surfaces.length, 1);
    const classes = doc.body.className.split(/\s+/).filter(Boolean);
    assert.equal(new Set(classes).size, classes.length, 'body classes do not accumulate');
    api.render(snapshot('classic', 10, 28, 36), doc);
    assert.equal(doc.body.className, '');
    assert.equal(styleSurface(doc).style.display, 'none');
}

// Core clock keeps exactly one timer and the optional renderer cannot stop it.
{
    const doc = fakeDocument();
    doc.elements.time = new FakeNode('div', doc);
    doc.elements['time-period'] = new FakeNode('div', doc);
    doc.elements['date-part'] = new FakeNode('span', doc);
    doc.elements['day-part'] = new FakeNode('span', doc);
    doc.elements['clock-container'].appendChild(doc.elements.time);
    const timers = [];
    const listeners = {};
    const window = {
        document: doc,
        addEventListener: (name, callback) => { listeners[name] = callback; },
        WebClockStyles: {render() { throw new Error('optional renderer failed'); }, reset: () => { doc.body.className = ''; }}
    };
    const context = vm.createContext({
        window, document: doc, Date, String, Number, isFinite, setInterval: (callback, delay) => timers.push({callback, delay}),
        WebClockTime: {period: () => 'AM'}
    });
    vm.runInContext(clockSource, context);
    context.renderClock(Date.parse('2026-11-14T10:28:36Z'), 0,
        ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], '24h', 'en', {clock_style: 'flip'});
    assert.equal(doc.elements.time.textContent, '10:28');
    assert.equal(timers.length, 0);
}

// The essential core must start before optional style CSS/JS can delay parsing.
{
    const coreStart = indexSource.indexOf('WebClockCore.start');
    const styleCss = indexSource.indexOf('clock-styles.css');
    const styleJs = indexSource.indexOf('clock-styles.js');
    assert.ok(coreStart > 0);
    assert.ok(styleCss > coreStart, 'optional style CSS loads after the core starts');
    assert.ok(styleJs > coreStart, 'optional style JS loads after the core starts');
    assert.ok(styleCss < styleJs, 'style CSS is requested before its renderer');
}

// All clock-facing new JavaScript and inline preview code stays ES5-parseable.
for (const [name, code] of [
    ['static/clock-styles.js', rendererSource],
    ['static/clock.js', clockSource],
    ['templates/clock_preview.html', previewSource],
    ['templates/index.html', indexSource]
]) {
    assert.doesNotMatch(code, /\b(?:const|let|async)\b|=>|\?\./, name + ' must remain ES5');
}
console.log('Clock style checks passed: flip panels, seven-segment state, paper layout, fallback, 20 switches and ES5.');
