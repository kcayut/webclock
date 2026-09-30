# WebClock Server：集中管理與裝置 API

本專案負責管理排程、台灣工作日資料、裝置登錄、同步版本及最後回報，並讓自架時鐘頁執行網頁鬧鐘。
`/schedules` 編輯與預覽鬧鐘排程，時鐘頁 `/` 播放內建音色並顯示紅邊提示；`/admin` 分開管理顯示設定、訂閱行事曆與文字提醒。

獨立硬體的韌體、音檔、喇叭播放、音量、貪睡、RTC、按鍵及離線執行屬於後續裝置專案。網頁鬧鐘使用瀏覽器音訊與畫面，不控制硬體播放器。
裝置使用 HTTP/JSON API 接入，不需要匯入這個專案的 Python 模組。

目前是單一管理空間，**所有裝置共用同一組排程與日曆**。尚未提供個別裝置的排程指派、多租戶或使用者帳號。

## 啟動與目錄

沿用 `python app.py`、Docker Compose 或既有 systemd 服務。在 `/admin` 進入鬧鐘管理，或直接開啟 `/schedules`。

```text
app.py / setup.sh / update_clock.py / update_clock.sh  部署相容入口
webclock/
  app.py                     既有網頁時鐘、設定、行事曆與啟動
  api/
    __init__.py              共用存取檢查、錯誤回應與路由註冊
    management.py            管理頁與排程／裝置管理 API
    device.py                裝置取得設定、排程、日曆及回報 API
  services/
    schedule_service.py      排程驗證、儲存、下一次時間計算
    holiday_service.py       台灣工作日判斷與日曆匯出
    device_service.py        裝置登錄、狀態、同步要求與確認
    storage.py               原子 JSON 儲存
  translations/              網頁文案
  data/taiwan_calendar.json  唯讀日曆與來源
templates/                   自架版 HTML
static/                      網頁 CSS / JS
scripts/                     安裝與更新
tests/                       Server、API 與網頁回歸測試
doc/                         架構與 API 契約
webclock_state/              私人執行資料，不進 Git
  calendar.json              多來源行事曆網址、名稱及顯示選擇
  settings.json
  manual_notes.json
  schedules.json
  devices.json
```

根目錄保留相容入口與公開時鐘檔案。GitHub Pages 仍只發布公開時鐘；管理頁、API、私人行事曆與裝置資料不進公開離線快取。

## 排程與工作日

新增排程的最低內容為 `name`、`time`。Server 會產生 `id`，並預設 `type=alarm`、每天、啟用。`browser_sound` 控制網頁音色；`skip_holidays` 是獨立於 `rule` 的假日過濾欄位。

```json
{
  "id": "work_alarm",
  "name": "上班提醒",
  "type": "alarm",
  "time": "07:30",
  "rule": {"weekdays": [1, 2, 3, 4, 5]},
  "skip_holidays": true,
  "browser_sound": "bell",
  "enabled": true,
  "skipped_occurrences": []
}
```

- `type`：`alarm`、`reminder`、`announcement`；時鐘頁只執行 `alarm`，不將行事曆或文字提醒自動變成鬧鐘。硬體如何呈現仍由裝置決定。
- `rule` 擇一：`{}` 每天、`{"weekdays":[1,3,5]}`、`{"workday_only":true}`、`{"holiday_only":true}`、`{"dates":["2026-10-03"]}`。
- `skip_holidays`：可在每天、星期或指定日期規則上過濾假日。補班日仍是工作日；`holiday_only=true` 同時 `skip_holidays=true` 會回 400。
- `browser_sound`：`bell`、`beep`、`digital` 或 `silent`。這是網頁專用音色，和舊硬體 `sound` 欄位分開；`silent` 保留視覺提示。
- 星期採 ISO：星期一 `1` 至星期日 `7`。與舊手動提醒 API 的 `0–6` 不同。
- 排程固定採 `Asia/Taipei`，與大字時鐘的顯示時區分開。
- `skipped_occurrences` 是含時區的完整時間；跳過下一次不會關閉排程，可連續跳過。
- 管理 API 的 `next_occurrence`、`next_event` 為預覽結果，不是已執行記錄或事件佇列。

