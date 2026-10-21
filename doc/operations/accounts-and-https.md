# HTTPS、帳號與模式管理

[安裝指南](../installation.md) · [使用指南](../guides/guide.md)

新安裝需要管理員登入時，使用下方 managed 安裝指令；既有安裝依對應章節設定。

<a id="https"></a>
## managed 的 HTTPS／內網 HTTP 設定

自行架設的 managed **預設要求 HTTPS**。沒有憑證時，安裝器會詢問是否需要 TLS；選擇 `n` 後，還須輸入 `HTTP` 再次確認，才會在 `.env` 儲存 `WEBCLOCK_ALLOW_HTTP=1`。直接 Enter、取消或無法讀取回答都不會啟用 HTTP。HTTP 仍須登入、裝置加入與個別程式授權，但密碼、憑證和私人資料沒有傳輸加密，只適用於可信任內網。

**HA App 可以在沒有 TLS 的內網 HA 使用**：它使用經驗證的 Ingress 管理入口與獨立裝置通道，不需要這個額外選項，也不會因它而放寬入口驗證。

新安裝可把已有的憑證一起交給安裝器，驗證 HTTPS 成功後才完成安裝；**不會代為申請網域、取得憑證或讓裝置信任自簽憑證**。憑證缺少配對、過期或不受信任時會停止，不會自動退回 HTTP。

先讓 `clock.example` 指向主機，換成實際名稱，準備名稱相符且所有顯示裝置信任的憑證與私鑰：

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --managed --tls-cert /absolute/path/fullchain.pem --tls-key /absolute/path/privkey.pem --tls-host clock.example
```

Docker 使用相同命令加 `--docker`。若憑證由私人 CA 簽發，再加 `--tls-ca /absolute/path/ca.pem`，並在每台顯示裝置信任該 CA；安裝器與健康檢查不會略過憑證驗證。密碼會在終端機互動輸入。完成後使用安裝器顯示的 HTTPS 網址，不要改用 IP 造成憑證名稱不符。

已有安裝要自行設定或更新 TLS 時：

**Bare metal：**在安裝目錄的 `.env` 指定服務帳號可讀取的絕對路徑：

```dotenv
WEBCLOCK_TLS_CERT=/absolute/path/fullchain.pem
WEBCLOCK_TLS_KEY=/absolute/path/privkey.pem
```

```bash
sudo systemctl restart webclock
```

使用憑證對應的名稱開啟 `https://主機名稱:5000/admin`。兩個欄位必須同時設定；檔案無效或不完整時啟動失敗，不會自動退回 HTTP。

**Docker：**把憑證及私鑰放在安裝目錄的 `tls/fullchain.pem`、`tls/privkey.pem`，在 `.env` 設定：

```dotenv
WEBCLOCK_HTTP_PORT=443
WEBCLOCK_TLS_CERT=/app/tls/fullchain.pem
WEBCLOCK_TLS_KEY=/app/tls/privkey.pem
```

```bash
docker compose up -d --force-recreate
```

開啟 `https://主機名稱/admin`。`tls/` 唯讀掛載至容器，已排除 Git 與映像建置；請另行安全保存憑證，主機完整資料備份不包含這個目錄。憑證更新後重啟服務／容器。

若前方已有反向代理，可轉送至上述 HTTPS 入口，並保留原本的 Host。WebClock 不會因任意 `X-Forwarded-Proto` 標頭就信任請求是 HTTPS。只在代理端終止 TLS、後端仍用 HTTP 時，預設仍會拒絕；本節的 HTTP 選項會允許所有能連到後端的 HTTP 請求，並非「信任代理」設定。

### 既有安裝選擇 HTTP

先更新至含此選項的版本、停止服務並備份 `.env` 與資料。不要重新執行全新安裝。尚未配置 TLS 時，可在安裝目錄執行互動確認：

```bash
./venv/bin/python scripts/install_check.py transport
```

Docker 沒有主機 Python 時：

```bash
docker compose run --rm --no-deps -v "$PWD:/install" -w /install webclock python scripts/install_check.py transport --kind docker
```

選擇 `n`，再輸入 `HTTP` 才會保存。已有 TLS 時仍會驗證憑證；若確定改用 HTTP，先從 `.env` 移除 `WEBCLOCK_TLS_CERT`、`WEBCLOCK_TLS_KEY`，再執行確認。手動或非互動部署可自行明確設定 `WEBCLOCK_ALLOW_HTTP=1`，代表接受相同的明文傳輸風險。

完成後重新啟動服務；Docker 使用 `docker compose up -d --force-recreate` 重新載入環境。未啟用 TLS 時以 `http://主機:連接埠/admin` 登入，帳號與資料不變。曾用 HTTPS 的瀏覽器可能保有 Secure Cookie，切換前請登出，必要時清除該網站 Cookie 後重新登入／加入裝置。一般內網 HTTP 網址也無法提供瀏覽器要求安全連線的離線快取功能（localhost 等瀏覽器允許的例外除外）。

