"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const template = fs.readFileSync(path.join(__dirname, "../templates/schedules.html"), "utf8");
const source = fs.readFileSync(path.join(__dirname, "../static/schedules.js"), "utf8");
assert.doesNotMatch(template, /id="(?:schedule-(?:repeat|snooze)|sound-form|enable-audio|ringing)"/);
assert.match(template, /<input type="hidden" id="schedule-rule">/);
assert.doesNotMatch(template.match(/<select id="schedule-special-rule">(.*?)<\/select>/)[1], /value="(?:once|every_day|weekdays|dates)"/);
assert.match(template, /alarm-audio\.js/);
assert.match(template, /data-time-format="\{\{ time_format \}\}"/);
assert.ok(template.indexOf("time-format.js") < template.indexOf("schedules.js"));
assert.ok(template.indexOf("time-inputs.js") < template.indexOf("schedules.js"));
assert.ok(template.indexOf("schedules.js") < template.indexOf("management.js"), "Language controls wait for the schedule translation hook");
const row = {id: "alarm", name: "Morning", type: "alarm", enabled: true, time: "07:30", rule: {},
    skipped_occurrences: [], next_occurrence: "2026-10-01T07:30:00+08:00"};
const nextDate = "2026-10-02T07:30:00+08:00";
const plain = value => JSON.parse(JSON.stringify(value));
const flush = () => new Promise(resolve => setImmediate(resolve));
let activeElement = null;

function element(tag = "div") {
    const classes = new Set();
    return {
        tag, textContent: "", className: "", disabled: false, hidden: false, value: "", checked: false,
        open: false, returnValue: "", onclose: null,
        children: [], listeners: {}, attributes: {}, classList: {
            toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
            contains(name) { return classes.has(name); }
        },
        append(...children) {
            children.forEach(child => {
                if (child.parentNode) child.parentNode.children = child.parentNode.children.filter(item => item !== child);
                child.parentNode = this;
                this.children.push(child);
            });
        },
        replaceChildren(...children) { this.children = children; },
        setAttribute(key, value) { this.attributes[key] = value; },
        getAttribute(key) { return this.attributes[key]; },
        addEventListener(type, listener) { this.listeners[type] = listener; },
        trigger(type) { return this.listeners[type].call(this, {preventDefault() {}}); },
        scrollIntoView() {}, focus() { this.focused = true; activeElement = this; },
        showModal() { assert.equal(this.open, false); this.open = true; },
        close(value = "") { this.returnValue = value; this.open = false; if (this.onclose) this.onclose(); }
    };
}
const elements = new Map(Array.from(template.matchAll(/\bid="([^"]+)"/g), match => [match[1], element()]));
const $ = id => {
    assert.ok(elements.has(id), "The management template must contain " + id);
    return elements.get(id);
};
$("csrf-token").content = "schedules-csrf-token";
const englishLabels = {
    alarm: "Alarm",
    weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    today: "Today", tomorrow: "Tomorrow", this_week: "This {weekday}", next_week: "Next {weekday}", next_ring: "Next ring: {datetime}",
    calendar_event_summary: "{sources} · {minutes} min before events", calendar_day_summary: "{sources} · Days with events", calendar_missing: "Removed source ({id})",
    calendar_target_summary: "{title} · {scope}",
    skipped: "Skipped {datetime}", coverage: "{start} to {end}", delete_confirm: "Delete {name}?",
    current_datetime: "Now: {datetime}", ring_in: "In {duration}", saved_next: "Saved · in {duration}",
    duration_days: "{count} d", duration_hours: "{count} hr", duration_minutes: "{count} min", under_minute: "Under 1 min",
    weekly_summary: "Weekly {days}", pause_title: "Disable {name}?", pause_skip: "Skip {datetime}",
    resume_at: "Resumes {datetime} (in {duration})", resume_saved: "Skipped once · Resumes {datetime} (in {duration})",
    admin_name: "Administrator name", save_name: "Save name", reported_name: "Device-reported name", device_type: "Device type",
    registered_at: "Registered", capabilities: "Capabilities", capabilities_reported_at: "Capabilities reported",
    capability_display: "Display", capability_audio: "Audio", capability_notifications: "Notifications", capability_background: "Background", capability_calendar: "Calendar",
    yes: "Supported", no: "Not supported", sync_status: "Sync confirmation", sync_idle: "Not requested", sync_pending: "Awaiting confirmation",
    sync_confirmed: "Confirmed", sync_timed_out: "Timed out", sync_requested_at: "Requested", sync_acknowledged_at: "Confirmed at",
    device_data_stale: "Device data stale"
};
$("schedule-i18n").textContent = JSON.stringify({
    en: englishLabels,
    'zh-TW': {...englishLabels, alarm: "鬧鐘", edit_alarm: "編輯鬧鐘", admin_name: "管理者名稱", device_data_stale: "裝置資料未更新", weekdays: ["一", "二", "三", "四", "五", "六", "日"]},
    ja: {...englishLabels, alarm: "アラーム", edit_alarm: "アラームを編集", admin_name: "管理者名", device_data_stale: "端末データを更新できませんでした", weekdays: ["月", "火", "水", "木", "金", "土", "日"]}
});
$("editor").hidden = true;
const weekdays = Array.from({length: 7}, (_, i) => Object.assign(element("input"), {value: String(i + 1)}));
$("alarms-panel").setAttribute("data-management-panel", "alarms");
$("devices-panel").setAttribute("data-management-panel", "devices");
const saveButton = element("button");
$("schedule-form").querySelector = selector => {
    assert.equal(selector, '[type="submit"]');
    return saveButton;
};
$("schedule-form").reset = () => {
    ["id", "name", "dates"].forEach(key => $("schedule-" + key).value = "");
    $("schedule-type").value = "alarm";
    // The time helper makes this canonical field hidden; native reset keeps its current value.
    $("schedule-rule").value = "every_day";
    $("schedule-sound").value = "bell";
    $("schedule-skip-holidays").checked = false;
    $("schedule-enabled").checked = true;
    weekdays.forEach(input => input.checked = false);
};
const pending = [], requests = [], intervals = [], navigation = {}, inputRefreshes = [];
const timeouts = new Map();
let monotonicTime = 0, timeoutId = 0;
const body = element("body");
body.setAttribute("data-initial-panel", "alarms");
body.setAttribute("data-time-format", "24h");
class WrongDeviceDate extends Date {
    constructor(...args) { super(...(args.length ? args : ['2040-01-01T00:00:00Z'])); }
    static now() { return Date.parse('2040-01-01T00:00:00Z'); }
}
const context = vm.createContext({
    console, Date: WrongDeviceDate, Set, Map, Number, JSON, Object, Array, Promise,
    performance: {now: () => monotonicTime},
    document: {
        documentElement: {lang: "en"}, body,
        get activeElement() { return activeElement; },
        getElementById: id => elements.get(id) || null, createElement: element, addEventListener() {},
        querySelectorAll(selector) {
            if (selector === '[data-management-panel]') return [$("alarms-panel"), $("devices-panel")];
            if (selector === '[data-management-link]' || selector.startsWith('[data-schedule-')) return [];
            if (selector === '[name="calendar-source"]:checked') return descendants($("schedule-calendar-sources")).filter(input => input.name === "calendar-source" && input.checked);
            assert.ok(['[name="weekday"]', '[name="weekday"]:checked'].includes(selector));
            return selector.endsWith(":checked") ? weekdays.filter(input => input.checked) : weekdays;
        }
    },
    window: {confirm: () => true, location: {hash: ""}, scrollTo() {},
        WebClockTimeInputs: {refresh(root, format, language) {
            assert.equal(root, $("schedule-form"));
            inputRefreshes.push({format, language, required: $("schedule-time").required, disabled: $("schedule-time").disabled});
        }},
        addEventListener(type, handler) { navigation[type] = handler; }},
    fetch(url, options) {
        return new Promise(resolve => {
            const request = {url, options, resolve};
            requests.push(request);
            pending.push(request);
        });
    },
    setInterval(callback, delay) { intervals.push({callback, delay}); },
    setTimeout(callback, delay) { const id = ++timeoutId; timeouts.set(id, {callback, delay}); return id; },
    clearTimeout(id) { timeouts.delete(id); }
});
const probe = `globalThis.qa = {api, edit, loadSchedules, loadDevices, scheduleData, remainingTime, queuePreview, syncServerTime, get: () => schedules};`;
const instrumented = source.replace("    refresh();\n    setInterval", "    " + probe + "\n    refresh();\n    setInterval");
assert.notEqual(instrumented, source, "Management state probe must attach");
// Audio support is optional: initialization, forms and commands must work without it.
vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/time-format.js"), "utf8"), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/management.js"), "utf8"), context);
vm.runInContext(instrumented, context);
function showPanel(name) {
    context.window.location.hash = "#" + name;
    navigation.hashchange();
}
const qa = context.qa;
function take(url, method = "GET") {
    assert.ok(pending.length, "Expected " + method + " " + url);
    const request = pending.shift();
    assert.equal(request.url, "/api/v1" + url);
    assert.equal(request.options.method || "GET", method);
    assert.equal((request.options.headers || {})["X-CSRF-Token"], method === "GET" ? undefined : "schedules-csrf-token");
    if (request.options.body) assert.equal(request.options.headers["Content-Type"], "application/json");
    return request;
}
function reply(request, data, ok = true) {
    request.resolve({ok, json: async () => data});
}
function runPreview() {
    assert.equal(timeouts.size, 1, "Draft changes must leave only one debounced preview");
    const [id, timer] = Array.from(timeouts)[0];
    timeouts.delete(id);
    assert.equal(timer.delay, 200);
    return timer.callback();
}
const catalog = [{id: 'local', name: 'Local', provider: 'local'}, {id: 'work', name: 'Work calendar', provider: 'apple'}];
function scheduleReply(request, schedules, serverTime = '2026-09-30T10:00:00+08:00', calendarSources = catalog, timeFormat = "24h") {
    reply(request, {schedules, calendar_sources: calendarSources, time_format: timeFormat, server_time: serverTime, day: {date: "2026-09-30", type: "workday"}, holiday_coverage: {start: "2023-01-01", end: "2027-12-31"}});
}
function pauseReply(request, skipped = row.next_occurrence, next = nextDate) {
    reply(request, {skipped_occurrence: skipped, next_occurrence: next, server_time: "2026-09-30T10:00:00+08:00"});
}
function descendants(root) { return root.children.flatMap(child => [child, ...descendants(child)]); }
function calendarInput(id) { return descendants($("schedule-calendar-sources")).find(input => input.name === 'calendar-source' && input.value === id); }
function deviceNameInput(id) { return descendants($("device-list")).find(input => input.tag === "input" && input.getAttribute("data-device-name") === id); }
function button(list, label) {
    const result = descendants($(list)).find(child => child.tag === "button" && child.textContent === label);
    assert.ok(result, "Expected button " + label);
    return result;
}
const content = root => [root.textContent, ...root.children.map(content)].join(" ");
const completionTimeout = setTimeout(() => {
    throw new Error("Unfinished mocked requests: " + pending.map(request => request.url).join(", "));
}, 5000);

