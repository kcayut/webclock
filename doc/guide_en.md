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
```

Enter calendar URLs in the admin page, not in `.env`. Existing installations may continue using `ICAL_URL` until calendar sources are first saved in the admin page.

## Calendars and text reminders

Under **Calendars & reminders** in `/admin`, expand **Calendar source settings** to add named Google, Apple iCloud, or other ICS sources. Multiple sources are supported. URLs remain masked until the eye button is pressed and are masked again after saving.

Source settings and clock display selection are saved separately. Hiding a source does not delete its URL or change alarm source selection. URLs are stored in `webclock_state/calendar.json` and are excluded from the public clock, status APIs, and downloaded backups. Never commit this file or private URLs to a public repository.

### Apple iCloud

1. Open [iCloud Calendar](https://www.icloud.com/calendar/) and sign in.
2. Open the calendar information button, enable **Public Calendar**, and copy the link.
3. Paste the `webcal://` or HTTPS link into WebClock and save it.

WebClock refreshes the read-only source about every five minutes. It does not need Apple credentials and does not sync the Apple Reminders app. Anyone with the public link can read the calendar, so use a separate calendar containing only items intended for the clock and stop public sharing when it is no longer needed. Masking the URL on screen does not change its access permissions.

### Text reminders

Manual reminders can use a specific date and time or a daily/weekly display window. No selected weekday means every day. An overnight window belongs to its starting day. Start and end cannot be equal; clear both fields to remove the window. Windows include the start, exclude the end, and use the admin timezone.

Expired reminders are hidden rather than deleted. Pausing preserves the content but stops display until resumed. During a brief server disconnection, the loaded clock continues with saved display settings and browser-local reminders; calendars and server reminders return after reconnection.

## Calendar-linked alarms

Each alarm can independently select one or more calendar sources, including local reminders:

- **Alarm at event time:** trigger 0–1440 minutes before a timed event; all-day events are ignored.
- **Alarm if the day has an event:** trigger at the alarm's fixed time when any selected source has an event that day; all-day and multi-day events count.

Alarm selection is independent from clock display selection. Weekday, explicit-date, and Taiwan holiday conditions still apply and are evaluated against the actual alarm date in Taiwan. A failed or removed source produces no alarms, while other readable sources continue to work.

## Browser alarms on iPad

1. Add an alarm in `/schedules`, choosing its time, recurrence, and bell, beep, digital, or silent mode.
2. Daily, weekday, and explicit-date rules may skip Taiwan holidays; make-up workdays remain workdays. Holiday-only and skip-holiday rules cannot be combined.
3. On the iPad clock page, tap the bell to enable audio and confirm the short sound. Enable it again after every reload or reopen.
4. When an alarm fires, tap twice to dismiss only this occurrence on the current page. The schedule and other devices remain active.

Keep Safari in the foreground with the screen on, and check volume and mute settings. iOS may interrupt web audio and timers after screen lock, app switching, or tab switching, so background and locked-screen alarms are not guaranteed. Silent alarms still show the red-border alert.

The page refreshes each alarm's next occurrence about every 15 seconds. A loaded next occurrence can fire during a short disconnection, but reopening the page or loading later occurrences requires a connection. Alarms processed more than 60 seconds late are not replayed. Dates outside holiday-data coverage remain unknown rather than guessed.

## Night mode and offline use

Choose 24-hour or 12-hour (AM/PM) time under **Display settings → Time format**. The setting applies to clock, alarm, calendar reminder, and night-mode time displays and inputs. The default remains 24-hour time; switching formats does not change the actual scheduled times.

Automatic night mode can set a daily start time, restore time, dim level, or black screen. It changes only the web page, not the hardware backlight or Auto-Lock setting. Manual black screen takes priority.

Offline reopening of the self-hosted clock requires HTTPS or localhost and a compatible browser. Plain `http://LAN_IP` cannot prepare the offline cache, although an already loaded page can continue ticking. The cache contains only the clock shell and display assets, never admin pages, APIs, private calendars, or server reminders.

## Backups, data, and updates

The admin page can download and import JSON backups. After validation and confirmation, an import replaces server display settings and manual reminders. Limits are 1 MiB, 1,000 reminders, and 1,000 characters per reminder. Pre-import data is stored in `webclock_state/before-import.json` and replaced on each import.

Downloaded backups exclude calendar URLs, `.env`, and browser-local reminders. Before moving a host or updating, separately preserve:

- `.env`
- `manual_notes.json` from older installations
- the complete `webclock_state/` directory

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
