/* Self-hosted schedule management; deliberately excluded from the public offline shell. */
"use strict";

(function () {
    const labels = JSON.parse(document.getElementById("schedule-i18n").textContent);
    const $ = id => document.getElementById(id);
    const t = key => labels[key] || key;
    const format = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, name) => values[name]);
    const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value + "T00:00:00Z")) && new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value;
    let schedules = [], devices = [], calendarSources = [], refreshing = false, scheduleRequest = 0, deviceRequest = 0, editorPanel = "alarms", serverTime = null;
    let timeFormat = document.body.getAttribute("data-time-format") === "12h" ? "12h" : "24h";
    const displayTime = value => window.WebClockTime.format(value, timeFormat, document.documentElement.lang);
    const refreshTimeInputs = () => window.WebClockTimeInputs.refresh($("schedule-form"), timeFormat, document.documentElement.lang);
    function eventTime(value) {
        if (!value) return t("none");
        const instant = Date.parse(value);
        if (!Number.isFinite(instant)) return t("unknown");
        const date = new Date(instant).toLocaleDateString(document.documentElement.lang, {timeZone: "Asia/Taipei", month: "numeric", day: "numeric", weekday: "short"});
        return date + " " + displayTime(new Date(instant + 8 * 3600000).toISOString().slice(11, 16));
    }
    function nextTime(value) {
        if (!value) return t("none");
        const instant = Date.parse(value);
        if (!Number.isFinite(instant)) return t("unknown");
        const offset = 8 * 3600000, dayLength = 86400000;
        const date = new Date(instant + offset);
        const current = serverTime === null ? null : new Date(serverTime + offset);
        const targetDay = Math.floor((instant + offset) / dayLength);
        const currentDay = current ? Math.floor((serverTime + offset) / dayLength) : null;
        const weekStart = current ? currentDay - (current.getUTCDay() + 6) % 7 : null;
        let label = (date.getUTCMonth() + 1) + "/" + date.getUTCDate();
        if (!current || date.getUTCFullYear() !== current.getUTCFullYear()) label = date.getUTCFullYear() + "/" + label;
        if (current) {
            const weekday = t("weekdays")[(date.getUTCDay() + 6) % 7];
            if (targetDay === currentDay) label = t("today");
            else if (targetDay === currentDay + 1) label = t("tomorrow");
            else if (targetDay > currentDay && targetDay < weekStart + 7) label = format("this_week", {weekday});
            else if (targetDay >= weekStart + 7 && targetDay < weekStart + 14) label = format("next_week", {weekday});
        }
        return label + " " + displayTime(date.toISOString().slice(11, 16));
    }
    function node(tag, text, className) {
        const element = document.createElement(tag);
        if (text !== undefined) element.textContent = text;
        if (className) element.className = className;
        return element;
    }
    function notice(text, error) {
        $("status").textContent = text;
        $("status").className = error ? "error" : "";
    }
    async function api(path, options) {
        const response = await fetch("/api/v1" + path, Object.assign({cache: "no-store"}, options));
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || t("request_failed"));
        return data;
    }
    const json = (method, body) => ({method: method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    function action(label, handler, className) {
        const button = node("button", label, className);
        button.type = "button";
        button.addEventListener("click", async function () {
            button.disabled = true;
            try { await handler(); }
            catch (error) { notice(error.message || t("request_failed"), true); }
            finally { button.disabled = false; }
        });
        return button;
    }
    function ruleText(rule, skipHolidays) {
        let text = t("every_day");
        if (rule.workday_only) text = t("workday_only");
        else if (rule.holiday_only) text = t("holiday_only");
        else if (rule.weekdays) text = rule.weekdays.map(day => t("weekdays")[day - 1]).join(" / ");
        else if (rule.dates) text = rule.dates.join(", ");
        return text + (skipHolidays ? " · " + t("skip_holidays") : "");
    }
    function renderNextEvent() {
        const next = schedules.filter(schedule => schedule.type === "alarm" && schedule.enabled && schedule.next_occurrence)
            .sort((a, b) => Date.parse(a.next_occurrence) - Date.parse(b.next_occurrence))[0];
        $("next-event").textContent = next ? nextTime(next.next_occurrence) + " · " + next.name : t("none");
    }
    function sourceName(id) {
        const source = calendarSources.find(item => item.id === id);
        return source ? (id === "local" ? t("calendar_local") : source.name) : format("calendar_missing", {id});
    }
    function calendarText(link) {
        return format(link.mode === "event" ? "calendar_event_summary" : "calendar_day_summary", {
            sources: link.source_ids.map(sourceName).join(" / "), minutes: link.offset_minutes || 0
        });
    }
    function acceptScheduleChange(id, updated) {
        ++scheduleRequest;
        const previous = schedules.find(schedule => schedule.id === id);
        if (updated && updated.next_occurrence === undefined) {
            const sameTime = previous && previous.time === updated.time && !!previous.skip_holidays === !!updated.skip_holidays && JSON.stringify(previous.rule) === JSON.stringify(updated.rule) && JSON.stringify(previous.calendar_link || null) === JSON.stringify(updated.calendar_link || null);
            updated = Object.assign({}, updated, {next_occurrence: updated.enabled && sameTime ? previous.next_occurrence : null});
        }
        schedules = schedules.filter(schedule => schedule.id !== id);
        if (updated) schedules.push(updated);
        renderSchedules();
        renderNextEvent();
    }
    function renderSchedules() {
        const list = $("schedule-list");
        const otherList = $("other-schedule-list");
        list.replaceChildren();
        otherList.replaceChildren();
        schedules.forEach(schedule => {
            const row = node("li", undefined, "schedule-row" + (schedule.enabled ? "" : " disabled"));
            const details = node("div", undefined, "schedule-details");
            const description = ruleText(schedule.rule, schedule.skip_holidays) + " · " +
                (schedule.type === "alarm" ? t("sound_" + (schedule.browser_sound || "bell")) : t(schedule.type));
            details.append(node("h3", schedule.name), node("p", description));
            if (schedule.calendar_link) details.append(node("p", calendarText(schedule.calendar_link)));
            const next = nextTime(schedule.next_occurrence);
            details.append(node("p", schedule.type === "alarm" ? format("next_ring", {datetime: next}) : t("next") + ": " + next, "schedule-next"));
            const actions = node("div", undefined, "schedule-row-actions");
            const toggle = action(t(schedule.enabled ? "disable" : "enable"), async () => {
                const updated = await api("/schedules/" + encodeURIComponent(schedule.id), json("PUT", {enabled: !schedule.enabled}));
                acceptScheduleChange(schedule.id, updated);
                await loadSchedules();
            }, "schedule-toggle");
            toggle.setAttribute("role", "switch");
            toggle.setAttribute("aria-checked", String(schedule.enabled));
            toggle.setAttribute("aria-label", t("enabled") + " · " + schedule.name);
            toggle.title = t(schedule.enabled ? "disable" : "enable");
            actions.append(toggle, action(t("edit"), () => edit(schedule)));
            const byEvent = schedule.calendar_link && schedule.calendar_link.mode === "event";
            const shownTime = byEvent ? t("calendar_event_time") : displayTime(schedule.time);
            const time = node("p", undefined, "schedule-time" + (byEvent ? " calendar-time" : ""));
            if (!byEvent && timeFormat === "12h") {
                time.setAttribute("aria-label", shownTime);
                shownTime.split(" ").forEach(part => {
                    const piece = node("span", part, part.includes(":") ? "schedule-time-value" : "schedule-time-period");
                    piece.setAttribute("aria-hidden", "true");
                    time.append(piece);
                });
            } else time.textContent = shownTime;
            row.append(time, details, actions);
            (schedule.type === "alarm" ? list : otherList).append(row);
        });
        if (!schedules.some(schedule => schedule.type === "alarm")) list.append(node("li", t("none"), "empty"));
        if (!schedules.some(schedule => schedule.type !== "alarm")) otherList.append(node("li", t("none"), "empty"));
        renderEditorActions();
    }
    function closeEditor() {
        $("editor").hidden = true;
        $(editorPanel + "-panel").classList.toggle("is-editing", false);
        if (!$(editorPanel + "-panel").hidden) $(editorPanel === "alarms" ? "add-schedule" : "add-other-schedule").focus();
    }
    function renderEditorActions() {
        const actions = $("editor-actions");
        actions.replaceChildren();
        const schedule = schedules.find(item => item.id === $("schedule-id").value);
        actions.hidden = !schedule;
        if (!schedule) return;
        const skip = action(t("skip_next"), async () => {
            const result = await api("/schedules/" + encodeURIComponent(schedule.id) + "/skip-next", {method: "POST"});
            const latest = schedules.find(item => item.id === schedule.id);
            acceptScheduleChange(schedule.id, latest ? Object.assign({}, latest, {
                next_occurrence: result.next_event ? result.next_event.datetime : null,
                skipped_occurrences: (latest.skipped_occurrences || []).concat(result.skipped.datetime)
            }) : null);
            notice(format("skipped", {datetime: eventTime(result.skipped.datetime)}));
            await loadSchedules();
        });
        skip.disabled = !schedule.enabled || !schedule.next_occurrence;
        actions.append(skip, action(t("delete"), async () => {
            if (!window.confirm(format("delete_confirm", {name: schedule.name}))) return;
            await api("/schedules/" + encodeURIComponent(schedule.id), {method: "DELETE"});
            acceptScheduleChange(schedule.id, null);
            closeEditor();
            notice(t("deleted"));
            await loadSchedules();
        }, "danger"));
    }
    async function loadSchedules() {
        const request = ++scheduleRequest;
        const data = await api("/schedules");
        if (request !== scheduleRequest) return;
        if ((data.time_format === "12h" || data.time_format === "24h") && data.time_format !== timeFormat) {
            timeFormat = data.time_format;
            document.body.setAttribute("data-time-format", timeFormat);
            refreshTimeInputs();
            renderDevices();
        }
        serverTime = Number.isFinite(Date.parse(data.server_time)) ? Date.parse(data.server_time) : null;
        calendarSources = data.calendar_sources || [];
        if (!$("editor").hidden) renderCalendarSources(selectedCalendarSources());
        schedules = data.schedules;
        renderSchedules();
        renderNextEvent();
        const day = data.day || {};
        $("day-status").textContent = (day.date || "") + " · " + t(day.type || "unknown");
        const coverage = data.holiday_coverage;
        $("day-source").textContent = (day.known === false ? t("unknown_calendar") + " " : "") + t("official") + (coverage ? " · " + format("coverage", coverage) : "");
    }
    function setRule() {
        $("weekday-field").hidden = $("schedule-rule").value !== "weekdays";
        $("date-field").hidden = $("schedule-rule").value !== "dates";
        $("schedule-date-picker").disabled = $("date-field").hidden;
    }
    function selectedCalendarSources() {
        return Array.from(document.querySelectorAll('[name="calendar-source"]:checked'), input => input.value);
    }
    function renderCalendarSources(selected) {
        const choices = calendarSources.map(source => source.id);
        selected.forEach(id => { if (!choices.includes(id)) choices.push(id); });
        const list = $("schedule-calendar-sources");
        list.replaceChildren();
        choices.forEach(id => {
            const label = node("label", undefined, "check");
            const input = node("input");
            input.type = "checkbox";
            input.name = "calendar-source";
            input.value = id;
            input.checked = selected.includes(id);
            label.append(input, node("span", sourceName(id)));
            list.append(label);
        });
    }
    function setCalendarMode() {
        const alarm = $("schedule-type").value === "alarm";
        const mode = alarm ? $("schedule-calendar-mode").value : "none";
        $("schedule-calendar-mode-field").hidden = !alarm;
        $("calendar-source-field").hidden = mode === "none";
        $("schedule-offset-field").hidden = mode !== "event";
        $("schedule-offset").disabled = mode !== "event";
        $("schedule-offset").required = mode === "event";
        $("schedule-time-field").hidden = mode === "event";
        $("schedule-event-time").hidden = mode !== "event";
        $("schedule-time").required = mode !== "event";
        $("schedule-time").disabled = mode === "event";
        $("calendar-mode-hint").textContent = t(mode === "event" ? "calendar_event_hint" : "calendar_day_hint");
        refreshTimeInputs();
    }
    function edit(schedule, type = "alarm") {
        $("schedule-form").reset();
        if (!schedule) $("schedule-time").value = "07:30";
        $("schedule-date-picker").value = "";
        $("form-error").textContent = "";
        $("schedule-id").value = schedule ? schedule.id : "";
        $("schedule-type").value = schedule ? schedule.type : type;
        $("schedule-type-field").hidden = $("schedule-type").value === "alarm";
        $("schedule-sound-field").hidden = $("schedule-type").value !== "alarm";
        $("schedule-sound").value = schedule && schedule.browser_sound || "bell";
        $("schedule-skip-holidays").checked = !!(schedule && schedule.skip_holidays);
        const link = schedule && schedule.calendar_link;
        $("schedule-calendar-mode").value = link ? link.mode : "none";
        $("schedule-offset").value = link ? String(link.offset_minutes || 0) : "0";
        renderCalendarSources(link ? link.source_ids : []);
        $(editorPanel + "-panel").classList.toggle("is-editing", false);
        editorPanel = $("schedule-type").value === "alarm" ? "alarms" : "devices";
        $(editorPanel + "-panel").append($("editor"));
        $(editorPanel + "-panel").classList.toggle("is-editing", true);
        $("editor-title").textContent = t(schedule ? (editorPanel === "alarms" ? "edit_alarm" : "edit_other") : type === "alarm" ? "add_alarm" : "add_other");
        if (schedule) {
            ["name", "type", "time"].forEach(key => $("schedule-" + key).value = schedule[key]);
            $("schedule-enabled").checked = schedule.enabled;
            const rule = schedule.rule;
            $("schedule-rule").value = ["weekdays", "workday_only", "holiday_only", "dates"].find(key => rule[key]) || "every_day";
            document.querySelectorAll('[name="weekday"]').forEach(input => input.checked = (rule.weekdays || []).includes(Number(input.value)));
            $("schedule-dates").value = (rule.dates || []).join(", ");
        }
        $("editor").hidden = false;
        setRule();
        setCalendarMode();
        renderEditorActions();
        $("editor").scrollIntoView({block: "start"});
        $("schedule-name").focus({preventScroll: true});
    }
    $("add-schedule").addEventListener("click", () => edit(null));
    $("add-other-schedule").addEventListener("click", () => edit(null, "reminder"));
    $("cancel-edit").addEventListener("click", closeEditor);
    $("schedule-rule").addEventListener("change", setRule);
    $("schedule-calendar-mode").addEventListener("change", setCalendarMode);
    $("add-schedule-date").addEventListener("click", function () {
        const date = $("schedule-date-picker").value;
        if (!validDate(date)) { $("form-error").textContent = t("select_date"); return; }
        const dates = $("schedule-dates");
        if (!dates.value.split(",").some(value => value.trim() === date)) dates.value += (dates.value.trim() ? ", " : "") + date;
        $("form-error").textContent = "";
    });
    $("preview-sound").addEventListener("click", function () {
        const sound = $("schedule-sound").value;
        if (sound === "silent") { notice(t("sound_silent")); return; }
        const played = window.AlarmAudio && window.AlarmAudio.unlock(sound);
        notice(t(played ? "sound_previewed" : "audio_unavailable"), !played);
    });
    $("schedule-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        const button = this.querySelector('[type="submit"]');
        $("form-error").textContent = "";
        button.disabled = true;
        try {
            const id = $("schedule-id").value;
            const rule = {}, mode = $("schedule-rule").value;
            if (mode === "weekdays") {
                rule.weekdays = Array.from(document.querySelectorAll('[name="weekday"]:checked'), input => Number(input.value));
                if (!rule.weekdays.length) throw new Error(t("select_weekday"));
            } else if (mode === "dates") {
                rule.dates = $("schedule-dates").value.split(",").map(value => value.trim());
                if (rule.dates.some(value => !validDate(value))) throw new Error(t("select_date"));
            } else if (mode !== "every_day") rule[mode] = true;
            if ($("schedule-skip-holidays").checked && mode === "holiday_only") throw new Error(t("holiday_conflict"));
            const data = {rule: rule, enabled: $("schedule-enabled").checked, skip_holidays: $("schedule-skip-holidays").checked};
            ["name", "type", "time"].forEach(key => data[key] = $("schedule-" + key).value);
            if (data.type === "alarm") data.browser_sound = $("schedule-sound").value;
            const calendarMode = data.type === "alarm" ? $("schedule-calendar-mode").value : "none";
            if (calendarMode === "event" && !data.time) data.time = "07:30";
            if (calendarMode !== "none") {
                const sourceIds = selectedCalendarSources();
                if (!sourceIds.length || sourceIds.some(id => !calendarSources.some(source => source.id === id))) throw new Error(t("select_calendar_source"));
                if (calendarMode === "event" && !/^\d+$/.test($("schedule-offset").value)) throw new Error(t("calendar_offset_error"));
                const offset = calendarMode === "event" ? Number($("schedule-offset").value) : 0;
                if (!Number.isInteger(offset) || offset < 0 || offset > 1440) throw new Error(t("calendar_offset_error"));
                data.calendar_link = {mode: calendarMode, source_ids: sourceIds, offset_minutes: offset};
            } else if (id && schedules.some(schedule => schedule.id === id && schedule.calendar_link)) {
                data.calendar_link = null;
            }
            const saved = await api("/schedules" + (id ? "/" + encodeURIComponent(id) : ""), json(id ? "PUT" : "POST", data));
            acceptScheduleChange(saved.id, saved);
            closeEditor();
            notice(t("saved"));
            await loadSchedules();
        } catch (error) { $("form-error").textContent = error.message || t("request_failed"); }
        finally { button.disabled = false; }
    });
    async function loadDevices() {
        const request = ++deviceRequest;
        const data = await api("/devices");
        if (request !== deviceRequest) return;
        devices = data.devices;
        renderDevices();
    }
    function renderDevices() {
        const list = $("device-list");
        list.replaceChildren();
        devices.forEach(device => {
            const card = node("li", undefined, "panel card"), heading = node("div", undefined, "card-heading");
            const status = device.status || device;
            const connection = typeof device.online === "boolean" ? (device.online ? "online" : "offline") : "unknown";
            heading.append(node("h3", device.name || device.id), node("span", t(connection), "badge" + (device.online ? "" : " offline")));
            card.append(heading);
            const details = node("dl");
            const values = {
                last_seen: device.last_seen ? eventTime(device.last_seen) : t("unknown"), firmware: status.firmware || device.firmware,
                config_revision: status.config_revision, schedule_revision: status.schedule_revision, holiday_revision: status.holiday_revision
            };
            Object.entries(values).forEach(([key, value]) => {
                const text = value == null ? t("unknown") : String(value);
                const detail = node("dd", key.endsWith("_revision") ? text.slice(0, 12) : text);
                if (key.endsWith("_revision")) detail.title = text;
                details.append(node("dt", t(key)), detail);
            });
            card.append(details);
            const commands = (device.commands || []).filter(command => command.action === "sync");
            if (commands.length) {
                const command = commands[commands.length - 1];
                card.append(node("p", t("command") + ": " + t(command.action) + " · " + t(command.status || "pending"), "meta"));
            }
            const actions = node("div", undefined, "actions");
            actions.append(action(t("sync"), async () => {
                await api("/devices/" + encodeURIComponent(device.id) + "/commands", json("POST", {action: "sync"}));
                notice(t("pending"));
                await loadDevices();
            }));
            card.append(actions);
            list.append(card);
        });
        if (!devices.length) list.append(node("li", t("no_devices"), "empty"));
    }
    async function refresh() {
        if (refreshing) return;
        refreshing = true;
        try { await Promise.all([loadSchedules(), loadDevices()]); }
        catch (error) { notice(error.message || t("request_failed"), true); }
        finally { refreshing = false; }
    }
    refresh();
    setInterval(refresh, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}());