(async () => {
    scheduleReply(take("/schedules"), [row, {...row, id: "notice", name: "Device reminder", type: "reminder", next_occurrence: "2026-09-30T12:00:00+08:00"}]);
    reply(take("/devices"), {devices: [{id: "desk", online: true, last_seen: "2026-09-30T10:00:00+08:00"}]});
    await flush();
    assert.deepEqual(intervals.map(item => item.delay), [15000, 1000], "Poll server data and update the editor clock independently");
    assert.equal(timeouts.size, 0, "The closed editor must not request previews");
    assert.match($("day-status").textContent, /2026-09-30.*workday/);
    assert.match($("next-event").textContent, /Morning/);
    assert.doesNotMatch(content($("schedule-list")), /Device reminder/);
    assert.match(content($("other-schedule-list")), /Device reminder/);
    assert.doesNotMatch(content($("other-schedule-list")), /Morning/);
    assert.match(content($("device-list")), /config_revision.*unknown.*schedule_revision.*unknown.*holiday_revision.*unknown/);
    assert.equal(descendants($("device-list")).filter(item => item.tag === "button").length, 2);
    assert.equal(button("schedule-list", "disable").attributes.role, "switch");
    assert.equal(button("schedule-list", "disable").attributes["aria-checked"], "true");
    assert.equal($("next-event").textContent, "Tomorrow 07:30 · Morning");
    assert.match(content($("schedule-list")), /Next ring: Tomorrow 07:30/);

    qa.edit({...row, rule: {weekdays: [1, 2, 3, 4, 5, 6, 7]}, browser_volume: 0});
    assert.equal($("select-every-day").hidden, true, "Existing seven-day rules also hide the shortcut");
    assert.equal($("schedule-volume").value, "0", "Saved mute must not fall back to maximum volume");
    await $("add-schedule").trigger("click");
    assert.equal($("schedule-rule").value, "once");
    assert.equal($("schedule-volume").value, "100");
    assert.equal($("schedule-volume-value").textContent, "100%");
    assert.equal($("select-every-day").hidden, false);
    assert.equal($("schedule-name").value, "");
    assert.equal($("weekday-field").hidden, false, "Weekdays are visible before choosing a repeat rule");
    assert.equal($("schedule-date-picker").disabled, false, "The date picker is immediately usable");
    assert.match($("editor-now").textContent, /2026.*10:00/);
    assert.equal(qa.scheduleData().name, "Alarm", "A blank name uses the selected language's type label");
    for (const [serverTime, time, date] of [
        ["2026-09-30T22:00:00Z", "07:30", "2026-10-01"],
        ["2026-10-01T07:30:00+08:00", "07:30", "2026-10-01"],
        ["2026-10-01T07:30:01+08:00", "07:30", "2026-10-02"],
        ["2026-12-31T23:59:59+08:00", "00:00", "2027-01-01"],
    ]) {
        qa.syncServerTime(serverTime);
        $("schedule-time").value = time;
        assert.deepEqual(plain(qa.scheduleData().rule), {dates: [date]}, "Time-only alarms use the next Taipei occurrence");
    }
    qa.syncServerTime("2026-10-01T07:29:59+08:00");
    $("schedule-time").value = "07:30";
    monotonicTime += 2000;
    assert.deepEqual(plain(qa.scheduleData().rule), {dates: ["2026-10-02"]}, "Elapsed monotonic time advances the server clock despite an incorrect device clock");
    qa.syncServerTime(null);
    assert.throws(() => qa.scheduleData(), /preview_failed/, "Missing server time cannot silently use the device date");
    qa.syncServerTime("2026-09-30T10:00:00+08:00");
    assert.equal(qa.remainingTime("2026-10-01T12:03:00+08:00"), "1 d 2 hr 3 min");
    assert.equal(qa.remainingTime("2026-09-30T10:00:30+08:00"), "Under 1 min");
    weekdays[0].checked = true;
    await weekdays[0].trigger("change");
    assert.deepEqual(plain(qa.scheduleData().rule), {weekdays: [1]});
    weekdays[4].checked = true;
    await weekdays[4].trigger("change");
    assert.match($("schedule-repeat-summary").textContent, /Weekly Mon \/ Fri/);
    $("schedule-date-picker").value = "2026-10-10";
    await $("schedule-date-picker").trigger("change");
    assert.deepEqual(plain(qa.scheduleData().rule), {dates: ["2026-10-10"]});
    assert.ok(weekdays.every(input => !input.checked), "Choosing a date clears weekly repetition");
    weekdays[2].checked = true;
    await weekdays[2].trigger("change");
    assert.equal($("schedule-date-picker").value, "");
    assert.equal($("schedule-dates").value, "");
    weekdays[2].checked = false;
    await weekdays[2].trigger("change");
    assert.equal($("schedule-rule").value, "once", "Clearing every weekday restores a one-time alarm");

    $("schedule-date-picker").value = "2026-10-10";
    await $("schedule-date-picker").trigger("change");
    await $("select-every-day").trigger("click");
    assert.ok(weekdays.every(input => input.checked));
    assert.equal($("select-every-day").hidden, true);
    assert.equal($("schedule-date-picker").value, "");
    assert.equal($("schedule-dates").value, "");
    assert.deepEqual(plain(qa.scheduleData().rule), {});
    assert.equal($("schedule-repeat-summary").textContent, "every_day");
    assert.equal(weekdays[0].focused, true, "Focus leaves the hidden daily button");
    const dailyPreview = runPreview();
    assert.deepEqual(JSON.parse(pending[0].options.body).rule, {}, "Daily click queues a preview without a form change event");
    reply(take("/schedules/preview", "POST"), {next_occurrence: nextDate, server_time: "2026-09-30T10:00:00+08:00"});
    await dailyPreview;
    weekdays[6].checked = false;
    await weekdays[6].trigger("change");
    assert.equal($("select-every-day").hidden, false);
    assert.deepEqual(plain(qa.scheduleData().rule), {weekdays: [1, 2, 3, 4, 5, 6]});
    weekdays[6].checked = true;
    await weekdays[6].trigger("change");
    assert.equal($("select-every-day").hidden, true, "Manually selecting all days also hides the shortcut");
    $("schedule-special-rule").value = "workday_only";
    await $("schedule-special-rule").trigger("change");
    assert.deepEqual(plain(qa.scheduleData().rule), {workday_only: true});
    assert.equal($("select-every-day").hidden, false);
    await $("select-every-day").trigger("click");
    assert.equal($("schedule-special-rule").value, "");
    weekdays.forEach(input => input.checked = false);
    await weekdays[0].trigger("change");

    await $("schedule-form").trigger("change");
    const olderPreview = runPreview(), olderPreviewRequest = take("/schedules/preview", "POST");
    assert.deepEqual(JSON.parse(olderPreviewRequest.options.body).rule, {dates: ["2026-10-01"]});
    $("schedule-time").value = "08:00";
    await $("schedule-form").trigger("input");
    await $("schedule-form").trigger("change");
    const newerPreview = runPreview(), newerPreviewRequest = take("/schedules/preview", "POST");
    reply(newerPreviewRequest, {next_occurrence: "2026-10-01T08:00:00+08:00", server_time: "2026-09-30T10:00:00+08:00"});
    await newerPreview;
    assert.equal($("editor-next").textContent, "Next ring: Tomorrow 08:00");
    assert.equal($("editor-countdown").textContent, "In 22 hr");
    $("schedule-time").value = "09:00";
    await $("schedule-form").trigger("input");
    assert.equal($("editor-next").textContent, "Next ring: Tomorrow 08:00", "Keep the last result while computing a changed time");
    assert.equal($("editor-countdown").textContent, "In 22 hr");
    intervals.find(item => item.delay === 1000).callback();
    assert.equal($("editor-countdown").textContent, "In 22 hr", "The clock tick must not clear a pending preview");
    $("schedule-time").value = "08:00";
    await $("schedule-form").trigger("change");
    const quietPreview = runPreview();
    reply(take("/schedules/preview", "POST"), {next_occurrence: "2026-10-01T08:00:00+08:00", server_time: "2026-09-30T10:00:00+08:00"});
    await quietPreview;
    let liveRegionWrites = 0;
    for (const id of ["editor-next", "editor-countdown"]) {
        let value = $(id).textContent;
        Object.defineProperty($(id), "textContent", {
            get: () => value, set: next => { value = next; ++liveRegionWrites; }
        });
    }
    intervals.find(item => item.delay === 1000).callback();
    assert.equal(liveRegionWrites, 0, "An unchanged countdown must not retrigger live-region announcements every second");
    reply(olderPreviewRequest, {next_occurrence: "2040-01-01T07:30:00+08:00", server_time: "2040-01-01T00:00:00+08:00"});
    await olderPreview;
    assert.equal($("editor-next").textContent, "Next ring: Tomorrow 08:00", "An old preview cannot replace a newer draft or server clock");
    monotonicTime += 60000;
    intervals.find(item => item.delay === 1000).callback();
    assert.match($("editor-now").textContent, /10:01/);
    assert.equal($("editor-countdown").textContent, "In 21 hr 59 min");
    qa.syncServerTime("2026-09-30T23:59:59+08:00");
    monotonicTime += 2000;
    intervals.find(item => item.delay === 1000).callback();
    assert.equal($("editor-next").textContent, "Next ring: Today 08:00", "Relative labels advance across Taipei midnight between server polls");
    qa.syncServerTime("2026-10-01T07:59:59+08:00");
    monotonicTime += 2000;
    intervals.find(item => item.delay === 1000).callback();
    const elapsedPreview = runPreview(), elapsedRequest = take("/schedules/preview", "POST");
    assert.deepEqual(JSON.parse(elapsedRequest.options.body).rule, {dates: ["2026-10-02"]}, "An elapsed time-only preview recalculates the next one-time date");
    reply(elapsedRequest, {next_occurrence: "2026-10-02T08:00:00+08:00", server_time: "2026-10-01T08:00:01+08:00"});
    await elapsedPreview;
    qa.queuePreview();
    const closedPreview = runPreview(), closedPreviewRequest = take("/schedules/preview", "POST");
    await $("cancel-edit").trigger("click");
    const closedText = $("editor-next").textContent;
    reply(closedPreviewRequest, {next_occurrence: "2040-01-01T07:30:00+08:00", server_time: "2040-01-01T00:00:00+08:00"});
    await closedPreview;
    assert.equal($("editor-next").textContent, closedText, "A response received after closing the editor must be ignored");
    assert.equal(timeouts.size, 0);

    for (const [serverTime, target, expected] of [
        ['2026-09-30T10:00:00+08:00', '2026-09-30T22:00:00+08:00', 'Today 22:00'],
        ['2026-09-30T10:00:00+08:00', '2026-10-01T07:30:00+08:00', 'Tomorrow 07:30'],
        ['2026-09-30T10:00:00+08:00', '2026-10-02T07:30:00+08:00', 'This Fri 07:30'],
        ['2026-09-30T10:00:00+08:00', '2026-10-04T07:30:00+08:00', 'This Sun 07:30'],
        ['2026-09-30T10:00:00+08:00', '2026-10-06T07:30:00+08:00', 'Next Tue 07:30'],
        ['2026-09-30T10:00:00+08:00', '2026-10-11T07:30:00+08:00', 'Next Sun 07:30'],
        ['2026-09-30T10:00:00+08:00', '2026-10-12T07:30:00+08:00', '10/12 07:30'],
        ['2026-10-04T10:00:00+08:00', '2026-10-05T07:30:00+08:00', 'Tomorrow 07:30'],
        ['2026-10-04T10:00:00+08:00', '2026-10-06T07:30:00+08:00', 'Next Tue 07:30'],
        ['2026-09-30T17:00:00Z', '2026-10-01T02:00:00Z', 'Today 10:00'],
        ['2026-12-31T23:59:00+08:00', '2027-01-01T07:30:00+08:00', 'Tomorrow 07:30'],
        ['2026-12-31T23:59:00+08:00', '2027-01-11T07:30:00+08:00', '2027/1/11 07:30'],
        [null, '2026-10-01T07:30:00+08:00', '2026/10/1 07:30'],
    ]) {
        const request = qa.loadSchedules();
        scheduleReply(take('/schedules'), [{...row, next_occurrence: target}], serverTime);
        await request;
        assert.equal($("next-event").textContent, expected + ' · Morning');
        assert.ok(content($("schedule-list")).includes('Next ring: ' + expected));
    }
    await button("schedule-list", "edit").trigger("click");
    $("schedule-name").value = "Unsaved time draft";
    $("schedule-time").value = "13:45";
    const beforeFormatChange = inputRefreshes.length;
    for (const [time, expected] of [["00:00", "12:00 AM"], ["12:00", "12:00 PM"], ["13:45", "01:45 PM"]]) {
        const request = qa.loadSchedules();
        scheduleReply(take("/schedules"), [{...row, time, next_occurrence: "2026-10-01T" + time + ":00+08:00"}], '2026-09-30T10:00:00+08:00', catalog, "12h");
        await request;
        assert.equal($("next-event").textContent, "Tomorrow " + expected + " · Morning");
        const displayedTime = $("schedule-list").children[0].children[0];
        assert.equal(displayedTime.attributes["aria-label"], expected);
        assert.deepEqual(displayedTime.children.map(part => part.textContent), expected.split(" "));
        assert.equal(displayedTime.children[1].className, "schedule-time-period", "English places the small AM / PM after the time");
        assert.equal($("schedule-name").value, "Unsaved time draft", "Changing the clock format preserves editor text");
        assert.equal($("schedule-time").value, "13:45", "Changing the clock format preserves canonical time");
    }
    assert.equal(body.getAttribute("data-time-format"), "12h");
    assert.equal(inputRefreshes.length, beforeFormatChange + 1, "Unchanged format polls preserve incomplete input drafts");
    assert.match(content($("device-list")), /10:00 AM/, "Format changes redraw previously fetched device timestamps");
    context.document.documentElement.lang = "zh-TW";
    const chinese = qa.loadSchedules();
    scheduleReply(take("/schedules"), [{...row, time: "12:00", next_occurrence: "2026-10-01T00:00:00+08:00"}], '2026-09-30T10:00:00+08:00', catalog, "12h");
    await chinese;
    assert.equal($("next-event").textContent, "Tomorrow 上午 12:00 · Morning");
    assert.equal($("schedule-list").children[0].children[0].attributes["aria-label"], "下午 12:00");
    assert.equal($("schedule-list").children[0].children[0].children[0].className, "schedule-time-period", "Chinese places the small period before the time");
    context.document.documentElement.lang = "en";
    const restored = qa.loadSchedules();
    scheduleReply(take('/schedules'), [row]);
    await restored;
    assert.equal(body.getAttribute("data-time-format"), "24h");
    assert.doesNotMatch(content($("device-list")), /10:00 AM/);

    const cancellingPause = button("schedule-list", "disable").trigger("click");
    const cancelledPauseRequest = take("/schedules/preview", "POST");
    assert.deepEqual(JSON.parse(cancelledPauseRequest.options.body), {id: row.id, enabled: true, skip_next: true});
    assert.equal($("pause-dialog").open, true);
    assert.equal($("pause-title").textContent, "Disable Morning?");
    assert.equal($("pause-once").disabled, true, "Wait for the server before offering to resume next cycle");
    $("pause-dialog").close();
    await cancellingPause;
    assert.equal(pending.length, 0, "Cancelling must not write schedule changes");
    const cancelledPauseText = $("pause-resume").textContent;
    pauseReply(cancelledPauseRequest);
    await flush();
    assert.equal($("pause-resume").textContent, cancelledPauseText, "A late preview cannot update a closed dialog");
    assert.equal($("pause-once").disabled, true);
    assert.equal(qa.get()[0].enabled, true);

    const unavailablePause = button("schedule-list", "disable").trigger("click");
    pauseReply(take("/schedules/preview", "POST"), row.next_occurrence, null);
    await flush();
    assert.equal($("pause-once").disabled, true, "Do not promise a resume when no following occurrence exists");
    assert.equal($("pause-resume").textContent, "resume_unavailable");
    $("pause-dialog").close();
    await unavailablePause;

    const failedPause = button("schedule-list", "disable").trigger("click");
    reply(take("/schedules/preview", "POST"), {error: "unavailable"}, false);
    await flush();
    assert.equal($("pause-once").disabled, true);
    assert.equal($("pause-resume").textContent, "pause_preview_failed");
    $("pause-dialog").close();
    await failedPause;

    const pausingOnce = button("schedule-list", "disable").trigger("click");
    pauseReply(take("/schedules/preview", "POST"));
    await flush();
    assert.equal($("pause-once").disabled, false);
    assert.match($("pause-skipped").textContent, /Skip .*07:30/);
    assert.match($("pause-resume").textContent, /Resumes .*07:30 \(in 21 hr 30 min\)/);
    $("pause-dialog").close("skip");
    await flush();
    const pauseOnceRequest = take("/schedules/alarm/skip-next", "POST");
    assert.deepEqual(JSON.parse(pauseOnceRequest.options.body), {expected_occurrence: row.next_occurrence}, "Skip exactly the occurrence shown in the dialog");
    reply(pauseOnceRequest, {skipped: {datetime: row.next_occurrence}, next_event: {datetime: nextDate}});
    await flush();
    assert.equal(qa.get()[0].enabled, true, "Keep recurrence scheduled while the UI shows a temporary pause");
    assert.equal(button("schedule-list", "enable").attributes["aria-checked"], "false");
    assert.match($("schedule-list").children[0].className, /disabled/);
    assert.equal(qa.get()[0].next_occurrence, nextDate);
    assert.match($("status").textContent, /Skipped once · Resumes .*07:30 \(in 21 hr 30 min\)/);
    scheduleReply(take("/schedules"), [{...row, next_occurrence: nextDate, skipped_occurrences: [row.next_occurrence]}]);
    await pausingOnce;
    assert.equal(button("schedule-list", "enable").attributes["aria-checked"], "false", "Refresh preserves the temporary off state");
    await button("schedule-list", "edit").trigger("click");
    assert.equal($("schedule-enabled").checked, false, "The editor also displays temporary off");
    assert.equal(button("editor-actions", "skip_next").disabled, true, "Cannot stack another skipped date while waiting");
    await button("editor-actions", "skip_next").trigger("click");
    assert.equal($("form-error").textContent, "pause_pending");
    assert.equal(pending.length, 0, "Even a repeated handler call cannot queue another skip");
    $("schedule-name").value = "Renamed while paused";
    const pausedEdit = qa.scheduleData();
    assert.equal(pausedEdit.enabled, true, "Saving an unrelated field must preserve automatic resume");
    assert.equal(pausedEdit.skipped_occurrences, undefined, "Saving must preserve the original skipped date");
    $("schedule-enabled").checked = true;
    assert.deepEqual(plain(qa.scheduleData().skipped_occurrences), [], "Explicitly enabling cancels the pending skip");
    $("schedule-enabled").checked = false;
    const pausedPreview = runPreview();
    reply(take("/schedules/preview", "POST"), {next_occurrence: nextDate, server_time: "2026-09-30T10:00:00+08:00"});
    await pausedPreview;
    qa.syncServerTime(row.next_occurrence);
    intervals.find(item => item.delay === 1000).callback();
    assert.equal(button("schedule-list", "enable").attributes["aria-checked"], "false", "Stay paused through the original timestamp");
    monotonicTime += 1000;
    intervals.find(item => item.delay === 1000).callback();
    assert.equal(button("schedule-list", "disable").attributes["aria-checked"], "true", "Resume after the original skipped time, without waiting for the next ring or server polling");
    assert.equal($("schedule-enabled").checked, true);
    assert.equal(button("editor-actions", "skip_next").disabled, false);
    assert.equal($("schedule-name").value, "Renamed while paused", "The automatic transition preserves the draft");
    assert.deepEqual(plain(qa.get()[0].skipped_occurrences), [row.next_occurrence], "Retain the skip so this minute cannot ring late");
    await $("cancel-edit").trigger("click");

    const reloadPause = qa.loadSchedules();
    scheduleReply(take("/schedules"), [{...row, next_occurrence: nextDate, skipped_occurrences: [row.next_occurrence]}]);
    await reloadPause;
    const enablePaused = button("schedule-list", "enable").trigger("click");
    const resumeRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(resumeRequest.options.body), {enabled: true, skipped_occurrences: []}, "Manually enabling cancels the pause instead of opening another skip dialog");
    reply(resumeRequest, row);
    await flush();
    scheduleReply(take("/schedules"), [row]);
    await enablePaused;
    assert.equal(button("schedule-list", "disable").attributes["aria-checked"], "true");
    const restorePause = qa.loadSchedules();
    scheduleReply(take("/schedules"), [row]);
    await restorePause;

    const oldPoll = qa.loadSchedules();
    const oldResponse = take("/schedules");
    const disabling = button("schedule-list", "disable").trigger("click");
    pauseReply(take("/schedules/preview", "POST"));
    await flush();
    $("pause-dialog").close("disable");
    await flush();
    const disableRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(disableRequest.options.body), {enabled: false}, "Toggle must not overwrite other edits with stale schedule data");
    const disabled = {...row, name: "Updated elsewhere", enabled: false, next_occurrence: null};
    reply(disableRequest, disabled);
    await flush();
    assert.equal(qa.get().find(item => item.id === row.id).enabled, false, "Confirmed mutation must render before the follow-up GET");
    assert.equal($("next-event").textContent, "none");
    scheduleReply(take("/schedules"), [disabled]);
    await disabling;
    scheduleReply(oldResponse, [row]);
    await oldPoll;
    assert.deepEqual(plain(qa.get()), [disabled], "A stale GET must not undo the confirmed mutation");
    assert.equal(button("schedule-list", "enable").attributes["aria-checked"], "false");
    await button("schedule-list", "edit").trigger("click");
    assert.equal(button("editor-actions", "skip_next").disabled, true);
    const disabledPreview = runPreview();
    reply(take("/schedules/preview", "POST"), {next_occurrence: null, server_time: "2026-09-30T10:00:00+08:00"});
    await disabledPreview;
    $("schedule-enabled").checked = true;
    $("schedule-time").value = "08:15";
    await $("schedule-form").trigger("change");
    assert.equal($("editor-next").textContent, "disabled", "Do not replace the last result with a loading message");
    assert.equal(button("editor-actions", "skip_next").disabled, true, "Wait for the enabled draft's preview, not the stored disabled row");
    const enabledPreview = runPreview(), enabledRequest = take("/schedules/preview", "POST");
    assert.equal(JSON.parse(enabledRequest.options.body).enabled, true);
    const enabledOccurrence = "2026-10-01T08:15:00+08:00";
    reply(enabledRequest, {next_occurrence: enabledOccurrence, server_time: "2026-09-30T10:00:00+08:00"});
    await enabledPreview;
    assert.equal(button("editor-actions", "skip_next").disabled, false, "Enabling in the editor makes skip available without saving first");
    $("schedule-time").value = "";
    await $("schedule-form").trigger("input");
    assert.equal(button("editor-actions", "skip_next").disabled, true, "An invalid draft cannot skip the old occurrence");
    $("schedule-time").value = "08:15";
    await $("schedule-form").trigger("change");
    const correctedPreview = runPreview();
    reply(take("/schedules/preview", "POST"), {next_occurrence: enabledOccurrence, server_time: "2026-09-30T10:00:00+08:00"});
    await correctedPreview;
    const readySkip = button("editor-actions", "skip_next");
    await $("schedule-form").trigger("change");
    assert.equal(button("editor-actions", "skip_next"), readySkip, "A same-value blur/change must not replace the button under the pointer");
    assert.equal(readySkip.disabled, false);
    assert.equal(timeouts.size, 0, "Do not recalculate an identical draft just before its action is clicked");
    const draftSkipping = button("editor-actions", "skip_next").trigger("click");
    const draftSkipRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(draftSkipRequest.options.body), {
        rule: {}, enabled: true, skip_holidays: false, name: disabled.name, type: "alarm", time: "08:15", browser_sound: "bell", browser_volume: 100, skip_next: enabledOccurrence
    }, "Skip atomically saves the currently enabled draft and its new time");
    assert.equal(button("editor-actions", "skip_next").disabled, true, "Do not submit another skip while saving");
    const draftSkipped = {...disabled, ...JSON.parse(draftSkipRequest.options.body), skipped_occurrences: [enabledOccurrence]};
    delete draftSkipped.skip_next;
    delete draftSkipped.next_occurrence;
    reply(draftSkipRequest, draftSkipped);
    await flush();
    scheduleReply(take("/schedules"), [{...draftSkipped, next_occurrence: "2026-10-02T08:15:00+08:00"}]);
    await draftSkipping;
    assert.equal($("editor").hidden, false, "Skipping retains the open editor");
    assert.equal($("schedule-enabled").checked, false);
    assert.equal(button("editor-actions", "skip_next").disabled, true);
    $("schedule-enabled").checked = true;
    await $("schedule-form").trigger("change");
    const unpausedPreview = runPreview(), unpausedRequest = take("/schedules/preview", "POST");
    assert.deepEqual(JSON.parse(unpausedRequest.options.body).skipped_occurrences, [], "Manually enabling clears the pending skip in the draft preview");
    reply(unpausedRequest, {next_occurrence: enabledOccurrence, server_time: "2026-09-30T10:00:00+08:00"});
    await unpausedPreview;
    assert.equal(button("editor-actions", "skip_next").disabled, false, "Eligibility follows cleared draft skips, not the persisted pause");
    const reskipping = button("editor-actions", "skip_next").trigger("click");
    const reskipRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(reskipRequest.options.body).skipped_occurrences, []);
    assert.equal(JSON.parse(reskipRequest.options.body).skip_next, enabledOccurrence, "Re-enabling and skipping targets the original occurrence, not a later date");
    reply(reskipRequest, draftSkipped);
    await flush();
    scheduleReply(take("/schedules"), [{...draftSkipped, next_occurrence: "2026-10-02T08:15:00+08:00"}]);
    await reskipping;
    assert.equal($("schedule-enabled").checked, false, "Re-skipping the same occurrence must restore the temporary off display");
    assert.equal(button("editor-actions", "skip_next").disabled, true);
    assert.deepEqual(plain(qa.get()[0].skipped_occurrences), [enabledOccurrence]);

    const older = qa.loadSchedules(), olderRequest = take("/schedules");
    const newer = qa.loadSchedules(), newerRequest = take("/schedules");
    scheduleReply(newerRequest, [row]);
    await newer;
    scheduleReply(olderRequest, [disabled]);
    await older;
    assert.equal(qa.get()[0].name, "Morning", "Latest GET must win even if an earlier one arrives last");

    await button("schedule-list", "edit").trigger("click");
    $("schedule-name").value = "Pause draft";
    $("schedule-time").value = "08:15";
    $("schedule-enabled").checked = false;
    const cancelEditorPause = $("schedule-form").trigger("submit");
    const editorPausePreview = take("/schedules/preview", "POST");
    assert.deepEqual(JSON.parse(editorPausePreview.options.body), {
        id: row.id, rule: {}, enabled: true, skip_holidays: false, browser_sound: "bell", browser_volume: 100,
        name: "Pause draft", type: "alarm", time: "08:15", skip_next: true
    }, "Preview uses the edited draft while calculating its enabled recurrence");
    pauseReply(editorPausePreview, "2026-10-01T08:15:00+08:00", "2026-10-02T08:15:00+08:00");
    await flush();
    assert.equal($("pause-title").textContent, "Disable Pause draft?");
    $("pause-dialog").close();
    await cancelEditorPause;
    assert.equal(pending.length, 0);
    assert.equal($("editor").hidden, false);
    assert.equal($("schedule-name").value, "Pause draft");
    assert.equal($("schedule-time").value, "08:15");
    assert.equal($("schedule-enabled").checked, false, "Cancelling the choice preserves the whole draft");
    assert.equal(saveButton.disabled, false);

    const draftOccurrence = "2026-10-01T08:15:00+08:00", draftResume = "2026-10-02T08:15:00+08:00";
    const failedEditorPause = $("schedule-form").trigger("submit");
    pauseReply(take("/schedules/preview", "POST"), draftOccurrence, draftResume);
    await flush();
    $("pause-dialog").close("skip");
    await flush();
    const failedPauseSave = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(failedPauseSave.options.body), {
        rule: {}, enabled: true, skip_holidays: false, browser_sound: "bell", browser_volume: 100,
        name: "Pause draft", type: "alarm", time: "08:15", skip_next: draftOccurrence
    }, "Saving edits and skipping the previewed occurrence is one atomic update");
    reply(failedPauseSave, {error: "Occurrence changed; preview again"}, false);
    await failedEditorPause;
    assert.equal($("form-error").textContent, "pause_stale");
    assert.equal($("editor").hidden, false);
    assert.equal($("schedule-name").value, "Pause draft", "A failed pause save must not clear the draft");
    assert.equal($("schedule-time").value, "08:15");
    assert.equal($("schedule-enabled").checked, false);
    assert.equal(saveButton.disabled, false);
    assert.equal(qa.get()[0].name, "Morning");

    $("schedule-time").value = row.time;
    const savedEditorPause = $("schedule-form").trigger("submit");
    pauseReply(take("/schedules/preview", "POST"));
    await flush();
    $("pause-dialog").close("skip");
    await flush();
    const pauseSave = take("/schedules/alarm", "PUT");
    const pausedDraft = {...row, ...JSON.parse(pauseSave.options.body), skipped_occurrences: [row.next_occurrence]};
    delete pausedDraft.next_occurrence;
    delete pausedDraft.skip_next;
    reply(pauseSave, pausedDraft);
    await flush();
    assert.equal(qa.get()[0].next_occurrence, null, "Skipping invalidates the old occurrence even when time and repeat rules are unchanged");
    scheduleReply(take("/schedules"), [{...pausedDraft, next_occurrence: nextDate}]);
    await savedEditorPause;
    assert.equal($("editor").hidden, true);
    assert.equal(qa.get()[0].enabled, true);
    assert.equal(qa.get()[0].next_occurrence, nextDate);
    assert.match($("status").textContent, /Skipped once · Resumes .*07:30/);
    const restoreEditorPause = qa.loadSchedules();
    scheduleReply(take("/schedules"), [row]);
    await restoreEditorPause;

    await button("schedule-list", "edit").trigger("click");
    assert.equal($("editor").parentNode, $("alarms-panel"));
    assert.equal($("alarms-panel").classList.contains("is-editing"), true);
    $("schedule-name").value = "Unsaved draft";
    showPanel("devices");
    assert.equal($("alarms-panel").hidden, true);
    assert.equal($("devices-panel").hidden, false);
    showPanel("alarms");
    assert.equal($("schedule-name").value, "Unsaved draft", "Navigation keeps the editor DOM and draft");
    $("schedule-name").value = row.name;
    assert.equal($("schedule-type-field").hidden, true);
    assert.equal($("schedule-sound-field").hidden, false);
    assert.equal($("schedule-sound").value, "bell", "Existing alarms default to bell");
    await $("preview-sound").trigger("click");
    assert.equal($("status").textContent, "audio_unavailable");
    const previewed = [];
    assert.equal($("select-every-day").hidden, true, "Existing daily alarms open with all weekdays selected");
    context.window.AlarmAudio = {unlock(sound, volume) { previewed.push({sound, volume}); return true; }};
    $("schedule-volume").value = "25";
    await $("schedule-volume").trigger("input");
    assert.equal($("schedule-volume-value").textContent, "25%");
    $("schedule-sound").value = "digital";
    await $("preview-sound").trigger("click");
    assert.deepEqual(previewed, [{sound: "digital", volume: 25}]);
    assert.equal($("status").textContent, "sound_previewed");
    $("schedule-sound").value = "silent";
    await $("preview-sound").trigger("click");
    assert.equal(previewed.length, 1, "Silent preview must not play a sound");
    $("schedule-sound").value = "digital";
    $("schedule-volume").value = "0";
    await $("preview-sound").trigger("click");
    assert.equal(previewed.length, 1, "Zero-volume preview stays silent");
    $("schedule-volume").value = "25";
    $("schedule-skip-holidays").checked = true;
    assert.equal($("schedule-id").value, row.id);
    assert.equal($("schedule-name").value, row.name);
    $("schedule-name").value = "Edited";
    const editing = $("schedule-form").trigger("submit");
    const editRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(editRequest.options.body), {rule: {}, enabled: true, skip_holidays: true, browser_sound: "digital", browser_volume: 25, name: "Edited", type: "alarm", time: "07:30"});
    const edited = {...row, name: "Edited", browser_sound: "digital", browser_volume: 25, skip_holidays: true};
    reply(editRequest, edited);
    await flush();
    scheduleReply(take("/schedules"), [edited]);
    await editing;
    assert.equal($("editor").hidden, true);
    assert.equal($("alarms-panel").classList.contains("is-editing"), false);
    assert.match(content($("schedule-list")), /skip_holidays.*sound_digital/);
    assert.match(content($("schedule-list")), /Next ring: Tomorrow 07:30/);
    await button("schedule-list", "edit").trigger("click");
    assert.equal($("schedule-sound").value, "digital");
    assert.equal($("schedule-volume").value, "25");
    assert.equal($("schedule-volume-value").textContent, "25%");
    assert.equal($("schedule-skip-holidays").checked, true);

    showPanel("devices");
    await $("add-other-schedule").trigger("click");
    assert.equal($("editor").parentNode, $("devices-panel"));
    assert.equal($("alarms-panel").classList.contains("is-editing"), false);
    assert.equal($("devices-panel").classList.contains("is-editing"), true);
    assert.equal($("schedule-type").value, "reminder");
    assert.equal($("schedule-type-field").hidden, false);
    assert.equal($("schedule-sound-field").hidden, true);
    assert.equal($("schedule-calendar-mode-field").hidden, true);
    $("schedule-name").value = "Weekly reminder";
    $("schedule-type").value = "reminder";
    weekdays.forEach(input => input.checked = false);
    $("schedule-rule").value = "weekdays";
    assert.equal($("weekday-field").hidden, false);
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "select_weekday");
    assert.equal(pending.length, 0);
    weekdays[0].checked = true;
    weekdays[4].checked = true;
    await weekdays[0].trigger("change");
    $("schedule-skip-holidays").checked = true;
    const creating = $("schedule-form").trigger("submit");
    const createRequest = take("/schedules", "POST");
    const created = {id: "weekly", ...JSON.parse(createRequest.options.body), skipped_occurrences: [], next_occurrence: nextDate};
    assert.deepEqual(JSON.parse(createRequest.options.body), {rule: {weekdays: [1, 5]}, enabled: true, skip_holidays: true, name: "Weekly reminder", type: "reminder", time: "07:30"});
    reply(createRequest, created);
    await flush();
    scheduleReply(take("/schedules"), [created]);
    await creating;
    assert.equal($("add-other-schedule").focused, true, "Saving device schedules returns focus to their add button");
    assert.equal($("status").textContent, "Saved · in 1 d 21 hr 30 min", "Save confirmation names compact duration units instead of using only colons");

    showPanel("alarms");
    $("schedule-time").value = "23:45";
    await $("add-schedule").trigger("click");
    assert.equal($("schedule-time").value, "07:30", "A new alarm must not inherit a cancelled canonical time");
    assert.equal($("schedule-sound").value, "bell");
    assert.equal($("schedule-volume").value, "100", "New alarms do not inherit another alarm's volume");
    assert.equal($("schedule-skip-holidays").checked, false);
    $("schedule-special-rule").value = "holiday_only";
    await $("schedule-special-rule").trigger("change");
    $("schedule-skip-holidays").checked = true;
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "holiday_conflict");
    assert.equal(pending.length, 0, "Contradictory holiday options must not send a request");
    assert.equal($("schedule-date-picker").disabled, false);
    $("schedule-date-picker").value = "2026-10-10";
    await $("schedule-date-picker").trigger("change");
    assert.deepEqual(plain(qa.scheduleData().rule), {dates: ["2026-10-10"]});
    assert.equal($("clear-schedule-date").hidden, false);
    assert.equal(pending.length, 0, "Picking a date only changes the draft");
    $("schedule-dates").value = "2026-10-03, 2026-10-10";
    await $("schedule-dates").trigger("input");
    assert.equal($("schedule-date-picker").value, "");
    assert.deepEqual(plain(qa.scheduleData().rule), {dates: ["2026-10-03", "2026-10-10"]}, "Advanced rules preserve existing multiple-date support");
    for (const invalid of ["", "2026-02-30", "not-a-date"]) {
        $("schedule-dates").value = invalid;
        await $("schedule-form").trigger("submit");
        assert.equal($("form-error").textContent, "select_date");
        assert.equal(pending.length, 0, "Invalid dates must not send a request");
        assert.equal($("schedule-dates").value, invalid, "Validation preserves the draft for correction");
    }
    await $("clear-schedule-date").trigger("click");
    assert.equal($("schedule-rule").value, "once");
    assert.equal($("schedule-dates").value, "");
    assert.equal($("schedule-date-picker").value, "");
    await $("cancel-edit").trigger("click");
    assert.equal($("alarms-panel").classList.contains("is-editing"), false);
    assert.equal($("add-schedule").focused, true);

    showPanel("devices");
    await button("other-schedule-list", "edit").trigger("click");
    const skipPreview = runPreview();
    reply(take("/schedules/preview", "POST"), {next_occurrence: created.next_occurrence, server_time: "2026-09-30T10:00:00+08:00"});
    await skipPreview;
    const skipping = button("editor-actions", "skip_next").trigger("click");
    const skipRequest = take("/schedules/weekly", "PUT");
    assert.equal(JSON.parse(skipRequest.options.body).skip_next, created.next_occurrence);
    const skipDate = "2026-10-06T07:30:00+08:00";
    const skipped = {...created, next_occurrence: skipDate, skipped_occurrences: [created.next_occurrence]};
    reply(skipRequest, skipped);
    await flush();
    assert.equal($("next-event").textContent, "none");
    assert.match(content($("other-schedule-list")), /Next Tue 07:30/);
    scheduleReply(take("/schedules"), [skipped]);
    await skipping;
    assert.match($("status").textContent, /Skipped/);

    const deleting = button("editor-actions", "delete").trigger("click");
    reply(take("/schedules/weekly", "DELETE"), {ok: true});
    await flush();
    assert.equal(qa.get().length, 0);
    scheduleReply(take("/schedules"), []);
    await deleting;
    assert.equal(content($("schedule-list")).trim(), "none");

    showPanel("alarms");
    await $("add-schedule").trigger("click");
    assert.equal($("schedule-date-picker").value, "", "Opening another editor clears the date picker");
    assert.equal($("schedule-date-picker").disabled, false, "The date picker remains available without opening advanced rules");
    $("schedule-name").value = "Linked alarm";
    $("schedule-calendar-mode").value = "event";
    await $("schedule-calendar-mode").trigger("change");
    assert.equal($("schedule-time-field").hidden, true);
    assert.equal($("schedule-event-time").hidden, false);
    assert.equal($("schedule-time").required, false);
    assert.equal($("schedule-time").disabled, true);
    assert.equal(inputRefreshes.at(-1).disabled, true, "Event mode also disables the visible time controls");
    assert.equal($("schedule-offset-field").hidden, false);
    assert.equal($("calendar-source-field").hidden, false);
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "select_calendar_source");
    assert.equal(pending.length, 0);
    calendarInput("local").checked = true;
    calendarInput("work").checked = true;
    $("schedule-offset").value = "-1";
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "calendar_offset_error");
    $("schedule-offset").value = "15";
    $("schedule-time").value = "";
    const linking = $("schedule-form").trigger("submit");
    const linkedRequest = take("/schedules", "POST");
    assert.equal(JSON.parse(linkedRequest.options.body).time, "07:30", "An event-relative alarm does not require an unused fixed time");
    const link = {mode: "event", source_ids: ["local", "work"], offset_minutes: 15};
    assert.deepEqual(JSON.parse(linkedRequest.options.body).calendar_link, link);
    const linked = {...row, name: "Linked alarm", calendar_link: link};
    reply(linkedRequest, linked);
    await flush();
    scheduleReply(take("/schedules"), [linked]);
    await linking;
    assert.match(content($("schedule-list")), /Work calendar.*15 min before events/);
    assert.match(content($("schedule-list")), /calendar_event_time/);
    await button("schedule-list", "edit").trigger("click");
    assert.equal(calendarInput("local").checked, true);
    assert.equal(calendarInput("work").checked, true);
    $("schedule-name").value = "Unsaved calendar draft";
    calendarInput("local").checked = false;
    const linkedPoll = qa.loadSchedules();
    scheduleReply(take("/schedules"), [linked]);
    await linkedPoll;
    assert.equal($("schedule-name").value, "Unsaved calendar draft");
    assert.equal(calendarInput("local").checked, false, "Polling preserves source selections in the draft");
    showPanel("devices"); showPanel("alarms");
    assert.equal(calendarInput("work").checked, true);
    $("schedule-calendar-mode").value = "day";
    await $("schedule-calendar-mode").trigger("change");
    assert.equal($("schedule-time-field").hidden, false);
    assert.equal($("schedule-time").disabled, false);
    assert.equal(inputRefreshes.at(-1).required, true);
    assert.equal($("schedule-offset-field").hidden, true);
    const changingDay = $("schedule-form").trigger("submit");
    const dayRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(dayRequest.options.body).calendar_link, {mode: "day", source_ids: ["work"], offset_minutes: 0});
    const dayLinked = {...linked, calendar_link: {mode: "day", source_ids: ["work"], offset_minutes: 0}};
    const withoutPreview = {...dayLinked}; delete withoutPreview.next_occurrence;
    reply(dayRequest, withoutPreview);
    await flush();
    assert.equal(qa.get()[0].next_occurrence, null, "Changing link semantics invalidates the previous next occurrence");
    scheduleReply(take("/schedules"), [dayLinked]);
    await changingDay;
    await button("schedule-list", "edit").trigger("click");
    const removedSourcePoll = qa.loadSchedules();
    scheduleReply(take("/schedules"), [dayLinked], '2026-09-30T10:00:00+08:00', [catalog[0]]);
    await removedSourcePoll;
    assert.equal(calendarInput("work").checked, true, "Removing a source does not silently erase an existing selection");
    assert.match(content($("schedule-calendar-sources")), /Removed source \(work\)/);
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "select_calendar_source");
    assert.equal(pending.length, 0);
    $("schedule-calendar-mode").value = "none";
    await $("schedule-calendar-mode").trigger("change");
    const unlinking = $("schedule-form").trigger("submit");
    const unlinkRequest = take("/schedules/alarm", "PUT");
    assert.equal(JSON.parse(unlinkRequest.options.body).calendar_link, null, "Returning to fixed time explicitly clears the stored link");
    const unlinked = {...dayLinked, calendar_link: null};
    reply(unlinkRequest, unlinked);
    await flush();
    scheduleReply(take("/schedules"), [unlinked]);
    await unlinking;

    const datedLinked = {...linked, rule: {dates: ["2026-10-01"]}};
    const datedPoll = qa.loadSchedules();
    scheduleReply(take("/schedules"), [datedLinked]);
    await datedPoll;
    assert.doesNotMatch(content($("schedule-list")), /once/, "A linked date may contain multiple events and must not promise one ring");
    for (const changeRule of [
        async () => { await $("clear-schedule-date").trigger("click"); },
        async () => { $("schedule-date-picker").value = "2026-10-02"; await $("schedule-date-picker").trigger("change"); },
        async () => {
            weekdays[0].checked = true;
            await weekdays[0].trigger("change");
            assert.equal($("schedule-calendar-mode").value, "event", "Weekly filters preserve existing calendar linkage");
            weekdays[0].checked = false;
            await weekdays[0].trigger("change");
        },
    ]) {
        await button("schedule-list", "edit").trigger("click");
        assert.equal($("schedule-calendar-mode").value, "event", "Opening an existing linked-date alarm preserves its meaning");
        assert.deepEqual(plain(qa.scheduleData().calendar_link), link);
        await changeRule();
        assert.equal($("schedule-calendar-mode").value, "none", "Explicit one-time selections leave event-based repetition");
        assert.equal($("schedule-time").disabled, false);
        assert.equal(qa.scheduleData().calendar_link, null, "Saving a manual one-time choice explicitly clears the old link");
        await $("cancel-edit").trigger("click");
    }

    await $("add-schedule").trigger("click");
    $("schedule-calendar-mode").value = "event";
    await $("schedule-calendar-mode").trigger("change");
    calendarInput("work").checked = true;
    $("schedule-offset").value = "10";
    const meeting = {source_id: "work", uid: "weekly-meeting", recurring: true, recurrence_id: "2026-10-02T01:00:00+00:00",
        text: "Weekly meeting", starts_at: Date.parse("2026-10-02T09:00:00+08:00"), all_day: false};
    const laterMeeting = {...meeting, recurrence_id: "2026-10-09T01:00:00+00:00", starts_at: meeting.starts_at + 7 * 86400000};
    const calendarEvents = [meeting, laterMeeting, {...meeting, uid: "single", recurring: false, recurrence_id: "", text: "One-off event"},
        {...meeting, uid: "all-day", all_day: true}];
    $("schedule-calendar-scope").value = "series";
    await $("schedule-calendar-scope").trigger("change");
    assert.throws(() => qa.scheduleData(), /calendar_target_required/, "Choosing a scope must never silently target all events");
    reply(take("/calendar-events?source_id=work"), {events: calendarEvents});
    await flush();
    assert.equal($("schedule-calendar-target").children.length, 2, "Series deduplicate occurrences and exclude single/all-day events in relative-time mode");
    $("schedule-calendar-target").value = $("schedule-calendar-target").children[1].value;
    await $("schedule-calendar-target").trigger("change");
    const seriesTarget = {source_id: "work", uid: meeting.uid, scope: "series", recurrence_id: "", title: meeting.text};
    assert.deepEqual(plain(qa.scheduleData().calendar_link), {mode: "event", source_ids: ["work"], offset_minutes: 10, target: seriesTarget});
    $("schedule-calendar-scope").value = "occurrence";
    await $("schedule-calendar-scope").trigger("change");
    reply(take("/calendar-events?source_id=work"), {events: calendarEvents});
    await flush();
    assert.equal($("schedule-calendar-target").children.length, 4);
    $("schedule-calendar-target").value = $("schedule-calendar-target").children[1].value;
    await $("schedule-calendar-target").trigger("change");
    const occurrenceTarget = {...seriesTarget, scope: "occurrence", recurrence_id: meeting.recurrence_id};
    assert.deepEqual(plain(qa.scheduleData().calendar_link.target), occurrenceTarget, "Occurrence identity uses the original recurrence ID");
    // Changing language must preserve the entire draft, including calendar target identity.
    $("schedule-name").value = "Draft meeting alarm";
    $("schedule-volume").value = "37";
    $("schedule-advanced").open = true;
    $("schedule-enabled").checked = false;
    const languageDraft = plain(qa.scheduleData());
    for (const language of ["zh-TW", "en"]) {
        context.document.documentElement.lang = language;
        context.window.applyManagementLanguage(language);
        assert.equal($("editor").hidden, false);
        assert.equal($("schedule-advanced").open, true);
        assert.deepEqual(plain(qa.scheduleData()), languageDraft);
        reply(take("/calendar-events?source_id=work"), {events: calendarEvents});
        await flush();
        assert.deepEqual(plain(qa.scheduleData()), languageDraft);
        assert.equal(inputRefreshes.at(-1).language, language);
    }
    const saveTarget = $("schedule-form").trigger("submit");
    const targetRequest = take("/schedules", "POST");
    const targeted = {...row, calendar_link: JSON.parse(targetRequest.options.body).calendar_link};
    assert.deepEqual(targeted.calendar_link.target, occurrenceTarget);
    reply(targetRequest, targeted);
    await flush();
    scheduleReply(take("/schedules"), [targeted]);
    await saveTarget;
    assert.match(content($("schedule-list")), /Weekly meeting.*calendar_scope_occurrence/);
    await button("schedule-list", "edit").trigger("click");
    assert.equal($("calendar-target-status").textContent, "", "Do not report a missing target before the catalog responds");
    reply(take("/calendar-events?source_id=work"), {events: []});
    await flush();
    assert.deepEqual(plain(qa.scheduleData().calendar_link.target), occurrenceTarget, "A cancelled/missing event keeps its target rather than switching to all events");
    assert.equal($("calendar-target-status").textContent, "calendar_target_missing");
    const staleCatalog = $("refresh-calendar-targets").trigger("click");
    const staleCatalogRequest = take("/calendar-events?source_id=work");
    $("schedule-calendar-scope").value = "all";
    await $("schedule-calendar-scope").trigger("change");
    reply(staleCatalogRequest, {events: calendarEvents});
    await staleCatalog;
    assert.equal(qa.scheduleData().calendar_link.target, undefined, "Late catalog results cannot restore a removed target");
    assert.equal($("calendar-target-field").hidden, true);
    await $("cancel-edit").trigger("click");

    const refreshedDevice = {
        id: "desk", name: "Desk", reported_name: "Firmware desk", admin_name: null,
        device_type: "browser", registered_at: "2026-09-29T09:00:00+08:00",
        last_seen: "2026-09-30T10:00:00+08:00", online: true, firmware: "1.0",
        capabilities: {display: true, audio: false}, capabilities_reported_at: "2026-09-30T09:59:00+08:00",
        sync_status: {state: "confirmed", command_id: "old-command", requested_at: "2026-09-30T09:55:00+08:00", acknowledged_at: "2026-09-30T09:56:00+08:00"},
        commands: []
    };
    let nameInput = deviceNameInput("desk");
    nameInput.value = "Unsaved device name";
    nameInput.focus();
    await nameInput.trigger("input");
    const polling = intervals.find(item => item.delay === 15000).callback();
    scheduleReply(take("/schedules"), []);
    reply(take("/devices"), {devices: [refreshedDevice]});
    await polling;
    nameInput = deviceNameInput("desk");
    assert.equal(nameInput.value, "Unsaved device name", "15-second refresh preserves the rename draft");
    assert.equal(activeElement, nameInput, "15-second refresh restores focus to the rename field");
    assert.match(content($("device-list")), /Firmware desk.*browser.*Display: Supported.*Audio: Not supported.*Notifications: unknown/);
    assert.match(content($("device-list")), /Sync confirmation: Confirmed.*Requested.*Confirmed at/);

    const failedRefresh = qa.loadDevices(), failedRefreshRequest = take("/devices");
    reply(failedRefreshRequest, {error: "offline"}, false);
    await assert.rejects(failedRefresh, /offline/);
    assert.match(content($("device-list")), /Firmware desk/, "A failed refresh retains the last successful list");
    assert.equal($("device-refresh-status").textContent, "Device data stale");
    assert.equal(deviceNameInput("desk").value, "Unsaved device name");

    const failedRename = button("device-list", "Save name").trigger("click");
    const failedRenameRequest = take("/devices/desk", "PATCH");
    assert.deepEqual(JSON.parse(failedRenameRequest.options.body), {name: "Unsaved device name"});
    reply(failedRenameRequest, {error: "disk full"}, false);
    await failedRename;
    assert.equal(deviceNameInput("desk").value, "Unsaved device name", "A failed save retains the rename draft");
    assert.equal(button("device-list", "Save name").disabled, false, "A failed save enables the current retry button");
    const savedDevice = {...refreshedDevice, name: "Managed desk", admin_name: "Managed desk"};
    const savingName = button("device-list", "Save name").trigger("click");
    reply(take("/devices/desk", "PATCH"), {device: savedDevice});
    await savingName;
    assert.match(content($("device-list")), /Managed desk/);
    assert.equal(deviceNameInput("desk").value, "Managed desk", "The rendered result matches the saved server value");

    nameInput = deviceNameInput("desk");
    nameInput.value = "Language-safe draft";
    nameInput.focus();
    await nameInput.trigger("input");
    const staleTranslations = {"zh-TW": "裝置資料未更新", en: "Device data stale", ja: "端末データを更新できませんでした"};
    for (const language of ["zh-TW", "en", "ja"]) {
        context.document.documentElement.lang = language;
        context.window.applyManagementLanguage(language);
        nameInput = deviceNameInput("desk");
        assert.equal(nameInput.value, "Language-safe draft", "Language changes preserve device rename drafts");
        assert.equal(activeElement, nameInput, "Language changes preserve device rename focus");
        assert.equal($("device-refresh-status").textContent, staleTranslations[language], "Language changes translate the stale-data notice");
    }
    context.document.documentElement.lang = "en";
    context.window.applyManagementLanguage("en");

    const beforeRename = qa.loadDevices(), beforeRenameRequest = take("/devices");
    nameInput = deviceNameInput("desk");
    nameInput.value = "First submitted name";
    await nameInput.trigger("input");
    const concurrentSave = button("device-list", "Save name").trigger("click");
    const concurrentSaveRequest = take("/devices/desk", "PATCH");
    assert.deepEqual(JSON.parse(concurrentSaveRequest.options.body), {name: "First submitted name"});
    reply(beforeRenameRequest, {devices: [{...refreshedDevice, name: "Before-save stale name"}]});
    await beforeRename;
    assert.doesNotMatch(content($("device-list")), /Before-save stale name/, "Starting a rename invalidates earlier list requests");
    nameInput.value = "Newer unsaved name";
    await nameInput.trigger("input");

    const refreshDuringSave = qa.loadDevices(), refreshDuringSaveRequest = take("/devices");
    const latestReportedDevice = {...savedDevice, firmware: "2.0", reported_name: "New firmware self-name",
        capabilities: {background: true}, capabilities_reported_at: "2026-09-30T10:01:00+08:00"};
    reply(refreshDuringSaveRequest, {devices: [latestReportedDevice]});
    await refreshDuringSave;
    assert.equal(deviceNameInput("desk").value, "Newer unsaved name");
    assert.equal($("device-refresh-status").textContent, "", "A successful refresh clears the stale-data notice");
    assert.equal(button("device-list", "Save name").disabled, true, "Polling cannot enable a pending rename button");
    context.document.documentElement.lang = "ja";
    context.window.applyManagementLanguage("ja");
    assert.equal(button("device-list", "Save name").disabled, true, "Language changes cannot enable a pending rename button");
    const requestsBeforeDuplicate = requests.length;
    await button("device-list", "Save name").trigger("click");
    assert.equal(requests.length, requestsBeforeDuplicate, "The handler also rejects a duplicate rename while saving");
    context.document.documentElement.lang = "en";
    context.window.applyManagementLanguage("en");

    const delayedRefresh = qa.loadDevices(), delayedRefreshRequest = take("/devices");
    const firstSavedDevice = {...savedDevice, name: "First submitted name", admin_name: "First submitted name", sync_status: {state: "pending"}};
    reply(concurrentSaveRequest, {device: firstSavedDevice});
    await concurrentSave;
    assert.match(content($("device-list")), /First submitted name/);
    assert.equal(deviceNameInput("desk").value, "Newer unsaved name", "A successful save preserves edits made after submission");
    assert.equal(button("device-list", "Save name").disabled, false, "Success enables the currently rendered save button");
    assert.match(content($("device-list")), /New firmware self-name.*firmware 2\.0.*Background: Supported/,
        "A delayed rename response preserves newer device reports");
    assert.match(content($("device-list")), /Sync confirmation: Confirmed/,
        "A delayed rename response cannot roll back newer sync confirmation");
    reply(delayedRefreshRequest, {devices: [refreshedDevice]});
    await delayedRefresh;
    assert.match(content($("device-list")), /First submitted name/, "A delayed list response cannot roll back a completed rename");
    assert.equal(deviceNameInput("desk").value, "Newer unsaved name");

    const saveNewerDraft = button("device-list", "Save name").trigger("click");
    const saveNewerDraftRequest = take("/devices/desk", "PATCH");
    assert.deepEqual(JSON.parse(saveNewerDraftRequest.options.body), {name: "Newer unsaved name"});
    reply(saveNewerDraftRequest, {device: {...firstSavedDevice, name: "Newer unsaved name", admin_name: "Newer unsaved name"}});
    await saveNewerDraft;
    const externalRename = qa.loadDevices(), externalRenameRequest = take("/devices");
    reply(externalRenameRequest, {devices: [savedDevice]});
    await externalRename;
    assert.equal(deviceNameInput("desk").value, "Managed desk", "A successfully submitted draft is cleared so later server updates appear");

    const syncing = button("device-list", "sync").trigger("click");
    const commandRequest = take("/devices/desk/commands", "POST");
    assert.deepEqual(JSON.parse(commandRequest.options.body), {action: "sync"});
    reply(commandRequest, {id: "command", action: "sync", status: "pending"});
    await flush();
    reply(take("/devices"), {devices: [{id: "desk", online: false, status: {firmware: "1.0", config_revision: "config123", schedule_revision: "schedule123", holiday_revision: "holiday123"}, commands: [{action: "sync", status: "pending"}]}]});
    await syncing;
    assert.match(content($("device-list")), /offline.*1.0.*config123.*schedule123.*holiday123.*Sync confirmation: Awaiting confirmation.*sync/);

    const oldDevices = qa.loadDevices(), oldDevicesRequest = take("/devices");
    const newDevices = qa.loadDevices(), newDevicesRequest = take("/devices");
    reply(newDevicesRequest, {devices: []});
    await newDevices;
    reply(oldDevicesRequest, {devices: [{id: "stale"}]});
    await oldDevices;
    assert.equal(content($("device-list")).trim(), "no_devices");
    const emptyPost = qa.api("/schedules/alarm/skip-next", {method: "POST"});
    const emptyPostRequest = take("/schedules/alarm/skip-next", "POST");
    assert.equal(emptyPostRequest.options.body, undefined);
    reply(emptyPostRequest, {ok: true});
    await emptyPost;
    assert.equal(pending.length, 0);
    assert.ok(requests.every(request => !/sound|audio|snooze|restart/.test(request.url)));
    console.log("Schedule management forms, commands and freshness checks passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(completionTimeout));
