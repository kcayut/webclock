<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

**繁體中文** · [English](README_en.md) · [日本語](README_jp.md)

[文件索引](doc/README.md) · [目錄分工與維護](doc/development/repository-layout.md)

**[開啟 GitHub 線上時鐘](https://kcayut.github.io/webclock/)** · [下載與離線使用](doc/installation.md#no-server)

把 iPad、平板或閒置螢幕變成大時鐘。公開版開啟網頁即可使用；自行架設版另外提供行事曆、文字提醒、網頁鬧鐘、夜間模式與備份還原。

> [!IMPORTANT]
> 網頁鬧鐘必須保持瀏覽器在前景且螢幕開啟；iOS 鎖定畫面或切換 App 後，不保證聲音與計時持續。

## 三種使用方式

- **直接使用：**開啟[線上時鐘](https://kcayut.github.io/webclock/)，不需帳號或伺服器。時間與時區跟隨裝置，適合舊 iPad、平板與閒置螢幕。
- **下載離線時鐘：**電腦[下載 ZIP 並解壓縮](doc/installation.md#offline-download)，用瀏覽器開啟最外層的 `index.html`，不必安裝 Server。平板請看[離線快取與 iOS 9 限制](doc/installation.md#offline-cache)。
- **自行架設：**在電腦、NAS 或 Raspberry Pi 執行完整版。`/admin` 管理顯示、行事曆與文字提醒；`/schedules` 管理鬧鐘與裝置狀態。

自行架設版支援繁中、英文、日文，以及 Google、Apple iCloud 等 ICS 行事曆。可依群組管理顯示裝置，並以完整 `.webclock` 備份搬移帳號與設定。詳見[使用指南](doc/guides/guide.md)。

## 安裝方式

| 方式 | 適合環境 |
| --- | --- |
| **Bare metal** | Raspberry Pi OS、Debian、Ubuntu；直接安裝並開機自動執行 |
| **Docker** | 已有 Docker 的電腦、NAS 或 Linux 主機 |
| **Home Assistant** | HA OS 加入 App 來源後點選安裝；Integration 與卡片由 HACS 安裝 |

**Linux／Raspberry Pi 一行安裝：**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh
```

**Docker 一行安裝：**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --docker
```

安裝器使用 [GitHub 最新正式版](https://github.com/kcayut/webclock/releases/latest)，完成健康檢查後提供時鐘與管理頁網址；Docker 直接取得同版預建映像。

**[安裝 HA App](doc/installation.md#home-assistant)** · **[安裝 HA 整合與卡片](doc/home-assistant.md#安裝整合)**

Linux／Docker 預設為免登入的 self 模式，限可信任區網使用；需要帳號登入時，使用 [managed](doc/installation.md#https)：預設 HTTPS，可信任內網可二次確認改用 HTTP。HA App 的管理入口由 HA 登入保護；匯入 managed 備份後仍須登入原 WebClock 帳號。

- [完整安裝指南](doc/installation.md)：前置條件、首次設定與排錯。
- [裝置顯示設定](doc/guides/display-devices.md)：主畫面圖示、全螢幕與恆亮，包含 iPad mini 1／iOS 9。
- [使用指南](doc/guides/guide.md)：行事曆、鬧鐘、群組與備份。
- [更新與復原](doc/operations/update-operations.md) · [HTTPS 與帳號管理](doc/operations/accounts-and-https.md)。
- [裝置 API](doc/api/server-api.md) · [ESP32-S3 原型](firmware/README.md) · [發行與實機驗證狀態](doc/ha-release.md)。

## 支持開發

WebClock 目前所有功能皆可免費使用。如果這個專案對你有幫助，歡迎支持後續開發，謝謝！

<!-- Brand assets: https://www.paypalobjects.com/paypal-ui/logos/svg/paypal-mark-color.svg | https://storage.ko-fi.com/cdn/cup-border.png | O’Pay and ECPay logos supplied by the project owner -->
<table>
  <tr>
    <td align="center" width="160">
      <a href="https://www.paypal.com/paypalme/oilstuck">
        <img src="doc/images/support/paypal.svg" height="48" alt="透過 PayPal 支持開發"><br>
        <strong>PayPal</strong>
      </a>
    </td>
    <td align="center" width="160">
      <a href="https://ko-fi.com/kcayut">
        <img src="doc/images/support/ko-fi.png" height="48" alt="透過 Ko-fi 支持開發"><br>
        <strong>Ko-fi</strong>
      </a>
    </td>
    <td align="center" width="220">
      <a href="https://payment.opay.tw/Broadcaster/Donate/6CF8CF9E519E0ED13E244399607ADDD7">
        <img src="doc/images/support/opay.png" height="48" alt="透過歐付寶支持開發"><br>
        <strong>O’Pay（歐付寶）</strong>
      </a><br>
      歐付寶會員編號：2218408
    </td>
    <td align="center" width="160">
      <a href="https://p.ecpay.com.tw/A2FA21C">
        <img src="doc/images/support/ecpay.png" height="48" alt="透過綠界科技支持開發"><br>
        <strong>ECPay（綠界科技）</strong>
      </a>
    </td>
  </tr>
</table>

## 使用與智慧財產聲明

本專案與相關內容之著作權及智慧財產權均由作者保留。允許個人於非商業目的下下載、安裝、修改及使用；任何商業使用、營利服務、轉售或以本專案提供收費服務，皆須事先取得作者書面授權。

除上述明確允許的個人非商業使用外，未授予其他權利。如需商業授權，請透過 [WebClock GitHub 專案頁面](https://github.com/kcayut/webclock) 聯絡作者。

## 問題與建議

歡迎透過 [Issues](https://github.com/kcayut/webclock/issues) 回報問題或提出建議。
