# WebClock Server：集中管理與裝置 API

**繁體中文** · [English](server-api_en.md) · [日本語](server-api_jp.md) · [回到 README](../README.md)

本專案負責管理排程、台灣工作日資料、裝置登錄、同步版本及最後回報，並讓自架時鐘頁執行網頁鬧鐘。
`/schedules` 編輯與預覽鬧鐘排程，時鐘頁 `/` 播放內建音色並顯示紅邊提示；`/admin` 分開管理顯示設定、訂閱行事曆與文字提醒。

獨立硬體的韌體、音檔、喇叭播放、音量、貪睡、RTC、按鍵及離線執行由裝置端負責，目前尚未實作。ESPHome 的開發準備放在 [`firmware/`](../firmware/README.md)，使用與開發流程見 [ESPHome 裝置指南](esp-home.md)。網頁鬧鐘使用瀏覽器音訊與畫面，不控制硬體播放器。
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
firmware/                    ESPHome 韌體開發準備，尚無可燒錄成品
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
  "browser_volume": 100,
  "enabled": true,
  "skipped_occurrences": []
}
```

- `type`：`alarm`、`reminder`、`announcement`；時鐘頁只執行 `alarm`，不將行事曆或文字提醒自動變成鬧鐘。硬體如何呈現仍由裝置決定。
- `rule` 擇一：`{}` 每天、`{"weekdays":[1,3,5]}`、`{"workday_only":true}`、`{"holiday_only":true}`、`{"dates":["2026-10-03"]}`。
- `skip_holidays`：可在每天、星期或指定日期規則上過濾假日。補班日仍是工作日；`holiday_only=true` 同時 `skip_holidays=true` 會回 400。
- `browser_sound`：`bell`、`beep`、`digital`、`chime`、`melody`、`pulse`、`sonar` 或 `silent`。這是網頁專用音色，和舊硬體 `sound` 欄位分開；`silent` 保留視覺提示。
- `browser_volume`：每個鬧鐘獨立的網頁音量，整數 0–100；新舊排程未提供時均預設 100。0 只顯示提醒，試聽與實際響鈴共用此設定；實際音量仍受裝置音量影響，不沿用舊硬體 `volume`。
- 星期採 ISO：星期一 `1` 至星期日 `7`。與舊手動提醒 API 的 `0–6` 不同。
- 排程固定採 `Asia/Taipei`，與大字時鐘的顯示時區分開。
- `skipped_occurrences` 是含時區的完整時間；跳過下一次仍保留排程 `enabled=true`，管理畫面在原定響鈴時間過後恢復啟用顯示。已有尚未到期的略過時間時，不可再跳過另一日期；略過預覽、修改及跳過 API 回 400 `Occurrence already skipped; wait for resume`。
- 管理 API 的 `next_occurrence`、`next_event` 為預覽結果，不是已執行記錄或事件佇列。

鬧鐘可選填 `calendar_link`，未提供或 `null` 時維持固定時間規則：

```json
{"calendar_link":{"mode":"event","source_ids":["local","work"],"offset_minutes":15}}
```

- `event`：依所選來源的有時間行程，提前 `offset_minutes`（0–1440）響鈴；全天事項略過。
- `day`：當天所選來源有行程時，以排程的 `time` 響鈴；`offset_minutes` 為 0。全天及跨日行程也算，結束時間不包含在內。
- `source_ids` 是來源的穩定 ID；`local` 代表 `/admin` 管理的伺服器本地提醒，不是時鐘面板的瀏覽器本機提醒。任一選中來源符合即可，與顯示選擇獨立。
- 可選填 `target` 指定行程：`{"source_id":"work","uid":"meeting","scope":"occurrence","recurrence_id":"2026-09-30T02:30:00+00:00","title":"每週例會"}`。`scope=occurrence` 只跟該次，`scope=series` 跟整個重複系列；未提供 `target` 時跟隨所選來源的全部行程。
- 選取識別值取自下述行程目錄 API。單次行程與整個系列的 `recurrence_id` 為空字串；重複行程的單次使用原始 `RECURRENCE-ID`，改期仍沿用該值。`title` 僅供顯示，改期、取消及響鈴時間以同步後的行事曆資料為準；訂閱快取最長 5 分鐘。
- 星期、指定日期及假日過濾都以實際響鈴的台灣日期判斷。預覽查詢未來 366 天，依行程模式保留秒精度，`skipped_occurrences` 也保留完整時間。
- 沒有日期或固定時段的常駐本地文字不參與聯動。來源移除或讀取失敗不退回每日鬧鐘，也不使用過期訂閱資料。
- 聯動由伺服器計算，供網頁鬧鐘使用；既有 schema 2 裝置排程回應會排除聯動鬧鐘，避免舊硬體將新條件誤當成每日響鈴。

日曆目前涵蓋 **2023-01-01 至 2027-12-31**，依政府行政機關辦公日曆判斷，不代表所有公司的出勤規則，也不包含颱風停班或個人輪班。超出範圍回 `unknown`；工作日、假日及「跳過假日」規則不猜測下一次時間，未啟用假日過濾的每天、星期及指定日期仍可計算。日曆目前隨 Server 資料檔更新，尚未自動下載未來年度資料。

## 管理 API

API 接受 JSON，預期錯誤以 `{"error":"..."}` 回應（已匹配的 API 路由）。資料驗證錯誤為 400、不存在為 404、儲存 I/O 失敗為 500；失敗寫入不會覆蓋已保存的資料。另有認證、Content-Type、大小及 HTTP 方法錯誤，見下方錯誤表。請求上限 1 MiB。

本文件涵蓋排程、行事曆聯動及裝置同步；舊時鐘的設定／提醒 API 另依[使用指南](guide.md)操作。以下 URL 均相對於自行架設的 Server，不是公開 GitHub Pages 時鐘。

| 路徑 | 方法與用途 |
| --- | --- |
| `/api/v1/schedules` | GET 排程、下一次事件、Server 時間、今日日期與日曆範圍；POST 新增 |
| `/api/calendar` | GET/POST 行事曆來源；PATCH 僅更新顯示選擇 |
| `/api/v1/calendar-events?source_id=work` | GET 所選來源未來 366 天的行程目錄；多來源重複 `source_id` 參數 |
| `/api/v1/schedules/preview` | POST 排程草稿；可附 `skip_next: true` 預覽略過及恢復後的下一次，不寫入 |
| `/api/v1/schedules/<id>` | PUT 修改指定欄位；DELETE 刪除 |
| `/api/v1/schedules/<id>/skip-next` | POST 跳過下一次，回 `skipped` 與 `next_event` |
| `/api/v1/browser-alarms` | GET 時鐘頁的下次鬧鐘、Server 時間及假日資料狀態 |
| `/api/v1/holidays?date=2026-09-30` | GET 日期類型；省略日期時查台灣今天 |
| `/api/v1/devices` | GET 裝置列表、最後回報與待確認同步指令 |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`，回 202 與 `command` |