要恢復強制 HTTPS，配置有效憑證並將 `WEBCLOCK_ALLOW_HTTP=0`，再重新啟動／建立容器。上述 `transport` 命令在驗證有效 TLS 後，也會將 HTTP 選項關閉；驗證失敗則保留原設定。這個選擇屬於主機 `.env` 設定，不會隨網頁完整備份匯入而自動改變目的主機。

<a id="enable-managed"></a>
## 既有 self 安裝啟用 managed

不要重新執行全新安裝指令。先配置上述 HTTPS 或完成內網 HTTP 確認、停止所有寫入者，並依[完整備份流程](../guides/guide.md#主機端完整資料備份與還原)保存現有資料。舊資料會保留，但舊顯示裝置須用六碼重新加入。

**Bare metal：**在實際安裝目錄執行。下例採預設資料目錄；自訂路徑時改成服務實際使用的 state 位置。

```bash
sudo systemctl stop webclock
# 在此完成主機備份，再進行下一步。
service_user="$(systemctl show webclock --property=User --value)"
sudo -u "${service_user:-root}" ./venv/bin/python scripts/manage_auth.py --state-dir "$PWD/webclock_state" setup --username admin --enable-managed && sudo systemctl start webclock
```

**Docker：**在實際安裝目錄執行，維持現有掛載：

```bash
docker compose stop
# 在此完成主機端資料備份，再進行下一步。
docker compose run --rm --no-deps webclock python scripts/manage_auth.py --state-dir /app/webclock_state setup --username admin --enable-managed && docker compose up -d
```

初始化失敗時保持停止，先排除問題。首次登入 `/admin` 後，前往「裝置」建立群組、指派內容、產生六位加入碼；在每台時鐘首頁選「加入顯示群組」。完整操作見[群組設定與裝置加入](../guides/guide.md#群組設定與裝置加入)。

<a id="web-setup"></a>
## 用一次性設定碼建立第一位管理員

要在網頁輸入第一位管理員的帳密，可先在主機發出設定碼。已有管理員時不能再發碼或重新綁定；改用[密碼復原](#account-recovery)。先完成 HTTPS 或內網 HTTP 確認、停止寫入並建立完整備份，再選擇下列指令。

以下指令使用預設資料目錄。自訂安裝須將 `--state-dir` 換成服務實際使用的路徑；Docker 填容器內的掛載路徑。發碼失敗時保持服務停止，排除問題後再重試。

**Bare metal，於安裝目錄執行：**

```bash
sudo systemctl stop webclock
service_user="$(systemctl show webclock --property=User --value)"
sudo -u "${service_user:-root}" ./venv/bin/python scripts/manage_auth.py --state-dir "$PWD/webclock_state" setup-code && sudo systemctl start webclock
```

**Docker，使用現有掛載：**

```bash
docker compose stop
docker compose run --rm --no-deps webclock python scripts/manage_auth.py --state-dir /app/webclock_state setup-code && docker compose up -d
```

開啟 `https://主機名稱/setup`，貼上終端機顯示的設定碼，輸入帳號與至少 12 字元的密碼。成功後進入 managed，再到 `/login` 登入。設定碼預設 10 分鐘到期、只可使用一次；主機可加 `--expires-in 300` 改為 5 分鐘，有效範圍為 1 至 3600 秒。重新發碼會使前一個碼失效；碼不由匿名 API 發放，請勿貼到公開訊息或日誌。

<a id="mode-switch"></a>
## 雙向切換與主要使用者

已有管理員後，以 HTTPS（或主機已明確允許的內網 HTTP）開啟 `/mode`。managed 下須以 admin 登入；self 下日常管理仍免登入，但切換時必須輸入既有 admin 的帳密。

1. **managed → self：**明確選擇主要使用者，重新輸入 admin 密碼，確認所選空間可由可連線的網段使用者管理。主要使用者可為 member，角色不會改成 admin。
2. 按「預覽」，核對各帳號將啟用或休眠的狀態，以及設定、來源、私人網址數量、提醒、排程、事件、群組與裝置。預覽不顯示私人網址內容；目前沒有另行公開的跨帳號內容。
3. 確認後套用。伺服器在同一個寫入鎖內核對預覽、建立完整備份，再一次保存模式與主要使用者。預覽後資料改變、備份失敗或密碼錯誤時不切換，保留草稿後重新預覽。
4. **self → managed：**在 `/mode` 輸入既有 admin 帳密，預覽並套用；原帳號與角色恢復使用，self 期間對主要使用者的修改保留，不複製或合併其他帳號。

切換會清除登入 session、程式 token 與資料範圍快取的舊授權。仍合法的顯示裝置依原 owner／群組繼續核對，不把其他帳號的裝置改派至主要使用者。休眠帳號無法讀寫、輪詢私人來源或取得待響排程；恢復後不補響休眠期間錯過的鬧鐘。瀏覽器自行建立的 localStorage 提醒保持本機資料。

managed 的 `/mode` 也提供成員建立、停用／啟用及刪除；self 不提供帳號管理。主要使用者、原資料擁有者與復原管理員受保護，不能刪除或停用必要帳號。刪除其他帳號會封存其身分與資料並撤銷存取，不會立即清除私人檔案。此流程尚未提供公開註冊、郵件或忘記密碼連結。

<a id="owner-data"></a>
## 多帳號資料與完整還原

舊資料保持原位置；`auth.json` 的 `data_owner_id` 固定指出原資料擁有者，`owner_id` 指出 self 目前選定的主要使用者。新增帳號的設定、提醒、來源、排程、事件及程式請求收據存在 `webclock_state/owners/<owner_id>/`。群組／裝置授權與程式憑證仍在狀態根目錄，依 owner 檢查權限。更改模式只切換使用的空間；完整備份包含主要、休眠及封存帳號，網頁的 version 1 部分匯出／匯入僅處理目前空間的設定和提醒，不能換帳號或切模式。新匯出會附 `owner_id`，匯入不同帳號的檔案會被拒絕；舊版沒有歸屬欄位的 version 1 檔案仍只寫入目前授權空間。

預設模式備份位於狀態目錄**旁邊**的 `.webclock-mode-backups-<狀態目錄名稱>/<備份ID>/`。例如預設安裝是專案內的 `.webclock-mode-backups-webclock_state/`；目錄權限為 `700`，manifest 為 `600`。備份未加密，內含私人網址與帳號資料，請限制存取並定期另存至安全位置。

可用 `WEBCLOCK_MODE_BACKUP_DIR=/獨立/私人/備份目錄` 指定模式備份父目錄；服務帳號必須能建立與寫入該處；已存在的父目錄須為 `700`，伺服器不會改動其他既有目錄權限。它不能在任何資料根目錄內，也不能包含資料根目錄。Docker 必須把該路徑另行掛載至持久儲存，容器內的路徑與主機路徑要分別核對。Home Assistant App 可匯入 `.webclock` 完整備份並保留 managed 帳號，但仍不提供模式切換；HA 冷備份用於整個 App 復原。勿直接改 App 的模式或把主機目錄備份放進資料目錄造成遞迴。

需要回復模式切換前的完整狀態時，在安裝目錄先停止全部寫入者，再還原選定副本。以下為預設 bare metal 路徑，`<備份ID>` 換成實際目錄名稱，還原前副本必須是全新路徑：

```bash
sudo systemctl stop webclock
mkdir -p -m 700 "$HOME/private-webclock-backups"
sudo ./venv/bin/python scripts/backup_clock.py verify "$PWD/.webclock-mode-backups-webclock_state/<備份ID>"
sudo ./venv/bin/python scripts/backup_clock.py restore "$PWD/.webclock-mode-backups-webclock_state/<備份ID>" --project "$PWD" --stopped --yes --rollback-dir "$HOME/private-webclock-backups/before-mode-restore-001"
```

自訂資料位置須另外傳 `--state-dir`／`--notes-file`，保持原包含關係；Docker 先停容器，使用已安裝相依套件的主機 Python 與主機掛載路徑執行。完整步驟見[主機備份與還原](../guides/guide.md#主機端完整資料備份與還原)。

還原保留帳密、角色與內容，但會使歷史登入 session、程式 token、裝置憑證、加入碼及首次設定碼失效；顯示裝置須重新授權。已有帳號的 self 仍是受保護安裝，不能被沒有帳號的舊備份覆蓋；不支援多帳號的舊程式也不能啟動這份資料。成功後檢查路徑、擁有者與資料，再手動啟動服務。失敗或中斷時保持停止，保留還原前副本與 `.webclock-restore-*`；實際斷電恢復仍須在部署環境驗收。

<a id="account-recovery"></a>
## 管理員密碼復原

停止全部寫入者後，用服務帳號執行主機復原；預設復原原管理員，可加 `--username 帳號` 選擇另一位現有 admin。以下使用預設資料目錄，自訂安裝須將 `--state-dir` 換成服務實際使用的路徑；復原失敗時保持停止，排除問題後再重試：

```bash
sudo systemctl stop webclock
service_user="$(systemctl show webclock --property=User --value)"
sudo -u "${service_user:-root}" ./venv/bin/python scripts/manage_auth.py --state-dir "$PWD/webclock_state" reset-password && sudo systemctl start webclock
```

Docker 改以停止後的 `docker compose run --rm --no-deps webclock python scripts/manage_auth.py --state-dir /app/webclock_state reset-password && docker compose up -d` 執行；自訂掛載須換成實際容器內路徑。密碼互動輸入，不放在命令列。復原保留帳號身分、目前模式與主要使用者，並使舊登入 session 失效；獨立程式憑證須在「程式存取」另外撤銷，不會重建替代帳號。
