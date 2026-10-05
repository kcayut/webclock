<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

[繁體中文](README.md) · **English** · [日本語](README_jp.md)

**[Open WebClock](https://kcayut.github.io/webclock/)**

Turn an iPad, tablet, or spare screen into a large clock. Use the public clock directly, or self-host it for calendars, reminders, browser alarms, night mode, and backups.

> [!IMPORTANT]
> Browser alarms require the page to remain visible with the screen on. Audio and timers are not guaranteed after iOS locks the screen or switches apps.

## Two ways to use WebClock

- **Use it online:** open the [public clock](https://kcayut.github.io/webclock/). No account or server is required. Time and timezone follow the device.
- **Self-host it:** run the full version on a computer, NAS, or Raspberry Pi. `/admin` manages the display, calendars, and text reminders; `/schedules` manages alarms and device status.

The self-hosted UI supports Traditional Chinese, English, and Japanese. It can subscribe to Google, Apple iCloud, and other ICS calendars. Calendar URLs stay on your server and are excluded from the public clock, status responses, and admin-page JSON exports; complete host backups still contain private data.

The clock renders time, date, and weekday first; connection, browser-storage, or optional-feature failures should not stop an already loaded page running in the foreground. Device management supports naming, reported capabilities, and sync confirmation. Groups, six-character enrollment, per-device authorization and revocation are available for isolated managed-mode testing; production mode migration, moving and disabling devices remain pending. See the [guide](doc/guide_en.md#device-sync-status) for operation and limits, and the [phase-A acceptance record](doc/phase-a-acceptance.md) for current evidence and pending checks (Traditional Chinese). CI and iPad mini 1 / iOS 9 physical acceptance are tracked separately.

## Quick installation

Clone the project and create the configuration file:

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
```

Choose one method:

```bash
# Docker (default: http://HOST_IP/)
touch manual_notes.json
mkdir -p webclock_state
docker compose up -d --build

# Raspberry Pi OS / Ubuntu / Debian (default port: 5000)
sudo bash setup.sh

# Manual Python run
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open the clock home page when installation finishes. Management is at `/admin`; alarms and devices are at `/schedules`.

Set the initial interface language in `.env` before deployment with `WEBCLOCK_LANGUAGE=zh-TW`, `en`, or `ja`. The Linux installer asks when it first creates `.env`. After deployment, the language remains available at the bottom of the management sidebar and is saved to `webclock_state/settings.json`.

**More information:** [English guide](doc/guide_en.md) · [Device API](doc/server-api_en.md) · [ESPHome development guide](doc/esp-home.md) · [Firmware preparation](firmware/README.md) (last two links: Traditional Chinese; no installable firmware yet).

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
