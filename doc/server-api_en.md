# WebClock Server: Central Management and Device API

[繁體中文](server-api.md) · **English** · [日本語](server-api_jp.md) · [README](../README_en.md)

This project manages schedules, Taiwan workday data, device registration, synchronization revisions, and device status. It also lets the self-hosted clock page run browser alarms. `/schedules` edits and previews alarms, `/` plays built-in browser tones and shows a red-border alert, and `/admin` separately manages display settings, subscribed calendars, and text reminders.

Firmware, audio files, speakers, volume, snooze, RTC, buttons, and standalone offline execution belong to a future hardware project. Devices integrate through HTTP/JSON and do not import this project's Python modules.

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
  "enabled": true,
  "skipped_occurrences": []
}
```

- `type`: `alarm`, `reminder`, or `announcement`. The clock page executes only `alarm`; calendar events and text reminders do not automatically become alarms.
- `rule`: one of `{}` for daily, `{"weekdays":[1,3,5]}`, `{"workday_only":true}`, `{"holiday_only":true}`, or `{"dates":["2026-10-03"]}`.
- `skip_holidays`: filters holidays for daily, weekday, or explicit-date rules. Make-up workdays remain workdays. Combining it with `holiday_only=true` returns 400.
- `browser_sound`: `bell`, `beep`, `digital`, or `silent`. It is independent from old hardware sound fields.
- Weekdays use ISO values Monday `1` through Sunday `7`; the legacy reminder API uses `0–6`.
- Schedules always use `Asia/Taipei`, independently from the large clock's display timezone.
- `skipped_occurrences` contains complete timezone-aware timestamps. Skipping the next occurrence does not disable the schedule.
- `next_occurrence` and `next_event` are previews, not execution logs or queued events.

An alarm may include `calendar_link`; omit it or use `null` for a fixed-time schedule.

```json
{"calendar_link":{"mode":"event","source_ids":["local","work"],"offset_minutes":15}}
```

- `event`: fire 0–1440 minutes before timed events; all-day events are ignored.
- `day`: fire at the schedule's fixed `time` when a selected source has an event that day; all-day and multi-day events count.
- `source_ids` contains stable source IDs; `local` means local reminders. Alarm selection is independent from clock display selection.
- Weekday, explicit-date, and holiday filters use the actual alarm date in Taiwan. Preview searches up to 366 days.
- Persistent local text without a date or fixed window does not participate. Missing or unreadable sources do not fall back to daily alarms or stale data.
- The server computes linked alarms for browser use. Schema 2 device responses exclude them so old hardware does not misread them as daily alarms.

The bundled Taiwan calendar covers **2023-01-01 through 2027-12-31**. It follows the government office calendar, not every company's policy, typhoon closures, or personal shifts. Dates outside coverage return `unknown`; holiday-dependent rules do not guess.

## Management API

APIs accept JSON and return errors as `{"error":"..."}`. Invalid input returns 400, missing resources 404, and write failures 500 without overwriting saved data. The request limit is 1 MiB.

| Path | Method and purpose |
| --- | --- |
| `/api/v1/schedules` | GET schedules and previews; POST a schedule |
| `/api/calendar` | GET/POST calendar sources; PATCH display selection only |
| `/api/v1/schedules/<id>` | PUT selected fields; DELETE a schedule |
| `/api/v1/schedules/<id>/skip-next` | POST to skip the next occurrence |
| `/api/v1/browser-alarms` | GET upcoming browser alarms and holiday-data state |
| `/api/v1/holidays?date=2026-09-30` | GET the date classification; defaults to today in Taiwan |
| `/api/v1/devices` | GET registered devices and pending commands |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`; returns 202 |

Management APIs assume a trusted LAN and have no login. The server rejects browser requests from a different Origin, but this is not full authentication. Restrict remote deployments at a reverse proxy and enable HTTPS.

Each `/api/calendar` source contains `id`, `name`, `provider`, `url`, and `display_enabled`; `local_display_enabled` controls local reminders. Keep IDs stable when updating because alarms reference them. POST saves the complete source set, while PATCH accepts only source IDs and display flags. URLs appear only in the dedicated management response and never in clock, schedule, device, backup, or offline-cache output.

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
| `holiday_coverage`, `holiday_known` | holiday-data range and availability |

The query starts at the current minute so API latency does not skip an alarm that just became due. It is not a complete offline schedule snapshot. The page refreshes about every 15 seconds. A loaded next occurrence can fire during a brief disconnection, but reopening or loading later occurrences requires a connection. Alarms processed more than 60 seconds late are not replayed.

The page synthesizes three tones with native Web Audio. Users must tap the bell and hear a confirmation after every page load. iOS may interrupt audio and timers when switching apps or tabs or locking the screen; keep the page visible and the screen on. Background or locked-screen alarms are not guaranteed.

The visual alert pulses the red border every two seconds. Users may disable flashing for a steady border, and browsers with `prefers-reduced-motion` also use a steady border. Two separate taps dismiss only the current occurrence on the current page; schedules and other devices are unchanged.

## Device API

Device paths remain under `/api/v1/device/*`; configuration responses use **`schema_version: 2`**. The device API does not expose old hardware playback fields. `browser_sound` is for the web page only. Schema 1 prototypes must be updated.

| Path | Method and purpose |
| --- | --- |
| `/api/v1/device/config` | GET schema, timezone, and three revisions |
| `/api/v1/device/schedules` | GET revision and schedules |
| `/api/v1/device/holidays` | GET calendar snapshot, provenance, range, and revision |
| `/api/v1/device/register` | POST device `id` and `name`; returns 201 |
| `/api/v1/device/status` | POST status and acknowledgements; returns device and pending commands |

Schedule and holiday endpoints are read-only. Set `DEVICE_API_TOKEN` in `.env` and send `Authorization: Bearer <token>` for all device calls. An empty value keeps trusted-LAN mode. This is one shared token, not per-device identity, and does not protect management APIs.

### Synchronization flow

1. Register with a stable device `id`.
2. GET `config` and verify `schema_version=2`.
3. Compare revisions and download only changed schedules or holidays; fetch everything on first connection.
4. GET `config` again after downloads. Retry if a revision changed, and replace local cache only after validation.
5. POST `status` with persisted revisions. The server does not treat a download as proof that hardware executed a schedule.

Revisions are SHA-256 strings. All three GET resources support `If-None-Match` or `?revision=...` and return 304 when unchanged. For `config`, use its response ETag rather than `config_revision`, because the ETag also covers schedule and holiday revisions. Holiday snapshot `schema_version=1` describes only that snapshot format and is separate from device configuration schema 2.

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

`online` means a status report was received within 120 seconds. About one report per 60 seconds is recommended. **Request sync** queues only a `sync` command. It remains in status responses until acknowledged. Repeated requests keep one pending command. Devices should deduplicate by command ID and acknowledge only after success.

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
node tests/test_offline.js
node tests/test_schedule_ui.js
node tests/test_alarms.js
node tests/test_calendar_ui.js
node tests/test_management_navigation.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

Tests cover management CRUD, workdays, make-up workdays, skips, revisions, access checks, device reporting, acknowledgements, and legacy-data preservation. Update integration tests exercise real old/new server processes and Git/data rollback, but systemd, pip, and Linux service queries are mocked. They do not prove deployment on a target host or physical hardware acceptance.
