# Docker 與 Home Assistant 一鍵更新實作計劃

目標：既有安裝可更新至正式 Release，保留設定、帳號、裝置及程式憑證，並提供進度與失敗復原資訊。

原始設計日期：2026-10-14；基準提交：`6f20cbd836fc7c8089c32b84f678ea4f7e84e518`（v1.1.0）。實作與驗證進度見[驗證紀錄](../acceptance/docker-ha-update-acceptance.md)。本文保留當時的設計範圍，並非目前發行狀態。

## 1. 實作範圍

P0～P5 涵蓋 Docker 更新交易、Home Assistant App／HACS 更新入口與驗證。Docker 使用容器外的受限程序；App 由 Supervisor 更新，整合與卡片由 HACS 更新。WebClock 容器不掛載 Docker socket，App 不自行覆寫 HA 整合。

本機、CI、公開發行與實機結果分別記錄；缺少 HA OS 或 ARM 實測時標示 `not_ready`。P6 跨元件協調屬獨立進階功能。

## 2. 「一鍵」的交付定義

更新前先呈現目前版本、目標版本、更新說明、短暫中斷與備份方式；使用者啟動後，系統接續完成預檢、備份、更新、重啟與確認。一般更新不要求手改 `.env`、自行尋找 tag 或重新配對裝置。

| 安裝方式 | 必做交付 | 執行更新的位置 | 本階段邊界 |
| --- | --- | --- | --- |
| 官方 Docker Compose，Linux＋systemd | 一次啟用後，managed 管理員可由 WebClock 更新頁觸發；self 可用宿主機單一命令 | 宿主機獨立 worker | 首版正式支援 amd64／arm64、單一官方 Compose 安裝 |
| Docker Desktop、NAS、Portainer、客製 Compose | 顯示安裝類型、限制與既有平台操作入口；符合預檢者可用同一交易核心的宿主機 CLI | 宿主機／原平台 | 不假稱具備 systemd 背景服務；未驗收環境標示不支援自動更新 |
| HA OS 商店 WebClock App | 從 HA 原生更新頁備份後更新；WebClock 頁面清楚導向對應入口 | Supervisor | 更新的是 Server App，不連帶更新 HA OS／Core |
| HACS WebClock Integration | 使用 HACS 提供的更新項目；明示重新啟動 HA 後才生效 | HACS／HA | 三張卡片隨 Integration 更新；App 為另一更新項目 |
| HA Container 或其他無 Supervisor 環境 | Server 走 Docker／既有安裝方式；Integration 走 HACS | 各安裝平台 | 不顯示不存在的 App 商店更新能力 |
| HA Local App | 顯示本機建置流程及轉用商店安裝的說明 | HA 本機建置 | 不自動轉成商店 App，不搬動／刪除 `/data` |

**P0～P5 不承諾一顆按鈕同時更新 App、Integration 並重啟 HA。** HA 的目標是保留平台已有的更新按鈕，補足 WebClock 的入口、狀態、發布與實際升級驗收；跨元件協調另見 P6。

## 3. 已有能力與修改起點

下表為查核基準；路徑相對於 repository 根目錄。

