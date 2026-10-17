# 裝置與 AI 程式寫入 API

Home Assistant、ESP 或 AI agent 可用同一套 HTTP API 建立、修改、刪除鬧鐘與 WebClock 本地行事曆事件，再獨立指派給已授權群組／裝置。這一版不含音檔上傳、本地重複事件或 Google／iCloud 寫回；鬧鐘可繼續使用既有內建音色、排程規則及外部重複行程聯動。

程式建立的內容不會自動廣播；self 模式也一樣。新鬧鐘必須明確指派給已完成六碼加入的群組／裝置，接收端使用 v2 裝置同步；匿名 self 畫面及舊 schema 2 裝置不會取得這些程式鬧鐘。原本由後台建立的鬧鐘保留既有行為。WebClock 本地事件也預設不公開；管理者可另外選擇公開顯示事件，但聯動這類事件的鬧鐘不支援舊 schema 2。

## self 與 managed 身份

| 項目 | self | managed |
|---|---|---|
| 憑證發行者 | 既有 self 管理入口／HA Ingress 的管理者 | 登入的 WebClock 管理員 |
| 程式如何呼叫 | 獨立的 `Authorization: Bearer …` 程式憑證 | 同樣使用獨立程式憑證 |
| 傳輸 | 信任的區網可使用 HTTP；公開網路使用 HTTPS | 伺服器強制 HTTPS |
| 授權範圍 | 安裝實例的 owner、指定 scope 與資源 | 目前 owner、managed 模式、指定 scope 與資源 |

即使 self 管理頁在可信任區網不需登入，新的程式寫入 API 仍必須帶憑證。顯示裝置 token、六碼加入碼、`DEVICE_API_TOKEN`、管理頁 Cookie 都不能取代程式憑證。self 憑證綁定 self；切換到 managed 後必須重新核發，不能沿用。HA App 的 self 儲存模式與 WebClock managed 登入是不同模式。

在管理頁「程式存取」(`/integrations`) 建立及撤銷憑證；進階管理也可呼叫 `POST /api/v1/control-clients` 核發；`GET /api/v1/control-clients` 列出；`DELETE /api/v1/control-clients/<id>` 撤銷。這些管理操作沿用原本管理身份、CSRF 與入口限制。核發內容範例：

```json
{
  "name": "Home Assistant",
  "scopes": ["schedules:read", "schedules:write", "events:read", "events:write", "assignments:write"],
  "group_ids": ["REPLACE_GROUP_ID"],
  "device_ids": [],
  "calendar_source_ids": [],
  "schedule_ids": [],
  "event_ids": [],
  "expires_in": 2592000
}
```

憑證只在核發回應中顯示一次，伺服器保存摘要；到期／撤銷後即失效。空資源清單不代表全部權限：憑證可操作自己成功建立的內容，以及明確授權的既有內容。讀取與寫入 scope 分開；指派另需 `assignments:write` 與明確群組／裝置 ID。外部行程聯動需授權 `calendar_source_ids`；自己建立的 WebClock 事件可用其精確 ID 聯動，不因此取得全部本地事件的權限。

## 請求與版本

全部程式端路由位於 `/api/v1/control`，內容為 JSON。伺服器驗證所有時間、規則、身份與目標；不要讓模型自行推定保存成功。

| 操作 | 路徑 | JSON 內容 |
|---|---|---|
| 憑證範圍 | `GET /identity` | 無 |
| 外部事件目錄 | `GET /calendar-events?source_id=<授權來源>` | 無；可重複 source_id |
| 列出 | `GET /schedules`、`GET /events` | 無 |
| 讀取 | `GET /schedules/<id>`、`GET /events/<id>` | 無 |
| 建立 | `POST /schedules` | `{"request_id":"stable-request-001","schedule":{...}}` |
| 建立 | `POST /events` | `{"request_id":"stable-request-002","event":{...}}` |
| 修改 | `PATCH /schedules/<id>`、`PATCH /events/<id>` | `{"revision":"上次讀到的版本","schedule或event":{要修改的欄位}}` |
| 刪除 | `DELETE /schedules/<id>`、`DELETE /events/<id>` | `{"revision":"上次讀到的版本"}` |
| 讀取指派 | `GET /<schedules或events>/<id>/targets/<group或device>/<target_id>` | 無 |
| 更改指派 | 同上，`PUT` | `{"revision":"指派版本","assigned":true}` |

