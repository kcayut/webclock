# ESP 鬧鐘：ESPHome 原型使用與同步契約

[回到 README](../README.md) · [Server API 契約](server-api.md) · [硬體、接線與燒錄](../firmware/README.md)

已提供第一版 ESPHome YAML 與 WebClock 外部元件，選定 **ESP32-S3-DevKitC-1-N8R8 + SSD1306 128×64 I²C OLED + PS1240 無源壓電蜂鳴器 + 停止按鈕**。裝置使用現有 schema 2 API，同步固定規則鬧鐘，保存後在本機執行，不需要 Home Assistant 或 MQTT。

**驗證狀態：ESPHome 2026.9.1／ESP-IDF 5.5.5 交叉編譯與主機端排程／同步解析測試通過；尚未實機燒錄、接線、聲音或長時間運作驗收。** 主機測試使用本次建置的 ArduinoJson，並啟用 AddressSanitizer／UndefinedBehaviorSanitizer。本文區分已寫入原型的行為與後續提案；Server 測試、主機端核心測試或韌體編譯通過，都不能代替硬體驗收。

## 安裝與操作

依 [韌體 README](../firmware/README.md) 接線，使用 Python 3.12 安裝釘選的 ESPHome 2026.9.1，複製 `secrets.example.yaml`（保留已存在的 `secrets.yaml`），填入 Server 位址、共用 token 與裝置名稱，再執行 `esphome config`／`compile`。

目前提供的是 **YAML + 元件原始碼 + USB 燒錄方法**，尚無通用的公開預編譯下載、專案專用一鍵安裝頁或 OTA 服務：

