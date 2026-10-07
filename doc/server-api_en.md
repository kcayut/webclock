# WebClock Server: Central Management and Device API

Home Assistant native enrollment: `POST /api/v2/device/token/prepare`, `token/join`, `token/leave`; JSON + `X-WebClock-Client: native-v1`, no browser cookies/headers. See the [native transport contract](server-api.md#非瀏覽器加入home-assistant) and [installation guide](home-assistant.md).

## B0–B4 administration, groups and managed devices (2026-10-06)

Administrator sessions, owner-scoped groups, invitations, atomic enrollment, authenticated group display/alarms, and group management UI are implemented. Existing installations remain in `self`; `managed` requires explicit host-side activation. Devices may leave, and administrators may move, disable/resume, or revoke individual device access. See the [guide](guide_en.md) and the [B0–B1 contract](b0-b1-contract.md) for storage and update/restore boundaries.

Public `GET /api/time` returns only time. Managed `/api/status` returns time and empty events; old `/api/v1/device/*` returns 403 and `/api/v1/browser-alarms` returns 401. An admin session cannot grant device access. Non-private `/api/health` reports `managed_device_schema: 3` and `managed_devices_ready: true`: the endpoints exist; this flag does not certify deployment-mode migration or physical hardware acceptance. The legacy schema 2 descriptions below assume self mode. Existing ESP codecs do not automatically support schema 3.

### Group management API

Managed requests require the admin session; writes in both modes require CSRF. `/schedules#devices` provides these operations.

| Path | Method and purpose |
| --- | --- |
| `/api/v1/groups` | GET list; POST create with no content selected by default |
| `/api/v1/groups/initialize` | POST explicit default-group initialization with existing content |
| `/api/v1/groups/<id>` | GET; PATCH name, enabled state, display overrides and content; DELETE a group without members |
| `/api/v1/groups/catalog` | GET display defaults and IDs/labels for selectable content, without source URLs |
| `/api/v1/groups/<id>/members` | GET member authorization and safe observations, without credentials |
| `/api/v1/groups/<id>/invite` | POST generate/regenerate; GET state; DELETE close |
| `/api/management/language` | POST `{"language":"en"}`, changing only the browser session's management language |

Missing `display_overrides` fields inherit global defaults, including each nested `night` field; `false` and `0` are valid overrides. `content` contains `calendar_source_ids`, `manual_note_ids` and `schedule_ids`, with optional `calendar_targets`; empty arrays select nothing, and note IDs are positive integers. Group display language is independent from management language. `/api/control` still updates global display `language`.

Group GET/list/save responses include a `revision` covering group data and current effective display settings. PATCH may include that revision; a mismatch returns 409 `group_settings_changed` without writing. For shared settings, `GET /api/control` returns `{settings, revision}`. POST the existing settings object with `If-Match: "<revision>"`; a mismatch returns 409 `settings_changed`, and success returns updated `settings`/`revision`. Management pages always supply versions and serialize their shared-setting writes. Legacy maintenance CLI/API calls without a version retain unconditional-update compatibility. These opaque hashes compare current state and are not a change history.

`calendar_targets` is an array of `{source_id, uid, scope, recurrence_id}` objects with an optional display-only `title`. `scope` is `series` or `occurrence`; `recurrence_id` is empty for a series or nonrecurring event, and uses the original `RECURRENCE-ID` to follow a rescheduled recurring occurrence. Whole sources still use `calendar_source_ids`. Without exclusions, canonicalization removes selections covered by a source or series. With exclusions, necessary narrower inclusions are retained. Whole-source/series selections include future events. Old data without `calendar_targets`, or with `[]`, remains compatible; PATCH preserves omitted lists. Selected targets outside the catalog’s 366-day window are retained.

Each group has one six-character invitation, valid for 600 seconds with 5 slots by default (1–100). The installation supports at most 100 devices. Plaintext appears only in the generating POST response, never in GET, persisted state or member lists. Closing/regenerating leaves members unchanged. Closed, expired, full or disabled-group invitations reject enrollment. Enrollment-related limits are 10 attempts per source and 100 globally per 60 seconds; 429 includes `Retry-After`.

### Schema 3 device API

| Path | Method and purpose |
| --- | --- |
| `/api/v2/device/join/prepare` | POST `{}`; create/reuse a 10-minute attempt, return `attempt_id`/`expires_at`, and set the pending cookie |
| `/api/v2/device/identity` | GET cookie round-trip confirmation; `pending` attempts omit group, while `active` returns `{status: "active", identity, group: {id, name}}` |
| `/api/v2/device/join` | POST `{"attempt_id":"…","code":"ABC234"}`; atomically consume capacity and enroll, returning 201 initially or 200 for the same committed attempt |
| `/api/v2/device/leave` | POST `{}` with a cookie and same-origin CSRF only; remove this device's authorization and observations, return 200 `{status: "left"}`, and clear the cookie at the same path |
| `/api/v2/device/display` | GET effective device/group settings, selected events, next event and targeted announcements |
| `/api/v2/device/browser-alarms` | GET selected alarms and computed occurrences |
| `/api/v2/device/status` | POST name, capabilities, revisions and command ACKs; credential determines identity, with no caller-supplied `id`/`group_id` |

Browsers perform prepare → identity cookie confirmation → join. The pending secret becomes the same device credential after commit, allowing retries after a lost success response without consuming another slot. Codes never enter URLs or browser storage. `webclock_device` is a host-only, HttpOnly, SameSite=Lax cookie scoped to `/api/v2/device`; managed mode requires HTTPS and Secure cookies. Prepare/join/leave reject Bearer; other device endpoints accept a dedicated device Bearer, not an admin session or legacy shared `DEVICE_API_TOKEN`. Cookie writes require same-origin CSRF. An authenticated device Bearer bypasses cookie CSRF but still undergoes Origin checks; cross-origin reads are not enabled.

Leaving and individual administrative revocation remove the selected device's authorization, completed enrollment attempt and `devices.json` observations. The device disappears from management lists and frees a slot under the installation's 100-device limit. Its old credential and enrollment retries become permanently invalid: APIs reject them immediately, while offline devices remain subject to the existing lease of at most 300 seconds. Other members, groups and local reminders remain; the original invitation's used slot is not refunded. Devices in disabled groups can still leave. After success, the device can prepare again and enroll with a new invitation as a new identity. A save failure returns 500 (`storage_failure` for device leave) without clearing the cookie or reporting success. If observations were removed but saving authorization fails, the original authorization remains valid and a later status report rebuilds observations; cross-file atomic rollback is not guaranteed. Disable and move operations retain device credentials and observations; revoked access cannot be resumed.

Display and alarms return `schema_version: 3`, `identity`, config/schedule/holiday revisions, millisecond `server_timestamp` and a `lease` of at most 300 seconds. Identity includes owner/device/group IDs, credential generation, assignment revision and `identity_revision`. Current authorization and content scope are rechecked before every response, including 304; a scope change during I/O returns 409 `display_scope_changed` instead of old content. ETag responses use `private, no-cache` and `Vary: Cookie, Authorization`; 304 renews through `X-WebClock-Server-Timestamp`, `X-WebClock-Lease-Expires-At` and `X-WebClock-Identity-Revision`. Enrollment/identity responses use `no-store`.

Private caches are scoped to device identity. A 401/403, identity change or expired lease clears private events, announcements, and browser alarms; network failures may retain only unexpired data from the current run. Alarms use `Asia/Taipei`, independently from the group's display timezone. Missing linked sources suppress the affected alarm rather than falling back to daily ringing. This is not an ESP seven-day offline trigger list or proof of old-iPad, lock-screen audio or hardware acceptance.

[繁體中文](server-api.md) · **English** · [日本語](server-api_jp.md) · [README](../README_en.md)

This project manages schedules, Taiwan workday data, device registration, synchronization revisions, and device status. In self mode, the self-hosted clock page also runs browser alarms. `/schedules` edits and previews alarms, `/` plays built-in browser tones and shows a red-border alert, and `/admin` separately manages display settings, subscribed calendars, and text reminders. Enrolled schema 3 clocks receive private content from their effective device/group assignments.

Device execution remains a firmware responsibility. [`firmware/`](../firmware/README.md) now contains an ESP32-S3 ESPHome prototype that cross-compiles successfully, with an OLED, fixed-rule alarm synchronization, persistent cache, passive piezo output, and a stop button. Physical hardware has not been validated. Calendar-linked alarms, faithful browser tones/audio files, snooze, battery-backed RTC, OTA, and a generic public firmware image remain unimplemented. Devices integrate through HTTP/JSON and do not import this project's Python modules.

See the [ESPHome device guide](esp-home.md) and [detailed API examples](server-api.md#裝置-api), both in Traditional Chinese, for the current prototype workflow, limitations, and complete response examples. Each boot requires valid time and successful server configuration validation before alarms activate; cached alarms can continue through network loss during that run, but do not activate automatically after an offline reboot.

There is currently one owner's management space. **Legacy self-mode devices use the same schedules and calendars**. Schema 3 resolves device overrides and group assignments for authenticated devices. Multiple user accounts and multi-tenancy are not implemented.

### Per-item group assignment and display windows

`GET /api/v1/groups/assignments` provides the current owner's groups and note/schedule assignments; calendar assignments accompany `GET /api/calendar/display-items`. `PUT /api/v1/groups/assignments` accepts `item` (`{kind:"manual_note",id}`, `{kind:"schedule",id}`, or `{kind:"calendar",target}`) and `group_ids`, updating the owner's affected groups in one atomic save. An empty list removes all assignments. `all:true` means all groups existing at save time, not future groups. For a series, `keep_partial_group_ids` preserves untouched partial assignments and must not overlap selected groups. Invalid items or unknown/foreign groups reject the whole write.

Each assignment includes a `revision`. PUT may supply its read revision; a mismatch returns 409 `assignment_changed`. `GET /api/v1/groups/assignments?item=<URL-encoded JSON>` returns `{groups, assignment}` for reloading one item. Revisions cover the current group roster and that item’s assignments, including relevant series/occurrence grants and exclusions, so a changed partial selection cannot be overwritten merely because its partial label is unchanged. Unrelated items can change without blocking this save. Per-item changes also invalidate stale whole-group edits. Legacy calls without versions remain compatible; current management editors always send them and never automatically resend after a 409.

Optional `content.calendar_exclusions` uses the same selectors as `calendar_targets`; omission means an empty list. Display authorization follows occurrence exclusion, occurrence inclusion, series exclusion, series inclusion, then whole source. Removing an inherited occurrence creates an exact exception without removing the source or future events. Assigning or removing an entire series replaces its occurrence exceptions. Alarm source authorization remains independent.

`/api/calendar` PATCH also accepts a complete `calendar_targets` list with optional `display_window`: omitted or `{mode:"day"}` means event day; `{mode:"relative",before_minutes:180,end:"day_end"}` starts three hours early, with `event_end` also available. Minutes must be an integer from 0 to 525600. Individual occurrences support `{mode:"absolute",start:"2026-10-06T08:00",end:"2026-10-07T10:00"}`. Windows use the management display timezone and include the start but exclude the end. Series windows follow each actual occurrence; occurrence rules take precedence. Original event times and alarms are unchanged.

`GET /api/calendar/display-items` returns selected events, safe source names, actual times, effective display windows, group assignments and missing states, sorted by full time. An explicitly selected series has one representative card; occurrence exceptions remain separate. Private subscription URLs are excluded. Fetch failure returns 503, not an empty selection. Host backups include these settings; admin version 1 JSON export still contains settings and notes only.


### Targeted announcements

Announcements reuse `manual_notes.json` and the existing form routes: POST `/add` to create, POST `/schedule/<id>` to edit, POST `/toggle/<id>` to pause/resume, and POST `/delete/<id>` to delete. Existing management authentication and CSRF rules apply. Forms use `announcement=1` with repeated `announcement_group_ids`/`announcement_device_ids` fields. Optional `expires_at` is `YYYY-MM-DDTHH:MM`, converted from the management display timezone to an aware ISO 8601 value. Regular reminders use an empty `announcement` value and have no announcement expiry.

A stored note may include `announcement_targets: {group_ids: [], device_ids: []}` and `expires_at`. Each ID list accepts at most 100 entries, deduplicated on save; IDs contain 1–128 ASCII `[A-Za-z0-9_-]` characters. `expires_at` is an aware ISO 8601 string; an empty string removes the additional absolute deadline. A group or device match is sufficient, subject to current device/group authorization; empty targets deliver nowhere. Date, range/daily, weekday, enabled, and absolute-expiry conditions use the management timezone, independently of alarm calculations in `Asia/Taipei`.

`GET /api/v2/device/display` adds `announcements: [{id, text, visible_until}]`. The Unix-millisecond `visible_until` is the earliest of the current snapshot's 300-second limit, absolute expiry, and the end of the current display window; it does not shorten the overall display/alarm lease. Announcements are excluded from `events`, `next_event`, the server-local calendar source, and browser alarms, and do not use `schedules.type=announcement`. Legacy schemas 1/2 keep their contracts. Anonymous self-mode status returns no announcements; enrolled self-mode devices can use v2 to receive matching announcements. Browsers do not persist announcements and clear them on authorization loss, identity/scope changes, lease expiry, or individual expiry.

Forms allow saving empty targets without delivery, but reject missing or foreign-owner targets. Version 1 `/api/backup` retains announcement fields in `notes`; import validates structure and the ownership of existing recipients. Missing historical IDs may remain without granting access or creating recipients. Full host backups preserve the data, and historical restoration still revokes device credentials. See the [announcement guide](guide_en.md#announcements-for-selected-groups-or-devices) for management steps.

## Startup and layout

Use `python app.py`, Docker Compose, or the existing systemd service. Open alarm management from `/admin` or go directly to `/schedules`.

```text
app.py / setup.sh / update_clock.py / update_clock.sh  compatible deployment entry points
webclock/
  app.py                     clock, settings, calendars, and startup
  api/
    management.py            management pages and schedule/device APIs
    device.py                legacy self-mode schema 2 device APIs
    managed_device.py        schema 3 enrollment, identity, group display and status
    groups.py                groups, invitations, content catalog and members
  services/                  schedule, holiday, device, and JSON storage services
  translations/              web UI text
  data/taiwan_calendar.json  read-only calendar data and provenance
templates/                   self-hosted HTML
static/                      web CSS and JavaScript
scripts/                     installation and update logic
tests/                       server, API, and web regression tests
doc/                         guides and API contracts
firmware/                    ESP32-S3 ESPHome YAML, sync component, host tests; cross-compiled, hardware untested
webclock_state/              private runtime data; never commit it
```

Root-level compatibility entry points and public clock assets remain in place. GitHub Pages publishes only the public clock; management pages, APIs, private calendars, and device data are excluded from its offline cache.

## Schedules and workdays

The minimum schedule fields are `name` and `time`. The server creates an `id` and defaults to `type=alarm`, daily, and enabled.

```json
{
  "id": "work_alarm",
  "name": "Work reminder",
  "type": "alarm",
  "time": "07:30",
  "rule": {"weekdays": [1, 2, 3, 4, 5]},
  "skip_holidays": true,
  "browser_sound": "bell",
  "browser_volume": 100,
  "enabled": true,
  "skipped_occurrences": []
}
```

- `type`: `alarm`, `reminder`, or `announcement`. The clock page executes only `alarm`; calendar events and text reminders do not automatically become alarms.
- `rule`: one of `{}` for daily, `{"weekdays":[1,3,5]}`, `{"workday_only":true}`, `{"holiday_only":true}`, or `{"dates":["2026-10-03"]}`.
- `skip_holidays`: filters holidays for daily, weekday, or explicit-date rules. Make-up workdays remain workdays. Combining it with `holiday_only=true` returns 400.
- `browser_sound`: `bell`, `beep`, `digital`, `chime`, `melody`, `pulse`, `sonar`, or `silent`. It is independent from old hardware sound fields.
- `browser_volume`: per-alarm integer from 0 to 100, defaulting to 100 for new and existing schedules. Preview and ringing use the same level; 0 keeps visual alerts only. Device volume still affects loudness. Legacy hardware `volume` is not reused.
- Weekdays use ISO values Monday `1` through Sunday `7`; the legacy reminder API uses `0–6`.
- Schedules always use `Asia/Taipei`, independently from the large clock's display timezone.
- `skipped_occurrences` contains complete timezone-aware timestamps. A one-occurrence pause keeps `enabled=true`; the recurring alarm UI resumes after the skipped time. While a future skip remains pending, another skip is rejected with 400 `Occurrence already skipped; wait for resume`.
- `next_occurrence` and `next_event` are previews, not execution logs or queued events.

An alarm may include `calendar_link`; omit it or use `null` for a fixed-time schedule.

```json
{"calendar_link":{"mode":"event","source_ids":["local","work"],"offset_minutes":15}}
```

- `event`: fire 0–1440 minutes before timed events; all-day events are ignored.
- `day`: fire at the schedule's fixed `time` when a selected source has an event that day; all-day and multi-day events count.
- `source_ids` contains stable source IDs; `local` means server-local reminders managed in `/admin`, not browser-local reminders in the clock panel. Alarm selection is independent from clock display selection.
- Optional `target` selects an event: `{"source_id":"work","uid":"meeting","scope":"occurrence","recurrence_id":"2026-09-30T02:30:00+00:00","title":"Weekly meeting"}`. Use `scope=occurrence` for one occurrence or `scope=series` for the recurring series; no target follows all selected-source events.
- Get stable identifiers from the event catalog below. `recurrence_id` is empty for a nonrecurring event or a series, and is the original `RECURRENCE-ID` for an occurrence, even after rescheduling. `title` is display-only; current calendar data determines rescheduling and cancellation. Subscription caching may delay changes by up to five minutes.
- Weekday, explicit-date, and holiday filters use the actual alarm date in Taiwan. Preview searches up to 366 days.
- Persistent local text without a date or fixed window does not participate. Missing or unreadable sources do not fall back to daily alarms or stale data.
- The server computes linked alarms for browser use. Schema 2 device responses exclude them so old hardware does not misread them as daily alarms.

The bundled Taiwan calendar covers **2023-01-01 through 2027-12-31**. It follows the government office calendar, not every company's policy, typhoon closures, or personal shifts. Dates outside coverage return `unknown`; holiday-dependent rules do not guess.

## Management API

APIs accept JSON. Matched API routes return errors as `{"error":"..."}`: data validation returns 400, missing items 404, and failed storage writes 500 while retaining that file’s previous data. Device leave/revocation spans files; its failure boundary is described above. Other HTTP errors are listed below; unknown routes, unsupported methods, and proxy responses need not be JSON. Request bodies are limited to 1 MiB.

| Path | Method and purpose |
| --- | --- |
| `/api/v1/schedules` | GET schedules and previews; POST a schedule |
| `/api/calendar` | GET/POST calendar sources; PATCH display selection only |
| `/api/v1/calendar-events?source_id=work` | GET selected-source event catalog for the next 366 days; repeat `source_id` for multiple sources |
| `/api/v1/schedules/preview` | POST draft; optional `skip_next: true` previews the skipped and next occurrence without saving |
| `/api/v1/schedules/<id>` | PUT selected fields; DELETE a schedule |
| `/api/v1/schedules/<id>/skip-next` | POST to skip the next occurrence |
| `/api/v1/browser-alarms` | GET upcoming browser alarms and holiday-data state |
| `/api/v1/holidays?date=2026-09-30` | GET the date classification; defaults to today in Taiwan |
| `/api/v1/devices` | GET registered devices and pending commands |
| `/api/v1/devices/<id>` | PATCH `{"name":"Living-room clock"}`; returns 200 with `device`; DELETE revokes an independently authorized device belonging to the current owner, returning 200 `{status: "revoked"}` |
| `/api/v1/devices/<id>/authorization` | PATCH `{"group_id":"destination-group-id","enabled":false}`; either field may be omitted; move or disable/resume a device, returning 200 with safe `device` authorization fields |
| `/api/v1/devices/<id>/content-settings` | GET/PATCH device content overrides, inheritance and effective preview; PATCH requires revision |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`; returns 202 |

Managed `GET /api/v1/devices` lists the current owner’s authorized devices, including those without reports, with `can_revoke: true`. The management UI disables naming and sync when `reported: false`. Self mode retains legacy observations with `can_revoke: false`; existing observations without a source marker cannot be identified as remnants of a past leave, so they are retained rather than deleted by guesswork. DELETE returns 404 for missing devices, another owner’s devices, or legacy shared-token-only devices; it cannot revoke a shared token per device.

`GET /api/v1/devices/<id>/display-settings` returns `{display_overrides, inherited_settings, effective_settings, sources, revision}`. Sources use paths such as `brightness` and `night.enabled`, with `device|group|default` values. Device list rows and authorization responses also include `display_settings`. PATCH the same path with `{"revision":"read revision","display_overrides":{"brightness":10}}` to replace the entire device override map; omitted fields inherit and `{}` resets all. Only display fields are accepted; `night` requires all five fields. Explicit `false`/`0` survive. No content, identity or private sources are accepted. Resolution is device > group > shared defaults; moving retains overrides, display edits preserve `assignment_revision`, and effective changes update device `config_revision`/ETag without changing Taipei alarm scheduling. Revision covers device/parent settings and group assignment. Stale writes return 409 `display_settings_changed` without saving. Missing/foreign/legacy devices return 404; re-enrollment returns 409 `device_rejoin_required`. Existing validation, CSRF, storage and corrupt-state errors remain 400/403/500/503.

`GET /api/v1/devices/<id>/content-settings` returns `{content_overrides, inherited_content, effective_content, sources, revision}`. The `sources` keys `calendar`, `manual_note_ids` and `schedule_ids` use `device|group`; device lists and authorization-change responses also include `content_settings`. PATCH requires `{"revision":"read revision","content_overrides":{"manual_note_ids":[],"schedule_ids":["alarm-id"]}}` and replaces the entire override map. Omitted categories inherit; `{}` restores all inheritance; an explicit empty list supplies none. A custom calendar selection requires `calendar_source_ids` and may include `calendar_targets`/`calendar_exclusions`; these three form one category, with omitted targets/exclusions becoming empty lists. Existing IDs are validated and deduplicated; private URLs and edits to shared content are not accepted.

Changes save atomically and increment `assignment_revision`, invalidating old identity snapshots/ETags; unchanged retries do not write. Moves retain explicit device selections and recalculate inherited categories from the new group. Reads still require active device authorization; deleted sources/schedules never fall back to all content. Revisions cover parent content and device assignment; stale writes return 409 `content_settings_changed`. The 404, re-enrollment 409 and 400/403/500/503 boundaries match device display settings. Full host backups and historical restores preserve `content_overrides` while invalidating old credentials; admin version 1 JSON excludes device authorization data.

`PATCH /api/v1/devices/<id>/authorization` accepts a nonempty object containing only `enabled` (boolean) and/or `group_id` (an existing group ID). A different destination must belong to the same owner and be enabled. A device in a disabled group can still be paused, resumed, or moved out; resuming it does not enable its group. Success returns `{device: {id, group_id, group_name, group_enabled, enabled, authorization_status, assignment_revision, rejoin_required}, display_settings, content_settings}`. GET device-list rows include these fields without replacing the device `name`. `authorization_status` is `active|disabled|revoked`; `rejoin_required: true` includes revoked records and historical records whose credential was cleared. Neither credentials nor their digests are exposed.

The request commits atomically to the authorization file. An actual change increments `assignment_revision` once; an unchanged retry does not write. Moving and disabling/resuming retain the credential, device name, capabilities, reports, and sync ACK, without changing invitation usage. Disabled devices are denied private APIs; after resuming, the original cookie can confirm identity again. Moving produces the new group scope and revisions, invalidates old ETags, and prevents an in-flight request from returning the former scope or 304. Offline private content remains subject to its maximum 300-second lease.

Invalid input returns 400. Missing, foreign-owner, or legacy-observation-only devices, and missing/foreign-owner destination groups, return 404 `not_found`. Moving into a disabled group returns 409 `group_disabled`. Revoked records, records requiring re-enrollment, and cleared credentials return 409 `device_rejoin_required`; historical credentials cannot be restored through this endpoint. Management authentication/CSRF failures return 401/403, storage failure returns 500 while retaining the authorization file, and corrupt authorization state returns 503 `access_not_ready`. Renaming remains a separate PATCH `/api/v1/devices/<id>`, avoiding a combined cross-file transaction.

Self-mode management keeps the trusted-LAN shared-access behavior; managed mode requires an admin session. Origin and CSRF checks are not authentication. Remote deployments still need HTTPS and correct proxy configuration.

All management POST/PUT/PATCH/DELETE requests require a CSRF token and the matching `webclock_csrf` session cookie, including settings, reminders, backup imports, previews, and device sync commands. Management pages supply them automatically. Other clients must GET `/api/csrf`, retain its cookie, and send the returned `csrf_token` as `X-CSRF-Token`; HTML forms use a hidden `csrf_token` field. Managed clients must also sign in through HTTPS `/login` and use the new CSRF token returned after login. Omitting Origin does not bypass CSRF validation. Missing or invalid CSRF tokens return 403 `csrf_failed`; a missing or expired managed session returns 401 `authentication_required` for API/JSON requests before management writes run. Cross-origin metadata is rejected with 403 (`cross_origin_forbidden` at the managed access guard, otherwise `csrf_failed` at the CSRF check). See the [request example](server-api.md#管理-api).

Reminder deletion `/delete/<id>` accepts only token-protected POST; GET/HEAD return 405. Management HTML, error pages, and token responses use `no-store` without cross-origin read access. Uninitialized self mode uses an ephemeral signing secret, so a restart invalidates its CSRF cookies. Once authorization state is initialized, the signing secret persists across ordinary restarts; login/logout rotates the CSRF token, and host password recovery invalidates all managed sessions. Reload the management page or obtain a new CSRF token after an invalidation. The public clock needs no CSRF cookie. Only in self mode does `/api/v1/device/*` retain the independent `DEVICE_API_TOKEN` contract without CSRF; managed mode rejects those legacy calls. CSRF protection itself does not authenticate users.

Each `/api/calendar` source contains `id`, `name`, `provider`, `url`, and `display_enabled`; `local_display_enabled` controls local reminders. Keep IDs stable when updating because alarms reference them. POST saves the complete source set; PATCH accepts source IDs, display flags, and per-item display rules described above. URLs appear only in the dedicated management response and never in clock, schedule, device, backup, or offline-cache output.

`GET /api/v1/calendar-events` requires existing source IDs and returns `events` plus `server_time`. Event fields are `source_id`, `uid`, `text`, `starts_at`, `ends_at`, `all_day`, `recurring`, and `recurrence_id`; timestamps are Unix milliseconds and subscription URLs are excluded. Canceled/deleted events disappear from the catalog without changing an existing target to another event. If any requested source cannot be read, the endpoint returns 503 `calendar_not_ready`, not a partial or empty success response; the management UI retains current selections.

`POST /api/v1/schedules/preview` returns `server_time`, `timezone`, and `next_occurrence`, plus `skipped_occurrence` for `skip_next: true`. The editor uses server time for the next-ring countdown. The resume countdown ends at the skipped time, not the following ring. `PUT /api/v1/schedules/<id>` may save edits with `skip_next: "full preview timestamp"`; `POST /api/v1/schedules/<id>/skip-next` accepts `expected_occurrence` to reject stale previews with 400 `Occurrence changed; preview again`. Permanent disable uses `enabled=false`. Early resume keeps expired skips, removes future skips, and sets `enabled=true`.

## Browser alarms

In self mode, `GET /api/v1/browser-alarms` returns the following fields. Managed mode returns 401 `device_authorization_required`, including when the browser has an administrator session.

| Field | Meaning |
| --- | --- |
| `server_timestamp` | Unix milliseconds used to calibrate trigger time |
| `enabled_count`, `enabled_ids` | all enabled alarms, including those without a next occurrence |
| `alarms` | fixed alarms' next occurrence plus due/current and first future linked events, up to 1000 |
| `alarms[].occurrence_id` | occurrence identifier used to prevent duplicate playback |
| `alarms[].starts_at` | trigger time in Unix milliseconds |
| `alarms[].sound` | browser tone from `browser_sound` |
| `alarms[].volume` | 0–100 from `browser_volume`; updated pages default to 100 when older responses omit it |
| `holiday_coverage`, `holiday_known` | holiday-data range and availability |

The query starts at the current minute so API latency does not skip an alarm that just became due. It is not a complete offline schedule snapshot. The page refreshes about every 15 seconds. A loaded next occurrence can fire during a brief disconnection, but reopening or loading later occurrences requires a connection. Alarms processed more than 60 seconds late are not replayed.

The page synthesizes seven tones with native Web Audio and also provides `silent` mode. Users must tap the bell and hear a confirmation after every page load. iOS may interrupt audio and timers when switching apps or tabs or locking the screen; keep the page visible and the screen on. Background or locked-screen alarms are not guaranteed.

The visual alert pulses the red border every two seconds. Users may disable flashing for a steady border, and browsers with `prefers-reduced-motion` also use a steady border. Two separate taps dismiss only the current occurrence on the current page; schedules and other devices are unchanged.

## Device API

Device paths remain under `/api/v1/device/*`; configuration responses use **`schema_version: 2`**. The device API does not expose old hardware playback fields. `browser_sound` and `browser_volume` describe browser playback, not portable hardware commands. The ESPHome prototype explicitly maps all non-silent tones to one beep and scales volume by a device limit; see its [hardware mapping](esp-home.md#顯示聲音與按鍵). Schema 1 prototypes must be updated.

| Path | Method and purpose |
| --- | --- |
| `/api/v1/device/config` | GET schema, timezone, and three revisions |
| `/api/v1/device/schedules` | GET revision and schedules |
| `/api/v1/device/holidays` | GET calendar snapshot, provenance, range, and revision |
| `/api/v1/device/register` | POST device `id` and `name`; returns 201 |
| `/api/v1/device/status` | POST status and acknowledgements; returns device and pending commands |

Schedule and holiday endpoints are read-only. In self mode, set `DEVICE_API_TOKEN` in `.env` and send `Authorization: Bearer <token>` for all device calls; an empty value keeps trusted-LAN access. This is one shared token, not per-device identity, and does not protect management APIs or authorize any legacy device endpoint in managed mode.

### Transport, scope, and input limits

POST bodies must be JSON objects with `Content-Type: application/json`; unknown fields are rejected. Requests are limited to 1 MiB. GET responses use `Cache-Control: private, no-cache`; registration and status use `no-store`. A supplied Origin must match the server origin. Validate HTTPS certificates on the device.

GET does not require registration and does not filter by device ID, date range, or page. Schedules include disabled records and non-alarm types; clients must evaluate their rules. Calendar-linked schedules are excluded entirely. The holiday snapshot is the complete government workday table, not subscribed calendar events: currently 1826 dates, roughly 122 KB or more depending on serialization. Its `days` object is keyed by date, with `type`, `name`, and `makeup_workday` values. Dates outside coverage are absent and must be treated as unknown. Config has no server time; devices need a separate time source.

| Request | Accepted input |
| --- | --- |
| register | Required `id` and `name`; optional `device_type` and `capabilities`. ID: 1–64 ASCII letters, digits, underscores or hyphens. Name: nonblank string, input length at most 100; surrounding whitespace is trimmed |
| status | Required `id`; optional `firmware`, `config_revision`, `schedule_revision`, `holiday_revision`, `acknowledged_commands`, `device_type`, and `capabilities` only |
| Status strings | Nonblank strings, input length at most 128 each; trimmed on save. Omission preserves old values; null or empty strings cannot clear them |
| `device_type` | Optional self-reported nonblank string, input length at most 50; trimmed on save, with no fixed hardware enumeration. Omission preserves the previous value |
| `capabilities` | Nonempty object with only `display`, `audio`, `notifications`, `background`, and `calendar` keys. Values must be JSON booleans; empty objects, null, unknown keys, and `0`/`1` are rejected |
| ACK list | At most 100 IDs, each using the device ID format |

Supplying `capabilities` replaces the whole previous capability object and updates server-generated `capabilities_reported_at`; omission preserves both. A missing capability is unknown, not `false`. Until reported, `device_type`, `capabilities`, and `capabilities_reported_at` are `null`. These are self-reported observations, not verified hardware results or authorization decisions.

Management PATCH `/api/v1/devices/<id>` accepts only `{"name":"Living-room clock"}` and requires the management CSRF token. The input must be a nonblank string of at most 100 characters, trimmed on save; blank/empty strings, null, and extra fields return 400. Success returns `{"device":{...}}`. Effective `name` prefers `admin_name`, otherwise `reported_name`; `admin_name` is initially `null`. Re-registration updates the reported name without overwriting the administrator name. Existing records containing only `name` remain readable. Names and capability data persist in `devices.json`; clearing the administrator name is not currently supported.

Repeated registration still returns 201, updates the reported name, and preserves previous status and commands. Registration itself does not update the heartbeat; new devices have `online: false`, `sync_status: {"state":"idle"}`, and no `last_seen`. Status returns 200 with `device` and `commands`; the same pending list also appears under `device.commands`. Server-generated registration, heartbeat, and command timestamps are UTC ISO strings, not Unix milliseconds. RTC, Wi-Fi, battery, error, and actual ringing fields are not accepted yet. Reported revision strings are stored without proving that the device persisted or executed anything.

Validation errors use 400; token failures 401; Origin failures 403; missing registered devices 404; unsupported methods 405; oversized bodies 413; missing JSON Content-Type 415; storage I/O failures 500. Application API routing errors return JSON; proxy error pages may still be HTML, so check HTTP status and Content-Type before parsing. Retry transient failures with backoff; do not ACK failed synchronization or downgrade to an empty token after authentication failure. Complete response examples and management input limits are in the [Traditional Chinese reference](server-api.md#裝置-api).

### Synchronization flow

1. Register with a stable device `id`.
2. GET `config` and verify `schema_version=2`.
3. Compare revisions and download only changed schedules or holidays; fetch everything on first connection.
4. Check each downloaded revision against the first config, then GET `config` again. Retry if the version set changed. Only after validation and durable storage succeed, switch configuration, schedules, holidays, and their revisions together.
5. POST `status` with persisted revisions. The server does not treat a download as proof that hardware executed a schedule.

Revisions are SHA-256 strings. All three GET resources support `If-None-Match` or `?revision=...` and return 304 when unchanged. For `config`, use its response ETag rather than `config_revision`, because the ETag also covers schedule and holiday revisions. Holiday snapshot `schema_version=1` describes only that snapshot format and is separate from device configuration schema 2.

Treat revisions as opaque values; do not hash raw HTTP bodies or order revisions as timestamps. Preserve each resource's own ETag. A 304 has no body and is usable only with a complete, validated local copy; missing or damaged cache requires an unconditional download. The second config check must compare with the first config from the same synchronization attempt.

Replace the complete snapshot only after validation and durable storage, including deletions and a valid empty schedule list. Do not silently truncate oversized responses. On download, parsing, schema, or storage failure, retain the previous complete valid snapshot and do not report new revisions or ACK. Polling must not block local timekeeping or alarms. No current device contract provides authorization expiry or immediate offline revocation.

### Status and command acknowledgement

The minimum status is `{"id":"bedroom"}`. Optional string fields preserve their previous values when omitted:

```json
{
  "id": "bedroom",
  "firmware": "0.1.0",
  "config_revision": "saved config revision",
  "schedule_revision": "saved schedule revision",
  "holiday_revision": "saved holiday revision",
  "acknowledged_commands": ["completed sync command ID"]
}
```

`online` means a status report was received within 120 seconds. About one report per 60 seconds is a general recommendation; the ESPHome prototype checks and reports about every 30 seconds, backing off on failures. **Request sync** queues only a `sync` command. It remains in status responses until acknowledged. Repeated requests keep one pending command. Devices should deduplicate by command ID and acknowledge only after persistence and activation succeed.

Every `device` also includes `sync_status`, without changing command polling or ACK input:

| `state` | Meaning and additional fields |
| --- | --- |
| `idle` | No pending command or saved ACK |
| `pending` | Waiting for ACK; `command_id`, `requested_at`, `timeout_at` |
| `timed_out` | At least 300 seconds since the request without ACK; same fields as `pending` |
| `confirmed` | Latest matching ACK saved; `command_id`, `requested_at`, `acknowledged_at` |

Times are server-generated UTC ISO strings. Timeout does not cancel the command; repeat requests retain its ID and original request time, and a late matching ACK can confirm it. Unknown IDs, another device's command IDs, and duplicate ACKs do not confirm another command or change the saved acknowledgement time. Pending commands and the last ACK survive server restarts; a new sync request takes precedence as `pending`. Matching reported revisions do not create an ACK, and `confirmed` is a device acknowledgement, not proof of successful sound or display output.

Reproducible request → poll → ACK sequence (example IDs):

1. `POST /api/v1/device/register` with `{"id":"bedroom","name":"Bedroom"}`.
2. Management sends `POST /api/v1/devices/bedroom/commands` with `{"action":"sync"}`. Call the returned `command.id` `C`; 202 is queued, not completed.
3. The device sends `POST /api/v1/device/status` with `{"id":"bedroom"}` and receives `C` in `commands`. Polling without ACK returns the same pending command, including after a server restart.
4. The device downloads, validates, and persists data using the sync flow above, then posts its three saved revisions and `"acknowledged_commands":["C"]` to `status`.
5. The response no longer includes `C`, and refreshing the management list removes the pending command. Retry the ACK if its successful response is lost. On sync failure, keep the old cache and do not ACK. Only this device's matching command is removed.

The UI's “sync requested,” `online`, matching revisions, or an absent pending command do not prove that hardware rang successfully.

### Planned extensions

A rolling multi-day trigger list, such as seven days with an expiry, is a proposal with no current endpoint or schema. `/api/v1/browser-alarms` is not such an offline snapshot. New support must cover calendar-source changes, renewal even when settings do not change, deletion, capacity, and authorization scope without changing schema 2 semantics. B2–B4 provides browser enrollment, per-device credentials, group display, and individual authorization lifecycle controls. Hosts can explicitly switch with `--enable-managed`; `--enable-managed-test` remains a compatible alias. ESP integration with the new contract remains future work. See the [ESPHome guide](esp-home.md) (Traditional Chinese) for development stages and physical acceptance checks.

## Legacy data and storage

- Old audio APIs, sound files, the hardware sound service, and the simulated Python device were removed. The only current device command is `sync`.
- Legacy schedule and device fields remain in stored files when present but are not exposed or applied. New APIs reject them.
- Existing user data under `webclock_state/sounds/` or `webclock_state/fake-device/` is not deleted, but the server no longer reads it.
- Legacy root `manual_notes.json` is copied once to the state directory. `NOTES_FILE` and `WEBCLOCK_STATE_DIR` remain supported overrides.

Back up the complete state directory, reminders, and `.env`. The `/admin` JSON export contains only display settings and manual reminders, not schedules or devices. See the [English guide](guide_en.md#backups-data-and-updates) for update and migration steps.

One server process writes JSON, with limits of 1000 schedules and 100 devices. Move to transactional cross-process storage before adding multiple workers.

## Verification

```bash
python -m unittest discover -s tests -p 'test_*.py'
node tests/test_clock.js
node tests/test_time_format.js
node tests/test_offline.js
node tests/test_schedule_ui.js
node tests/test_alarms.js
node tests/test_calendar_ui.js
node tests/test_management_navigation.js
node tests/test_management_theme.js
node tests/test_group_ui.js
node tests/test_device_enrollment.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

Tests cover management CRUD, workdays, make-up workdays, skips, revisions, access checks, device reporting, acknowledgements, and legacy-data preservation. Update integration tests exercise real old/new server processes and Git/data rollback, but systemd, pip, and Linux service queries are mocked. They do not prove deployment on a target host or physical hardware acceptance.

See the [phase-one acceptance record](phase1-acceptance.md) for local verification, pending iPad mini 1 / iOS 9 checks, and Taiwan calendar maintenance after 2027 (Traditional Chinese).
