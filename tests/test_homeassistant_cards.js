/* Runnable without HA/npm dependencies: node tests/test_homeassistant_cards.js */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag = '') { this.tag = tag; this.children = []; this.textContent = ''; this.nodes = {}; }
  set innerHTML(value) { this.html = value; }
  get innerHTML() { return this.html; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(node) { this.children.unshift(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelector(selector) { return this.nodes[selector] ||= new Element(selector); }
  attachShadow() { this.shadowRoot = new Element(); return this.shadowRoot; }
}
let now = 1000;
let intervalCount = 0;
const registry = new Map();
const context = {HTMLElement: Element, Intl, Date, Number, JSON, performance: {now: () => now},
  window: {}, document: {createElement: tag => new Element(tag)},
  customElements: {define: (name, cls) => registry.set(name, cls), get: name => registry.get(name)},
  setInterval: () => { intervalCount++; return intervalCount; }, clearInterval: () => { intervalCount--; }};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../custom_components/webclock/www/webclock-cards.js'), 'utf8'), context);
const stamp = Date.parse('2026-10-06T23:59:58Z');
const hass = {states: {}, callWS: async () => ({server_timestamp: stamp})};
function card(kind, suffix = kind) {
  const Card = registry.get(`webclock-${suffix}-card`);
  const value = new Card(); value.isConnected = true;
  value.setConfig({entity: `sensor.${kind}`});
  hass.states[`sensor.${kind}`] = {state: '1', attributes: {
    entry_id: 'test', webclock_kind: kind === 'alarm' ? 'alarms' : kind,
    timezone_offset: 0, language: 'en', time_format: '24h', lease_expires_at: stamp + 300000,
    events: [{text: '<img src=x onerror=alert(1)>', time: '08:00'}],
    alarms: [{name: 'Wake up', starts_at: stamp + 60000}],
  }};
  value.hass = hass;
  value._anchor = {server: stamp, local: now, wall: Date.now()};
  value._render(); return value;
}
(async () => {
  assert.equal(registry.size, 3);
  const clock = card('time');
  const first = clock.shadowRoot.querySelector('.body').querySelector('.clock').textContent;
  now += 3000; clock._render();
  assert.notEqual(clock.shadowRoot.querySelector('.body').querySelector('.clock').textContent, first);
  assert.match(clock.shadowRoot.querySelector('.body').querySelector('.date').textContent, /October 7/);
  const calendar = card('calendar');
  const body = calendar.shadowRoot.querySelector('.body');
  const row = body.children.find(node => node.tag === 'ul').children[0];
  assert.equal(row.children[1].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(row.children[1].innerHTML, undefined); // Text is never interpreted as markup.
  const alarms = card('alarm');
  assert.equal(alarms.shadowRoot.querySelector('.body').children.find(n => n.tag === 'ul').children.length, 1);
  now += 300001;
  calendar._render(); alarms._render();
  assert.match(body.children[0].textContent, /No authorized/);
  assert.equal(body.children.find(node => node.tag === 'ul').children.length, 0);
  hass.states['sensor.calendar'].state = 'unavailable';
  calendar._render();
  assert.equal(body.children.find(node => node.tag === 'ul').children.length, 0);
  clock.connectedCallback(); clock.connectedCallback();
  assert.equal(intervalCount, 1);
  clock.disconnectedCallback();
  assert.equal(intervalCount, 0);
  const Card = registry.get('webclock-time-card');
  assert.throws(() => new Card().setConfig({entity: 'media_player.test'}));
  let resolve;
  hass.callWS = () => new Promise(done => {resolve = done;});
  clock.isConnected = true; clock._lastSync = -Infinity; clock._syncing = false;
  const pending = clock._syncTime();
  clock.setConfig({entity: 'sensor.another'});
  resolve({server_timestamp: stamp + 99999});
  await pending;
  assert.equal(clock._anchor, null); // Old entity's late clock cannot contaminate the new card.
  console.log('HA cards: server time, midnight, text escaping, lease expiry, revocation, cleanup and stale replies passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