1. 使用資料 USB 線連接開發板的 **USB-to-UART** 埠。這份 YAML 指定 UART0，Improv Serial 與日誌都走這個埠。
2. 用桌面 Chrome／Edge 開啟 [ESPHome Web](https://web.esphome.io/)，連接序列埠，選 Install 並上傳 `firmware/.esphome/build/webclock-alarm/build/firmware.factory.bin`（以專案根目錄為起點）。
3. 燒錄後以 Improv Serial 設定 Wi-Fi；這版沒有 fallback 熱點、裝置 HTTP 設定頁或網路 OTA。
4. 等待 NTP 校時及 Server 同步，在 WebClock `/schedules` 建立數分鐘後的鬧鐘，核對裝置版本，再觀察實際響鈴。

裝置 ID 為 `wc-<MAC>`，同一板子重啟或更新仍使用相同 ID。名稱來自 `device_name`。ID 不是認證憑證，註冊成功也不代表建立每台裝置的安全配對。

Improv 只負責 Wi-Fi；**WebClock URL／token／名稱目前編入個人韌體**，修改時需重新編譯與 USB 燒錄。Wi-Fi 帳密不編入映像，會由裝置保存。已填妥設定的 YAML、`secrets.yaml`、編譯產物都不應公開；忽略規則不能讓已外流的韌體恢復保密。範例 `192.0.2.10` 為文件示意位址，不能當作可連線的 Server。

目前首次安裝、保留資料升級及恢復出廠尚未完成硬體驗收。清除 flash 會失去 Wi-Fi、快取及去重紀錄，不能保證保留設定。網頁安裝能力與瀏覽器支援以 [ESP Web Tools 官方文件](https://esphome.github.io/esp-web-tools/) 為準。

## 顯示、聲音與按鍵

OLED 主畫面顯示大時間、日期、星期數字（1＝星期一，7＝星期日）及秒數。未取得時間時顯示 `--:--`，不把開機預設日期當成真實時間。不會因同步失敗自動彈出錯誤面板；基本畫面不等待 Server 認證，診斷由序列日誌與後台的最後回報查看。

時間與日期使用原創七段線條繪製，不依賴遠端字型下載，也沒有中文鬧鐘名稱顯示。

| 項目 | 第一版行為 |
| --- | --- |
| `type=alarm` | 本機響鈴 |
| `reminder`／`announcement` | 可在快照中存在，但不播放；也計入 64 筆上限 |
| `bell`／`beep`／`digital`／`chime`／`melody`／`pulse`／`sonar` | 全部映射成同一種 4 kHz 嗶聲，不模擬網頁音色 |
| 聲音節奏 | 每秒輸出 350 ms，最多 60 秒 |
| 每鬧鐘音量 | `browser_volume / 100 × volume_limit` 作為 PWM 輸出值；預設 `volume_limit=0.25`，可調範圍 0 至 0.5 |
| `silent` 或音量 0 | 不發聲，仍顯示響鈴外框 |
| 同一分鐘多筆 | 合併為一次，採非靜音事件的最高音量 |
| GPIO5 停止鍵 | 停止本裝置當次聲音與外框，不永久停用 Server 排程、不通知其他裝置 |
| 新快照套用 | 當次事件被取消或不再符合規則時停止；修改其他鬧鐘不無故中止當前響鈴 |
| 貪睡、測試音按鍵 | 尚未提供 |

PWM 百分比不是音壓百分比，不同蜂鳴器、頻率及外殼都影響實際音量。第一次接線先使用低 `volume_limit` 實測；聲音硬體以 PS1240 無源壓電蜂鳴器為準，不能直接換成有源蜂鳴器或低阻抗喇叭。[PS1240 規格](https://www.adafruit.com/product/160)

## 現有 Server API 與範圍

完整 HTTP 格式、欄位限制與錯誤碼以 [Server API 契約](server-api.md#裝置-api) 為準。

| 能力 | 目前原型使用方式 |
| --- | --- |
| `POST /api/v1/device/register` | 以 MAC 衍生 ID 與設定名稱註冊 |
| `GET /api/v1/device/config` | 驗證 schema 2／Asia-Taipei 設定，讀取三種 revision 與 HTTP ETag |
| `GET /api/v1/device/schedules` | 下載全域固定規則快照，完整替換 |
| `GET /api/v1/device/holidays` | 下載台灣工作日快照；不是私人 ICS 行程 |
| `POST /api/v1/device/status` | 回報已啟用版本，取得待處理 `sync` 指令並確認完成 |
| 每台裝置／帳號資料隔離 | 尚無，所有裝置取得同一份全域資料 |
| 行事曆聯動 | schema 2 排除整筆 `calendar_link`；原型不支援 |

`/api/v1/browser-alarms` 是網頁近期鬧鐘回應，並非完整離線清單；原型不使用這個 endpoint。

`DEVICE_API_TOKEN` 非空時，裝置 API 帶 `Authorization: Bearer <token>`；空值只適用於 Server 本身採可信任區網模式。這是所有裝置共用的 token，不能單獨撤銷一台，也不保護管理頁或管理 API。經不可信網路傳輸時使用 HTTPS；原型啟用憑證驗證，不接受失效／不受信任憑證，也不自動跟隨重新導向。反向代理的登入 HTML 不是合法 API 回應；必須讓裝置能直接取得 JSON。

## 已實作的同步流程

元件位於 [firmware/components/webclock](../firmware/components/webclock/)，使用獨立網路 worker 執行 HTTP 與解析，主迴圈負責顯示、按鍵及響鈴。第一版直接使用 ESP-IDF HTTP client，不依賴 ESPHome `http_request` 的預設 1 KB 捕捉緩衝區。

1. 啟動主畫面及獨立 NTP 校時，讀取本機快取作為同步候選。快取的網址／token 範圍必須與目前設定相同，且沒有已知撤銷標記。**每次重啟仍須至少向 Server 成功驗證一次完整 config 才啟用鬧鐘；不會僅靠磁碟快取離線啟用。**
2. 向 Server 註冊，取得並驗證 `config`。運轉中已有有效快取時以 **config 的 HTTP ETag** 條件檢查；收到 304 才沿用已持有本文。`config_revision` 不是 config 的 HTTP ETag，不能互換。
3. 發現需更新時下載完整排程與工作日日曆，檢查 JSON、必要欄位、支援規則、容量及本文 revision。HTTP 不完整、非 JSON／HTML、超限都拒絕整份候選資料。
4. 再次取得 `config`，核對設定、排程、日曆三種 revision 沒有在下載中改變；不混用不同版本的資源。
5. 將完整快照保存到專用 `webclock` NVS，成功後交由主迴圈啟用。只有這兩步完成，worker 才回報新 revision 並 ACK 待處理同步指令。
6. 正常約每 **30 秒**進行一輪檢查與 `status` 回報；新收到同步要求會提早再跑一輪。同步是裝置輪詢，不是伺服器即時推播。

無變更時不反覆寫整份快取。錯誤重試從約 10 秒逐步退避，最長約 5 分鐘，另有少量隨機延遲；因此故障期間後台可能把仍在本機運作的時鐘標成離線。API 文件的一般「每 60 秒 status」建議不是此原型的實際間隔。

完整替換包含刪除及空清單：Server 已刪除的鬧鐘不能留在 ESP。逾時、404／5xx、解析失敗與容量超限不等於空清單；保留本次運轉中之前可用且未被撤銷的完整快照。持久寫入失敗時不啟用新資料、不 ACK；重新開機可能讀到完整舊或新快照，仍須重新向 Server 驗證，不能宣稱 flash 一定停留在舊版本。待處理指令失敗不 ACK，重送 ACK 不等於多次播放。

`online`、三種 revision 一致與 ACK 只能說明裝置回報及同步狀態，**不能證明蜂鳴器已實際出聲**。目前 Server 不提供正式 RTC、時間可信度、剩餘快取容量或硬體播放紀錄欄位，裝置不會僅靠多送欄位假定後台已支援。

## 容量、規則與保存

| 限制 | 原型上限／策略 |
| --- | --- |
| 硬體記憶體 | 8 MB Flash／8 MB Octal PSRAM；缺少 PSRAM 不視為相容板型 |
| 專用快取分割區 | `webclock` NVS 512 KiB，與 Wi-Fi／ESPHome 設定的 NVS 分開 |
| 單次 HTTP 回應 | 192 KiB |
| 序列化整份快取 | 224 KiB；保留 NVS 更新與記錄空間 |
| 排程總數 | 64 筆，包含非 alarm 與停用項目；不靜默截斷 |
| 不支援或損壞規則 | 拒絕整份候選快照，避免一部分成功後誤報同步完成 |

原型支援每日（空規則）、指定 ISO 星期（一＝1 至日＝7）、指定日期、工作日、假日、`enabled`、`skip_holidays` 與 `skipped_occurrences`。內部以 UTC 時間戳執行，規則日期固定轉成台灣 UTC+8；不支援自行切換排程時區。

日曆查不到的日期保持未知。工作日、假日或需要 `skip_holidays` 判定的鬧鐘，不把未知日期猜成工作日；不依賴工作日日曆的每日／星期／指定日期規則可繼續執行。這是規則快照，**沒有「未來七天清單」或清單到期契約**。

現有五年工作日 JSON 約 122 KB，只是目前資料量，不能代替最大容量驗證。總資料超限時需減少 Server 排程或另行設計裝置 API；不要只把常數調大就宣稱可靠。Flash 損壞或持久保存失敗不回報新的同步成功。

## 時間、斷網、斷電與認證

| 情境 | 原型行為／限制 |
| --- | --- |
| Server 無法連線，但 NTP 可用 | 基本時鐘照常；若本次開機從未向 Server 驗證成功，則不啟用鬧鐘 |
| 本次開機已完成驗證及校時，後來 Wi-Fi 中斷 | 繼續走時及執行快取，背景重連；Wi-Fi `reboot_timeout=0s`，沒有 Native API 的無客戶端重啟 |
| 斷電重開且無 NTP | 無電池 RTC，顯示 `--:--` 並不響鈴；保存排程不等於保存正確現在時間 |
| 重開後有 NTP，但 Server 仍離線 | 顯示時間，等待 Server 驗證後才啟用鬧鐘；不自動復活舊快取 |
| Server 在裝置離線時取消鬧鐘或撤銷 token | 持續運轉的 ESP 收到更新前可能執行舊快取，不能立即遠端撤回 |
| 收到 HTTP 401／403 | 停止排程與當前響鈴，嘗試保存撤銷標記；即使保存失敗，重開也要重新驗證才啟用。基本時鐘繼續 |
| 改變 Server URL 或 token | 快取範圍雜湊改變，不載入舊範圍資料，需成功同步新資料 |
| 觸發時間已過超過 5 秒 | 不補響舊事件，避免恢復網路／校時後突然響過期鬧鐘 |
| 時間往回調或重新啟動 | 持久化全域 `last_fired` 分鐘；相同或更早分鐘不再執行。若時鐘曾錯跳到未來，回調後在超過該紀錄前可能不響 |

每次響鈴先保存該分鐘的去重紀錄，再開始發聲。因此保存後、發聲前突然斷電，該次可能漏響；不能承諾斷電情況下恰好一次。去重紀錄無法保存時也不發聲，避免不停重試 flash 與重複執行。它是同分鐘合併的原型策略，不是每個事件的完整播放紀錄。

校時獨立於 WebClock 的登入與認證；現有 config 沒有 Server 時間。原型使用 ESPHome SNTP。需要斷電後、網路仍中斷時也能知道時間，下一版應加入備援 RTC；斷電期間要響，還必須有整機備援電源。RTC 電池本身不供應蜂鳴器；加入 RTC 也不會自動取消本版每次開機的 Server 驗證要求。[ESP-IDF System Time](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/system_time.html)

## 後續方向：完整行事曆清單與一般使用者安裝

以下尚未實作，沒有可呼叫的新 endpoint：

1. **伺服器產生多日觸發清單。** 沿用 Server 的規則及行事曆聯動計算，例如未來七天。新契約需含清單版本、資料範圍、產生／到期時間、穩定事件 ID、明確單位的 UTC 觸發時間與硬體音色能力；不直接改變 schema 2 語意。
2. **持續補足及來源失敗策略。** 即使設定沒改，也補足未來時間範圍；行程改期／取消、來源更新或讀取失敗都要重新判定，不能只比對排程設定版本。超限或過期須明確呈現。
3. **個別裝置憑證與資料歸屬。** 配合將來的部署／帳號模式，定義重新綁定、主要使用者、其他帳號資料保存及離線撤銷的限制；目前全域 token 不提供這些保證。
4. **通用預編譯安裝。** 增加裝置端 WebClock URL／配對流程，才能發布不含私人 token 的公用韌體及 ESP Web Tools manifest；再加入經驗證的 OTA、保留資料升級及恢復出廠。
5. **硬體擴充。** 完成首套硬體驗收後，再考慮備援 RTC、電源、不同螢幕／播放器、音色與貪睡，不將未測板型標為支援。

## 實機驗收清單

記錄板型、接線、ESPHome 版本、Server 版本及結果。以下尚未完成：

- [ ] ESPHome Web 經 USB-to-UART 燒錄，Improv 設定 Wi-Fi，重開後 Wi-Fi 與 `wc-<MAC>` ID 保留。
- [ ] OLED 位址、日期、星期、秒數、低亮度長時間運作及未校時 `--:--` 正確。
- [ ] 新增／修改／刪除／清空／停用／略過一次，及各種固定規則符合 Server，行事曆未知不誤響。
- [ ] 304、有損 JSON、下載中版本變動、HTML 反代登入頁、超容量與保存中斷電，不啟用半份資料。
- [ ] 同步確認只在保存及主迴圈啟用後送出，ACK 遺失重試與 Server 重啟可恢復。
- [ ] 完成驗證後路由器斷線超過 15 分鐘仍走時並按快取響鈴；恢復網路會自行同步。
- [ ] 每次重啟需驗證 Server；token 錯誤／撤銷、401／403 後離線重開、Server URL／token 變更，不重新啟用舊範圍快取。
- [ ] 每鬧鐘音量、silent／0 的外框、同分鐘合併、停止鍵、60 秒停止，以及更新取消當次事件會停止、修改其他事件不中止。
- [ ] 校時前進／回退、超過 5 秒不補響、響鈴前後斷電的去重限制符合本文。
- [ ] 所有公開檔案不含私人設定；個人編譯 `.bin` 不對外發布。未測的 OTA／保留資料升級不標為完成。

參考：[開發板官方指南](https://documentation.espressif.com/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html)、[SSD1306](https://esphome.io/components/display/ssd1306/)、[Improv Serial](https://esphome.io/components/improv_serial/)、[ESPHome External Components](https://esphome.io/components/external_components/)、[Wi-Fi 重啟設定](https://esphome.io/components/wifi/)。
