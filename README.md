<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

**繁體中文** · [English](README_en.md) · [日本語](README_jp.md)

**[開啟線上時鐘](https://kcayut.github.io/webclock/)**

把 iPad、平板或閒置螢幕變成大時鐘。公開版開啟網頁即可使用；自行架設版另外提供行事曆、文字提醒、網頁鬧鐘、夜間模式與備份還原。

> [!IMPORTANT]
> 網頁鬧鐘必須保持瀏覽器在前景且螢幕開啟；iOS 鎖定畫面或切換 App 後，不保證聲音與計時持續。

## 兩種使用方式

- **直接使用：**開啟[線上時鐘](https://kcayut.github.io/webclock/)，不需帳號或伺服器。時間與時區跟隨裝置，適合舊 iPad、平板與閒置螢幕。
- **自行架設：**在電腦、NAS 或 Raspberry Pi 執行完整版。`/admin` 管理顯示、行事曆與文字提醒；`/schedules` 管理鬧鐘與裝置狀態。

自行架設版支援繁中、英文、日文介面，可訂閱 Google、Apple iCloud 或其他 ICS 行事曆。行事曆網址保存在主機，不會出現在公開時鐘、狀態或備份中。

## 快速安裝

先取得專案並建立設定檔：

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
```

選擇一種方式：

```bash
# Docker（預設 http://主機IP/）
touch manual_notes.json
mkdir -p webclock_state
docker compose up -d --build

# Raspberry Pi OS / Ubuntu / Debian（預設連接埠 5000）
sudo bash setup.sh

# 手動執行
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

完成後開啟時鐘首頁；管理畫面在 `/admin`，鬧鐘與裝置管理在 `/schedules`。

部署前可在 `.env` 設定初始介面語言：`WEBCLOCK_LANGUAGE=zh-TW`（繁體中文）、`en`（English）或 `ja`（日本語）。Linux 安裝腳本會在首次建立 `.env` 時詢問；部署後也可隨時從管理側欄底部切換，選擇結果會儲存在 `webclock_state/settings.json`。

**詳細說明：**[繁體中文使用指南](doc/guide.md) · [裝置 API](doc/server-api.md) · [ESPHome 原型指南](doc/esp-home.md) · [ESP32-S3 接線、YAML 與燒錄](firmware/README.md)

ESP32-S3 鬧鐘原型已通過交叉編譯，支援 OLED、固定規則鬧鐘同步與運轉中斷網響鈴；尚未實機驗收，行事曆聯動與 RTC 斷電保時仍待開發。

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