管理 API 沿用可信任區網模式，不具備登入功能。Server 拒絕不同 Origin 的瀏覽器存取；這不是完整身份驗證。遠端部署須在反向代理限制存取並啟用 HTTPS。

所有管理寫入（POST／PUT／PATCH／DELETE，包括設定、提醒、備份匯入、排程預覽及裝置同步要求）都需要 CSRF token 和同一工作階段的 `webclock_csrf` cookie。管理頁會自動處理；程式呼叫先 GET `/api/csrf`，保存回應 cookie，再以 `X-CSRF-Token` 傳入回應的 `csrf_token`；HTML 表單則使用隱藏欄位 `csrf_token`。省略 Origin 也不能省略 token。缺少、錯誤或失效時回 403 `{"error":"CSRF validation failed; reload the management page.","code":"csrf_failed"}`；跨來源 Origin／Referer／`Sec-Fetch-Site: cross-site` 也會被拒絕。

例如，用同一個 cookie 檔預覽草稿（`WEBCLOCK_URL` 指向自架 Server）：

```bash
cookie_file=$(mktemp)
csrf_token=$(curl --fail --silent --show-error -c "$cookie_file" "$WEBCLOCK_URL/api/csrf" | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf_token"])')
curl --fail --silent --show-error -b "$cookie_file" \
  -H "X-CSRF-Token: $csrf_token" -H 'Content-Type: application/json' \
  -d '{"name":"Preview","time":"07:30"}' "$WEBCLOCK_URL/api/v1/schedules/preview"
rm -f "$cookie_file"
```

