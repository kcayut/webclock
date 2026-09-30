"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const template = fs.readFileSync(path.join(__dirname, "../templates/schedules.html"), "utf8");
const source = fs.readFileSync(path.join(__dirname, "../static/schedules.js"), "utf8");
assert.doesNotMatch(template, /schedule-(volume|repeat|snooze)|sound-form|enable-audio|ringing/);
assert.match(template, /alarm-audio\.js/);
const row = {id: "alarm", name: "Morning", type: "alarm", enabled: true, time: "07:30", rule: {},
    skipped_occurrences: [], next_occurrence: "2026-10-01T07:30:00+08:00"};
const nextDate = "2026-10-02T07:30:00+08:00";
const plain = value => JSON.parse(JSON.stringify(value));
const flush = () => new Promise(resolve => setImmediate(resolve));

function element(tag = "div") {
    return {
        tag, textContent: "", className: "", disabled: false, hidden: false, value: "", checked: false,
        children: [], listeners: {}, attributes: {}, classList: {toggle() {}},
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
        scrollIntoView() {}, focus() { this.focused = true; }
    };
}
const elements = new Map(Array.from(template.matchAll(/\bid="([^"]+)"/g), match => [match[1], element()]));
const $ = id => {
    assert.ok(elements.has(id), "The management template must contain " + id);
    return elements.get(id);
};
$("schedule-i18n").textContent = JSON.stringify({
    weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    today: "Today", tomorrow: "Tomorrow", this_week: "This {weekday}", next_week: "Next {weekday}", next_ring: "Next ring: {datetime}",
    calendar_event_summary: "{sources} · {minutes} min before events", calendar_day_summary: "{sources} · Days with events", calendar_missing: "Removed source ({id})",
    skipped: "Skipped {datetime}", coverage: "{start} to {end}", delete_confirm: "Delete {name}?"
});
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
    $("schedule-time").value = "07:30";
    $("schedule-rule").value = "every_day";
    $("schedule-sound").value = "bell";
    $("schedule-skip-holidays").checked = false;
    $("schedule-enabled").checked = true;
    weekdays.forEach(input => input.checked = false);
};
const pending = [], requests = [], intervals = [], navigation = {};
class WrongDeviceDate extends Date {
    constructor(...args) { super(...(args.length ? args : ['2040-01-01T00:00:00Z'])); }
    static now() { return Date.parse('2040-01-01T00:00:00Z'); }
}
const context = vm.createContext({
    console, Date: WrongDeviceDate, Set, Map, Number, JSON, Object, Array, Promise,
    document: {
        documentElement: {lang: "en"}, body: {getAttribute: () => "alarms"},
        getElementById: $, createElement: element, addEventListener() {},
        querySelectorAll(selector) {
            if (selector === '[data-management-panel]') return [$("alarms-panel"), $("devices-panel")];
            if (selector === '[data-management-link]') return [];
            if (selector === '[name="calendar-source"]:checked') return descendants($("schedule-calendar-sources")).filter(input => input.name === "calendar-source" && input.checked);
            assert.ok(['[name="weekday"]', '[name="weekday"]:checked'].includes(selector));
            return selector.endsWith(":checked") ? weekdays.filter(input => input.checked) : weekdays;
        }
    },
    window: {confirm: () => true, location: {hash: ""}, scrollTo() {},
        addEventListener(type, handler) { navigation[type] = handler; }},
    fetch(url, options) {
        return new Promise(resolve => {
            const request = {url, options, resolve};
            requests.push(request);
            pending.push(request);
        });
    },
    setInterval(callback, delay) { intervals.push({callback, delay}); }
});
const probe = `globalThis.qa = {loadSchedules, loadDevices, get: () => schedules};`;
const instrumented = source.replace("    refresh();\n    setInterval", "    " + probe + "\n    refresh();\n    setInterval");
assert.notEqual(instrumented, source, "Management state probe must attach");
// Audio support is optional: initialization, forms and commands must work without it.
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
    return request;
}
function reply(request, data, ok = true) {
    request.resolve({ok, json: async () => data});
}
const catalog = [{id: 'local', name: 'Local', provider: 'local'}, {id: 'work', name: 'Work calendar', provider: 'apple'}];
function scheduleReply(request, schedules, serverTime = '2026-09-30T10:00:00+08:00', calendarSources = catalog) {
    reply(request, {schedules, calendar_sources: calendarSources, server_time: serverTime, day: {date: "2026-09-30", type: "workday"}, holiday_coverage: {start: "2023-01-01", end: "2027-12-31"}});
}
function descendants(root) { return root.children.flatMap(child => [child, ...descendants(child)]); }
function calendarInput(id) { return descendants($("schedule-calendar-sources")).find(input => input.name === 'calendar-source' && input.value === id); }
function button(list, label) {
    const result = descendants($(list)).find(child => child.tag === "button" && child.textContent === label);
    assert.ok(result, "Expected button " + label);
    return result;
}
const content = root => [root.textContent, ...root.children.map(content)].join(" ");

