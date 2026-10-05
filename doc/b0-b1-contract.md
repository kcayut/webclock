# B0–B1：管理身份、群組與邀請契約

2026-10-05。B0–B1 提供管理登入、入口隔離、復原相容、群組與邀請服務/API。B2 的加入交易與受管顯示、B3 的輸碼/群組管理畫面、B4 的正式遷移仍未交付。`/api/health` 的 `managed_devices_ready` 固定為 `false`，schema 3 表示凍結的後續契約版本，不表示裝置已能加入。

## 部署與管理者

- 沒有授權檔的舊安裝保持 `self` 自用模式；讀取不自動寫檔，也不把舊裝置 ID 升格為身份。自用模式保留原本可信區網共用管理/顯示規則，CSRF 仍適用。
- 明確的主機操作才可初始化 `managed`；B0–B1 只允許隔離測試，必須指定 `--enable-managed-test`。正式安裝須等 B3/B4 驗收。
- 明確初始化後，每個安裝的 owner 為穩定 UUID。尚未寫入授權檔的純讀取暫回 `local-owner`；首次群組變更會保存 UUID，之後初始化管理員沿用同一 owner。群組、邀請及裝置各有不同 ID，不能用名稱、IP、加入碼或自報 ID 接管。
- 主機先停止 WebClock，以服務帳號對正確 state 目錄操作，再重新啟動。密碼使用互動式提示，不放命令列、環境變數或日誌。

```sh
./venv/bin/python scripts/manage_auth.py --state-dir /path/to/isolated-state setup --username admin --enable-managed-test
./venv/bin/python scripts/manage_auth.py --state-dir /path/to/isolated-state reset-password
./venv/bin/python scripts/manage_auth.py --state-dir /path/to/isolated-state status
```

密碼長度 12–1024 字元，以 scrypt 雜湊保存。登入 session 為隨機 256-bit token；伺服器只保存 SHA-256 摘要，8 小時到期，每次請求重新核對。最多 100 筆 session；登出撤銷目前 session，主機重設密碼使全部 session 失效並輪換簽章秘密，不撤銷獨立裝置或輪換邀請秘密。初始化/重設後必須重啟，使新的 cookie 簽章秘密生效。

`GET/POST /login`、`POST /logout` 支援表單與 JSON。登入成功轉 `/admin`；JSON 回 owner/期限/新 CSRF token，不回管理 session token。登入/登出輪換 CSRF；登入 POST 要求 HTTPS。cookie 為 host-only、HttpOnly、SameSite=Lax，managed 加 Secure；寫入仍驗證同源與 CSRF，不依賴舊 Safari 的 SameSite。反向代理必須讓服務觀察到正確 HTTPS scheme，不能直接信任任意外來 forwarded headers；目前未加入自動 ProxyFix。不同信任範圍使用不同 hostname，cookie 不以 port 隔離。

登入所有嘗試（含成功）以實際 `remote_addr` 計算：每來源每 60 秒 5 次、全站每 60 秒 50 次；忽略 `X-Forwarded-For`。回 `429`、`code=rate_limited` 與整數秒 `Retry-After`。記憶體來源表有界；重啟清除限速視窗。

## 入口權限

| 入口 | self | managed |
| --- | --- | --- |
| `/`、靜態資源 | 原本時鐘 | 只有公開時鐘殼；不內嵌私人設定、事件、session 或 CSRF |
| `GET /api/time` | 毫秒 `server_timestamp` | 相同，匿名 |
| `GET /api/status` | 原共用 settings/events/next_event | 毫秒時間、`events: []`、`next_event: null`；即使登入也不擴權 |
| `GET /api/health` | 不含資料的模式/schema/就緒狀態 | 相同；授權資料損壞回 503 |
| `/admin`、`/schedules`、提醒表單、calendar/backup/control、排程/裝置/群組 API | 原共用管理，寫入要 CSRF | 必須有效管理 session；HTML 導向登入，API 401 JSON |
| `/api/v1/device/*` schema 2 | 原 shared-token 契約 | 403 `legacy_device_api_disabled`，管理 cookie 或 shared token 均不能繞過 |
| `/api/v1/browser-alarms` | 原共用鬧鐘 | 401 `device_authorization_required`，管理登入不能替代裝置身份 |
| `/api/csrf` | 同源 bootstrap | 同源 bootstrap；取得 token 不取得管理權限 |

