<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

[繁體中文](README.md) · **English** · [日本語](README_jp.md)

[Documentation index](doc/README.md) · [Repository layout and maintenance](doc/development/repository-layout.md) (Traditional Chinese)

**[Open the GitHub-hosted clock](https://kcayut.github.io/webclock/)** · [Download and offline use](doc/installation.md#no-server) (Traditional Chinese)

Turn an iPad, tablet, or spare screen into a large clock. Use the public clock directly, or self-host it for calendars, reminders, browser alarms, night mode, and backups.

> [!IMPORTANT]
> Browser alarms require the page to remain visible with the screen on. Audio and timers are not guaranteed after iOS locks the screen or switches apps.

## Three ways to use WebClock

- **Use it online:** open the [public clock](https://kcayut.github.io/webclock/). No account or server is required. Time and timezone follow the device.
- **Download an offline clock:** on a computer, [download and extract the ZIP](doc/installation.md#offline-download), then open its top-level `index.html` in a browser. No server installation is needed. For tablets, see [offline caching and iOS 9 limitations](doc/installation.md#offline-cache) (Traditional Chinese).
- **Self-host it:** run the full version on a computer, NAS, or Raspberry Pi. `/admin` manages the display, calendars, and text reminders; `/schedules` manages alarms and device status.

The self-hosted UI supports Traditional Chinese, English, Japanese, and ICS calendars such as Google and Apple iCloud. Manage displays by group and move accounts and settings with a complete `.webclock` backup. See the [user guide](doc/guides/guide_en.md).

## Installation options

| Method | Environment |
| --- | --- |
| **Bare metal** | Raspberry Pi OS, Debian or Ubuntu; installs an automatically started systemd service |
| **Docker** | Computers, NAS devices or Linux hosts with Docker Compose |
| **Home Assistant** | Add the App repository on HA OS; install the integration and bundled cards through HACS |

**One-command Linux / Raspberry Pi installation:**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh
```

**One-command Docker installation:**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --docker
```

The installer uses the [latest official GitHub release](https://github.com/kcayut/webclock/releases/latest), verifies health, and prints the clock and management URLs. Docker pulls the matching prebuilt image.

**[Install the HA App](doc/installation.md#home-assistant)** · **[Install the HA integration and cards](doc/home-assistant.md#安裝整合)**

Linux and Docker default to self mode without sign-in; use only on a trusted LAN. For administrator sign-in, use [managed](doc/installation.md#https) with HTTPS by default, or explicitly confirm HTTP twice for a trusted LAN. The HA App uses HA sign-in; imported managed backups also require the original WebClock account.

- [Installation guide](doc/installation.md): prerequisites, first run, and troubleshooting.
- [Display setup](doc/guides/display-devices.md): home-screen shortcuts, fullscreen, and keeping the screen awake, including iPad mini 1 / iOS 9.
- [English guide](doc/guides/guide_en.md): calendars, alarms, groups, and backups.
- [Updates and recovery](doc/operations/update-operations.md) · [HTTPS and accounts](doc/operations/accounts-and-https.md).
- [Device API](doc/api/server-api_en.md) · [ESP32-S3 prototype](firmware/README.md) · [Release and hardware validation](doc/ha-release.md).

Installation, maintenance, and hardware documentation is in Traditional Chinese.

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