提醒刪除 `/delete/<id>` 只接受帶 token 的 POST，GET／HEAD 回 405。管理 HTML、錯誤頁及 token 回應使用 `no-store`，不開放跨來源讀取。現有單一 Server 程序在重啟後會使舊 token 失效，請重新載入管理頁或重新取得 token。公開時鐘不需要 CSRF cookie；`/api/v1/device/*` 仍沿用獨立的 `DEVICE_API_TOKEN`，不要求 CSRF token。CSRF 不會限制可直接連線的區網用戶，也不等於登入保護。

`/api/calendar` 的 `sources` 每筆包含 `id`、`name`、`provider`（`apple`／`google`／`ics`）、`url`、`display_enabled`；`local_display_enabled` 控制本地提醒顯示。新增來源可省略 ID，由伺服器產生；更新時保留 ID 以延續鬧鐘引用。POST 完整保存來源，PATCH 只接受來源 ID 與顯示旗標。舊 `{"url":"..."}` 與 `.env` 的 `ICAL_URL` 仍可讀取遷移。網址僅出現在專用管理回應，不進入時鐘 API、排程 API、裝置 API、備份匯出或離線快取。

`GET /api/v1/schedules` 的 `calendar_sources` 提供含本地提醒的來源目錄，每筆僅有 `id`、`name`、`provider`，供鬧鐘選擇使用。

`GET /api/v1/calendar-events` 必須指定既存來源，回傳 `events` 與 `server_time`。每筆行程只有 `source_id`、`uid`、`text`、`starts_at`、`ends_at`、`all_day`、`recurring`、`recurrence_id`；時間戳為 Unix 毫秒，不包含訂閱網址。取消或刪除的行程不會出現在目錄；已保存的指定行程鬧鐘不會因此改成跟隨其他行程。

`POST /api/v1/schedules/preview` 回 `server_time`、`timezone`、`next_occurrence`；附 `skip_next: true` 時另回 `skipped_occurrence`。管理頁編輯器以 Server 時間顯示下一次響鈴倒數；恢復倒數則計至略過的原定時刻，不是下一次實際響鈴時刻。`PUT /api/v1/schedules/<id>` 可將修改與 `skip_next: "預覽所得完整時間"` 一起儲存；`POST /api/v1/schedules/<id>/skip-next` 可附 `expected_occurrence` 防止預覽過期。時間已改變時回 400 `Occurrence changed; preview again`。永久停用設 `enabled=false`；提前恢復則保留已過期略過記錄、移除未到期記錄並設 `enabled=true`。

### 排程寫入與回應

POST／PUT 的本文使用 `Content-Type: application/json`，布林值與整數不可改成字串。不接受未定義欄位；不要直接把 GET 管理列表中含 `next_occurrence` 的整筆資料送回寫入 API。

| 欄位 | 限制與預設 |
| --- | --- |
| `id` | 可省略由 Server 產生，或提供 1–80 個英數字、底線、連字號；新增不可重複，PUT 不可變更 ID |
| `name`、`time` | 新增必填；名稱去除前後空白後 1–120 字元，時間嚴格為 `HH:MM`，例如 `07:30` |
| `type`、`enabled` | 預設 `alarm`、`true`；類型見上節 |
| `rule` | 預設 `{}`；星期陣列 1–7 筆、日期陣列 1–366 筆，值排序並去重；`workday_only`／`holiday_only` 的值只能是 `true` |
| `skip_holidays` | 布林值，預設 `false` |
| `browser_sound`、`browser_volume` | 預設 `bell`、100；音色與音量限制見上節 |
| `skipped_occurrences` | 預設 `[]`，最多 3660 筆含時區的 ISO 日期時間，每筆最長 40 字元；儲存時轉為台灣時區、排序並去重 |
| `calendar_link` | 可省略或 `null`；只適用 `alarm`，來源 1–50 筆，需為既存來源 ID；其餘語意見上節 |

