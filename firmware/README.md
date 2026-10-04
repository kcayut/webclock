# WebClock ESPHome 韌體原型

首版使用 **ESP32-S3-DevKitC-1-N8R8 + SSD1306 OLED**。已提供 [ESPHome YAML](webclock-esp32-s3.yaml) 與 [WebClock 外部元件](components/webclock/)，沿用 Server schema 2，同步固定規則鬧鐘、保存到 flash、運轉中斷網後本機響鈴。無須 VS Code 或 Home Assistant。

**驗證狀態：ESPHome 2026.9.1／ESP-IDF 5.5.5 交叉編譯與主機端排程／同步解析測試通過；尚未實機燒錄、接線、聲音或長時間運作驗收。** 主機測試使用本次建置的 ArduinoJson，並啟用 AddressSanitizer／UndefinedBehaviorSanitizer。這是原型，不是已驗收的鬧鐘成品；行事曆聯動、帳號隔離、RTC 斷電保時與 OTA 尚未提供。

## 硬體與接線

| 材料 | 選定規格／數量 | ESP32 接線 |
| --- | --- | --- |
| 開發板 | Espressif **ESP32-S3-DevKitC-1-N8R8** × 1，8 MB Flash／8 MB Octal PSRAM | 使用板上的 **USB-to-UART** 連接埠 |
| 螢幕 | **0.96 吋 SSD1306 128×64、I²C 四腳、3.3 V、0x3C** × 1 | VCC→3V3、GND→GND、SDA→GPIO8、SCL→GPIO9 |
| 蜂鳴器 | **PS1240 無源壓電蜂鳴器** × 1，例如 Adafruit #160 | GPIO4→100 Ω 串聯電阻→蜂鳴器→GND |
| 停止鍵 | 常開瞬時按鈕 × 1 | GPIO5→按鈕→GND；韌體已啟用內部上拉及消抖 |
| 配件 | 100 Ω 電阻、麵包板、杜邦線、可傳資料的 USB 線 | 所有 GND 共地；先斷電接線 |

官方開發板使用 Micro-USB；購買替代板前確認 **N8R8** 記憶體配置與腳位，不能只看「ESP32-S3」。GPIO35／36／37 已用於這個模組的記憶體。OLED 不能以同尺寸的 SH1106 直接替換；若 I²C 掃描為 `0x3D`，修改 YAML 的 `oled_address`。不要把有源蜂鳴器或 8 Ω 喇叭直接接上上述壓電蜂鳴器接線。

OLED 顯示時間、日期、星期數字（1＝一，7＝日）及秒數，未校時為 `--:--`。響鈴期間外框亮起；按鍵停止當次響鈴。字元以線段繪製，不下載字型。

## 編譯

以下命令從專案根目錄執行，需要 Python 3.12；首次建置會下載 ESPHome／ESP-IDF 工具鏈。ESPHome 固定為 **2026.9.1**。

```sh
python3.12 -m venv firmware/.venv
firmware/.venv/bin/python -m pip install -r firmware/requirements.txt
cp -n firmware/secrets.example.yaml firmware/secrets.yaml
```

`cp -n` 保留已存在的設定。編輯本機 `firmware/secrets.yaml`：

- `webclock_url`：填入 ESP 能連到的 Server 基底網址，例如 `http://192.168.1.20:5000`；不是 `localhost`。範例檔的 `192.0.2.10` 是文件示意位址，必須更換。
- `webclock_token`：與 Server 的 `DEVICE_API_TOKEN` 相同。只有 Server 本身採可信區網免 token 設定時才留空。
- `device_name`：在 WebClock 裝置列表使用的名稱。

```sh
firmware/.venv/bin/esphome config firmware/webclock-esp32-s3.yaml
firmware/.venv/bin/esphome compile firmware/webclock-esp32-s3.yaml
```

成功後，首次 USB 燒錄使用：