鬧鐘可選填 `calendar_link`，未提供或 `null` 時維持固定時間規則：

```json
{"calendar_link":{"mode":"event","source_ids":["local","work"],"offset_minutes":15}}
```

- `event`：依所選來源的有時間行程，提前 `offset_minutes`（0–1440）響鈴；全天事項略過。
- `day`：當天所選來源有行程時，以排程的 `time` 響鈴；`offset_minutes` 為 0。全天及跨日行程也算，結束時間不包含在內。
- `source_ids` 是來源的穩定 ID；`local` 代表本地提醒。任一選中來源符合即可，與顯示選擇獨立。
- 星期、指定日期及假日過濾都以實際響鈴的台灣日期判斷。預覽查詢未來 366 天，依行程模式保留秒精度，`skipped_occurrences` 也保留完整時間。
- 沒有日期或固定時段的常駐本地文字不參與聯動。來源移除或讀取失敗不退回每日鬧鐘，也不使用過期訂閱資料。
- 聯動由伺服器計算，供網頁鬧鐘使用；既有 schema 2 裝置排程回應會排除聯動鬧鐘，避免舊硬體將新條件誤當成每日響鈴。

日曆目前涵蓋 **2023-01-01 至 2027-12-31**，依政府行政機關辦公日曆判斷，不代表所有公司的出勤規則，也不包含颱風停班或個人輪班。超出範圍回 `unknown`；工作日、假日及「跳過假日」規則不猜測下一次時間，未啟用假日過濾的每天、星期及指定日期仍可計算。日曆目前隨 Server 資料檔更新，尚未自動下載未來年度資料。

## 管理 API

API 接受 JSON，錯誤以 `{"error":"..."}` 回應（已匹配的 API 路由）。輸入錯誤為 400、不存在為 404、寫入失敗為 500；不會覆蓋已保存的資料。請求上限 1 MiB。

