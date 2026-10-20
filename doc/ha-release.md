# WebClock 安裝交付與 Home Assistant 發行

一般使用者請看[Server 安裝](installation.md#home-assistant)與[整合／卡片安裝](home-assistant.md#安裝整合)。本頁供維護者發行與記錄驗收使用。

## 目前狀態

- **[v1.2.0 已公開發布](https://github.com/kcayut/webclock/releases/tag/v1.2.0)，並設為最新正式版**。本版提供 Docker 安全更新、離線救援、worker 維護與 HA 版本對齊，並補修備份、安裝及回退流程。
- Server、Docker、HA App、HACS 整合與卡片統一版號；HA App 仍標示 `experimental`。
- HA OS 商店／HACS 實際更新、完整備份搬家、主機斷電／重開機、實體 ARM、舊 iPad、音訊及長時間運行仍需實機驗收；詳見[更新驗證紀錄](acceptance/docker-ha-update-acceptance.md)。

<a id="release-1-2-0"></a>
## 1.2.0 發行驗證（2026-10-20）

- 發行提交：`c217a40edc25fa0838d243ddc782a6078f396c16`；GitHub 與 Gitea 的 `v1.2.0` 已獨立回讀，指向同一提交。
- [安裝與整合 CI](https://github.com/kcayut/webclock/actions/runs/39296056245) 全部通過：Server Python 538 項（4 項略過、其餘通過）、17 份 JavaScript、真實 HA 2026.9.4／Python 3.14 整合 13 項，以及 Docker／HA App 的 `linux/amd64`、`linux/arm64` 建置與啟動。
- 同一 CI 通過 self／managed HTTPS Docker 更新、設定切換中斷復原、故障映像回退、帳號資料保持、重啟策略恢復，以及真實 systemd worker 啟用、偏好保留、私有 socket 重建與 worker refresh。候選映像在 runner 本地產生，此結果不代替公開下載升級驗證。
- [Linux 更新與復原演練](https://github.com/kcayut/webclock/actions/runs/39296056247) 全部通過：真實 systemd 更新、備份／還原、managed HTTPS、失敗回復與舊授權失效。
- [標籤發行流程](https://github.com/kcayut/webclock/actions/runs/39297375020) 全部通過，發布 `ghcr.io/kcayut/webclock:1.2.0` 與 `ghcr.io/kcayut/webclock-addon:1.2.0`；空白 Docker 登入設定下的匿名 manifest 檢查通過，兩者皆含 `linux/amd64`、`linux/arm64`。
- 2026-10-20 獨立匿名回讀 GitHub `releases/latest`，確認 `v1.2.0`、非 draft、非 prerelease，且五個資產完整。下載全部資產後，四個檔案的 SHA256 均符合 `SHA256SUMS`，Server 壓縮檔內 `VERSION=1.2.0`、ZIP 完整性與兩個 shell 入口語法均通過。
- [公開新安裝驗證](https://github.com/kcayut/webclock/actions/runs/39422650558) 的 Linux／Docker 兩項皆通過：以公開安裝器完成 bootstrap，核對版本與 self 模式，經管理 API 儲存設定，再確認服務重啟後仍保留；Linux 另確認 stable 更新來源。
- [公開跨版本升級驗證](https://github.com/kcayut/webclock/actions/runs/39422693758) 通過：在乾淨 Linux amd64 runner 安裝公開 v1.1.0 Docker，再下載並校驗 v1.2.0 的 `portable_docker_update.sh`。更新完成後原資料雜湊不變，保存的工具可離線診斷，交易記錄為 `source_version=1.1.0`、`target_version=1.2.0`、`step=completed`；管理設定寫入及重啟保存也通過。此項涵蓋 self 模式，未涵蓋 managed 的既有 session／裝置憑證或公開資產 worker refresh。

發布流程記錄的多架構映像 manifest digest：

| 映像 | Digest |
| --- | --- |
| `ghcr.io/kcayut/webclock:1.2.0` | `sha256:ed2b848129c491c6801629125cee25fc7ff302abc14869433d97e2dfb18753a8` |
| `ghcr.io/kcayut/webclock-addon:1.2.0` | `sha256:61de72d77db3d538839a96b8aacf8440c09473fa3e80254c2caf89c88f4594b8` |

公開資產的 SHA256：

| 檔案 | SHA256 |
| --- | --- |
| `install.sh` | `4f1d69ddcefb12eb6a8fd17248ce2e063dd694113e244ce5efbb16a3f1fd7414` |
| `portable_docker_update.sh` | `6a35278ea51e895c8faeffc941e8e295b28b084ae07c600115b6b60de8a11cbb` |
| `webclock-1.2.0.tar.gz` | `d568898f0952106bb447ec29ecea97a5b986b3047a767a4b0cc11ac053ae1d63` |
| `webclock-clock-1.2.0.zip` | `400f26668f67e8c1a443b3e758e6ae9f428503d1e1ac7d3b6980bb2bc7121afe` |

## 1.1.0 發行驗證（2026-10-12）

- 發行提交：`020f837fdbc50a987b2da882b06424f881d3d489`；GitHub 與 Gitea 的 `v1.1.0` 使用同一提交。
- [安裝與整合 CI](https://github.com/kcayut/webclock/actions/runs/38251398111) 全部通過：418 項 Server Python 測試、JavaScript 回歸、真實 HA 2026.9.4／Python 3.14 整合與卡片，以及普通 Docker／HA App 的 `linux/amd64`、`linux/arm64` 建置與啟動。
- 同一 CI 在一次性 Linux runner 完成 self 與 managed HTTPS 新安裝、實際管理設定儲存、服務重啟與設定／授權資料保留；HA 容器驗證 Ingress、顯示入口隔離及重啟。
- [Linux 更新與復原演練](https://github.com/kcayut/webclock/actions/runs/38251397992) 全部通過，包含真實 systemd 更新、備份、還原及失敗回復。
- [標籤發行流程](https://github.com/kcayut/webclock/actions/runs/38251988151) 全部通過，發布 `ghcr.io/kcayut/webclock:1.1.0` 與 `ghcr.io/kcayut/webclock-addon:1.1.0`；以空白 Docker 登入設定確認匿名可取得兩個映像，且都有 `linux/amd64`、`linux/arm64`。
- [正式下載安裝演練](https://github.com/kcayut/webclock/actions/runs/38252762611) 兩項皆通過：從公開 Release 下載安裝器、核對 SHA256，在乾淨 runner 完成 Linux／Docker bootstrap，核對產品版本與 self 模式，經管理 API 儲存設定並確認重啟後保留；Linux 另核對 stable 更新來源。這是公開資產的完整安裝結果，與前述來源 checkout 測試分開記錄。

## 完整備份本機驗證（2026-10-09）

- Python **397 項全部通過**，最終完整執行耗時 **38.830 秒**；JavaScript **15 組回歸全部通過**。
- 實際 Chrome 完成：下載加密備份 → 模擬可信 HA Ingress 的空白目標 → 錯誤密碼保留輸入 → 正確密碼預覽 → 確認還原 → 原帳號登入 → 私人提醒保留 → 重啟後資料仍在。已檢查桌面 1280 px 與手機 390 px 畫面。
- 上述為本機伺服器、模擬可信 Ingress 與瀏覽器驗證，**不是真實 HA OS、ARM 或遠端 CI 驗收**，不改變原有尚未發行與實機待驗收狀態。

## 本機驗證（2026-10-08）

- Server **375 項測試通過，exit 0**，包含安裝包、Ingress、HTTPS 更新與失敗還原；JavaScript **14 組回歸通過**。
- 使用暫存資料啟動真正的 `8099`／`8100` 入口，模擬可信 HA 代理的 HTTPS Origin／Host，確認管理寫入成功、區網管理路徑被拒絕；重新啟動後群組與授權資料不變，日誌顯示實際主機名稱。
- HA 2026.9.4 的 **11 項測試斷言通過**，但 macOS／Python 3.14.6 在程序清理階段仍以 **SIGSEGV／139** 結束，不能視為整個測試程序成功。Linux CI 結果仍待執行。
- 本機沒有 Docker，未執行映像建置或 HA OS 商店安裝；上述 HTTP 入口測試不代替 Supervisor、ARM 或備份還原驗收。HTTPS 更新使用暫存 TLS 伺服器驗證，尚未在正式 Linux systemd 安裝更新。

## 發行檔案

| 用途 | 來源 |
| --- | --- |
| 產品版號與發行紀錄 | 根目錄 `VERSION`、`CHANGELOG.md`、`doc/releases/vX.Y.Z.md` |
| 一行安裝入口 | Release 的 `install.sh`，固定同一版號；使用者入口為 `releases/latest/download/install.sh` |
| 舊 Docker 升級／worker 維護入口 | v1.2.0 起提供 `portable_docker_update.sh`，固定同一版號並驗證 Server 壓縮檔；操作與限制見 [更新維護](operations/update-operations.md) |
| Server 原始碼與 Docker 部署檔 | Release 的 `webclock-X.Y.Z.tar.gz`，從已提交的公開檔案打包 |
| 電腦離線時鐘 | Release 的 `webclock-clock-X.Y.Z.zip`，解壓後開啟最外層 `index.html` |
| 下載完整性 | Release 的 `SHA256SUMS`，包含安裝器、獨立 Docker 更新入口與兩個壓縮檔；v1.1.0 尚無新更新入口 |
| 一般 Docker 映像 | 根目錄 `Dockerfile`，發布 `ghcr.io/kcayut/webclock:X.Y.Z` |
| App 商店來源 | 根目錄 `repository.yaml` 與 `homeassistant/addon/config.yaml` |
| App 映像 | 從專案根目錄建置 `homeassistant/addon/Dockerfile`，發布 `ghcr.io/kcayut/webclock-addon:版本` |
| HACS 整合 | 根目錄 `hacs.json`、`custom_components/webclock/`；三種卡片、翻譯、圖示包含其中 |
| 回歸與發行 | `.github/workflows/home-assistant.yml` |

HACS 使用自訂儲存庫，無須等待加入預設清單；已有 HACS 的使用者只需加入來源與下載。沒有 HACS 的使用者仍可手動複製整合。Server 的私人資料不在整合安裝包裡。

## 版本來源與規則

根目錄 **`VERSION` 是產品版號來源**。Server 的 `webclock.__version__` 與 `/api/health.version` 讀取它；Docker 預設版本、HA App `config.yaml`、整合 `manifest.json`、`const.py` 與卡片 `www/webclock-cards.js` 的 `VERSION` 必須一致。`python tools/build_release.py --check --tag vX.Y.Z` 與 CI 會拒絕不一致的版號，發行包只讀取 Git 已提交內容，不會帶入本機 `.env`、TLS 私鑰或使用者資料。

採用 `X.Y.Z`：不相容變更增加 `X`，相容功能增加 `Y`，相容修正增加 `Z`；Git tag 使用 `vX.Y.Z`。首次公開使用 **1.1.0**，因 App／整合／卡片此前已標示 1.1.0，沿用可避免既有安裝版號倒退。產品版號與 `auth_schema`、裝置 schema、備份格式等相容性欄位分開管理。

正式安裝入口只選正式 Release。Linux 安裝將 `webclock.releaseChannel=stable` 寫入該 checkout 的 Git 設定，之後安全更新器依最新正式版 tag 更新；Docker 在 `.env` 固定 `WEBCLOCK_VERSION`，依[更新流程](installation.md#update)主動更新；HACS 依 Release 取得整合，HA App 依來源中的版本取得對應映像。

## 發布順序

1. 更新 `VERSION`、上述各處版本、根目錄及 App changelog，新增 `doc/releases/vX.Y.Z.md` 發行說明。執行版本檢查與相關本機測試，再提交並推送。
2. 在同一個已驗證提交建立並推送 `vX.Y.Z` tag，觸發 **Installation tests and release**；不要先建立公開 Release。一般分支 push／PR 只驗證，正式 tag 才能進入發布。
3. CI 先執行 Linux 新安裝、Server 回歸、真實 HA 2026.9.4／Python 3.14 整合與卡片測試；再驗證普通 Docker 與 HA App 的 `linux/amd64`、`linux/arm64` 映像，包含啟動、健康檢查及適用的入口隔離／資料保存。
4. 通過後發布 `webclock` 與 `webclock-addon` 固定版號映像，再以**未登入 GHCR** 的環境檢查兩個映像的 manifest 與架構。第一次建立 package 時，如預設為 Private，維護者須在 GitHub Packages 將兩者設成 **Public**，再重跑失敗工作；匿名檢查不通過時不得公開 Release。
5. 最後才建立公開 GitHub Release，附上同一提交產生的安裝器、獨立 Docker 更新入口、Server 壓縮檔、離線 ZIP 與 `SHA256SUMS`，並設為最新正式版。回讀 Release 版號、資產與匿名下載結果，執行 `release-smoke` 並指定舊 `from_version` 驗證 Docker 跨版本更新，再更新本頁的公開驗證狀態。
6. 在 HA OS 加入來源並安裝；在 HACS 加入來源、下載、重啟 HA，再用 App 日誌的整合網址＋六碼加入並新增三張卡片。核對網址的主機名稱與 App「資訊」相同、可由 HA 內部 DNS 解析；不要以普通 Docker 的容器名代替 Supervisor 主機名稱驗收。記錄 HA／Supervisor 版本、架構、映像 digest 與結果。

workflow 使用標準公開 GitHub runner；沒有使用付費大型 runner 或保留 build cache／artifact。映像發布僅限原始 `kcayut/webclock` repository，PR 與 fork 不取得發布權限。

## 升級與復原驗收

- 安裝後重啟 App／HA 主機，確認 `/data`、群組與 HA 裝置身份仍在；原卡片不需重建。
- 商店 App 更新前做 HA 備份，更新後檢查整合、時間、行事曆、鬧鐘；在測試機驗證冷備份還原及回到前一版本。
- HACS 更新整合後重啟 HA、重新載入瀏覽器，確認卡片資源一起更新。
- 重新設定 Server 位址時，驗證失敗保留原設定、成功保留 HA 實體／卡片、舊裝置退出與離線清理提示；新的程式寫入憑證須另行設定。
- 完整搬家驗收：分別匯出加密及未加密 `.webclock` → 新 App 選檔自動辨識，加密檔才須輸入密碼 → 預覽 → 停止來源並確認還原 → 原 managed 帳密登入。核對所有帳號、iCal（含 `ICAL_URL`）、顯示設定、提醒、鬧鐘、原生事件、群組、裝置與程式授權，確認未加密提示清楚且管理員驗證仍保留。
- 分別驗證全新目標保留裝置／程式憑證、已有資料目標撤銷兩者、所有 session／舊邀請失效；HA 登入不能越過 managed 帳號登入，managed 管理員可在 `/mode` 管理成員，但模式切換停用，App options 不變。
- 驗證密碼錯誤、檔案損壞、預覽後資料異動均不覆寫；中斷後重啟先處理 `.portable-restore-pending/`，保留私人的最近一次還原前副本。HA OS 實際斷電／冷備份與瀏覽器 Cookie 接續須另行實測。
- 本機 App 與商店 App 有不同的安裝身份與資料目錄，可用[完整備份流程](guides/guide.md#完整備份與搬家)搬家；確認新 App 正常後才退役舊 App。只更新既有 Local App 者繼續用[本機更新流程](installation.md#update)，不要移除後重裝來更新。

官方依據：[App 發布](https://developers.home-assistant.io/docs/apps/publishing/)、[App 儲存庫](https://developers.home-assistant.io/docs/apps/repository/)、[HACS 整合結構](https://www.hacs.xyz/docs/publish/integration/)、[HACS manifest 與版本](https://www.hacs.xyz/docs/publish/start/)。