| 檔案／位置 | 現況 | 修改原則 |
| --- | --- | --- |
| `scripts/release_versions.py:40` | 解析官方 GitHub Releases，檢查資產完整性，支援 stable／beta 與 SemVer 比較 | 重用版本選擇；Docker 另驗證所選版本映像確實可取得 |
| `scripts/updater_service.py:32` | 裸機獨立 worker、持久狀態、排程、更新鎖與失敗暫停 | 重用可共用的行為；其 Git／systemd 更新動作不適用 Docker |
| `scripts/enable_updates.sh:7` | 啟用 Linux 裸機服務，依賴 `webclock.service` 及 Git 安裝 | 不直接拿來註冊 Docker，不改壞既有裸機服務 |
| `webclock/api/updates.py:33` | Docker 或 HA 直接判為平台管理；GET 回 unsupported，POST 禁止 | 改成明確能力判斷，保留 managed admin、same-origin 與 CSRF 防護 |
| `static/updates.js`、`templates/updates.html`、`webclock/translations/updates.py` | 已有版本、管道、進度、斷線重連與結果顯示 | 延伸既有頁面，補 Docker 與 HA 文案；保留繁中／英文／日文 |
| `docker-compose.yml:3` | `ghcr.io/kcayut/webclock:${WEBCLOCK_VERSION:-1.1.0}`，同時保留開發用 build | 正式更新固定官方映像；不可意外觸發本機 build |
| `docker-compose.yml:12` | state、模式切換備份、舊 notes 與 TLS 掛載 | 重建須保留掛載與網路設定；不得只備份部分 JSON |
| `install.sh`、`doc/installation.md:325` | 安裝器拒絕覆蓋既有安裝；Docker 更新仍需手改版本再 pull／up | 新安裝與既有安裝啟用更新器分開；不得以重跑 installer 取代升級 |
| `homeassistant/addon/config.yaml` | 公開 App 映像、Ingress 8099、display 8100、`backup: cold`；未啟用 Supervisor API 權限 | 原生更新優先，保留管理與顯示隔離 |
| `custom_components/webclock/`、`hacs.json` | HACS Integration 與卡片包 | 不新增另一套卡片下載器或搶接 HACS 的版本管理 |
| `tools/build_release.py:38`、`.github/workflows/home-assistant.yml` | `VERSION` 統一元件版號；已有套件、容器及公開發行流程 | 延伸既有 CI，補「舊版升新版」測試，不只測全新安裝 |
| `.github/workflows/release-smoke.yml`、`doc/ha-release.md` | 公開安裝與發布證據的既有位置 | 本機、CI、公開資產、部署及實機驗收各自記錄 |

## 4. 必須維持的資料與權限規則

1. **更新不等於還原或搬家。** 正常更新保留模式、帳號、群組、行事曆、提醒、裝置、程式 token 與既有有效授權；不得順便啟用 managed 或要求全部重新配對。
2. **回退不得復活已撤銷授權。** 既有 `scripts/update_clock.py` 已保留最新 managed／control 狀態；`scripts/backup_clock.py` 與 portable restore 的歷史還原會失效化部分憑證，不可直接作為透明更新回退。
3. **先停止所有寫入者，才建立一致備份。** 確認沒有其他容器／主機共用同一 state；備份失敗時不得開始新版。單機冷備份會有短暫停機，不承諾零停機。
4. **Flask 只提交固定動作。** 請求不得包含 shell、任意 URL、Compose 路徑、主機路徑、Docker context、容器名稱或任意 registry；worker 從宿主機受信任設定取得這些值。
5. **WebClock 不取得 Docker 管理權。** 不掛載 `/var/run/docker.sock`，不給容器 privileged 或 Docker 群組權限。宿主機 worker 即使可操作 Docker，也必須只暴露指定安裝的更新能力。
6. **self 的匿名管理頁不能授權主機更新。** self 使用宿主機 CLI；managed 的網頁操作需管理員與現有 CSRF／來源驗證。HA 管理操作留在 HA 原生權限範圍，不能僅憑任意 Ingress header 判定為管理員。
7. **祕密不進狀態 API。** `.env`、私有 iCal、token、TLS 私鑰、完整命令輸出及備份內容不得出現在前端、公開日誌或 CI artifacts；備份權限受限，清楚區分完整性雜湊與加密。
8. **未知不算成功。** 逾時、磁碟寫入失敗、重開機、無法判明新舊資料相容性，均保留可追查紀錄，回報 `interrupted`／`manual_recovery`／`not_ready` 等明確結果。

## 5. P0：固定支援範圍與介面契約

交付：短版設計紀錄與測試清單，完成後直接進入 P1。

