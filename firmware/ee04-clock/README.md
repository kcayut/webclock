# EE04 電子紙桌鐘韌體

[使用手冊](使用手冊.md) · [Server API](../../doc/api/server-api.md)

## 刷入韌體

開發者或製造端使用 USB 做首次刷機，另存每台自己的 OTA 密碼。從專案根目錄執行，以實際桌鐘埠替換示例埠。沿用[既有 ESPHome 環境](../README.md)，保持服務欄位空白即可交給使用者配對。

```sh
cfg=firmware/ee04-clock
cp -n "$cfg/secrets.example.yaml" "$cfg/secrets.yaml"
read -rs 'WEBCLOCK_DESK_OTA_PASSWORD?輸入這台桌鐘的 OTA 密碼：'
read -rs 'WEBCLOCK_DESK_AP_PASSWORD?輸入這台桌鐘專屬的熱點密碼：'
export WEBCLOCK_DESK_OTA_PASSWORD WEBCLOCK_DESK_AP_PASSWORD
firmware/.venv/bin/esphome run "$cfg/clock.yaml" --device /dev/cu.REPLACE_WITH_USB_PORT
```

熱點密碼每台各用一組隨機字串（建議 16 字元以上，可用 `openssl rand -hex 8` 產生），連同熱點名稱 WebClock-Setup 印在機背或隨機卡。將兩組密碼分別存妥，以相同的環境變數重建更新。ESPHome 的配網熱點也提供網頁韌體上傳，因此只把專屬熱點密碼交給裝置持有人。[官方配網元件](https://esphome.io/components/captive_portal/)

後續接上電源，以同一份設定與同一個 OTA 密碼執行以下命令，將示例位址換成桌鐘的區網 IP。OTA 更新保留 USB 配對及 Wi-Fi 設定。若整片抹除 flash 則需重新配網配對。從舊版帶有服務 secrets 的韌體升級時，第一次成功 USB 配對會優先使用新設定。

```sh
firmware/.venv/bin/esphome run "$cfg/clock.yaml" --device 192.0.2.50
```

## 核心與畫面

| 層 | 責任與入口 |
|---|---|
| 共用核心 | [desk.yaml](../core/desk.yaml)、[選單狀態](../core/menu.h)、[鬧鐘狀態](../core/local_alarm.h)、[日期及 RTC](../core/rtc.h) 管理按鍵事件、選單、草稿、儲存、響鈴及取消確認、RTC 和服務同步。核心送出狀態變更，沒有繪圖、字型、螢幕尺寸或座標。 |
| WebClock 服務 | [共用元件](../components/webclock)處理離線快取、版本衝突、程式憑證與群組範圍。群組行事曆使用顯示憑證，鬧鐘讀寫使用程式憑證。 |
| 畫面 | [經典畫面設定](../views/classic.yaml)持有字型、跑馬燈及重繪節奏；[版面](../views/classic-frame.yaml)讀取時鐘／鬧鐘／選單／響鈴確認狀態並繪製。沿用網頁將時間置中、粗體、約 35% 畫面寬度字級的方向；800 × 480 採 280 px 粗體，全天 1,440 種時分的實際數字墨跡高度為 196–203 px（約 22.7–23.5 mm），日期、鬧鐘和行事曆分列。[網頁樣式](../../static/clock.css) |
| 板型 | [clock.yaml](clock.yaml)選擇面板驅動、接腳、畫面與[蜂鳴器輸出](piezo.yaml)，兩板共用[ESP32-S3 設定](../core/esp32s3.yaml)與[分割表](../core/partitions.csv)；[USB 設定](../core/usb_profile.h)使用 ESP32-S3 原生 USB。 |

開發另一款造型時，在新機型 YAML 選取自己的畫面 package 和 render lambda，維持核心使用的按鍵、RTC、音效元件 ID。若只改外型及畫面，不必複製鬧鐘與同步程式。版面應處理選單、未校時、一般時鐘、日期編輯、鬧鐘編輯、配對、響鈴與取消確認、行事曆狀態。

## 驗證

從專案根目錄執行；服務整合測試需先成功編譯一次韌體以取得 ArduinoJson 標頭。

```sh
c++ -std=c++20 firmware/tests/test_clock.cpp -o /tmp/webclock-clock-test && /tmp/webclock-clock-test
venv/bin/python firmware/tests/test_service.py
venv/bin/python firmware/tests/test_pairing.py
```

實體驗收需確認首次熱點掃描／手填與輸錯重試、十分鐘逾時、USB 配網、配對重啟、雙向補送、無網響鈴、OTA、室內遠距辨識及電池續航。

配網頁以韌體內建 HTML 搭配模擬掃描資料，在 Chrome 實際測過點選及手填含中文、空格與特殊字元的 SSID，兩次都送出正確欄位。

本次數位驗證涵蓋 全天 1,440 種時分的實際字模範圍、選單狀態、響鈴取消確認，以及 USB 配對和服務同步的主機端整合測試。配對重試會沿用待加入裝置；誤用其他管理者的邀請會解除該次加入。USB 資料連線時韌體啟用 ESP-IDF 防自動淺眠設定，拔線後恢復電池省電。USB 配對完成的裝置只由本機每日鬧鐘執行響鈴，避開離線修改後舊排程重複響起。
