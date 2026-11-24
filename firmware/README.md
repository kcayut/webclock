# WebClock 桌鐘韌體

| 目錄 | 內容 |
|---|---|
| [ee04-clock/](ee04-clock/README.md) | [ESPHome 韌體入口](ee04-clock/clock.yaml)、板型、USB 刷機及 OTA、[使用手冊](ee04-clock/使用手冊.md) |
| [rlcd-clock/](rlcd-clock/README.md) | [RLCD 刷機](rlcd-clock/README.md#usb-刷入)、[400 × 300 畫面與使用手冊](rlcd-clock/使用手冊.md)、[自訂鬧鈴](rlcd-clock/AUDIO.md) |
| [core/](core/) | 按鍵、鬧鐘、RTC、裝置配對、ESP32-S3 設定與 OTA 分割表 |
| [views/](views/) | EE04 經典版面；兩款共用的字型載入、重繪與跑馬燈。RLCD 原生版面在 [rlcd-clock/screen.yaml](rlcd-clock/screen.yaml) |
| [components/webclock/](components/webclock/) | WebClock 服務的 ESPHome 同步元件 |
| [setup/](setup/pair.py) | 電腦端 USB 配對工具 |
| [tests/](tests/) | 核心、同步與配對測試 |

## 設定每台桌鐘的顯示內容

首次開機預設使用 **English**。主畫面按 **●**，用 **＋** 選 **Display settings**，按 **●** 進入。第一項是 **Language**，按 **●** 依序切換 **English → 繁體中文 → 日本語 → English**。切換後立即生效，按 **×** 逐層返回。各台獨立儲存語言；升級前已儲存的時間格式、提醒顯示與鬧鐘設定會沿用。網頁傳來的提醒與行事曆標題保留原文。[RLCD 三語畫面](rlcd-clock/languages.png) · [EE04 三語畫面](ee04-clock/languages.png)

在繁體中文介面，主畫面按 **●**，用 **＋** 選「顯示設定」，再按 **●** 進入。用 **＋** 移到要修改的項目，按 **●** 立即切換，按 **×** 返回。桌鐘會在本機儲存設定，離線也能修改。

| 選項 | 可選值 |
|---|---|
| 語言 | English（預設）、繁體中文、日本語 |
| 時間 | 24 小時、12 小時（上午／下午）、隱藏 |
| 日期 | 年月日、月日、隱藏 |
| 鬧鐘狀態、文字提醒、行事曆 | 各自顯示或隱藏 |
| 電池電壓、溫濕度（限 RLCD） | 各自顯示或隱藏 |

首次啟用採 24 小時、完整日期並顯示所有項目。網頁上的「傳送對象」決定哪些裝置能收到文字提醒；桌鐘再依本機設定顯示收到的內容。例如，臥室和書房可以同時收到提醒，只有開啟「文字提醒」的桌鐘會在跑馬燈顯示。隱藏「鬧鐘狀態」後，每日鬧鐘依然會響，也能正常停鈴。

需要指定單台桌鐘時，請先完成群組配對，再於網頁勾選該裝置。未指定對象的提醒沿用群組或裝置內容指派；個人模式啟用本機提醒時，公開時鐘也會收到。

服務端與韌體皆更新後，文字提醒和行事曆可獨立切換。連接舊服務端時，兩項都開啟才會顯示未分類內容。

## 準備編譯環境

在專案根目錄使用 Python 3.12 執行：

```sh
python3.12 -m venv firmware/.venv
firmware/.venv/bin/python -m pip install -r firmware/requirements.txt
```

選擇與實體螢幕相符的入口建立裝置設定並刷入：[微雪 4.2 吋 RLCD](rlcd-clock/README.md#usb-刷入) · [EE04 電子紙](ee04-clock/README.md#刷入韌體)。

## 韌體介面翻譯

兩款桌鐘共用 [三語字串](core/ui_language.h) 與 [選單](core/menu.h)。新增介面文字時，在三語字串一起維護譯文，並把用到的新字元加入 [共用字元清單](views/classic.yaml) 和兩款板使用的 Noto Sans CJK TC 字型子集。桌鐘採用相同的時區與數字日期格式，語言選項只切換操作文字。

## 共用元件測試

完成任一板型的編譯後，使用已安裝專案根目錄 `requirements.txt` 依賴的 Python，從專案根目錄執行 `python3 firmware/tests/run_tests.py`，驗證鬧鐘排程與同步資料解析。裝置端選單、配對與服務整合測試見 [RLCD 驗證](rlcd-clock/README.md#驗證)與 [EE04 驗證](ee04-clock/README.md#驗證)。