- 確認執行時 HEAD、未提交修改、既有 updater 測試與 CI 指令；程式探索優先 codebase-memory MCP。
- 記錄 Docker Compose 版本下限、OS／CPU、Docker context、project name、service、實際 volumes 與資料路徑。首版以官方 Compose 為支援邊界；客製服務不能只靠名稱猜測後接管。
- 使用目前官方文件核對 Compose／HA／HACS 行為；依 AGENTS.md 以 Context7 CLI 查詢。不要將本文日期的 API 當作永遠不變。
- 狀態 API 以最少新增欄位表達 `installation_type`、`update_provider`、`supported`、`writable`、`reason`、`management_url`。沿用既有版本與 phase 欄位；不存在的資訊回 `null` 或 unknown，不能猜版本。
- 將「能力存在」「目前帳號可以操作」「目前有可安裝版本」分開判斷。HA 原生入口不等於 WebClock 自身能 POST install。
- 第一版 Docker 預設 stable。自動更新另由使用者明確啟用，既有設定須保留；不要因啟用 helper 就默默開啟。HA 自動更新仍由 HA 原生設定控制，不設第二套排程。
- 同一份 release 的 Server／App／Integration／cards 維持共同版本號，但已安裝元件可暫時不同版本。需定義至少前一正式版的相容組合；不相容組合阻擋自動升級並提供順序，不以「全部必須同版」代替遷移設計。

完成條件：明確定義支援環境、授權方式、進度儲存、成功判定與停止回退的條件。

## 6. P1：Docker 宿主機更新交易

建議新增 `scripts/docker_update.py`；檔名可依專案結構調整。先完成可測試的宿主機 CLI，再接網頁。這是新功能規格，本文提及的新命令／檔案目前尚不存在。

### 6.1 交易順序

1. **取得安裝鎖及固定目標。** 同一安裝只允許一個 CLI／網頁／排程交易。紀錄 operation ID、來源版本、目前容器 image ID／digest、Compose 設定指紋、目標版本與目標 digest；重複請求返回原交易或 busy。
2. **預檢。** 驗證安裝身分、健康狀態、權限、磁碟空間、Compose 能力、資料掛載、TLS 健康檢查設定與版本相容性。未知客製設定回明確原因，原服務繼續運作。
3. **先下載再停機。** 從官方 Release 選定版本，確認同版本 GHCR 映像及正確 CPU 架構，拉取並固定 digest。拉取失敗不改 active 設定、不停止舊容器。`latest`／`stable` 等可變標籤不能作為交易與回退唯一依據。
4. **寫入可復原 journal。** journal 與備份放容器外、受限權限目錄，包含足以判斷已執行步驟的資訊；關鍵狀態無法落盤時，禁止進入下一個破壞性步驟。
5. **停止指定服務並冷備份。** 不使用整個 project 的 `down`。確認服務已停止、資料沒有第二寫入者，再備份 state、安裝設定、模式備份與相關持久資料。TLS 通常原掛載保留；完整復原所需的外部檔案須記錄與驗證，不暗示備份已涵蓋未複製的私鑰。
6. **原子切換設定並重建指定服務。** 保留 `.env` 的其他鍵、註解及使用者設定，只更新必要的版本與受控 image reference；不得 `source .env`。使用明確 project／service、固定映像及 `--no-build`；不使用 `--remove-orphans`、`down -v` 或 volume prune。若以 override 固定 digest，日後一般 Compose 啟動也必須讀取同一權威設定，避免又退回舊版本。
7. **確認實際就緒。** 核對運行容器的 image ID／digest、HTTP(S) `/api/health` 的版本與模式；服務不是 crash loop，state 路徑未變，代表性資料可讀。Compose `--wait` 可作輔助，不能取代應用層檢查；沒有 HEALTHCHECK 時 running 不等於健康。
8. **完成與保留復原點。** 成功才更新已安裝版本及結果；清理受限於本更新器建立的暫存物。保留至少上一個已驗證映像與備份，不主動全域 prune，也不改其他 Compose 服務。