新管理入口預設受保護，不逐條放行私人資料。跨來源管理操作拒絕；私人回應 `Cache-Control: no-store`，沒有 CORS `*`。公開 status/time/health 同樣 no-store；公開校時可 CORS `*`，不帶憑證。API 401/403 為 JSON，不回登入 HTML。SW 僅快取既有靜態白名單；登入、加入、群組、CSRF、管理頁/API 都不快取。

授權檔在運行中損壞時管理入口回 503，公開殼/時間仍可用；啟動時發現損壞則拒絕啟動，待主機復原。這只保證已載入且能執行的基本時鐘，不承諾服務停止時能重新載入。

## 持久檔與遷移

`auth.json` version 1：`mode` (`self|managed`)、`owner_id`、`username`、`password_hash`、互相獨立的 256-bit `session_secret`/`invite_secret`、`generation`、`sessions`。session map 以 token 摘要作 key，值為 owner/期限/世代。`auth-required` 先於 managed 初始化提交；存在 marker 而 auth 缺失/自用會拒絕服務，不降成免登入。秘密及授權 JSON 以原子寫入保存，檔案權限 0600。保持單程序寫入限制。

`device-access.json` version 1 頂層為 `groups`、`invites`、`devices`、`attempts` 四個 map。B1 的 devices/attempts 為空；後續 B2 加入必須在這**同一檔**原子提交扣額、身份、群組與憑證。`devices.json` 僅保留既有名稱/能力/ACK 觀察，不成為加入交易第二個必要提交。

群組記錄：`id`、`owner_id`、`name`、`enabled`、`display_overrides`、`content`、`content_version`、`created_at`、`updated_at`、`is_default`。`content` 僅存 `calendar_source_ids`（字串）、`manual_note_ids`（既有正整數 ID）、`schedule_ids`（字串）。沒有 ICS URL 副本。既有 JSON fixture 在 `tests/fixtures/legacy-b0-state.json`；遷移測試證明舊檔位元內容保留、隱藏來源不自動公開、自報裝置不自動認證。

`POST /api/v1/groups/initialize {}` 是明確、可重試的預設群組遷移：沿用目前有效設定，引用既有可見來源/本機提醒及排程；重送仍回同一群組。一般讀取不初始化；一般新建群組的三種內容清單預設皆空。

## 群組 API

| 方法/路徑 | body/結果 |
| --- | --- |
| `GET /api/v1/groups` | `{groups: [...]}` |
| `POST /api/v1/groups` | `name` 必填；可選 `enabled`、`display_overrides`、`content`；201 回群組 |
| `GET /api/v1/groups/:id` | 回群組及目前 `effective_settings` |
| `PATCH /api/v1/groups/:id` | 更新上述欄位；名稱不改 ID |
| `DELETE /api/v1/groups/:id` | 有成員時 409；先移轉成員才能刪除 |
| `POST /api/v1/groups/:id/invite` | `{capacity: 5}` 可省略 capacity；201 回邀請 metadata 及一次性明文 `code` |
| `GET /api/v1/groups/:id/invite` | `{invite: metadata|null}`，沒有 code/digest |
| `DELETE /api/v1/groups/:id/invite` | 關閉並回 metadata，不變更成員 |