| 路徑 | 方法與用途 |
| --- | --- |
| `/api/v1/schedules` | GET 排程、下一次事件、Server 時間、今日日期與日曆範圍；POST 新增 |
| `/api/calendar` | GET/POST 行事曆來源；PATCH 僅更新顯示選擇 |
| `/api/v1/schedules/<id>` | PUT 修改指定欄位；DELETE 刪除 |
| `/api/v1/schedules/<id>/skip-next` | POST 跳過下一次，回 `skipped` 與 `next_event` |
| `/api/v1/browser-alarms` | GET 時鐘頁的下次鬧鐘、Server 時間及假日資料狀態 |
| `/api/v1/holidays?date=2026-09-30` | GET 日期類型；省略日期時查台灣今天 |
| `/api/v1/devices` | GET 裝置列表、最後回報與待確認同步指令 |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`，回 202 與 `command` |

管理 API 沿用可信任區網模式，不具備登入功能。Server 拒絕不同 Origin 的瀏覽器存取；這不是完整身份驗證。遠端部署須在反向代理限制存取並啟用 HTTPS。

`/api/calendar` 的 `sources` 每筆包含 `id`、`name`、`provider`（`apple`／`google`／`ics`）、`url`、`display_enabled`；`local_display_enabled` 控制本地提醒顯示。新增來源可省略 ID，由伺服器產生；更新時保留 ID 以延續鬧鐘引用。POST 完整保存來源，PATCH 只接受來源 ID 與顯示旗標。舊 `{"url":"..."}` 與 `.env` 的 `ICAL_URL` 仍可讀取遷移。網址僅出現在專用管理回應，不進入時鐘 API、排程 API、裝置 API、備份匯出或離線快取。

`GET /api/v1/schedules` 的 `calendar_sources` 提供含本地提醒的來源目錄，每筆僅有 `id`、`name`、`provider`，供鬧鐘選擇使用。

## 網頁鬧鐘

`GET /api/v1/browser-alarms` 回應欄位：

| 欄位 | 內容 |
| --- | --- |
| `server_timestamp` | 伺服器時間戳，單位為 Unix 毫秒，供時鐘頁校準觸發時間 |
| `enabled_count` | 已啟用的鬧鐘數量 |
| `enabled_ids` | 所有已啟用鬧鐘的 ID，包含沒有下次發生時間的鬧鐘；頁面據此取消已停用或刪除的響鈴 |
| `alarms` | 固定鬧鐘的下次時間；聯動鬧鐘包含本分鐘已到時間及第一筆未來行程，上限 1000 筆 |
| `alarms[].id` | 排程 ID |
| `alarms[].occurrence_id` | 這一次發生的識別碼，供顯示頁避免重複響鈴 |
| `alarms[].name` | 鬧鐘名稱 |
| `alarms[].starts_at` | 下次發生時間，單位為 Unix 毫秒 |
| `alarms[].sound` | 網頁音色，來自排程的 `browser_sound` |
| `holiday_coverage`、`holiday_known` | 假日資料涵蓋範圍與是否已知 |

查詢從當分鐘起算，避免剛到時刻的鬧鐘因 API 延遲就直接跳至下一次；同一分鐘內不同秒的聯動行程會保留。這份回應不是完整離線排程快照。時鐘頁約每 15 秒更新一次；已載入的下次時間可在暫時斷線時觸發，重新開頁與取得後續週期仍需連線。超過 60 秒才恢復處理的過期鬧鐘不補響。

頁面使用原生 Web Audio 合成 3 款音色，不下載音檔或載入音訊框架。每次開頁需點小鈴鐺「啟用聲音」並聽到短音；相容舊 Safari 的 `webkitAudioContext`。iOS 需要使用者操作啟用音訊，切換 App、分頁或鎖屏也可能中斷音訊與計時，因此須保持時鐘頁在前景、螢幕開啟，不保證背景或鎖屏響鈴。[Apple Web Audio 說明](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/Using_HTML5_Audio_Video/PlayingandSynthesizingSounds/PlayingandSynthesizingSounds.html)、[MDN iOS 中斷行為](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/state#resuming_interrupted_play_states_in_ios_safari)

視覺提示僅讓紅邊以每 2 秒一週期改變透明度；連線面板的「閃爍紅邊」可關閉閃爍，改為常亮。支援 `prefers-reduced-motion` 的瀏覽器也會改為常亮。使用兩次分開的點擊關閉目前顯示頁的當次鬧鐘；同一次觸控產生的 touch／click 不當成兩次操作。關閉不修改排程，也不停止其他裝置。

## 裝置 API

路徑保留 `/api/v1/device/*`，設定回應的 **`schema_version` 為 2**。裝置 API 不提供舊硬體 `sound`、`volume`、`repeat`、`snooze_minutes` 播放欄位；`browser_sound` 僅供網頁呈現，不是硬體播放指令。舊原型 client 需要更新，不能將 schema 2 視為 schema 1 相容。

| 路徑 | 方法與用途 |
| --- | --- |
| `/api/v1/device/config` | GET schema、時區、`config_revision`、`schedule_revision`、`holiday_revision` |
| `/api/v1/device/schedules` | GET `{"revision":"...","schedules":[...]}` |
| `/api/v1/device/holidays` | GET 日曆逐日快照、來源、範圍與 `revision` |
| `/api/v1/device/register` | POST `{"id":"bedroom","name":"臥室裝置"}`；回 201 與 `device` |
| `/api/v1/device/status` | POST 狀態與同步確認，回 `device` 和待執行 `commands` |

裝置讀取排程與日曆的 API 不接受寫入。狀態列表位於管理 API `/api/v1/devices`。

可在 `.env` 設 `DEVICE_API_TOKEN`，裝置將它放在 `Authorization: Bearer <token>`，適用於所有 `/api/v1/device/*` 呼叫。空值維持可信任區網模式；這是共用 token，不是每台裝置獨立身份，也不保護管理 API。

### 同步流程

1. 裝置以固定 `id` 註冊。重複註冊保留狀態與待確認指令，並更新名稱。
2. GET `config`，確認支援 `schema_version=2`。
3. 比較三種 revision，只下載變更的排程或日曆；第一次接入需取得完整資料。
4. 下載完成再 GET `config`，確認版本沒有在同步途中改變；有變更時重試。裝置應在驗證成功後才替換本機快取，失敗則保留上次資料。
5. POST `status`，回報已保存的版本；Server 不會假定「已下載」等於硬體已成功執行排程。

revision 是內容的 SHA-256 字串，內容相同就不變。三個 GET 資源都支援 `If-None-Match` 或 `?revision=...`，一致回 304，無回應本文。排程及日曆使用本文中的 `revision`；`config` 應使用其回應 ETag（去除引號後可用於 query），**不是** `config_revision`，因為 ETag 同時包含排程和日曆版本。

日曆快照的 `schema_version=1` 只描述日曆格式，與裝置設定的 `schema_version=2` 是不同契約。

### 狀態與同步確認

註冊後，最低回報為 `{"id":"bedroom"}`。下列字串欄位可選；省略時保留之前回報的值，尚未回報的欄位不提供：

```json
{
  "id": "bedroom",
  "firmware": "0.1.0",
  "config_revision": "已保存的設定版本",
  "schedule_revision": "已保存的排程版本",
  "holiday_revision": "已保存的日曆版本",
  "acknowledged_commands": ["已完成的同步指令ID"]
}
```

`online` 表示最近 120 秒內收到狀態回報，僅為最近連線情況。建議裝置約每 60 秒回報；不要求 RTC、Wi-Fi、電池或其他特定硬體能力。

管理頁的「要求同步」只加入 `sync` 指令。裝置下次 POST `status` 時取得 `commands`，完成同步後再用 `acknowledged_commands` 回報。指令在確認前持續回傳；重複按同步只保留同一筆待確認指令。裝置應依指令 ID 去重，失敗時不要確認。確認只影響該 `id` 的同步指令。

本專案提供上述 Server 契約、API 測試及網頁鬧鐘。獨立硬體的本機快取、準時觸發、斷線行為及指令執行由未來裝置專案實作與驗證。

## 舊原型與資料保存

- 舊音效 API、音檔、硬體聲音服務及 Python 模擬裝置已移除，裝置指令目前只有 `sync`。目前網頁鬧鐘改由瀏覽器合成內建音色。
- 舊 `schedules.json` 的 `sound`、`volume`、`repeat`、`snooze_minutes` 會留存檔案，編輯其他欄位也保留，但不公開、不套用。新 API 不接受這些欄位。
- 新增的 `browser_sound` 與 `skip_holidays` 正常透過排程管理儲存，不沿用舊音檔或舊硬體音量設定。
- 舊裝置硬體欄位、`test_sound`／`restart` 待執行命令同樣留存，但不公開也不再交給裝置。
- `webclock_state/sounds/`、`webclock_state/fake-device/` 等既有使用者資料不會自動刪除。Server 不再讀取它們。
- 舊根目錄 `manual_notes.json` 仍會首次複製到狀態目錄，保留原檔。`NOTES_FILE` 和 `WEBCLOCK_STATE_DIR` 仍可覆寫路徑。

請備份整個狀態目錄、提醒檔和 `.env`。`/admin` 的 JSON 匯出仍只包含顯示設定與手動提醒，不含智慧排程或裝置資料。Linux 更新器會備份預設路徑和服務實際設定的 `WEBCLOCK_STATE_DIR`、`NOTES_FILE`，失敗時嘗試一起回復程式、套件與資料。Docker 的自訂路徑仍需自行掛載及備份。操作方式與首次升級步驟見 [README](../README.md#資料保存與更新)。

目前用單一 Server process 寫入 JSON，最多 1000 筆排程、100 台裝置；增加多個 worker 前需改用支援跨程序交易的儲存方式。

## 驗證

```bash
python -m unittest discover -s tests -p 'test_*.py'
node tests/test_clock.js
node tests/test_offline.js
node tests/test_schedule_ui.js
node tests/test_alarms.js
node tests/test_calendar_ui.js
node tests/test_management_navigation.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

測試涵蓋管理 CRUD、工作日／補班日、跳過、同步版本、存取檢查、裝置回報／確認及舊資料保存。更新整合測試會啟動真實舊版／新版 Server，驗證 Git 升級、外部資料路徑及新版寫入後的失敗還原；需完整 Git 歷史與舊版使用的 `holidays` 套件，缺少時會明確略過。systemd、pip 與 Linux 服務環境查詢使用替身，不代表目標主機部署或硬體驗收。
