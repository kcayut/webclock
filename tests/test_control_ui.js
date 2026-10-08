// Run with node tests/test_control_ui.js.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
    let content = '';
    const node = {children: [], listeners: {}, attrs: {}, hidden: false, value: '', disabled: false,
        addEventListener(name, callback) { this.listeners[name] = callback; },
        trigger(name) { this.listeners[name].call(this, {preventDefault() {}}); },
        setAttribute(key, value) { this.attrs[key] = value; },
        getAttribute(key) { return this.attrs[key]; },
        removeAttribute(key) { delete this.attrs[key]; },
        appendChild(child) { this.children.push(child); }};
    Object.defineProperty(node, 'textContent', {get() { return content + this.children.map(c => c.textContent).join(''); },
        set(value) { content = value; this.children = []; }});
    return node;
}
const ids = Object.fromEntries(['control-i18n', 'control-create', 'control-clients', 'control-status',
    'control-token', 'control-secret', 'control-reveal', 'csrf-token'].map(id => [id, element()]));
const keys = ['expires', 'revoke', 'confirm', 'empty', 'title', 'saved', 'error', 'revoked', 'show', 'hide'];
ids['control-i18n'].textContent = JSON.stringify(Object.fromEntries(['en', 'ja', 'zh-TW'].map(language =>
    [language, Object.fromEntries(keys.map(key => [key, language + ':' + key]))])));
const submit = element(), form = ids['control-create'], list = ids['control-clients'];
form.elements = {name: {value: 'Draft'}, days: {value: '30'}};
form.action = '/clients';
form.querySelector = () => submit;
form.querySelectorAll = selector => selector.includes('name="scopes"') ? [{value: 'events:read'}] : [];
list.dataset = {url: '/clients'};
ids['csrf-token'].content = 'csrf';
ids['control-secret'].hidden = true;
const requests = [], window = {confirm: () => confirmResult, addEventListener(name, listener) { this[name] = listener; }};
let confirmResult = true;
const document = {documentElement: {lang: 'en'}, getElementById: id => ids[id], createElement: element,
    querySelectorAll: () => Object.values(ids).filter(node => node.attrs['data-control-text'])};
const context = vm.createContext({document, window, fetch(url, options) {
    return new Promise(resolve => requests.push({url, options, resolve}));
}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../static/control-access.js'), 'utf8'), context);
const flush = () => new Promise(setImmediate);
async function reply(request, data, ok = true) {
    request.resolve({ok, json: () => Promise.resolve(data)}); await flush();
}
(async () => {
    const initial = requests.shift();
    form.trigger('submit');
    await reply(requests.shift(), {client: {id:'one', name:'Client', expires_at:1234567, token:'temporary-secret'}});
    assert.equal(ids['control-token'].type, 'password');
    assert.equal(ids['control-secret'].hidden, false);
    assert.equal(list.textContent.includes('temporary-secret'), false);
    await reply(initial, {clients:[]});
    assert.equal(list.children.length, 1, 'Delayed initial GET must retain the new credential');
    document.documentElement.lang = 'ja'; window.applyManagementLanguage('ja');
    assert.equal(ids['control-status'].textContent, 'ja:saved');
    assert.equal(form.elements.name.value, 'Draft');
    ids['control-reveal'].trigger('click');
    assert.equal(ids['control-token'].type, 'text');
    assert.equal(ids['control-reveal'].attrs['aria-pressed'], 'true');
    form.trigger('submit'); await reply(requests.shift(), {}, false);
    assert.equal(list.children.length, 1); assert.equal(form.elements.name.value, 'Draft');
    const revoke = list.children[0].children[1];
    confirmResult = false; revoke.trigger('click'); assert.equal(requests.length, 0);
    confirmResult = true; revoke.trigger('click'); await reply(requests.shift(), {}, false);
    assert.equal(list.children.length, 1); assert.equal(revoke.disabled, false);
    revoke.trigger('click'); await reply(requests.shift(), {});
    assert.equal(ids['control-token'].value, ''); assert.equal(ids['control-secret'].hidden, true);
    assert.equal(ids['control-status'].textContent, 'ja:revoked');
    form.trigger('submit');
    await reply(requests.shift(), {client: {id:'two', name:'Second', expires_at:1234567, token:'new-secret'}});
    window.pagehide(); assert.equal(ids['control-token'].value, ''); assert.equal(ids['control-secret'].hidden, true);
    console.log('Control credential UI checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
