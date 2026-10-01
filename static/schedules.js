/* Self-hosted schedule management; deliberately excluded from the public offline shell. */
"use strict";

(function () {
    const labels = JSON.parse(document.getElementById("schedule-i18n").textContent);
    const $ = id => document.getElementById(id);
    const t = key => labels[key] || key;
    const format = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, name) => values[name]);
    const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value + "T00:00:00Z")) && new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value;
    let schedules = [], devices = [], calendarSources = [], refreshing = false, scheduleRequest = 0, deviceRequest = 0, editorPanel = "alarms", serverTime = null;
    let serverSynced = 0, previewTimer, previewRequest = 0, previewTime = null, previewDraft = null;
    let pauseRequest = 0, nextPauseEnd = null, editorPausedUntil = null, saving = false;
    let calendarEvents = [], calendarTarget = null, calendarRequest = 0;
    let timeFormat = document.body.getAttribute("data-time-format") === "12h" ? "12h" : "24h";
    const displayTime = value => window.WebClockTime.format(value, timeFormat, document.documentElement.lang);
    const refreshTimeInputs = () => window.WebClockTimeInputs.refresh($("schedule-form"), timeFormat, document.documentElement.lang);
    const serverNow = () => serverTime === null ? null : serverTime + performance.now() - serverSynced;
    function syncServerTime(value) {
        serverTime = Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;
        serverSynced = performance.now();
    }
    function remainingTime(value) {
        const now = serverNow(), target = Date.parse(value);
        if (now === null || !Number.isFinite(target)) return t("unknown");
        const minutes = Math.floor(Math.max(0, target - now) / 60000);
        if (!minutes) return t("under_minute");
        return [["duration_days", Math.floor(minutes / 1440)], ["duration_hours", Math.floor(minutes % 1440 / 60)], ["duration_minutes", minutes % 60]]
            .filter(([, count]) => count).map(([key, count]) => format(key, {count})).join(" ");
    }
    function renderEditorTime() {
        if ($("editor").hidden) return;
        const now = serverNow();
        const datetime = now === null ? t("unknown") : new Date(now).toLocaleDateString(document.documentElement.lang, {
            timeZone: "Asia/Taipei", year: "numeric", month: "numeric", day: "numeric", weekday: "short"
        }) + " " + displayTime(new Date(now + 8 * 3600000).toISOString().slice(11, 16));
        $("editor-now").textContent = format("current_datetime", {datetime});
        if (!previewTime) return;
        if (now !== null && Date.parse(previewTime) < now) { queuePreview(); return; }
        const next = format("next_ring", {datetime: nextTime(previewTime)});
        const countdown = format("ring_in", {duration: remainingTime(previewTime)});
        if ($("editor-next").textContent !== next) $("editor-next").textContent = next;
        if ($("editor-countdown").textContent !== countdown) $("editor-countdown").textContent = countdown;
    }
    function queuePreview(event) {
        // Input and blur/change can report the same value; keep a ready action clickable.
        if (event && previewDraft !== null) {
            try { if (JSON.stringify(scheduleData()) === previewDraft) return; }
            catch (error) {}
        }
        clearTimeout(previewTimer);
        const request = ++previewRequest;
        previewTime = null;
        previewDraft = null;
        if ($("editor").hidden) return;
        renderEditorActions();
        let data;
        try { data = scheduleData(); }
        catch (error) { $("editor-next").textContent = error.message; $("editor-countdown").textContent = ""; return; }
        previewDraft = JSON.stringify(data);
        if ($("schedule-id").value) data.id = $("schedule-id").value;
        previewTimer = setTimeout(async () => {
            try {
                const result = await api("/schedules/preview", json("POST", data));
                if (request !== previewRequest || $("editor").hidden) return;
                syncServerTime(result.server_time);
                previewTime = result.next_occurrence;
                $("editor-next").textContent = previewTime ? format("next_ring", {datetime: nextTime(previewTime)}) : t(data.enabled ? "none" : "disabled");
                if (!previewTime) $("editor-countdown").textContent = "";
                renderEditorTime();
                renderEditorActions();
            } catch (error) {
                if (request === previewRequest) {
                    previewDraft = null;
                    $("editor-next").textContent = t("preview_failed");
                    $("editor-countdown").textContent = "";
                }
            }
        }, 200);
    }
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
        const now = serverNow();
        const current = now === null ? null : new Date(now + offset);
        const targetDay = Math.floor((instant + offset) / dayLength);
        const currentDay = current ? Math.floor((now + offset) / dayLength) : null;
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
        if (!response.ok) throw new Error(data.error === "Occurrence already skipped; wait for resume" ? t("pause_pending") : data.error || t("request_failed"));
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
    function ruleText(rule, skipHolidays, calendarLink) {
        let text = t("every_day");
        if (rule.workday_only) text = t("workday_only");
        else if (rule.holiday_only) text = t("holiday_only");
        else if (rule.weekdays) text = format("weekly_summary", {days: rule.weekdays.map(day => t("weekdays")[day - 1]).join(" / ")});
        else if (rule.dates) text = (rule.dates.length === 1 && !calendarLink ? t("once") + " · " : "") + rule.dates.join(", ");
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
        const summary = format(link.mode === "event" ? "calendar_event_summary" : "calendar_day_summary", {
            sources: link.source_ids.map(sourceName).join(" / "), minutes: link.offset_minutes || 0
        });
        return summary + (link.target ? " · " + format("calendar_target_summary", {
            title: link.target.title || t("calendar_untitled"), scope: t("calendar_scope_" + link.target.scope)
        }) : "");
    }
    const isRecurringAlarm = schedule => schedule.type === "alarm" && !schedule.rule.dates && !schedule.calendar_link;
    const pendingSkip = schedule => schedule.enabled && serverNow() !== null &&
        (schedule.skipped_occurrences || []).find(value => Date.parse(value) >= serverNow());
    function resumeMessage(value, key = "resume_saved") {
        return format(key, {datetime: eventTime(value), duration: remainingTime(value)});
    }
    function choosePause(schedule, draft = {}) {
        const dialog = $("pause-dialog"), request = ++pauseRequest;
        let occurrence = null;
        $("pause-title").textContent = format("pause_title", {name: draft.name || schedule.name});
        $("pause-skipped").textContent = "";
        $("pause-resume").textContent = t("loading");
        $("pause-once").disabled = true;
        dialog.returnValue = "";
        const choice = new Promise(resolve => {
            dialog.onclose = () => {
                ++pauseRequest;
                resolve(dialog.returnValue === "skip" && occurrence ? {skip: occurrence} : dialog.returnValue === "disable" ? {disable: true} : null);
            };
        });
        dialog.showModal();
        api("/schedules/preview", json("POST", Object.assign({id: schedule.id}, draft, {enabled: true, skip_next: true}))).then(result => {
            if (request !== pauseRequest || !dialog.open) return;
            syncServerTime(result.server_time);
            occurrence = result.skipped_occurrence;
            $("pause-skipped").textContent = occurrence ? format("pause_skip", {datetime: eventTime(occurrence)}) : "";
            $("pause-resume").textContent = result.next_occurrence && occurrence ? resumeMessage(occurrence, "resume_at") : t("resume_unavailable");
            $("pause-once").disabled = !occurrence || !result.next_occurrence;
        }).catch(error => {
            if (request === pauseRequest) $("pause-resume").textContent = error.message === t("pause_pending") ? error.message : t("pause_preview_failed");
        });
        return choice;
    }
    async function skipSchedule(schedule, expected) {
        if (pendingSkip(schedule)) throw new Error(t("pause_pending"));
        let result;
        try {
            result = await api("/schedules/" + encodeURIComponent(schedule.id) + "/skip-next", expected ? json("POST", {expected_occurrence: expected}) : {method: "POST"});
        } catch (error) {
            if (error.message === "Occurrence changed; preview again") throw new Error(t("pause_stale"));
            throw error;
        }
        const latest = schedules.find(item => item.id === schedule.id);
        acceptScheduleChange(schedule.id, latest ? Object.assign({}, latest, {
            next_occurrence: result.next_event ? result.next_event.datetime : null,
            skipped_occurrences: (latest.skipped_occurrences || []).concat(result.skipped.datetime)
        }) : null);
        notice(result.next_event && isRecurringAlarm(schedule) ? resumeMessage(result.skipped.datetime) : format("skipped", {datetime: eventTime(result.skipped.datetime)}));
        await loadSchedules();
    }
    function acceptScheduleChange(id, updated) {
        ++scheduleRequest;
        const previous = schedules.find(schedule => schedule.id === id);
        if (updated && updated.next_occurrence === undefined) {
            const sameTime = previous && previous.time === updated.time && !!previous.skip_holidays === !!updated.skip_holidays && JSON.stringify(previous.rule) === JSON.stringify(updated.rule) && JSON.stringify(previous.calendar_link || null) === JSON.stringify(updated.calendar_link || null) && JSON.stringify(previous.skipped_occurrences || []) === JSON.stringify(updated.skipped_occurrences || []);
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
        nextPauseEnd = null;
        schedules.forEach(schedule => {
            const skip = pendingSkip(schedule), paused = isRecurringAlarm(schedule) && skip;
            const enabled = schedule.enabled && !paused;
            if (skip) nextPauseEnd = nextPauseEnd === null ? Date.parse(skip) : Math.min(nextPauseEnd, Date.parse(skip));
            const row = node("li", undefined, "schedule-row" + (enabled ? "" : " disabled"));
            const details = node("div", undefined, "schedule-details");
            const description = ruleText(schedule.rule, schedule.skip_holidays, schedule.calendar_link) + " · " +
                (schedule.type === "alarm" ? t("sound_" + (schedule.browser_sound || "bell")) : t(schedule.type));
            details.append(node("h3", schedule.name), node("p", description));
            if (schedule.calendar_link) details.append(node("p", calendarText(schedule.calendar_link)));
            const next = nextTime(schedule.next_occurrence);
            if (paused) details.append(node("p", resumeMessage(paused, "resume_at"), "schedule-next"));
            details.append(node("p", schedule.type === "alarm" ? format("next_ring", {datetime: next}) : t("next") + ": " + next, "schedule-next"));
            const actions = node("div", undefined, "schedule-row-actions");
            const toggle = action(t(enabled ? "disable" : "enable"), async () => {
                if (enabled && isRecurringAlarm(schedule)) {
                    const choice = await choosePause(schedule);
                    if (!choice) return;
                    if (choice.skip) { await skipSchedule(schedule, choice.skip); return; }
                }
                const data = {enabled: !enabled};
                if (paused) data.skipped_occurrences = schedule.skipped_occurrences.filter(value => Date.parse(value) < serverNow());
                const updated = await api("/schedules/" + encodeURIComponent(schedule.id), json("PUT", data));
                acceptScheduleChange(schedule.id, updated);
                await loadSchedules();
            }, "schedule-toggle");
            toggle.setAttribute("role", "switch");
            toggle.setAttribute("aria-checked", String(enabled));
            toggle.setAttribute("aria-label", t("enabled") + " · " + schedule.name);
            toggle.title = t(enabled ? "disable" : "enable");
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
        clearTimeout(previewTimer);
        ++previewRequest;
        ++calendarRequest;
        previewTime = null;
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
        const paused = isRecurringAlarm(schedule) && pendingSkip(schedule) || null;
        if (editorPausedUntil !== paused) {
            $("schedule-enabled").checked = schedule.enabled && !paused;
            editorPausedUntil = paused;
        }
        const skip = action(t("skip_next"), () => saveEditor(true));
        skip.disabled = saving || !$("schedule-enabled").checked || !previewTime;
        try { skip.disabled = skip.disabled || !!pendingSkip(Object.assign({}, schedule, scheduleData())); }
        catch (error) { skip.disabled = true; }
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
        syncServerTime(data.server_time);
        calendarSources = data.calendar_sources || [];
        if (!$("editor").hidden) renderCalendarSources(selectedCalendarSources());
        schedules = data.schedules;
        renderSchedules();
        renderNextEvent();
        const day = data.day || {};
        $("day-status").textContent = (day.date || "") + " · " + t(day.type || "unknown");
        const coverage = data.holiday_coverage;
        $("day-source").textContent = (day.known === false ? t("unknown_calendar") + " " : "") + t("official") + (coverage ? " · " + format("coverage", coverage) : "");
        renderEditorTime();
        queuePreview();
    }
    function setRule(manual = false) {
        const mode = $("schedule-rule").value;
        if (manual && (mode === "once" || mode === "dates") && $("schedule-calendar-mode").value !== "none") {
            $("schedule-calendar-mode").value = "none";
            setCalendarMode();
        }
        $("multiple-dates-field").hidden = mode !== "dates";
        $("schedule-dates").disabled = mode !== "dates";
        $("clear-schedule-date").hidden = !$("schedule-dates").value && !$("schedule-date-picker").value;
        const days = Array.from(document.querySelectorAll('[name="weekday"]:checked'), input => t("weekdays")[Number(input.value) - 1]);
        $("schedule-repeat-summary").textContent = mode === "weekdays" ? format("weekly_summary", {days: days.join(" / ")}) :
            mode === "dates" ? t("dates") + " · " + $("schedule-dates").value : t(mode);
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
            input.addEventListener("change", loadCalendarTargets);
            label.append(input, node("span", sourceName(id)));
            list.append(label);
        });
    }
    const calendarKey = item => JSON.stringify([item.source_id, item.uid, item.recurrence_id || ""]);
    function renderCalendarTargets(failed = false, ready = true) {
        const scope = $("schedule-calendar-scope").value, select = $("schedule-calendar-target");
        const choose = node("option", t("calendar_target_choose"));
        choose.value = "";
        select.replaceChildren(choose);
        const seen = new Set();
        let found = false, allDayTarget = false, selectedTime = "";
        calendarEvents.forEach(event => {
            if (calendarTarget && event.all_day && $("schedule-calendar-mode").value === "event" &&
                calendarKey(Object.assign({}, event, {recurrence_id: scope === "series" ? "" : event.recurrence_id})) === calendarKey(calendarTarget)) allDayTarget = true;
            if (scope === "series" && !event.recurring || $("schedule-calendar-mode").value === "event" && event.all_day) return;
            const target = {source_id: event.source_id, uid: event.uid, scope,
                recurrence_id: scope === "series" ? "" : event.recurrence_id || "", title: (event.text || t("calendar_untitled")).slice(0, 500)};
            const key = calendarKey(target);
            if (seen.has(key)) return;
            seen.add(key);
            const time = event.all_day ? new Date(event.starts_at).toLocaleDateString(document.documentElement.lang, {timeZone: "Asia/Taipei"}) + " " + t("calendar_all_day") : eventTime(new Date(event.starts_at).toISOString());
            const option = node("option", target.title + " · " + sourceName(event.source_id) + " · " + time);
            option.value = key;
            select.append(option);
            if (calendarTarget && calendarKey(calendarTarget) === key) { calendarTarget = target; found = true; selectedTime = time; }
        });
        const missingText = t(allDayTarget ? "calendar_target_all_day" : "calendar_target_missing");
        if (calendarTarget && !found) {
            const missing = node("option", (calendarTarget.title || t("calendar_untitled")) + (ready ? " · " + missingText : ""));
            missing.value = calendarKey(calendarTarget);
            select.append(missing);
        }
        select.value = calendarTarget ? calendarKey(calendarTarget) : "";
        $("calendar-target-status").textContent = failed ? t("calendar_target_failed") : !ready ? "" :
            calendarTarget && !found ? missingText : !seen.size ? t("calendar_target_empty") : selectedTime;
    }
    async function loadCalendarTargets() {
        const request = ++calendarRequest, sources = selectedCalendarSources();
        const active = $("schedule-calendar-mode").value !== "none" && $("schedule-calendar-scope").value !== "all";
        $("calendar-target-field").hidden = !active;
        $("schedule-calendar-target").disabled = !active;
        $("schedule-calendar-target").required = active;
        if (!active) return;
        if (calendarTarget && !sources.includes(calendarTarget.source_id)) calendarTarget = null;
        calendarEvents = calendarEvents.filter(event => sources.includes(event.source_id));
        renderCalendarTargets(false, false);
        if (!sources.length) { $("calendar-target-status").textContent = t("select_calendar_source"); return; }
        try {
            const data = await api("/calendar-events?" + sources.map(id => "source_id=" + encodeURIComponent(id)).join("&"));
            if (request !== calendarRequest || $("editor").hidden) return;
            calendarEvents = data.events;
            renderCalendarTargets();
            queuePreview();
        } catch (error) {
            if (request === calendarRequest && !$("editor").hidden) renderCalendarTargets(true, false);
        }
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
        $("date-once-hint").textContent = t(mode === "none" ? "date_once_hint" : "calendar_rule_hint");
        loadCalendarTargets();
        refreshTimeInputs();
    }
    function edit(schedule, type = "alarm") {
        $("schedule-form").reset();
        editorPausedUntil = null;
        previewTime = null;
        previewDraft = null;
        $("editor-next").textContent = "";
        $("editor-countdown").textContent = "";
        if (!schedule) $("schedule-time").value = "07:30";
        $("schedule-rule").value = !schedule && type === "alarm" ? "once" : "every_day";
        $("schedule-date-picker").value = "";
        $("form-error").textContent = "";
        $("schedule-id").value = schedule ? schedule.id : "";
        $("schedule-type").value = schedule ? schedule.type : type;
        $("schedule-type-field").hidden = $("schedule-type").value === "alarm";
        $("schedule-sound-field").hidden = $("schedule-type").value !== "alarm";
        $("schedule-sound").value = schedule && schedule.browser_sound || "bell";
        $("schedule-skip-holidays").checked = !!(schedule && schedule.skip_holidays);
        const link = schedule && schedule.calendar_link;
        calendarEvents = [];
        calendarTarget = link && link.target ? Object.assign({}, link.target) : null;
        $("schedule-calendar-scope").value = calendarTarget ? calendarTarget.scope : "all";
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
            $("schedule-date-picker").value = rule.dates && rule.dates.length === 1 ? rule.dates[0] : "";
        }
        if ($("schedule-rule").value === "every_day") document.querySelectorAll('[name="weekday"]').forEach(input => input.checked = true);
        $("schedule-advanced").open = !!(schedule && (schedule.skip_holidays || schedule.rule.workday_only || schedule.rule.holiday_only || (schedule.rule.dates || []).length > 1));
        $("editor").hidden = false;
        setRule();
        setCalendarMode();
        renderEditorActions();
        renderEditorTime();
        queuePreview();
        $("editor").scrollIntoView({block: "start"});
        ($("schedule-time-hour") || $("schedule-name")).focus({preventScroll: true});
    }
    $("add-schedule").addEventListener("click", () => edit(null));
    $("add-other-schedule").addEventListener("click", () => edit(null, "reminder"));
    $("cancel-edit").addEventListener("click", closeEditor);
    $("schedule-rule").addEventListener("change", function () {
        if (this.value !== "dates") $("schedule-date-picker").value = $("schedule-dates").value = "";
        if (this.value !== "weekdays") document.querySelectorAll('[name="weekday"]').forEach(input => input.checked = this.value === "every_day");
        setRule(true);
    });
    document.querySelectorAll('[name="weekday"]').forEach(input => input.addEventListener("change", () => {
        $("schedule-rule").value = document.querySelectorAll('[name="weekday"]:checked').length ? "weekdays" : "once";
        $("schedule-date-picker").value = $("schedule-dates").value = "";
        setRule(true);
    }));
    $("schedule-date-picker").addEventListener("change", function () {
        $("schedule-dates").value = this.value;
        $("schedule-rule").value = this.value ? "dates" : "once";
        document.querySelectorAll('[name="weekday"]').forEach(input => input.checked = false);
        setRule(true);
    });
    $("clear-schedule-date").addEventListener("click", () => {
        $("schedule-date-picker").value = $("schedule-dates").value = "";
        $("schedule-rule").value = "once";
        document.querySelectorAll('[name="weekday"]').forEach(input => input.checked = false);
        setRule(true);
        queuePreview();
    });
    $("schedule-dates").addEventListener("input", () => {
        $("schedule-date-picker").value = "";
        setRule();
    });
    $("schedule-calendar-mode").addEventListener("change", function () {
        if (this.value !== "none" && $("schedule-rule").value === "once") {
            $("schedule-rule").value = "every_day";
            document.querySelectorAll('[name="weekday"]').forEach(input => input.checked = true);
            setRule();
        }
        setCalendarMode();
    });
    $("schedule-calendar-scope").addEventListener("change", () => {
        calendarTarget = null;
        loadCalendarTargets();
    });
    $("schedule-calendar-target").addEventListener("change", function () {
        const scope = $("schedule-calendar-scope").value;
        const event = calendarEvents.find(item => calendarKey(Object.assign({}, item, {recurrence_id: scope === "series" ? "" : item.recurrence_id})) === this.value);
        if (event) calendarTarget = {source_id: event.source_id, uid: event.uid, scope,
            recurrence_id: scope === "series" ? "" : event.recurrence_id || "", title: (event.text || t("calendar_untitled")).slice(0, 500)};
        else if (!this.value) calendarTarget = null;
        renderCalendarTargets();
    });
    $("refresh-calendar-targets").addEventListener("click", loadCalendarTargets);
    ["input", "change"].forEach(event => $("schedule-form").addEventListener(event, queuePreview));
    $("preview-sound").addEventListener("click", function () {
        const sound = $("schedule-sound").value;
        if (sound === "silent") { notice(t("sound_silent")); return; }
        const played = window.AlarmAudio && window.AlarmAudio.unlock(sound);
        notice(t(played ? "sound_previewed" : "audio_unavailable"), !played);
    });
    function scheduleData() {
        const id = $("schedule-id").value;
        const rule = {}, mode = $("schedule-rule").value;
        if (mode === "weekdays") {
            rule.weekdays = Array.from(document.querySelectorAll('[name="weekday"]:checked'), input => Number(input.value));
            if (!rule.weekdays.length) throw new Error(t("select_weekday"));
        } else if (mode === "dates") {
            rule.dates = $("schedule-dates").value.split(",").map(value => value.trim());
            if (rule.dates.some(value => !validDate(value))) throw new Error(t("select_date"));
        } else if (mode !== "every_day" && mode !== "once") rule[mode] = true;
        if ($("schedule-skip-holidays").checked && mode === "holiday_only") throw new Error(t("holiday_conflict"));
        const data = {rule: rule, enabled: $("schedule-enabled").checked || !!editorPausedUntil, skip_holidays: $("schedule-skip-holidays").checked};
        if (editorPausedUntil && $("schedule-enabled").checked) {
            const schedule = schedules.find(item => item.id === id);
            data.skipped_occurrences = schedule.skipped_occurrences.filter(value => Date.parse(value) < serverNow());
        }
        ["name", "type", "time"].forEach(key => data[key] = $("schedule-" + key).value);
        data.name = data.name.trim() || t(data.type);
        if (data.type === "alarm") data.browser_sound = $("schedule-sound").value;
        const calendarMode = data.type === "alarm" ? $("schedule-calendar-mode").value : "none";
        if (calendarMode === "event" && !data.time) data.time = "07:30";
        if (calendarMode !== "event" && (!/^([01]\d|2[0-3]):[0-5]\d$/.test(data.time) || ($("schedule-time")._clockTimeControl || {}).invalid)) throw new Error(t("select_time"));
        if (mode === "once") {
            const now = serverNow();
            if (now === null) throw new Error(t("preview_failed"));
            const today = new Date(now + 8 * 3600000).toISOString().slice(0, 10);
            const target = Date.parse(today + "T" + data.time + ":00+08:00");
            rule.dates = [new Date(target + 8 * 3600000 + (target < now ? 86400000 : 0)).toISOString().slice(0, 10)];
        }
        if (calendarMode !== "none") {
            const sourceIds = selectedCalendarSources();
            if (!sourceIds.length || sourceIds.some(id => !calendarSources.some(source => source.id === id))) throw new Error(t("select_calendar_source"));
            if (calendarMode === "event" && !/^\d+$/.test($("schedule-offset").value)) throw new Error(t("calendar_offset_error"));
            const offset = calendarMode === "event" ? Number($("schedule-offset").value) : 0;
            if (!Number.isInteger(offset) || offset < 0 || offset > 1440) throw new Error(t("calendar_offset_error"));
            data.calendar_link = {mode: calendarMode, source_ids: sourceIds, offset_minutes: offset};
            if ($("schedule-calendar-scope").value !== "all") {
                if (!calendarTarget || !sourceIds.includes(calendarTarget.source_id)) throw new Error(t("calendar_target_required"));
                data.calendar_link.target = Object.assign({}, calendarTarget);
            }
        } else if (id && schedules.some(schedule => schedule.id === id && schedule.calendar_link)) {
            data.calendar_link = null;
        }
        return data;
    }
    async function saveEditor(skipNext = false) {
        if (saving) return;
        const button = $("schedule-form").querySelector('[type="submit"]');
        $("form-error").textContent = "";
        saving = true;
        button.disabled = true;
        try {
            const id = $("schedule-id").value, data = scheduleData();
            const previous = schedules.find(schedule => schedule.id === id);
            if (skipNext) {
                if (previous && pendingSkip(Object.assign({}, previous, data))) throw new Error(t("pause_pending"));
                if (!id || !$("schedule-enabled").checked || !previewTime) return;
                data.skip_next = previewTime;
            }
            renderEditorActions();
            if (previous && previous.enabled && !data.enabled && isRecurringAlarm(data)) {
                const choice = await choosePause(previous, data);
                if (!choice) return;
                if (choice.skip) { data.enabled = true; data.skip_next = choice.skip; }
            }
            const saved = await api("/schedules" + (id ? "/" + encodeURIComponent(id) : ""), json(id ? "PUT" : "POST", data));
            if (skipNext) editorPausedUntil = null;
            acceptScheduleChange(saved.id, saved);
            if (skipNext) queuePreview();
            else closeEditor();
            notice(t("saved"));
            try {
                await loadSchedules();
                const latest = schedules.find(schedule => schedule.id === saved.id);
                if (data.skip_next) notice(latest && latest.next_occurrence && isRecurringAlarm(data) ? resumeMessage(data.skip_next) : format("skipped", {datetime: eventTime(data.skip_next)}));
                else notice(latest && latest.next_occurrence ? format("saved_next", {duration: remainingTime(latest.next_occurrence)}) : t("saved") + " · " + t(data.enabled ? "none" : "disabled"));
            } catch (error) { notice(t("saved") + " · " + t("preview_failed")); }
        } catch (error) { $("form-error").textContent = error.message === "Occurrence changed; preview again" ? t("pause_stale") : error.message || t("request_failed"); }
        finally { saving = false; button.disabled = false; renderEditorActions(); }
    }
    $("schedule-form").addEventListener("submit", function (event) {
        event.preventDefault();
        return saveEditor();
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
        if (refreshing || $("pause-dialog").open) return;
        refreshing = true;
        try { await Promise.all([loadSchedules(), loadDevices()]); }
        catch (error) { notice(error.message || t("request_failed"), true); }
        finally { refreshing = false; }
    }
    refresh();
    setInterval(refresh, 15000);
    setInterval(() => {
        if (nextPauseEnd !== null && serverNow() > nextPauseEnd) renderSchedules();
        renderEditorTime();
    }, 1000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}());
