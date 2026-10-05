# WebClock Server: Central Management and Device API

[繁體中文](server-api.md) · **English** · [日本語](server-api_jp.md) · [README](../README_en.md)

This project manages schedules, Taiwan workday data, device registration, synchronization revisions, and device status. It also lets the self-hosted clock page run browser alarms. `/schedules` edits and previews alarms, `/` plays built-in browser tones and shows a red-border alert, and `/admin` separately manages display settings, subscribed calendars, and text reminders.

Device execution remains a firmware responsibility. [`firmware/`](../firmware/README.md) now contains an ESP32-S3 ESPHome prototype that cross-compiles successfully, with an OLED, fixed-rule alarm synchronization, persistent cache, passive piezo output, and a stop button. Physical hardware has not been validated. Calendar-linked alarms, faithful browser tones/audio files, snooze, battery-backed RTC, OTA, and a generic public firmware image remain unimplemented. Devices integrate through HTTP/JSON and do not import this project's Python modules.

See the [ESPHome device guide](esp-home.md) and [detailed API examples](server-api.md#裝置-api), both in Traditional Chinese, for the current prototype workflow, limitations, and complete response examples. Each boot requires valid time and successful server configuration validation before alarms activate; cached alarms can continue through network loss during that run, but do not activate automatically after an offline reboot.

There is currently one shared management space: **all devices use the same schedules and calendars**. Per-device schedule assignment, multi-tenancy, and user accounts are not implemented.

## Startup and layout

Use `python app.py`, Docker Compose, or the existing systemd service. Open alarm management from `/admin` or go directly to `/schedules`.

```text
app.py / setup.sh / update_clock.py / update_clock.sh  compatible deployment entry points
webclock/
  app.py                     clock, settings, calendars, and startup
  api/
    management.py            management pages and schedule/device APIs
    device.py                device configuration, schedules, calendar, and status APIs
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

APIs accept JSON. Matched API routes return errors as `{"error":"..."}`: data validation returns 400, missing items 404, and failed storage writes 500 while retaining previous data. Other HTTP errors are listed below; unknown routes, unsupported methods, and proxy responses need not be JSON. Request bodies are limited to 1 MiB.

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
| `/api/v1/devices/<id>` | PATCH `{"name":"Living-room clock"}`; returns 200 with `device` |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`; returns 202 |

Management APIs assume a trusted LAN and have no login. The server rejects browser requests from a different Origin, but this is not full authentication. Restrict remote deployments at a reverse proxy and enable HTTPS.

All management POST/PUT/PATCH/DELETE requests require a CSRF token and the matching `webclock_csrf` session cookie, including settings, reminders, backup imports, previews, and device sync commands. Management pages supply them automatically. Other clients must GET `/api/csrf`, retain its cookie, and send the returned `csrf_token` as `X-CSRF-Token`; HTML forms use a hidden `csrf_token` field. Omitting Origin does not bypass this check. Missing, invalid, or expired tokens and cross-origin Origin/Referer or `Sec-Fetch-Site: cross-site` return 403 with `code: "csrf_failed"`. See the [request example](server-api.md#管理-api).

Reminder deletion `/delete/<id>` accepts only token-protected POST; GET/HEAD return 405. Management HTML, error pages, and token responses use `no-store` without cross-origin read access. A restart of the current single server process invalidates old tokens: reload the management page or obtain a new token. The public clock needs no CSRF cookie. `/api/v1/device/*` keeps its independent `DEVICE_API_TOKEN` contract and needs no CSRF token. CSRF protection does not authenticate users who can directly reach the server.

Each `/api/calendar` source contains `id`, `name`, `provider`, `url`, and `display_enabled`; `local_display_enabled` controls local reminders. Keep IDs stable when updating because alarms reference them. POST saves the complete source set, while PATCH accepts only source IDs and display flags. URLs appear only in the dedicated management response and never in clock, schedule, device, backup, or offline-cache output.

`GET /api/v1/calendar-events` requires existing source IDs and returns `events` plus `server_time`. Event fields are `source_id`, `uid`, `text`, `starts_at`, `ends_at`, `all_day`, `recurring`, and `recurrence_id`; timestamps are Unix milliseconds and subscription URLs are excluded. Canceled/deleted events disappear from the catalog without changing an existing target to another event.

`POST /api/v1/schedules/preview` returns `server_time`, `timezone`, and `next_occurrence`, plus `skipped_occurrence` for `skip_next: true`. The editor uses server time for the next-ring countdown. The resume countdown ends at the skipped time, not the following ring. `PUT /api/v1/schedules/<id>` may save edits with `skip_next: "full preview timestamp"`; `POST /api/v1/schedules/<id>/skip-next` accepts `expected_occurrence` to reject stale previews with 400 `Occurrence changed; preview again`. Permanent disable uses `enabled=false`. Early resume keeps expired skips, removes future skips, and sets `enabled=true`.

## Browser alarms

`GET /api/v1/browser-alarms` returns:

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

Schedule and holiday endpoints are read-only. Set `DEVICE_API_TOKEN` in `.env` and send `Authorization: Bearer <token>` for all device calls. An empty value keeps trusted-LAN mode. This is one shared token, not per-device identity, and does not protect management APIs.

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

Validation errors use 400; token failures 401; Origin failures 403; missing registered devices 404; unsupported methods 405; oversized bodies 413; missing JSON Content-Type 415; storage I/O failures 500. Check HTTP status and Content-Type before parsing: routing errors or proxy pages may be HTML. Retry transient failures with backoff; do not ACK failed synchronization or downgrade to an empty token after authentication failure. Complete response examples and management input limits are in the [Traditional Chinese reference](server-api.md#裝置-api).

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

A rolling multi-day trigger list, such as seven days with an expiry, is a proposal with no current endpoint or schema. `/api/v1/browser-alarms` is not such an offline snapshot. New support must cover calendar-source changes, renewal even when settings do not change, deletion, capacity, and authorization scope without changing schema 2 semantics. Per-device credentials, pairing, account ownership, and deployment-mode switching are also unimplemented. See the [ESPHome guide](esp-home.md) (Traditional Chinese) for development stages and physical acceptance checks.

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
bash -n setup.sh scripts/setup.sh update_clock.sh
```

Tests cover management CRUD, workdays, make-up workdays, skips, revisions, access checks, device reporting, acknowledgements, and legacy-data preservation. Update integration tests exercise real old/new server processes and Git/data rollback, but systemd, pip, and Linux service queries are mocked. They do not prove deployment on a target host or physical hardware acceptance.

See the [phase-one acceptance record](phase1-acceptance.md) for local verification, pending iPad mini 1 / iOS 9 checks, and Taiwan calendar maintenance after 2027 (Traditional Chinese).