```text
firmware/.esphome/build/webclock-alarm/build/firmware.factory.bin
```

**網址及 token 會編入這份個人韌體，不能把 `secrets.yaml` 或產出的 `.bin` 公開分享。** Wi-Fi 帳密不編入 YAML／韌體，燒錄後再透過 Improv Serial 設定。

完成一次韌體編譯後，可從專案根目錄執行 `python3 firmware/tests/run_tests.py` 做本機排程及同步解析檢查；需要 C++17 的 `clang++` 或 `g++`，並使用專案 Server 依賴已安裝的 Python 環境。

## 網頁燒錄與 Wi-Fi

1. 以資料線接上開發板的 **USB-to-UART** 埠，關閉占用該序列埠的終端或日誌視窗。
2. 用桌面 Chrome／Edge 開啟 [ESPHome Web](https://web.esphome.io/)，連線至開發板的序列埠。
3. 選擇 **Install**，上傳本機編譯的 `firmware.factory.bin`。首次安裝可清除裝置；升級時不要假定清除 flash 還能保留 Wi-Fi、快取及去重紀錄。
4. 完成後重新連線，用網頁的 Wi-Fi 設定操作（Improv Serial）設定家中 Wi-Fi。首版沒有 fallback 熱點、裝置 Web 設定頁或 OTA。
5. 在 WebClock `/schedules` 新增數分鐘後的 `alarm`。確認裝置列表出現 `wc-<MAC>`、收到同步版本，再觀察實際響鈴及停止鍵。

若無法進入下載模式，按住 BOOT、按一下 RESET，再放開 BOOT 後重試。也可直接用 ESPHome CLI 燒錄（將序列埠替換為實際值）：

```sh
firmware/.venv/bin/esphome run firmware/webclock-esp32-s3.yaml --device /dev/cu.usbserial-REPLACE_ME
```

CLI 燒錄後仍可關閉日誌，回到 ESPHome Web 設定 Wi-Fi。Improv 只設定 Wi-Fi；修改 WebClock 網址、token 或名稱，須修改 `secrets.yaml` 後重新編譯與 USB 燒錄。

## 原型範圍

- 約每 30 秒同步及回報狀態；背景網路工作不等待在時鐘主迴圈。保存、啟用成功後才 ACK。
- 同步整份 schema 2，最多 **64 筆排程（含非 alarm）**、每次 HTTP 回應 **192 KiB**、序列化快取 **224 KiB**；超限拒絕整份更新，保留本次運轉中之前可用且未被撤銷的資料。
- 只執行 `type=alarm`；每日、星期、指定日期、工作日／假日、停用、略過一次均依台灣時間計算。Server 目前不傳 `calendar_link`，所以行事曆聯動不會響。
- 非 `silent` 音色統一為 **4 kHz 嗶聲，每秒響 350 ms，最多 60 秒**。每鬧鐘音量乘上 `volume_limit` 映射到 PWM；不等於音壓百分比。同分鐘多筆合併、取最高音量。
- 按停止不改 Server 排程；`silent` 或音量 0 仍顯示外框。同步後當次事件已取消或不再符合規則，會停止當前響鈴；修改其他鬧鐘不會無故中止。
- **每次重啟都需取得可信時間，並至少向 Server 成功驗證一次完整 config，才啟用鬧鐘。** 之後持續供電、運轉中斷網可使用快取；離線重開不自動啟用。首版無 RTC，斷電重開仍需 NTP 校時。
- 超過觸發分鐘起點 5 秒不補響；先保存去重再發聲的斷電邊界可能漏響，不保證恰好一次。

[完整同步、限制與驗收](../doc/esp-home.md) · [Server API](../doc/server-api.md#裝置-api)

硬體參考：[Espressif 開發板](https://documentation.espressif.com/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html)、[ESPHome SSD1306](https://esphome.io/components/display/ssd1306/)、[PS1240](https://www.adafruit.com/product/160)。