`PUT` 合併指定的頂層欄位，未提供的欄位保留；提供 `rule` 或 `calendar_link` 時替換該物件，不是深層合併。`calendar_link: null` 解除聯動，`skipped_occurrences: []` 清除略過記錄。

| 操作 | 成功回應 |
| --- | --- |
| POST `/api/v1/schedules` | 201，本文為保存後的排程物件，沒有 `schedule` 外層 |
| PUT `/api/v1/schedules/<id>` | 200，本文為保存後的排程物件 |
| DELETE `/api/v1/schedules/<id>` | 200，`{"status":"deleted"}`；再次刪除為 404 |
| POST `/api/v1/schedules/<id>/skip-next` | 200，`{"skipped":{...},"next_event":{...}}`；沒有後續時間時 `next_event` 為 `null` |

`next_event`／`skipped` 物件包含排程欄位，另有含時區的 `datetime` 與 `occurrence_id`；不是只有時間字串。預覽的 `next_occurrence` 則是含時區的字串或 `null`。`null` 可能表示停用、日期已過、來源不可用或工作日資料不足，不能當作裝置故障。

一般排程寫入沒有 `If-Match` 版本鎖或合併衝突協定；裝置 GET 的 ETag 僅供讀取快取。管理端完成修改後應重新取得資料，不能把 ETag 當作防止多人覆寫的保證。

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
| `alarms[].volume` | 0–100 的網頁音量，來自 `browser_volume`；新版網頁讀到未提供此欄位的舊回應時使用 100 |
| `holiday_coverage`、`holiday_known` | 假日資料涵蓋範圍與是否已知 |

查詢從當分鐘起算，避免剛到時刻的鬧鐘因 API 延遲就直接跳至下一次；同一分鐘內不同秒的聯動行程會保留。這份回應不是完整離線排程快照。時鐘頁約每 15 秒更新一次；已載入的下次時間可在暫時斷線時觸發，重新開頁與取得後續週期仍需連線。超過 60 秒才恢復處理的過期鬧鐘不補響。