單筆保存／讀取回傳 `schedule` 或 `event` 及 `revision`；鬧鐘也回傳 `next_occurrence` 與其狀態。清單回傳 `schedules`／`events` 陣列，每筆保留自己的版本。刪除回傳 `status: deleted` 與 ID。指派回傳 `assigned` 與指派版本，不能拿事件版本取代指派版本。

`request_id` 使用 8–128 位英數、底線或連字號，每次新的建立操作使用新 ID。斷線後重送相同 ID 與相同內容，可拿回原建立結果；不可用新 ID 無條件重試。重送回應的 `replayed: true` 表示原始保存結果，內容可能已修改或刪除，請再 GET 讀回目前狀態。相同 ID 換內容會得到 `409 idempotency_conflict`。`409 request_incomplete` 表示前次保存中斷，資料若仍與原候選完全一致會自動完成收據；無法確認時需要管理者檢查，不能自行再次建立。

修改／刪除必須帶上次讀取的 SHA-256 `revision`；衝突會得到 `409 revision_conflict`。客戶端應重新讀取並讓使用者或代理確認如何合併，不能自動抓新版本覆蓋。建立內容與指派是兩個獨立操作，請分別確認回應；不宣稱跨操作原子成功。

## 鬧鐘與事件範例

每日 07:30 的鬧鐘內容，沿用既有 Asia/Taipei 排程：

```json
{"name":"起床","time":"07:30","enabled":true,"rule":{},"browser_sound":"bell"}
```

建立一個事件，事件開始前一天顯示，直到結束：

```json
{
  "title": "開會",
  "start": "2030-10-09T14:00:00+08:00",
  "end": "2030-10-09T15:00:00+08:00",
  "timezone": "Asia/Taipei",
  "all_day": false,
  "enabled": true,
  "display_window": {"mode":"relative","before_minutes":1440,"end":"event_end"}
}
```

`display_window` 只控制顯示，不改事件時間。支援 `{"mode":"day"}`；相對區間的 `end` 可選 `event_end` 或 `day_end`；指定區間使用 `{"mode":"absolute","start":"2030-10-08T18:00","end":"2030-10-09T15:00"}`，按該事件時區解讀。全天事件的 `start`／`end` 使用 `YYYY-MM-DD`，結束日期不包含在事件內。

要在這項事件前 15 分鐘開鬧鐘，取得建立結果的事件 `id` 後，再建立以下鬧鐘：

```json
{
  "name":"開會前提醒",
  "time":"00:00",
  "calendar_link": {
    "mode":"event",
    "source_ids":["webclock"],
    "offset_minutes":15,
    "target":{"source_id":"webclock","uid":"REPLACE_EVENT_ID","scope":"occurrence","recurrence_id":""}
  }
}
```

聯動模式的觸發時間由事件起點與提前分鐘數決定；`time` 是既有鬧鐘格式的必填欄位。更改事件後，下一次鬧鐘會重新計算；停用／刪除事件則不再產生該事件的觸發。事件和鬧鐘仍需各自指派給接收端。

## Home Assistant 操作

先完成原有六碼加入，再於 WebClock 整合「選項」貼入**程式寫入憑證**。留空保留目前憑證；勾選移除即停止後續程式操作。憑證不會放入卡片、sensor 屬性或自動化參數；仍須保護 HA 設定及備份。

整合提供 `list_alarms`、`create_alarm`、`update_alarm`、`delete_alarm`，以及對應的 `list_events`、`create_event`、`update_event`、`delete_event`。`get_target`／`assign_content` 用於群組或單台指派。`list_calendar_events` 以 `source_ids` 陣列取得已授權外部來源未來一年的行程目錄，供選擇精確事件聯動；本地事件使用 `list_events`。

