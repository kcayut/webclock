/* WebClock cards: HA transports data; device credentials never enter this file. */
(() => {
  'use strict';
  const labels = {
    'zh-TW': {time: '時間', calendar: '行事曆', alarms: '鬧鐘', empty: '目前沒有項目', unavailable: '尚無有效授權資料', enabled: '個已啟用鬧鐘', allDay: '全天'},
    en: {time: 'Time', calendar: 'Calendar', alarms: 'Alarms', empty: 'No items', unavailable: 'No authorized data available', enabled: 'enabled alarms', allDay: 'All day'},
    ja: {time: '時刻', calendar: 'カレンダー', alarms: 'アラーム', empty: '予定はありません', unavailable: '有効な認証データがありません', enabled: '件の有効なアラーム', allDay: '終日'},
  };

  class WebClockCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({mode: 'open'});
      this.shadowRoot.innerHTML = `<style>
        :host{display:block;height:100%;color:var(--primary-text-color)}
        ha-card{height:100%;box-sizing:border-box;padding:24px;background:var(--ha-card-background,var(--card-background-color));overflow:hidden}
        h2{font-size:18px;font-weight:500;line-height:1.4;margin:0 0 16px}
        .clock{font-variant-numeric:tabular-nums;font-size:clamp(32px,7vw,64px);font-weight:500;line-height:1.2;white-space:nowrap}
        .date,.muted{color:var(--secondary-text-color);font-size:14px;line-height:1.6}
        .date{margin-top:8px}ul{list-style:none;margin:0;padding:0;max-height:360px;overflow:auto}
        li{padding:12px 0;border-bottom:1px solid var(--divider-color);display:flex;flex-wrap:wrap;gap:4px 16px;align-items:baseline}
        li:last-child{border:0}time{font-variant-numeric:tabular-nums;color:var(--secondary-text-color);font-size:14px}
        .text{overflow-wrap:anywhere;white-space:pre-wrap}.summary{margin-bottom:8px}
      </style><ha-card><h2></h2><div class="body"></div></ha-card>`;
      this._generation = 0;
      this._lastSync = -Infinity;
    }
    setConfig(config) {
      if (!config || typeof config.entity !== 'string' || !config.entity.startsWith('sensor.')) {
        throw new Error('Select a WebClock sensor entity.');
      }
      if (config.entity !== this._config?.entity) {
        this._generation++;
        this._anchor = null;
        this._lastSync = -Infinity;
        this._syncing = false;
      }
      this._config = {...config};
      this._render();
      this._syncTime();
    }
    set hass(hass) {
      this._hass = hass;
      this._render();
      this._syncTime();
    }
    connectedCallback() {
      if (!this._timer) this._timer = setInterval(() => { this._render(); this._syncTime(); }, 1000);
      this._syncTime();
    }
    disconnectedCallback() {
      clearInterval(this._timer);
      this._timer = null;
      this._generation++;
      this._syncing = false;
    }
    getCardSize() { return this.constructor.kind === 'time' ? 3 : 4; }
    getGridOptions() { return {columns: 12, min_columns: 6}; }
    static getStubConfig(hass) {
      const entity = Object.keys(hass?.states || {}).find(id => hass.states[id].attributes?.webclock_kind === this.kind);
      return {entity: entity || `sensor.webclock_${this.kind}`};
    }
    static getConfigForm() {
      return {schema: [
        {name: 'entity', required: true, selector: {entity: {filter: {domain: 'sensor', integration: 'webclock'}}}},
        {name: 'title', selector: {text: {}}},
      ]};
    }
    _now() {
      return this._anchor ? this._anchor.server + performance.now() - this._anchor.local : null;
    }
    async _syncTime() {
      const state = this._hass?.states?.[this._config?.entity];
      const entryId = state?.attributes?.entry_id;
      if (!this.isConnected || !entryId || this._syncing || performance.now() - this._lastSync < 30000) return;
      this._syncing = true;
      this._lastSync = performance.now();
      const generation = this._generation;
      const start = performance.now();
      try {
        const result = await this._hass.callWS({type: 'webclock/time', entry_id: entryId});
        if (generation !== this._generation || !this.isConnected) return;
        if (Number.isFinite(result.server_timestamp)) {
          const end = performance.now();
          this._anchor = {server: result.server_timestamp + (end - start) / 2, local: end, wall: Date.now()};
          this._render();
        }
      } catch (_) {
        // Keep the last monotonic clock. Private rows still expire below.
      } finally {
        if (generation === this._generation) this._syncing = false;
      }
    }
    _format(stamp, attrs, date = false) {
      const offset = Number.isFinite(attrs.timezone_offset) ? attrs.timezone_offset : -new Date().getTimezoneOffset() / 60;
      const shifted = new Date(stamp + offset * 3600000);
      const options = date ? {year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'} :
        {hour: '2-digit', minute: '2-digit', second: this.constructor.kind === 'time' ? '2-digit' : undefined, hour12: attrs.time_format === '12h'};
      return new Intl.DateTimeFormat(labels[attrs.language] ? attrs.language : 'en', {...options, timeZone: 'UTC'}).format(shifted);
    }
    _render() {
      if (!this._config) return;
      const state = this._hass?.states?.[this._config.entity];
      const attrs = state?.attributes || {};
      const text = labels[attrs.language] || labels.en;
      const kind = this.constructor.kind;
      this.shadowRoot.querySelector('h2').textContent = this._config.title || text[kind];
      const body = this.shadowRoot.querySelector('.body');
      const now = this._now();
      if (kind === 'time') {
        if (!body.querySelector('.clock')) body.innerHTML = '<div class="clock"></div><div class="date"></div>';
        const stamp = now ?? Date.now();
        body.querySelector('.clock').textContent = this._format(stamp, attrs);
        body.querySelector('.date').textContent = this._format(stamp, attrs, true);
        return;
      }
      const authorized = attrs.webclock_kind === kind && state && !['unavailable', 'unknown'].includes(state.state)
        && now !== null && Number.isFinite(attrs.lease_expires_at)
        && Math.max(now, this._anchor.server + Date.now() - this._anchor.wall) < attrs.lease_expires_at;
      const rows = authorized ? (kind === 'calendar' ? attrs.events || [] :
        (attrs.alarms || []).filter(row => row.starts_at >= now)) : [];
      // Do not rebuild scrollable rows on each clock tick or unrelated HA update.
      const signature = JSON.stringify([authorized, rows, state?.state, attrs.language, attrs.time_format, attrs.timezone_offset]);
      if (signature === this._rendered) return;
      this._rendered = signature;
      body.replaceChildren();
      if (!authorized || !rows.length) {
        const empty = document.createElement('div');
        empty.className = 'muted'; empty.textContent = authorized ? text.empty : text.unavailable;
        body.append(empty);
      }
      if (authorized && kind === 'alarms') {
        const summary = document.createElement('div');
        summary.className = 'muted summary'; summary.textContent = `${state.state} ${text.enabled}`;
        body.prepend(summary);
      }
      const list = document.createElement('ul');
      for (const row of rows) {
        const item = document.createElement('li');
        const time = document.createElement('time');
        time.textContent = kind === 'calendar' ? row.time || '' :
          `${this._format(row.starts_at, attrs, true)} ${this._format(row.starts_at, attrs)}`;
        const label = document.createElement('span');
        label.className = 'text'; label.textContent = kind === 'calendar' ? row.text : row.name;
        item.append(time, label); list.append(item);
      }
      body.append(list);
    }
  }
  class WebClockTimeCard extends WebClockCard { static kind = 'time'; }
  class WebClockCalendarCard extends WebClockCard { static kind = 'calendar'; }
  class WebClockAlarmCard extends WebClockCard { static kind = 'alarms'; }
  window.customCards = window.customCards || [];
  for (const [type, element, name] of [
    ['webclock-time-card', WebClockTimeCard, 'WebClock Time'],
    ['webclock-calendar-card', WebClockCalendarCard, 'WebClock Calendar'],
    ['webclock-alarm-card', WebClockAlarmCard, 'WebClock Alarms'],
  ]) {
    if (!customElements.get(type)) {
      customElements.define(type, element);
      window.customCards.push({type, name, preview: true, description: 'WebClock managed display'});
    }
  }
})();