頁面使用原生 Web Audio 合成 7 種音色，另提供 `silent` 靜音模式，不下載音檔或載入音訊框架。每次開頁需點小鈴鐺「啟用聲音」並聽到短音；相容舊 Safari 的 `webkitAudioContext`。iOS 需要使用者操作啟用音訊，切換 App、分頁或鎖屏也可能中斷音訊與計時，因此須保持時鐘頁在前景、螢幕開啟，不保證背景或鎖屏響鈴。[Apple Web Audio 說明](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/Using_HTML5_Audio_Video/PlayingandSynthesizingSounds/PlayingandSynthesizingSounds.html)、[MDN iOS 中斷行為](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/state#resuming_interrupted_play_states_in_ios_safari)

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

### 傳輸與目前支援範圍

- 裝置直接呼叫 Server 的 HTTP/JSON API；不使用 ESPHome Native API 協定，也不需要 Home Assistant 或 MQTT。HTTPS 部署時須驗證伺服器憑證，不能把關閉驗證當成正式設定。
- POST 使用 `Content-Type: application/json`；正常 JSON 回應為 `application/json`。三個 GET 支援條件請求，其 `Cache-Control` 為 `private, no-cache`；註冊、回報與管理回應預設 `no-store`，不得加入公開 Service Worker 快取。
- 三個 GET 不要求先註冊，也不接受裝置 ID、日期區間、分頁或群組作為資料篩選。附加 `id`／`date` 不會限制回應；目前只處理 `revision` 條件參數。
- `/device/schedules` 包含所有非聯動排程，含停用項目與非 `alarm` 類型，沒有 `next_occurrence`。裝置必須自行判斷 `enabled`、`type`、規則及略過時間。`calendar_link` 排程整筆排除，並非轉成每天響鈴。
- `/device/holidays` 是政府工作日表，**不是 Apple／Google／ICS 行程清單**。目前一次下載全部涵蓋日期；沒有日期視窗或分頁。2023–2027 共 1826 天，JSON 約 122 KB 起，序列化方式及來源中繼資料會影響大小，解析所需 RAM 另外計算。
- `config` 沒有 `server_time`。排程時區固定為 `Asia/Taipei`；裝置須另外校時，不能把收到 HTTP 回應當成時間已正確。
- 尚無裝置配對、獨立 token、撤銷、使用者歸屬或每台排程指派；註冊的 `id` 為自報識別值，不是認證。共用 token 持有者能以其他已知 ID 回報，GET 也會取得共用資料。

### GET 回應形狀

以下 `<...>` 是說明用占位值，實際 revision 是 64 個十六進位字元；不要照抄作為裝置回報。

`GET /api/v1/device/config`：

```json
{
  "schema_version": 2,
  "timezone": "Asia/Taipei",
  "config_revision": "<config_revision>",
  "schedule_revision": "<schedule_revision>",
  "holiday_revision": "<holiday_revision>"
}
```

`config_revision` 只表示設定內容（目前為 schema 與時區）。修改鬧鐘通常只改變 `schedule_revision` 及整個 config 的 ETag，不會改變 `config_revision`。

`GET /api/v1/device/schedules` 的完整範例（只有一筆一般鬧鐘時）：

```json
{
  "revision": "<schedule_revision>",
  "schedules": [
    {
      "id": "work_alarm",
      "name": "上班提醒",
      "type": "alarm",
      "time": "07:30",
      "rule": {"weekdays": [1, 2, 3, 4, 5]},
      "enabled": true,
      "skip_holidays": true,
      "browser_sound": "bell",
      "browser_volume": 100,
      "skipped_occurrences": []
    }
  ]
}
```

`browser_sound`／`browser_volume` 雖在回應中，仍是網頁音色／音量，沒有承諾硬體可播放同音色或具有相同音量。硬體端需另定能力與映射；現行 API 不支援上傳音檔、控制音量、停止當次響鈴或貪睡命令。

`GET /api/v1/device/holidays` 的欄位：

| 欄位 | 內容 |
| --- | --- |
| `schema_version` | `1`，僅指工作日快照格式 |
| `timezone` | `Asia/Taipei` |
| `coverage` | `{"start":"2023-01-01","end":"2027-12-31"}`，起訖日均包含 |
| `source` | 來源中繼資料物件，含 `name`、`scope`、`generator`、`verified_at`、`urls`，以及各年度核對資料 |
| `days` | 以 `YYYY-MM-DD` 為 key 的物件；每日值含 `type`（`workday`／`holiday`）、`name`、`makeup_workday` |
| `revision` | 此快照的版本，與 config 的 `holiday_revision` 相同 |

`days` 節錄（實際回應包含整個範圍）：

```json
{
  "2026-10-03": {"type": "holiday", "name": "", "makeup_workday": false},
  "2026-10-05": {"type": "workday", "name": "", "makeup_workday": false}
}
```

快照不會為範圍外日期建立 `unknown` 項目；客戶端需依 coverage／缺少日期判斷未知。不要把「查不到」當平日。管理端單日 API `/api/v1/holidays?date=2028-01-01` 則回 `type: "unknown"`、`known: false`、`holiday: null`。這兩個 API 的回應形狀不同。

### 同步流程

1. 裝置以固定 `id` 註冊。重複註冊保留狀態與待確認指令，並更新名稱。
2. GET `config`，確認支援 `schema_version=2`。
3. 比較三種 revision，只下載變更的排程或日曆；第一次接入需取得完整資料。
4. 檢查下載資料的 `revision` 分別等於第一份 config 指定的版本，再 GET `config` 確認整組版本沒有在同步途中改變；有變更時重試。裝置應在驗證與持久保存成功後才一次切換設定、排程、日曆及其版本，失敗則保留完整的上次資料。
5. POST `status`，回報已保存的版本；Server 不會假定「已下載」等於硬體已成功執行排程。

revision 是內容的 SHA-256 字串，內容相同就不變。三個 GET 資源都支援 `If-None-Match` 或 `?revision=...`，一致回 304，無回應本文。排程及日曆使用本文中的 `revision`；`config` 應使用其回應 ETag（去除引號後可用於 query），**不是** `config_revision`，因為 ETag 同時包含排程和日曆版本。

日曆快照的 `schema_version=1` 只描述日曆格式，與裝置設定的 `schema_version=2` 是不同契約。

韌體實作還需遵守以下規則：

- 把 revision 當不透明版本字串；不能比較大小推斷新舊，也不能直接雜湊 HTTP 本文來比對。Server 雜湊的是排序後的資料內容，排程只雜湊陣列，不包含外層 `revision`。
- 每個資源保存各自的 ETag。`If-None-Match` 傳回原本含引號的 ETag；使用 query 時只傳不含引號的值。兩者擇一即可。
- 304 只表示內容未變，不是空清單；只有本機已有完整且驗證通過的對應資源時才能沿用。首次啟動、快取遺失／損毀時不帶條件重新下載；收到 304 不解析 JSON，也不清空資料。
- 第二次 config 若使用條件請求，必須使用**本次第一次取得**的 config ETag。304 代表它仍相同；200 則比較整組版本。不應使用更早的已套用 ETag 判斷這次下載是否一致。
- 清單是完整快照，成功後整份替換；合法的 `schedules: []` 表示刪除全部裝置排程。只做新增／更新會漏掉刪除，以及一般鬧鐘改為行事曆聯動後應移除的舊資料。
- 所有下載與解析都要設容量／逾時限制；超量、未知 schema、缺欄位、半份 JSON、Flash 寫入失敗均不得當作成功。不可截掉超額排程後回報整份已同步。
- 網路錯誤時退避重試並保留原有效快取；只在資料變動時寫入 Flash。輪詢不能阻塞本機響鈴。已知認證失效時停止存取受保護資料，不能改用空 token 重試；現有 schema 2 沒有授權有效期／離線撤銷協定。

例如，可每 30 秒檢查 config、每 60 秒回報 status；這是客戶端起始建議，不是 Server 主動推送或已實作的韌體預設。

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

| 請求 | 欄位限制 |
| --- | --- |
| register | 只接受 `id`、`name`，兩者必填；ID 為 1–64 個英數字、底線或連字號；name 必須非空白且原始長度不超過 100 字元，保存時去除前後空白 |
| status | 必填 `id`；可選 `firmware`、三種 revision、`acknowledged_commands`；不接受其他欄位 |
| status 的四個字串 | 必須非空白且原始長度不超過 128 字元，保存時去除前後空白；不可用 `null` 或空字串清除 |
| `acknowledged_commands` | 最多 100 個 ID，每個使用與裝置 ID 相同的字元／長度限制；省略等同 `[]` |

目前沒有 `wifi_rssi`、`rtc_ok`、`last_alarm`、同步錯誤或實際響鈴紀錄欄位；直接加入 status 會回 400。Server 只保存自報的 revision 字串，不檢查它是否等於目前版本，也不驗證 Flash 或播放結果。

首次註冊的完整回應為 201：

```json
{
  "device": {
    "id": "bedroom",
    "name": "臥室裝置",
    "registered_at": "2026-10-03T00:00:00+00:00",
    "commands": [],
    "online": false
  }
}
```

即使同 ID 已存在，重新註冊仍回 201，保留 `registered_at`、舊回報與指令並更新名稱；不是領取獨立憑證。新裝置還沒有 `last_seen`；註冊不會當作狀態心跳。兩台裝置使用同一 ID 會共用狀態與命令，韌體應產生並保存穩定且不衝突的 ID。

管理端 POST `{"action":"sync"}` 到 `/api/v1/devices/bedroom/commands` 後，202 回應形如：

```json
{
  "command": {
    "id": "a1234567890b4567890c4567890d4567",
    "action": "sync",
    "created_at": "2026-10-03T00:00:10+00:00"
  }
}
```

裝置 POST status 回 200：外層為 `{"device":{...},"commands":[...]}`。`device` 包含上例註冊欄位、新的 `last_seen`、`online` 與歷次已回報的四個字串；`device.commands` 和外層 `commands` 是同一份待確認指令。時間戳 `registered_at`、`last_seen`、`created_at` 由 Server 產生，為 UTC ISO 日期時間；不要與網頁鬧鐘的 Unix 毫秒混用。

`online` 表示最近 120 秒內收到狀態回報，僅為最近連線情況。建議裝置約每 60 秒回報；不要求 RTC、Wi-Fi、電池或其他特定硬體能力。

管理頁的「要求同步」只加入 `sync` 指令。裝置下次 POST `status` 時取得 `commands`，完成同步後再用 `acknowledged_commands` 回報。指令在確認前持續回傳；重複按同步只保留同一筆待確認指令。裝置應依指令 ID 去重，失敗時不要確認。確認只影響該 `id` 的同步指令。

本專案提供上述 Server 契約、API 測試及網頁鬧鐘。獨立硬體的本機快取、準時觸發、斷線行為及指令執行由未來裝置專案實作與驗證。

可重現的要求 → 輪詢 → ACK 順序（以下 ID 皆為範例）：

1. `POST /api/v1/device/register`：`{"id":"bedroom","name":"Bedroom"}`。
2. 管理端 `POST /api/v1/devices/bedroom/commands`：`{"action":"sync"}`；202 回應的 `command.id` 記為 `C`，此時尚未同步完成。
3. 裝置 `POST /api/v1/device/status`：`{"id":"bedroom"}`；在 `commands` 取得 `C`。未帶 ACK 重送會再取得同一筆，Server 重啟後也會保留。
4. 裝置依上述同步流程下載、驗證及持久保存，成功後 `POST /api/v1/device/status`，帶三種已保存 revision 及 `"acknowledged_commands":["C"]`。
5. 回應 `commands` 不再含 `C`，管理端重新載入列表後待確認指令消失。未收到成功回應可重送 ACK；失敗時不帶 ACK，保留舊快取。只會移除該裝置相符的指令。

管理畫面的「已要求同步」不是 ACK；`online`、版本相同或指令消失，都不是硬體已實際響鈴的證據。

### 最小連線檢查

以下在可信任 LAN、`DEVICE_API_TOKEN` 為空的測試 Server 執行；將位址改為裝置實際可達的主機，ESP 上的 `localhost`／`127.0.0.1` 指的是 ESP 自己。註冊與回報會保存測試裝置，先選好穩定 ID，不要每次隨機新增。

```bash
WEBCLOCK_URL='http://192.168.1.20:5000'
curl -i "$WEBCLOCK_URL/api/v1/device/config"
curl -i -H 'Content-Type: application/json' \
  -d '{"id":"bedroom","name":"臥室裝置"}' \
  "$WEBCLOCK_URL/api/v1/device/register"
curl -i -H 'Content-Type: application/json' \
  -d '{"id":"bedroom"}' \
  "$WEBCLOCK_URL/api/v1/device/status"
```

非空 token 時，所有裝置請求另帶 `Authorization: Bearer <實際的 DEVICE_API_TOKEN>`；勿把真實 token 寫進文件、Git、公開韌體或日誌。這個連線檢查只確認 API 可達，不代表已下載／保存排程。

### 錯誤與恢復

| 狀態 | 原因與處理 |
| --- | --- |
| 400 | JSON 欄位、型別、ID、日期或數量不符；如 `Invalid device status fields`。修正請求，不無限重送相同內容 |
| 401 | `A device API token is required`；token 缺少或不符。檢查裝置設定，不自行降成免驗證 |
| 403 | `csrf_failed` 表示管理寫入 token／cookie 缺少、失效或來源不符，重新載入管理頁或取得 token；`Cross-origin management access is not allowed` 表示既有來源檢查不符。檢查同源部署及代理設定；兩者都不等於登入保護 |
| 404 | 已匹配 status／指令路由中的裝置不存在，通常為 `Item not found`；確認連到正確 Server，再依現行註冊流程處理。未知 URL 的 404 不保證 JSON |
| 405 | 方法不支援，例如 PUT 裝置 schedules；可能回 HTML，不當作排程解析 |
| 413 | 請求本文超過 1 MiB；這是上傳限制，不是下載日曆的大小上限 |
| 415 | 需要 JSON 的 POST／PUT 未使用 JSON Content-Type |
| 500 | 儲存 I/O 失敗時為 `Storage failed; previous data has been retained`；保留快取、稍後重試，主機端檢查磁碟與權限 |

先檢查 HTTP 狀態碼，再依 Content-Type 解析；代理登入頁、未知路由或未預期例外不保證有 `error` JSON。逾時、斷線及 5xx 不 ACK 未完成同步。ACK 成功但回應遺失可重送；格式合法但不屬於該裝置的指令 ID 不會清除其他裝置命令。

韌體的認證／同步失敗不得阻塞基本走時；主畫面不自動彈出系統錯誤，診斷由後台或使用者主動開啟的設定入口處理。這些客戶端行為尚待實作，無可信時間時也不能憑空得知正確日期；詳見 [ESPHome 裝置指南](esp-home.md#時間離線與使用者操作)。

### 後續擴充界線

ESPHome 目標中的「未來七天觸發清單」尚未提供 API，現有 `schema_version=2` 不會回 `valid_until` 或完整行事曆聯動事件。`/api/v1/browser-alarms` 也不是七天離線清單，不能代替這個功能。

實作時需另定能力／版本契約，包含清單有效期限、滾動補充、來源更新與失效、刪除、範圍切換，以及容量上限的完整性處理；沿用目前 Server 排程計算，保留既有 schema 2 語意。獨立裝置認證與部署模式切換也仍是待辦，不能在現行 status 任意增加尚未支援的欄位。開發順序與硬體驗收見 [ESPHome 裝置指南](esp-home.md)。

## 舊原型與資料保存

- 舊音效 API、音檔、硬體聲音服務及 Python 模擬裝置已移除，裝置指令目前只有 `sync`。目前網頁鬧鐘改由瀏覽器合成內建音色。
- 舊 `schedules.json` 的 `sound`、`volume`、`repeat`、`snooze_minutes` 會留存檔案，編輯其他欄位也保留，但不公開、不套用。新 API 不接受這些欄位。
- 新增的 `browser_sound` 與 `skip_holidays` 正常透過排程管理儲存，不沿用舊音檔或舊硬體音量設定。
- 舊裝置硬體欄位、`test_sound`／`restart` 待執行命令同樣留存，但不公開也不再交給裝置。
- `webclock_state/sounds/`、`webclock_state/fake-device/` 等既有使用者資料不會自動刪除。Server 不再讀取它們。
- 舊根目錄 `manual_notes.json` 仍會首次複製到狀態目錄，保留原檔。`NOTES_FILE` 和 `WEBCLOCK_STATE_DIR` 仍可覆寫路徑。

請備份整個狀態目錄、提醒檔和 `.env`。`/admin` 的 JSON 匯出仍只包含顯示設定與手動提醒，不含智慧排程或裝置資料。Linux 更新器會備份預設路徑和服務實際設定的 `WEBCLOCK_STATE_DIR`、`NOTES_FILE`，失敗時嘗試一起回復程式、套件與資料。Docker 的自訂路徑仍需自行掛載及備份。操作方式與首次升級步驟見[繁體中文使用指南](guide.md#備份資料與更新)。

目前用單一 Server process 寫入 JSON，最多 1000 筆排程、100 台裝置；增加多個 worker 前需改用支援跨程序交易的儲存方式。

## 驗證

```bash
python -m unittest discover -s tests -p 'test_*.py'
node tests/test_clock.js
node tests/test_time_format.js
node tests/test_offline.js
node tests/test_schedule_ui.js
node tests/test_alarms.js
node tests/test_calendar_ui.js
node tests/test_management_navigation.js
node tests/test_management_theme.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

測試涵蓋管理 CRUD、工作日／補班日、跳過、同步版本、存取檢查、裝置回報／確認及舊資料保存。更新整合測試會啟動真實舊版／新版 Server，驗證 Git 升級、外部資料路徑及新版寫入後的失敗還原；需完整 Git 歷史與舊版使用的 `holidays` 套件，缺少時會明確略過。systemd、pip 與 Linux 服務環境查詢使用替身，不代表目標主機部署或硬體驗收。

本機驗證、iPad mini 1／iOS 9 待驗收步驟，以及 2027 年之後工作日資料維護方式，見[第一階段驗收紀錄](phase1-acceptance.md)。