```yaml
action: webclock.create_alarm
data:
  request_id: morning-alarm-20301009
  schedule:
    name: 起床
    time: "07:30"
    rule:
      dates: ["2030-10-09"]
response_variable: saved_alarm
```

需要重送時保留同一 `request_id`；要在另一日重新建立，產生另一個 ID。後續修改使用回應中的 `saved_alarm.schedule.id` 與 `saved_alarm.revision`。原有鬧鐘可先用 `webclock.list_alarms` 取得 ID／版本。設定未載入、缺少憑證、權限拒絕與版本衝突都會讓 action 失敗，不會回傳假的成功。

指派先呼叫 `webclock.get_target`，傳入 `resource: schedules`（或 `events`）、內容 `id`、`target_kind: group`（或 `device`）、`target_id`；再以取得的指派 `revision` 與相同欄位呼叫 `webclock.assign_content`，加上 `assigned: true`／`false`。

## AI agent／一般程式

標準庫工具 `scripts/control_clock.py` 可直接供受控 agent 或自動化使用。伺服器來源及憑證由環境預先設定；模型操作不接受任意 URL、額外標頭或憑證參數，不跟隨 HTTP redirect。不要把 token 寫進提示詞或提交的檔案。

```bash
export WEBCLOCK_SERVER_URL=https://clock.example
# 輸入時不回顯；環境變數應由宿主的秘密管理機制注入。
read -r -s WEBCLOCK_WRITE_TOKEN
export WEBCLOCK_WRITE_TOKEN
python3 scripts/control_clock.py identity list
python3 scripts/control_clock.py calendar-events list --source-id REPLACE_SOURCE_ID
python3 scripts/control_clock.py schedules list
python3 scripts/control_clock.py events create < event-request.json
python3 scripts/control_clock.py events get REPLACE_EVENT_ID
python3 scripts/control_clock.py events update REPLACE_EVENT_ID < event-update.json
python3 scripts/control_clock.py events target REPLACE_EVENT_ID --target-kind group --target-id REPLACE_GROUP_ID
python3 scripts/control_clock.py events assign REPLACE_EVENT_ID --target-kind group --target-id REPLACE_GROUP_ID < assignment.json
```

`event-request.json` 包含 `request_id` 與上方 `event` 內容；修改包含 `revision` 與 `event`，指派包含 `revision` 與布林 `assigned`。成功輸出伺服器實際 JSON，失敗以非零結束碼及不含憑證的錯誤 JSON 回報。若 agent 需要工具介面，可將這些固定操作包成其宿主工具；目前未另外提供 MCP server。

ESP 可用同一契約送 JSON 與 Bearer 標頭；需要保存未完成建立操作的 `request_id`，恢復網路後重送原內容。這一版提供伺服器與通用客戶端契約，尚未新增 ESP 本機輸入介面或實機驗收。

建立收據目前最多保存 10,000 筆，不會依時間自動刪除。達上限回傳 `capacity_reached`，需管理者處理；高寫入量或跨操作交易需求應改用具交易能力的儲存，不能靠清空收據規避重複建立保護。

## 驗證與狀態

本機 HA 測試使用 Home Assistant 2026.9.4／Python 3.14；新增測試涵蓋憑證分離、無 redirect／cookie、固定路徑、版本衝突、缺少憑證、選項保留／撤銷與 CLI JSON 契約。可執行：

```bash
python -m unittest discover -s homeassistant/tests -p 'test_*.py' -v
node homeassistant/tests/test_cards.js
```

伺服器已保存、裝置已同步與實際響鈴仍是三種不同狀態。這些測試不代表已部署到使用者的 HA、ESP、舊 iPad 或揚聲器。HTTP 錯誤不應以全權管理帳密或匿名重試來繞過。

HA 官方參考：[action 註冊與回應](https://developers.home-assistant.io/docs/dev_101_services/)、[action 錯誤處理](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/action-exceptions/)。