設定沿用目前顯示驗證，逐欄繼承 owner 共用值，包括 night 子欄位。`display_overrides` 一次替換該物件；缺欄位繼承，`{}` 清除全部覆寫，false/0 保留原意。`content` PATCH 只替換傳入的清單，未傳清單保持，`[]` 明確清空。內容引用必須存在；聯動鬧鐘依賴來源必須合法，來源未選來顯示不會自動停用該鬧鐘。B2 才實作依群組過濾並下發事件/鬧鐘。

群組最多 100 組；跨 owner 存取回 404。非法值回 400，儲存失敗回 500 並保留原資料；損壞授權 JSON 回 503 `access_not_ready`，不自動修補或覆寫。

## 六碼邀請

使用安全亂數，字母不分大小寫，排除 I/L/O/0/1；期限固定 600 秒，名額預設 5、允許 1–100，總裝置 100。每群同時一組；重產換邀請 ID/碼，但群組與成員不變。invite map 以 group ID 尋址；記錄獨立 `id`、`group_id`、`owner_id`、`code_digest`、`created_at`、`expires_at`、`capacity`、`used`、`closed`。摘要為獨立伺服器秘密的 HMAC-SHA256。

metadata 回 `remaining` 與 `status` (`active|closed|disabled|expired|full`)。明文只在成功產碼 response 出現一次；列表、群組、state 檔、一般管理匯出不含明文。輸碼只能在未來 POST body，不放 URL/query/Referer/console/access log。

`check_invite` 為 B1 可測的服務契約，尚未公開加入路由，也不扣名額。對所有驗碼嘗試採每來源每 60 秒 10 次、全站每 60 秒 100 次；來源表最多 100 筆，僅使用伺服器確認來源；回 429 `rate_limited` 加 `Retry-After` 秒。無效、過期、關閉、停用、額滿皆一般 `invalid_invitation`，不洩漏群組/owner。B2 必須在同一 storage lock/原子提交內重新驗證並扣額，不能把 B1 的查驗結果當成已完成授權。

## 已凍結、尚待 B2–B4 的裝置契約

新端點 namespace `/api/v2/device/*`、顯示 schema 3：`join/prepare` 建立 10 分鐘 attempt 與未啟用 HttpOnly cookie；往返確認後 `join` 在單檔交易啟用原憑證、生成 Server ID、綁組並扣額。成功回應遺失後，原 attempt/cookie 重送回同一有效身份，不再次扣額；撤銷不得重送復活。`display`/`browser-alarms`/`status` 使用獨立裝置憑證，不接受 body id/group_id 代替身份。這些路由目前未實作（404）。

未來 device record 固定：`id`、`owner_id`、`group_id`、`enabled`、`status` (`active|disabled|revoked`)、`credential_digest`（字串或 null）、`credential_generation`、`created_at`、`assignment_revision`、`rejoin_required`。憑證至少 256-bit，伺服器只存摘要。未來快照帶 identity/assignment 與三類內容 revision、授權期限；私人內容租約預設 300 秒。必須先驗權限再處理 ETag/304，304 續期要明確回租約；失權停止伺服器私人資料與待響鬧鐘，保留本機提醒和有效非私密設定。租約、加入與撤銷驗收留 B2–B4。

以下固定 B2 實作的 wire 格式；**目前所有這些 v2 路由仍為 404**，不能用來操作 B1：

| 方法/路徑（皆以 `/api/v2/device` 為前綴） | 請求/成功回應 |
| --- | --- |
| `POST /join/prepare` | 同源 CSRF，body `{}`；201 回 `{attempt_id, expires_at}` 並設定待用 `webclock_device` HttpOnly cookie；重用未到期嘗試可回 200 |
| `GET /identity` | cookie 往返確認；待加入回 `{status: "pending", attempt_id, expires_at}`；已認證回 `{status: "active", identity}` |
| `POST /join` | 同源 CSRF，body `{attempt_id, code}`；新加入 201、同一有效身份重試 200，皆回 `{schema_version: 3, identity, server_timestamp}`；不得再 Set-Cookie 輪換憑證 |
| `GET /display` | 回 `{schema_version: 3, identity, server_timestamp, lease, config_revision, schedule_revision, holiday_revision, settings, events, next_event}` |
| `GET /browser-alarms` | 同一授權範圍，回 schema/identity/server_timestamp/lease，加既有 `enabled_count`, `enabled_ids`, `alarms`；alarms 沿用既有 occurrence ID、時間、音色/音量語意 |
| `POST /status` | 同源 cookie+CSRF，或獨立 Bearer；接受既有自報名稱/類型/能力/revision/ACK 欄位但拒絕 body `id`, `owner_id`, `group_id`, `admin_name`；Server 從憑證補 ID，再沿用 DeviceService 回報與 commands 契約 |

