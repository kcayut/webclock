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

自行架設版支援繁中、英文、日文介面，可訂閱 Google、Apple iCloud 或其他 ICS 行事曆。行事曆網址保存在主機，不會出現在公開時鐘、狀態或管理頁 JSON 匯出中；主機端完整備份仍包含私人資料。

時鐘會先顯示時間、日期與星期；已載入且在前景執行時，連線、瀏覽器儲存或附加功能失敗不應讓它停住。裝置管理可命名、查看自報能力與同步確認狀態；群組、六碼加入、逐台授權、移組、停用／恢復與刪除授權已提供；managed 模式由主機端明確啟用，既有安裝預設維持 self。操作與限制見[使用指南](doc/guide.md#裝置同步狀態)，目前驗證與待辦見 [A 階段驗收紀錄](doc/phase-a-acceptance.md) / [B 階段群組與授權驗收](doc/phase-b-acceptance.md)；CI 與 iPad mini 1／iOS 9 實機驗收狀態分開記錄。

## 安裝方式

| 方式 | 適合環境 |
| --- | --- |
| **Bare metal** | Raspberry Pi OS、Debian、Ubuntu；直接安裝並開機自動執行 |
| **Docker** | 已有 Docker 的電腦、NAS 或 Linux 主機 |
| **Home Assistant** | 在 HA OS 安裝本機 App，以 HA 側邊欄管理；卡片另裝自訂整合 |

**[前往完整安裝指南 →](doc/installation.md)**：三種方式的快速指令、必要條件、self／managed 啟用方式與 HTTPS 設定。

**[把裝置變成時鐘 →](doc/display-devices.md)**：依 iPad／iPhone、Android、Windows、Mac 分版本整理主畫面圖示、全螢幕與螢幕恆亮，包含 iPad mini 1／iOS 9。

Linux／Docker 預設使用 **self（自用）**；需要獨立管理員登入與逐台授權時，全新安裝加 `--managed` 並設定 HTTPS。HA App 由 HA 登入保護管理入口，不等同 WebClock managed 模式；目前採本機建置；預建映像的商店安裝尚未驗證。

**使用說明：**[繁體中文使用指南](doc/guide.md) · [Home Assistant 整合與卡片](doc/home-assistant.md) · [裝置 API](doc/server-api.md) · [ESPHome 原型指南](doc/esp-home.md) · [ESP32-S3 韌體](firmware/README.md)

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