Docker 官方文件確認 `pull` 用於取得映像，`up` 提供 `--no-build`、`--no-deps`、`--wait` 與 `--wait-timeout`。具體組合與最低版本在 P0 鎖定，不能假定所有 NAS 的 Compose 都支援。參見 [Compose pull](https://docs.docker.com/reference/cli/docker/compose/pull/) 與 [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)。

### 6.2 失敗與回退

| 失敗時點 | 必須行為 |
| --- | --- |
| release／拉取／預檢失敗 | 不改目前版本與服務；回報可重試原因 |
| 停機後備份失敗，但資料未改 | 保留錯誤證據，重新啟動原映像並確認健康；原服務也無法恢復才進入人工處理 |
| 新容器建立或健康檢查失敗 | 停止失敗容器，確認資料相容性後使用原 image ID／digest 與設定回退，重新健康檢查 |
| 新版已改寫資料且舊版不相容 | 不讓舊映像盲讀新資料；保持停止，保留新資料與冷備份，回報 manual_recovery |
| 任一關鍵步驟被中斷或 journal 不完整 | 啟動時先核對容器與資料事實，禁止直接接著覆寫或宣稱回退成功 |
| 回退成功 | 明確顯示原版本與 rolled_back，暫停自動更新；不當成升級成功 |
| 回退失敗 | 顯示 manual_recovery，提供受限日誌／備份位置及宿主機救援步驟 |

自動回退優先只回退映像並保留最新資料，前提是舊版相容。需要還原資料時，必須另有經測試的 migration／rollback 策略，涵蓋更新後新寫入及已撤銷憑證；不能無條件覆蓋整份 state。若無法證明安全，保留兩份資料供人工復原。

版本相容性應以可機器檢查的規則或 release metadata 表達，含缺少 metadata 時的保守行為；不要每次靠 agent 閱讀發行說明推測 schema。先沿用既有 schema 與遷移檢查，只增加實際需要的欄位。

## 7. P2：啟用服務、更新頁與背景排程

建議新增 Docker 專用的啟用入口，例如 `scripts/enable_docker_updates.sh`；共用狀態、排程與版本解析的部分可從現有 worker 抽出最小函式，不建通用插件框架。

- **新安裝：**官方 Docker installer 可選擇註冊宿主機 worker，完成後顯示更新入口與能力；不支援 systemd 時清楚降為 CLI／平台原生操作。
- **既有 v1.1.0：**交付一個從官方 Release 取得、驗證後執行的啟用流程；先辨識既有 Compose／掛載，再接管指定服務。舊映像沒有新 API 時，首次升級由宿主機 CLI 完成，之後才啟用網頁控制。不能要求先重裝或把整個安裝目錄換掉。
- **可信任執行檔：**可操作 Docker 的程序與其配置不得由容器內 WebClock 寫入。不要直接把宿主機 root service 指向可被應用程式改寫的腳本或任意使用者可改的 Compose。啟用時建立受保護配置、限制受控欄位並檢查擁有者／symlink；客製變更需重新驗證。
- **窄介面：**沿用受限 Unix socket 請求模型，只提供 status／check／install／configure。掛載專用 socket 目錄並控制 UID／GID 與存取權限；不把備份與宿主機設定掛給 WebClock。驗證 worker 重啟後 socket 重建仍可連線。
- **選擇正確後端：**HA 判斷優先於一般 Docker；Docker 只有在已驗證的 helper 可用時才有本地更新能力。helper 不可用時回明確原因，不誤導為已是最新版，也不回退呼叫裸機 worker。
- **管理頁：**重用既有頁面與三語翻譯，顯示安裝方式、版本、針對該平台的動作及恢復指引。Docker 重啟期間只重連／查詢，不自動重送 install；返回後驗證同一 operation 的結果。
- **stable／beta：**Docker 重用現有語義：stable 排除 prerelease，beta 可含正式版與測試版；切回 stable 不自動降版。HA 沒有對應發行管道時不顯示虛假的切換功能。
- **排程：**沿用目前每日檢查與失敗退避概念；手動／自動共用交易鎖，失敗暫停自動升級。禁止透過重新啟動清除暫停或重跑已失敗交易。
- **worker 自身升級：**明確定義從已驗證 Release 安裝新版 worker 的受保護路徑與載入時點；正在執行的交易先落盤結束，保留上一份 worker。測試 journal 向後相容與重啟，不把主程式更新成功等同 helper 已更新。

交付一個有 `--help` 的單一宿主機操作入口，以及清楚的啟用、更新、查狀態、停用排程及人工復原說明；文件中的命令必須先在測試環境跑過。

## 8. P3：Home Assistant App 與 HACS 更新體驗

### 8.1 商店 App：由 HA 完成 Server 更新

- WebClock 更新頁顯示「此 Server 由 Home Assistant 管理」，提供前往 HA 更新／App 頁面的入口，保留目前版本與清楚操作說明。不能把跳頁按鈕標成已開始安裝。
- 入口使用受支援的 HA deep link 或可驗證的安裝資訊；實際 App slug 可能帶 repository 前綴，不能寫死 `webclock` 或猜 `local-webclock`。無法得知 slug 時導向通用 HA 更新頁。
- 原生流程為：檢查可用更新 → 選擇更新前備份 → 更新 App → 重新開啟 Ingress → 核對運行版本、資料與裝置。保留 `backup: cold`、`/data`、App options、LAN port 與 Ingress 設定。
- 測試 HA 確實建立包含 WebClock App 的備份，且備份失敗時不繼續更新。App 備份不等於 HA Core／HACS 配置備份，不可把單一 App 備份稱為全套 HA 復原點。
- 當 App 停止時 WebClock 頁面無法提供進度；此期間以 HA 原生更新狀態為準，重新連線後只回報實際版本。不要把 HA 工作進度寄存在即將被替換的 App 程序裡。
- 不預設 Supervisor 可自動降版或完成應用資料回退；失敗時保留 HA 日誌與備份，提供原生還原路徑。歷史備份還原的憑證及資料回溯風險要與正常更新區分。
- P3 不需為 App 新增 `hassio_api`／高權限角色，也不關閉保護模式；保留現有 HA 原生更新授權。

官方文件確認 `/data` 為持久儲存、`backup: cold` 會先停止 App，且 Supervisor API 權限需明確設定。參見 [HA App configuration](https://developers.home-assistant.io/docs/apps/configuration/)。

### 8.2 HACS：Integration 與卡片一起更新

- 使用 HACS 自帶的 update entity／更新入口，避免建立重複的 WebClock Integration 更新實體。文件分別寫清「WebClock Server App」與「WebClock Integration＋卡片」。
- HACS 更新完成後若待重啟，顯示需要重新啟動 HA；未重啟前不能宣稱執行中 Integration 已換版。HA 重啟會影響其他整合，不能由 WebClock 的一般檢查動作自動觸發。
- 驗證 `manifest.json`、`const.py`、卡片資源版本與 URL 一致，HA 重新啟動後資源註冊不重複、瀏覽器快取更新、三張卡片都能讀到新資料。
- 保留 config entry、選定群組、Server URL 與原憑證；App 更新不得改寫 Integration 的連線資料。實際同機 URL 仍以 App 日誌的 `Home Assistant integration URL:` 為準。
- 驗證「新 Integration＋前一版 Server」與「前一版 Integration＋新 Server」。有不相容變更時先定義安全順序；不得將升級期間的版本差異一律判錯。
- 未安裝 HACS 或 Integration 為手動複製時，清楚顯示相應方式，不假裝 HACS 可以接管；不得直接覆寫使用者的 custom_components。

HACS 官方提供 tracked repositories 的 update entities 及 `update.install`；下載後需重新啟動的項目另有 pending restart 狀態。參見 [HACS update entities](https://www.hacs.xyz/docs/use/entities/update/) 與 [HACS dashboard](https://www.hacs.xyz/docs/use/repositories/dashboard/)。

## 9. P4：測試與失敗演練

### 9.1 本機自動化測試

沿用 `tests/test_updates_api.py`、`tests/test_updates_ui.js`、`tests/test_updater_service.py`、更新安全／TLS 測試與 `homeassistant/tests/`。Docker 交易新增專注的單元測試與可重現容器演練，不以 mock 代替真實重建。

| 類別 | 必測案例 | 通過標準 |
| --- | --- | --- |
| 發行選擇 | 同版、stable／beta、正式版追上 beta、缺映像、錯架構、GHCR／GitHub 斷線或限流 | 不錯選／降版，未準備好不停止舊服務 |
| 設定保存 | ports、TZ、mode、notes、state、模式備份、TLS 與 `.env` 其他值 | 只改核准欄位；私有內容不進日誌 |
| 安裝接管 | v1.1.0 首次啟用、已啟用再執行、未知 Compose、別的 project、symlink／檔案被調換 | 不重裝、不接管錯服務、不執行不受信任配置 |
| 權限 | self 匿名、managed 非 admin、缺 CSRF、跨來源、display 8100、未配置 helper | 無法觸發更新或改排程 |
| 請求競態 | 連點、多分頁、CLI 與排程同時執行、送出後斷線、確認前 release 改變 | 單一交易；新目標需重新確認；不重複安裝 |
| 狀態可靠性 | 磁碟滿、唯讀、原子寫入失敗、worker／主機中斷、socket 重建 | 不假成功；重啟不清失敗／暫停，仍有復原線索 |
| 停機與備份 | 停止失敗、備份中斷、外部檔案缺失、第二寫入者 | 未有一致備份不升級，必要時回啟舊服務 |
| 新版失敗 | 啟動失敗、health 逾時、錯版本、crash loop、schema 不相容 | 安全回退或人工復原，結果與事實相符 |
| 授權保存 | 成功更新後舊有效 session／裝置／control 憑證仍有效；回退前剛撤銷的憑證 | 正常更新不撤銷；回退不復活已撤銷權限 |
| TLS | 正常 CA、私人 CA、錯名稱、過期憑證、HTTP redirect | 沿用驗證設定，不加 insecure／關閉驗證 |
| HA 邊界 | App 與 Integration 分開版本、重啟前後、Ingress 斷線、無 HACS、Local App | 顯示真實能力與狀態，8100 不開放管理 |

### 9.2 真實升級矩陣

- Docker：前一公開版 → 候選新版，self／managed 各一次；重啟宿主機後再驗證持久化與 worker。至少涵蓋 amd64、arm64 映像；QEMU 結果與實體 ARM 結果分列。
- Docker 故障演練：一個故意健康檢查失敗的候選映像，驗證原映像、設定與授權回退；再測資料不相容時確實停止並保留兩份資料。
- HA OS：在可還原的測試機由商店來源安裝前版，再讓商店提供候選新版，實際備份、更新、重開 Ingress、核對 `/data` 與已配對裝置；記錄 HA OS／Supervisor／Core 版本與 App slug。
- HACS：以真實 HACS 下載候選版本、確認 pending restart、重啟 HA、檢查原 config entry、三張卡片與快取；原生 App 備份與 HA 配置備份分別驗證。
- HA 失敗恢復：在可丟棄測試環境演練備份還原，記錄實際恢復範圍與憑證處理。未演練前只提供步驟，不標示已驗證回復。
- 舊裝置：至少一般瀏覽器回連與已有顯示裝置；iPad mini 1／iOS 9、通知／音訊及長期穩定性另列，沒有實機就不宣稱通過。

## 10. P5：發行、文件與完成條件

- 更新 `doc/installation.md`、`doc/home-assistant.md`、`doc/ha-release.md` 及相關多語 README，讓使用者一眼區分 Docker、HA App、HACS 三種入口，提供可直接複製的啟用與救援命令。
- 補新安裝與既有安裝的差異；移除需要手動編輯版本才可正常更新的主要流程，但保留進階人工復原說明。
- 若新增根目錄入口檔，更新 `tools/build_release.py` 的打包白名單；檢查正式 Release 真的包含 helper／啟用入口與完整性清單。注意目前打包讀取 committed blobs，測試 artifact 要記錄對應提交。
- 依變更選定新版本並統一 `VERSION`、App、Integration、cards 與預設 Docker tag；不可覆寫已發布的同版 tag／映像。
- 延伸既有 CI：單元／JS／HA integration → amd64／arm64 映像 → 前版升新版 → 故障回退 → 發行資產與匿名 pull。公開 Release 及商店可見版本應在映像可匿名拉取後才對使用者宣稱可更新；失敗時不露出半套版本。
- 正式發布需當時授權；發布後記錄 Release URL、commit、image digest、CI run 與公開 smoke 結果。工作目錄測試通過不等於使用者已能下載。

| 工作包 | 可平行內容 | 依賴 | 必要產出 |
| --- | --- | --- | --- |
| P0 契約與範圍 | 無 | 無 | 能力欄位、支援矩陣、版本相容規則 |
| P1 Docker 交易 | 可與 P3 平行 | P0 | CLI、備份／回退、故障測試 |
| P2 啟用／UI／排程 | 可先做 UI fixture | P0、P1 | 宿主機服務、更新頁與 v1.1.0 啟用路徑 |
| P3 HA／HACS | 可與 P1 平行；共用 UI 由同一 agent 整合 | P0 | 原生入口、版本／重啟文案、套件相容驗證 |
| P4 整合驗收 | 各平台可平行 | P1～P3 | 容器演練、HA OS／HACS 實機證據或 not_ready |
| P5 文件／發行 | 文件可先寫 | P4 | 驗收紀錄、正式資產及分層狀態 |

必做完成條件：

- [ ] Docker 使用者不必手改版本，managed 可由網頁啟動，self 有宿主機單一命令。
- [ ] Docker 的關閉／重建不會中止更新程序；故障與中斷後有可信狀態及可操作復原路徑。
- [ ] 更新成功保留資料與有效授權；回退不復活已撤銷憑證。
- [ ] HA App 使用原生更新與備份，HACS Integration／cards 更新及重啟邊界清楚。
- [ ] 裸機既有更新不退步，三語 UI、管理／顯示隔離與 TLS 驗證維持。
- [ ] 公開資產與升級演練各有證據；未做的部署／實機檢查明確標成 not_ready。

## 11. P6：進階的「更新全部 WebClock 元件」

僅在後續明確要求同一次操作更新 App＋Integration 時執行。P0～P5 先保持可獨立發布。

建議由 HA 側協調，使用 HA 已有的 Supervisor 與 HACS update entities／受支援服務；不要在即將停止的 WebClock App 內串接整個交易。

實作前必須證明：

1. 能可靠辨識實際 App slug、對應 HACS repository／entity、已安裝與候選版本，以及使用者是否有管理權限；不得僅以顯示名稱匹配後更新。
2. 能為 App `/data` 與 HA／HACS 配置建立適當復原點；一份 App partial backup 不涵蓋全部。
3. 能依相容矩陣選擇更新順序，第一步失敗便停止；未達必要能力或缺更新項目時，退回個別原生入口，不顯示「全部更新成功」。
4. 能持久化跨 HA restart 的 operation 狀態。若協調器位於 WebClock Integration，它也會被 HACS 更新替換；必須處理自身重載與續接，不只在記憶體等待。
5. 預覽清楚列出會重啟 HA 及影響其他整合，由使用者明確確認；只有一般版本檢查不構成 HA 重啟授權。
6. 能在重新啟動後核對兩個運行版本與卡片資源，未完成則顯示 partial／awaiting_restart；無須建立通用跨平台更新平台。

2026-10-14 查核的 Supervisor 文件已將舊 `/addons/<app>/update` 標為 deprecated，商店更新介面為 `/store/addons/<app>/update`，提供 `backup`、`background`，背景工作需查 job；文件未在此介面列任意 `version` 參數，不能照搬 Core API。這是設計依據，不是要求 P3 直接新增 Supervisor 呼叫。參見 [Supervisor endpoints](https://developers.home-assistant.io/docs/api/supervisor/endpoints/)。HACS 的受支援 `update.install` 也不代表它會替整個 WebClock 組合執行備份、重啟與回退。

## 12. 驗證紀錄要求

各階段紀錄須包含：

1. **已實作：**各平台使用者現在能做的事、主要修改檔案。
2. **本機驗證：**實際執行命令、通過／失敗與資料保存證據。
3. **CI／公開發行：**run、Release、digest；未發布時標示未發布。
4. **實機／部署：**Docker 主機、HA OS、HACS、ARM 的環境版本與結果；未提供環境者標 not_ready。
5. **剩餘限制：**未支援平台、失敗恢復邊界與 P6 是否另行執行。

本設計紀錄不包含正式部署、發布或實機驗收結果。