(async () => {
    scheduleReply(take("/schedules"), [row, {...row, id: "notice", name: "Device reminder", type: "reminder", next_occurrence: "2026-09-30T12:00:00+08:00"}]);
    reply(take("/devices"), {devices: [{id: "desk", online: true, last_seen: "2026-09-30T10:00:00+08:00"}]});
    await flush();
    assert.deepEqual(intervals.map(item => item.delay), [15000], "Only management refresh should be scheduled");
    assert.match($("day-status").textContent, /2026-09-30.*workday/);
    assert.match($("next-event").textContent, /Morning/);
    assert.doesNotMatch(content($("schedule-list")), /Device reminder/);
    assert.match(content($("other-schedule-list")), /Device reminder/);
    assert.doesNotMatch(content($("other-schedule-list")), /Morning/);
    assert.match(content($("device-list")), /config_revision.*unknown.*schedule_revision.*unknown.*holiday_revision.*unknown/);
    assert.equal(descendants($("device-list")).filter(item => item.tag === "button").length, 1);
    assert.equal(button("schedule-list", "disable").attributes.role, "switch");
    assert.equal(button("schedule-list", "disable").attributes["aria-checked"], "true");
    assert.equal($("next-event").textContent, "Tomorrow 07:30 · Morning");
    assert.match(content($("schedule-list")), /Next ring: Tomorrow 07:30/);
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
    const restored = qa.loadSchedules();
    scheduleReply(take('/schedules'), [row]);
    await restored;

    const oldPoll = qa.loadSchedules();
    const oldResponse = take("/schedules");
    const disabling = button("schedule-list", "disable").trigger("click");
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

    const older = qa.loadSchedules(), olderRequest = take("/schedules");
    const newer = qa.loadSchedules(), newerRequest = take("/schedules");
    scheduleReply(newerRequest, [row]);
    await newer;
    scheduleReply(olderRequest, [disabled]);
    await older;
    assert.equal(qa.get()[0].name, "Morning", "Latest GET must win even if an earlier one arrives last");

    await button("schedule-list", "edit").trigger("click");
    assert.equal($("editor").parentNode, $("alarms-panel"));
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
    context.window.AlarmAudio = {unlock(sound) { previewed.push(sound); return true; }};
    $("schedule-sound").value = "digital";
    await $("preview-sound").trigger("click");
    assert.deepEqual(previewed, ["digital"]);
    assert.equal($("status").textContent, "sound_previewed");
    $("schedule-sound").value = "silent";
    await $("preview-sound").trigger("click");
    assert.deepEqual(previewed, ["digital"], "Silent preview must not play a sound");
    $("schedule-sound").value = "digital";
    $("schedule-skip-holidays").checked = true;
    assert.equal($("schedule-id").value, row.id);
    assert.equal($("schedule-name").value, row.name);
    $("schedule-name").value = "Edited";
    const editing = $("schedule-form").trigger("submit");
    const editRequest = take("/schedules/alarm", "PUT");
    assert.deepEqual(JSON.parse(editRequest.options.body), {rule: {}, enabled: true, skip_holidays: true, browser_sound: "digital", name: "Edited", type: "alarm", time: "07:30"});
    const edited = {...row, name: "Edited", browser_sound: "digital", skip_holidays: true};
    reply(editRequest, edited);
    await flush();
    scheduleReply(take("/schedules"), [edited]);
    await editing;
    assert.equal($("editor").hidden, true);
    assert.match(content($("schedule-list")), /skip_holidays.*sound_digital/);
    assert.match(content($("schedule-list")), /Next ring: Tomorrow 07:30/);
    await button("schedule-list", "edit").trigger("click");
    assert.equal($("schedule-sound").value, "digital");
    assert.equal($("schedule-skip-holidays").checked, true);

    showPanel("devices");
    await $("add-other-schedule").trigger("click");
    assert.equal($("editor").parentNode, $("devices-panel"));
    assert.equal($("schedule-type").value, "reminder");
    assert.equal($("schedule-type-field").hidden, false);
    assert.equal($("schedule-sound-field").hidden, true);
    assert.equal($("schedule-calendar-mode-field").hidden, true);
    $("schedule-name").value = "Weekly reminder";
    $("schedule-type").value = "reminder";
    $("schedule-rule").value = "weekdays";
    await $("schedule-rule").trigger("change");
    assert.equal($("weekday-field").hidden, false);
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "select_weekday");
    assert.equal(pending.length, 0);
    weekdays[0].checked = true;
    weekdays[4].checked = true;
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

    showPanel("alarms");
    await $("add-schedule").trigger("click");
    assert.equal($("schedule-sound").value, "bell");
    assert.equal($("schedule-skip-holidays").checked, false);
    $("schedule-rule").value = "holiday_only";
    $("schedule-skip-holidays").checked = true;
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "holiday_conflict");
    assert.equal(pending.length, 0, "Contradictory holiday options must not send a request");
    $("schedule-rule").value = "dates";
    $("schedule-dates").value = "2026-02-30";
    await $("schedule-form").trigger("submit");
    assert.equal($("form-error").textContent, "select_date");
    assert.equal(pending.length, 0, "Invalid dates must not send a request");
    await $("cancel-edit").trigger("click");
    assert.equal($("add-schedule").focused, true);

    showPanel("devices");
    await button("other-schedule-list", "edit").trigger("click");
    const skipping = button("editor-actions", "skip_next").trigger("click");
    const skipRequest = take("/schedules/weekly/skip-next", "POST");
    const skipDate = "2026-10-06T07:30:00+08:00";
    reply(skipRequest, {skipped: {datetime: created.next_occurrence}, next_event: {datetime: skipDate}});
    await flush();
    assert.equal($("next-event").textContent, "none");
    assert.match(content($("other-schedule-list")), /Next Tue 07:30/);
    const skipped = {...created, next_occurrence: skipDate, skipped_occurrences: [created.next_occurrence]};
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
    $("schedule-name").value = "Linked alarm";
    $("schedule-calendar-mode").value = "event";
    await $("schedule-calendar-mode").trigger("change");
    assert.equal($("schedule-time-field").hidden, true);
    assert.equal($("schedule-time").required, false);
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
    const linking = $("schedule-form").trigger("submit");
    const linkedRequest = take("/schedules", "POST");
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

    const syncing = button("device-list", "sync").trigger("click");
    const commandRequest = take("/devices/desk/commands", "POST");
    assert.deepEqual(JSON.parse(commandRequest.options.body), {action: "sync"});
    reply(commandRequest, {id: "command", action: "sync", status: "pending"});
    await flush();
    reply(take("/devices"), {devices: [{id: "desk", online: false, status: {firmware: "1.0", config_revision: "config123", schedule_revision: "schedule123", holiday_revision: "holiday123"}, commands: [{action: "sync", status: "pending"}]}]});
    await syncing;
    assert.match(content($("device-list")), /offline.*1.0.*config123.*schedule123.*holiday123.*sync.*pending/);

    const oldDevices = qa.loadDevices(), oldDevicesRequest = take("/devices");
    const newDevices = qa.loadDevices(), newDevicesRequest = take("/devices");
    reply(newDevicesRequest, {devices: []});
    await newDevices;
    reply(oldDevicesRequest, {devices: [{id: "stale"}]});
    await oldDevices;
    assert.equal(content($("device-list")).trim(), "no_devices");
    assert.equal(pending.length, 0);
    assert.ok(requests.every(request => !/sound|audio|snooze|restart/.test(request.url)));
    console.log("Schedule management forms, commands and freshness checks passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
