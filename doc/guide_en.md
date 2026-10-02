# WebClock English Guide

[README](../README_en.md) · [繁體中文](guide.md) · [日本語](guide_jp.md) · [Device API](server-api_en.md)

## Public clock

Open the [WebClock public clock](https://kcayut.github.io/webclock/) directly. No account or server is required. Time and timezone follow the device; the date and weekday are displayed in Traditional Chinese. Landscape orientation is recommended. In iPad Safari, use **Share → Add to Home Screen** for quick access.

WebClock was originally designed for the first-generation iPad mini and keeps the clock page simple for old tablets. Adjust Auto-Lock and screen brightness in the device settings when using it as a persistent display.

In browsers with offline-cache support, connect once and wait until the connection panel reports that offline use is ready. Old Safari can still load the clock online and keep an already loaded page ticking after disconnection, even when it cannot reopen offline. Clearing site data or browser cache requires another online setup.

## Self-hosting

The self-hosted version provides these routes:

- `/`: clock page.
- `/admin`: display settings, calendars, text reminders, backup, and restore.
- `/schedules`: browser alarms and device sync status.

Docker uses host port `80` by default. The Linux installer and manual run default to port `5000`. See the [README quick installation](../README_en.md#quick-installation) for commands. Basic `.env` settings are:

```env
PORT=5000
HOST=0.0.0.0
WEBCLOCK_LANGUAGE=en
```

`WEBCLOCK_LANGUAGE` sets the interface language on first start and accepts `zh-TW`, `en`, or `ja`. You can switch it later at the bottom of the management sidebar. That choice is saved to `webclock_state/settings.json` and takes precedence over the deployment default.

Under **Appearance** in the management sidebar, choose the sun for **Light** or the moon for **Dark**. The selected icon is highlighted; light is the default. Navigation and content share the same palette. The choice stays in this browser’s same-origin `localStorage`, shared by `/admin` and `/schedules` and retained on reopening. It does not change the main clock or server display settings. Theme changes do not reload the page, so unsaved form values remain.

Enter calendar URLs in the admin page, not in `.env`. Existing installations may continue using `ICAL_URL` until calendar sources are first saved in the admin page.

## Calendars and text reminders

Under **Calendars & reminders** in `/admin`, expand **Calendar source settings** to add named Google, Apple iCloud, or other ICS sources. Multiple sources are supported. URLs remain masked until the eye button is pressed and are masked again after saving.

Source settings and clock display selection are saved separately. Hiding a source does not delete its URL or change alarm source selection. URLs are stored in `webclock_state/calendar.json` and are excluded from the public clock, status APIs, and JSON backups downloaded from the admin page. Never commit this file or private URLs to a public repository.

### Apple iCloud

1. Open [iCloud Calendar](https://www.icloud.com/calendar/) and sign in.
2. Open the calendar information button, enable **Public Calendar**, and copy the link.
3. Paste the `webcal://` or HTTPS link into WebClock and save it.

WebClock refreshes the read-only source about every five minutes. It does not need Apple credentials and does not sync the Apple Reminders app. Anyone with the public link can read the calendar, so use a separate calendar containing only items intended for the clock and stop public sharing when it is no longer needed. Masking the URL on screen does not change its access permissions.

### Text reminders

Manual reminders can use a specific date and time or a daily/weekly display window. No selected weekday means every day. An overnight window belongs to its starting day. Start and end cannot be equal; clear both fields to remove the window. Windows include the start, exclude the end, and use the admin timezone.

Expired reminders are hidden rather than deleted. Pausing preserves the content but stops display until resumed. During a brief server disconnection, the loaded clock continues with saved display settings and browser-local reminders; calendars and server reminders return after reconnection.

### Browser-local reminders and the connection panel

Open the connection panel with the connection-status button at the bottom left of the clock. Enter reminder text and an optional time, then add or delete it. These reminders stay in `localStorage` for the current site and browser and appear when the server is unavailable. The time is display text: it does not play a sound or hide the reminder afterward. New reminders have no date and remain until deleted; edit by deleting and adding again.

Browser-local reminders are not uploaded, shared across devices, or included in server backups. Clearing site data removes them. They are separate from the server's **Local reminders** source in `/admin` and cannot drive calendar-linked alarms. After reconnection, the clock displays server events and reminders again; browser-local items remain in the panel.

The same panel saves the Server URL; use **Reconnect now** to test it. Saving alone does not confirm a connection, so check the reported status. Opening the clock at another origin uses separate site storage. Saving local reminders and reopening offline are separate capabilities; offline reopening still requires the cache conditions below.

## Calendar-linked alarms

Each alarm can independently select one or more calendar sources, including server-local reminders from `/admin`:

- **Alarm at event time:** trigger 0–1440 minutes before a timed event; all-day events are ignored.
- **Alarm if the day has an event:** trigger at the alarm's fixed time when any selected source has an event that day; all-day and multi-day events count.

Alarm selection is independent from clock display selection. Weekday, explicit-date, and Taiwan holiday conditions still apply and are evaluated against the actual alarm date in Taiwan. A failed or removed source produces no alarms, while other readable sources continue to work.

After selecting sources, you can target one event and choose an occurrence or the entire recurring series. Without a target, the alarm follows all events from the selected sources. Occurrence links keep the original event identity across rescheduling and do not switch to another event after cancellation; series links follow that series. Subscription changes may take up to about five minutes to refresh; check the next-ring preview afterward.

## Browser alarms on iPad

1. Add an alarm in `/schedules` and choose its time and weekdays or date. “Every day” selects all seven weekdays, hides when all are selected, and reappears when any day is unchecked. Choose bell, beep, digital, chime, melody, pulse, sonar, or silent mode. Each alarm has its own 0–100% volume, defaulting to 100%; preview uses the same volume, and 0% keeps visual alerts only.
2. Daily, weekday, and explicit-date rules may skip Taiwan holidays; make-up workdays remain workdays. Holiday-only and skip-holiday rules cannot be combined.
3. On the iPad clock page, tap the bell to enable audio and confirm the short sound. Enable it again after every reload or reopen.
4. When an alarm fires, tap twice to dismiss only this occurrence on the current page. The schedule and other devices remain active.

Keep Safari in the foreground with the screen on, and check volume and mute settings. iOS may interrupt web audio and timers after screen lock, app switching, or tab switching, so background and locked-screen alarms are not guaranteed. Silent alarms still show the red-border alert.

The page refreshes each alarm's next occurrence about every 15 seconds. A loaded next occurrence can fire during a short disconnection, but reopening the page or loading later occurrences requires a connection. Alarms processed more than 60 seconds late are not replayed. Dates outside holiday-data coverage remain unknown rather than guessed.

## Next event, pause, and resume

The `/schedules` summary shows the next alarm. Its add/edit window shows current Taiwan time, the next ring, and time remaining. The main clock still cycles event/reminder text without an event countdown. Previews and countdowns do not prove execution or successful ringing.

Turning off a fixed-time recurring alarm offers a one-occurrence pause or permanent disable. A one-occurrence pause shows the skipped time and a resume countdown. After that skipped time, the enabled display returns and the next ring still follows the original rule. Turn it on during the pause to resume early; a permanently disabled alarm needs manual re-enabling. Date-based and calendar-linked alarms offer **Skip next** in the editor. Another date cannot be skipped while a future skipped occurrence is still pending.

## Device sync status

**Request sync** on the `/schedules` device page only queues a server command. The device polls by reporting its status, receives `sync`, downloads and validates its cache, then sends an ACK before the pending command disappears. Repeated requests reuse the pending command; an offline device cannot complete immediately. `online` only means a report arrived within 120 seconds. Neither ACK nor reported revisions prove successful ringing. See the [device contract](server-api_en.md#status-and-command-acknowledgement).

## Night mode and offline use

Choose 24-hour or 12-hour (AM/PM) time under **Display settings → Time format**. The setting applies to clock, alarm, calendar reminder, and night-mode time displays and inputs. The default remains 24-hour time; switching formats does not change the actual scheduled times.

Automatic night mode can set a daily start time, restore time, dim level, or black screen. It changes only the web page, not the hardware backlight or Auto-Lock setting. Manual black screen takes priority.

Offline reopening of the self-hosted clock requires HTTPS or localhost and a compatible browser. Plain `http://LAN_IP` cannot prepare the offline cache, although an already loaded page can continue ticking. The cache contains only the clock shell and display assets, never admin pages, APIs, private calendars, or server reminders.

## Backups, data, and updates

The admin page can download and import JSON backups. After validation and confirmation, an import replaces server display settings and manual reminders. Limits are 1 MiB, 1,000 reminders, and 1,000 characters per reminder. Pre-import data is stored in `webclock_state/before-import.json` and replaced on each import.

Admin version 1 JSON backups still contain only settings and manual reminders. They exclude smart schedules, devices, private calendar URLs, `.env`, and browser-local reminders; the existing import and `before-import.json` behavior is unchanged.

### Complete host-side data backup and restore

On Linux/macOS, run `scripts/backup_clock.py` with Python that already has the WebClock dependencies installed. It preserves the current single data space: `.env`, legacy `manual_notes.json`, default and custom state directories, and a custom reminder file, including smart schedules, devices, and `calendar.json` stored there. Source code, venv, runtime environment overrides, systemd units, Docker configuration, and browser localStorage are excluded. Preserve those separately and prepare matching source and dependencies when moving hosts.

**Before creating or restoring a backup, stop every service, container, and other process that writes this data.** `--stopped` is your confirmation; the tool does not stop or start services. Run the following from the installation directory with an account that can read and write the data; use administrator privileges when required to preserve original ownership. Each backup and pre-restore directory must be new and must not overlap data paths.

```bash
mkdir -p -m 700 "$HOME/private-webclock-backups"
venv/bin/python scripts/backup_clock.py create "$HOME/private-webclock-backups/backup-001" --project "$PWD" --stopped
venv/bin/python scripts/backup_clock.py verify "$HOME/private-webclock-backups/backup-001"
```

When a restore is needed, confirm every writer is stopped before running:

```bash
venv/bin/python scripts/backup_clock.py restore "$HOME/private-webclock-backups/backup-001" --project "$PWD" --stopped --yes --rollback-dir "$HOME/private-webclock-backups/before-restore-001"
```

`create` makes a mode `700` backup directory and mode `600` `manifest.json`, then verifies file contents with SHA-256. `verify` checks only the backup and needs no downtime. **Backups are unencrypted and contain private URLs and credentials.** Store them in a private directory outside the project and restrict access. Inside the project, only names matching `.webclock-backup*` are ignored by Git; arbitrary backup directories are not automatically ignored. Symlinks and special files are unsupported.

Target data paths come only from the target host's effective environment, `.env`, and explicit `--state-dir /target/state --notes-file /target/reminders.json` options, never from the source host's archived paths. If service environment overrides select custom paths, explicitly pass the actual paths to `create` and `restore`. Backups using custom locations require corresponding target locations with the same nesting and relative paths within each data root. The tool adjusts `WEBCLOCK_STATE_DIR` / `NOTES_FILE` only when an archived `.env` exists and target data paths differ, preserving its other settings. If the source used runtime environment variables without an `.env`, restore that environment separately before starting services. For Docker, stop the container first, then run host Python with the dependencies installed and pass host mount paths, not container `/app/...` paths. For Docker volumes, establish the actual host data location first.

`restore` requires `--yes` and a new `--rollback-dir`. It retains a complete pre-restore copy before replacing target data; items absent from the backup are restored as absent. It attempts recovery on failure but does not resume automatically after power loss. If recovery is incomplete, keep services stopped and retain the pre-restore copy and `.webclock-restore-*` staging data for recovery. Copies preserve numeric UID/GID. After a privileged restore to another host or an external directory, check that the service account can traverse parent directories and read/write the data. After success, check data, paths, and permissions before manually starting services. This does not establish Raspberry Pi, Docker, or iPad acceptance.

### Updating the application

After obtaining updated source, rebuild Docker with:

```bash
docker compose up -d --build
```

For a service created by the Linux installer, run:

```bash
sudo bash update_clock.sh
```

The updater requires a clean Git worktree and a fast-forward update. Before stopping the service, it validates data paths and backs up the Python environment and state. It attempts rollback on failure. If recovery is incomplete, preserve `.webclock-update-*` and its `manifest.json`, `failed-data/`, and `failed-venv/`. Do not edit admin data during an update, and do not treat local tests as proof of Raspberry Pi deployment.

For the first migration from the old updater, keep the old service running and run the following commands from an installation that tracks `origin/main`:

```bash
git fetch origin
updater_file="$(mktemp /tmp/webclock-updater.XXXXXX)"
git show origin/main:update_clock.py > "$updater_file" &&
    sudo python3 "$updater_file" "$PWD"
```

This entry point loads the new updater and switches source only after validation and backup. Do not run the old update script, `git pull`, or overwrite the installation first. A non-Git installation cannot automatically recover overwritten source, and automatic recovery after power loss is not guaranteed.

See the [phase-one acceptance record](phase1-acceptance.md) for local verification, pending iPad mini 1 / iOS 9 checks, and Taiwan calendar maintenance after 2027 (Traditional Chinese).
