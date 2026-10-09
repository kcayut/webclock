<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

[繁體中文](README.md) · **English** · [日本語](README_jp.md)

**[Open the GitHub-hosted clock](https://kcayut.github.io/webclock/)** · [Download and offline use](doc/installation.md#no-server) (Traditional Chinese)

Turn an iPad, tablet, or spare screen into a large clock. Use the public clock directly, or self-host it for calendars, reminders, browser alarms, night mode, and backups.

> [!IMPORTANT]
> Browser alarms require the page to remain visible with the screen on. Audio and timers are not guaranteed after iOS locks the screen or switches apps.

## Three ways to use WebClock

- **Use it online:** open the [public clock](https://kcayut.github.io/webclock/). No account or server is required. Time and timezone follow the device.
- **Download an offline clock:** on a computer, [download and extract the ZIP](doc/installation.md#offline-download), then open its top-level `index.html` in a browser. No server installation is needed. For tablets, see [offline caching and iOS 9 limitations](doc/installation.md#offline-cache) (Traditional Chinese).
- **Self-host it:** run the full version on a computer, NAS, or Raspberry Pi. `/admin` manages the display, calendars, and text reminders; `/schedules` manages alarms and device status.

The self-hosted UI supports Traditional Chinese, English, and Japanese, with Google, Apple iCloud, and other ICS calendars. Private URLs stay out of the public clock, status responses, and legacy JSON exports. Download one complete `.webclock` backup from management to move accounts, private calendars, and device settings to a new server or HA App. Password encryption is enabled by default, with an option to save an unencrypted file. See [backup and migration](doc/guide.md#完整備份與搬家) (Traditional Chinese).

The clock renders time, date, and weekday first; connection, browser-storage, or optional-feature failures should not stop an already loaded page running in the foreground. Device management supports naming, reported capabilities, and sync confirmation. Groups, six-character enrollment, per-device authorization, movement, disable/resume and revocation are available. Managed mode requires explicit host-side activation; existing installations remain in self mode by default. See the [guide](doc/guide_en.md#device-sync-status) for operation and limits, and the [phase-A acceptance record](doc/phase-a-acceptance.md) / [Phase B groups and authorization acceptance](doc/phase-b-acceptance.md) for current evidence and pending checks (Traditional Chinese). CI and iPad mini 1 / iOS 9 physical acceptance are tracked separately.

## Installation options

| Method | Environment |
| --- | --- |
| **Bare metal** | Raspberry Pi OS, Debian or Ubuntu; installs an automatically started systemd service |
| **Docker** | Computers, NAS devices or Linux hosts with Docker Compose |
| **Home Assistant** | Add the App repository on HA OS; install the integration and bundled cards through HACS |

**[Install the HA App](doc/installation.md#home-assistant)** · **[Install the HA integration and cards](doc/home-assistant.md#安裝整合)**

**[Open the installation guide →](doc/installation.md)** (Traditional Chinese): quick commands, prerequisites, self/managed activation and HTTPS setup for all three methods.

With an existing administrator, use `/mode` to [switch self/managed, choose the primary user, and manage members](doc/installation.md#mode-switch). See [multi-account backup and recovery](doc/installation.md#owner-data), [device/group settings](doc/guide.md#群組設定與裝置加入), [shared announcements](doc/guide.md#指定群組或裝置的公告), and [phase 2/4 acceptance](doc/phase2-acceptance.md) for steps, test results, and pending checks (Traditional Chinese).

**[Set up a clock display →](doc/display-devices.md)** (Traditional Chinese): home-screen shortcuts, fullscreen and keeping the screen awake on iPad/iPhone, Android, Windows and Mac, with version-specific steps including iPad mini 1/iOS 9.

Linux and Docker default to **self** mode. For administrator sign-in and per-device authorization, add `--managed` to a fresh installation and configure HTTPS. The HA App protects management through HA sign-in; importing a managed full backup also retains the original WebClock account sign-in. See the [release status](doc/ha-release.md) before installing: the first public image publication and HA OS acceptance are still pending. A local build remains available for development.

**More information:** [English guide](doc/guide_en.md) · [Home Assistant integration and cards](doc/home-assistant.md) · [Device API](doc/server-api_en.md) · [ESPHome development](doc/esp-home.md) · [Firmware](firmware/README.md) (HA and firmware guides: Traditional Chinese).

## Support WebClock

All WebClock features are free to use. If the project helps you, you are welcome to support its development. Thank you!

<!-- Brand assets: https://www.paypalobjects.com/paypal-ui/logos/svg/paypal-mark-color.svg | https://storage.ko-fi.com/cdn/cup-border.png | O’Pay and ECPay logos supplied by the project owner -->
<table>
  <tr>
    <td align="center" width="160"><a href="https://www.paypal.com/paypalme/oilstuck"><img src="doc/images/support/paypal.svg" height="48" alt="Support development via PayPal"><br><strong>PayPal</strong></a></td>
    <td align="center" width="160"><a href="https://ko-fi.com/kcayut"><img src="doc/images/support/ko-fi.png" height="48" alt="Support development via Ko-fi"><br><strong>Ko-fi</strong></a></td>
    <td align="center" width="220"><a href="https://payment.opay.tw/Broadcaster/Donate/6CF8CF9E519E0ED13E244399607ADDD7"><img src="doc/images/support/opay.png" height="48" alt="Support development via O’Pay"><br><strong>O’Pay</strong></a><br>O’Pay member ID: 2218408</td>
    <td align="center" width="160"><a href="https://p.ecpay.com.tw/A2FA21C"><img src="doc/images/support/ecpay.png" height="48" alt="Support development via ECPay"><br><strong>ECPay</strong></a></td>
  </tr>
</table>

## Feedback

Please use [Issues](https://github.com/kcayut/webclock/issues) to report a problem or suggest an improvement.