`identity` 固定為 `{device_id, owner_id, group_id, credential_generation, assignment_revision, identity_revision}`，後三者用來隔離請求與快取；identity_revision 為這個身份/指派範圍的摘要。`server_timestamp`、attempt 的 `expires_at` 與 `lease: {issued_at, expires_at}` 均用 Unix 毫秒數；持久檔的 created_at/expires_at 則使用含時區 ISO 8601 字串。config revision 包含實際繼承後設定；schedule revision 包含該組允許內容。心跳或改名不改內容 revision。

304 只可在當前憑證與指派仍有效時回傳，附 `X-WebClock-Server-Timestamp`、`X-WebClock-Lease-Expires-At`（Unix 毫秒）及 `X-WebClock-Identity-Revision`。缺少續租欄位的 304 不延長租約。v2 私人資料禁止 CORS `*`，使用 private/no-cache 且不進 SW。Bearer 與管理 session 永遠不互換；首版 browser 加入只支援同源自架頁。

未來 v2 錯誤固定 JSON `{code, error}`：無效憑證 401 `device_authentication_required`；已知失權 403 `device_authorization_revoked`；嘗試不符/裝置已加入而企圖換組 409 `join_attempt_conflict`；無效或不可用邀請 400 `invalid_invitation`；429 `rate_limited` 加 Retry-After 秒；保存失敗 500 `storage_failure`；損壞 state 503 `access_not_ready`。錯誤不含群組/owner 枚舉、六碼或憑證。B2 實作時須用這份格式加入正式回歸；本批次僅凍結格式。

## 更新、備份與還原

管理 `/api/backup` version 1 維持 settings + notes，排除身份/邀請/秘密。主機完整備份包含 `.env`、auth 與 access state，**未加密**，須保護備份目錄。自訂 `WEBCLOCK_STATE_DIR`/`NOTES_FILE` 使用既有 layout 規則與權限，不把秘密放公開 export。

managed 更新以公開 health + 本機保存資料驗證；不匿名讀管理資料，也不利用 shared token 繞過。self 保持現有 API 相容檢查；支援新 health 時由該契約決定 schema。更新失敗即時回滾保留最新受保護資料與撤銷狀態，只回程式/環境，並在啟動前以安裝版本的純驗證器確認可讀；舊程式不支援 auth schema 1 則保持停止，不能還原舊資料後直接啟動。

歷史還原先檢查目標最低保護模式；managed 不能套用沒有 managed 授權資料的舊備份。套用前在 staged state（含自訂路徑及休眠的預設 state）輪換兩個秘密/世代、清 sessions/attempts、關閉邀請；裝置保留記錄但清 credential_digest、遞增 credential_generation、標 revoked/disabled/rejoin_required。群組、內容與 `devices.json` 觀察保留。未知 credential schema 拒絕還原，不猜測清除；此流程不恢復任何歷史 session/碼/裝置憑證。

## 驗收邊界

本批次本機 Python、JavaScript、HTTPS Chrome 檢查結果見 TODO。沒有自動 commit/push、CI、正式部署或 iPad mini 1/iOS 9 實機驗收。B1 的產碼/查驗通過不代表 B2 的並發最後名額、原子加入或實際裝置顯示已完成。
