# WebClock 安裝交付與 Home Assistant 發行

一般使用者請看[Server 安裝](installation.md#home-assistant)與[整合／卡片安裝](home-assistant.md#安裝整合)。本頁供維護者發行與記錄驗收使用。

## 目前狀態

- **[v1.3.0 已公開發布](https://github.com/kcayut/webclock/releases/tag/v1.3.0)**。功能變更見[發行紀錄](releases/v1.3.0.md)。
- Server、Docker、HA App、HACS 整合與卡片統一版號；HA App 仍標示 `experimental`。
- HA OS 商店／HACS 實際更新、完整備份搬家、主機斷電／重開機、實體 ARM、舊 iPad、音訊及長時間運行仍需實機驗收；詳見[更新驗證紀錄](acceptance/docker-ha-update-acceptance.md)。

<a id="release-1-3-0"></a>
## 1.3.0 發行驗證（2026-11-13）

- 發行提交：`2fdd595d2e5a55478c53a32534c114e6f6987717`；GitHub 與 Gitea 的 `v1.3.0` 已獨立回讀，指向同一提交。
- [安裝與發行流程](https://github.com/kcayut/webclock/actions/runs/43396248421) 全部通過：Server 回歸、真實 HA 整合與卡片、Linux systemd、Docker 更新演練、`linux/amd64`／`linux/arm64` Server 與 App 映像，以及正式發布。
- 公開 Release 的五個資產完整，版本為 `1.3.0`、非 draft、非 prerelease，並設為最新正式版。
- 匿名讀取兩個 GHCR manifest 成功，皆包含 `linux/amd64` 與 `linux/arm64`。
- [公開安裝與跨版本升級](https://github.com/kcayut/webclock/actions/runs/43397975057) 全部通過：以公開安裝器完成 systemd 新安裝，並以 v1.3.0 入口將 Docker v1.2.0 升級；版本、self 模式、資料保存與重啟後狀態均通過。

發布流程記錄的多架構映像 manifest digest：

| 映像 | Digest |
| --- | --- |
| `ghcr.io/kcayut/webclock:1.3.0` | `sha256:c05f1d9dbb03b00c353b824a9e880d1a81beb6d5a09d0f046705f01c4380c203` |
| `ghcr.io/kcayut/webclock-addon:1.3.0` | `sha256:52cc52ed9e419a1db0e8897a4d0fdf0af6be207a9f2eba9dd105e7a45942dad6` |

公開資產的 SHA256：

| 檔案 | SHA256 |
| --- | --- |
| `install.sh` | `1b3a8caf886a75be0b9d7bd199314a6947a5cebdf175da0de5d43ea61c220e8d` |
| `portable_docker_update.sh` | `78d07635d27d9f5264dc3d69873a0647fb6f7ab7148bd3522ba7b95fca6bb9c7` |
| `webclock-1.3.0.tar.gz` | `5d732c8c0fd2fee66003902269452285d7227a91acba91cfe56835c11ca3d575` |
| `webclock-clock-1.3.0.zip` | `899b803fdb26bf12effb02e0813316fd05c6d905602426468f969c9dd3e3997c` |

## 歷史發行驗證

各版本的 CI、映像雜湊與本機驗證保存在對應發行紀錄：[v1.2.0](releases/v1.2.0.md#release-1-2-0)、[v1.1.0](releases/v1.1.0.md)。

## 發行檔案

| 用途 | 來源 |
| --- | --- |
| 產品版號與發行紀錄 | 根目錄 `VERSION`、`CHANGELOG.md`、`doc/releases/vX.Y.Z.md` |
| 一行安裝入口 | Release 的 `install.sh`，固定同一版號；使用者入口為 `releases/latest/download/install.sh` |
| Docker 升級／worker 維護入口 | `portable_docker_update.sh`，固定同一版號並驗證 Server 壓縮檔；操作與限制見 [更新維護](operations/update-operations.md) |
| Server 原始碼與 Docker 部署檔 | Release 的 `webclock-X.Y.Z.tar.gz`，從已提交的公開檔案打包 |
| 電腦離線時鐘 | Release 的 `webclock-clock-X.Y.Z.zip`，解壓後開啟最外層 `index.html` |
| 下載完整性 | Release 的 `SHA256SUMS`，包含安裝器、獨立 Docker 更新入口與兩個壓縮檔 |
| 一般 Docker 映像 | 根目錄 `Dockerfile`，發布 `ghcr.io/kcayut/webclock:X.Y.Z` |
| App 商店來源 | 根目錄 `repository.yaml` 與 `homeassistant/addon/config.yaml` |
| App 映像 | 從專案根目錄建置 `homeassistant/addon/Dockerfile`，發布 `ghcr.io/kcayut/webclock-addon:版本` |
| HACS 整合 | 根目錄 `hacs.json`、`custom_components/webclock/`；三種卡片、翻譯、圖示包含其中 |
| 回歸與發行 | `.github/workflows/home-assistant.yml` |

HACS 使用自訂儲存庫，無須等待加入預設清單；已有 HACS 的使用者只需加入來源與下載。沒有 HACS 的使用者仍可手動複製整合。Server 的私人資料不在整合安裝包裡。

## 版本來源與規則

根目錄 **`VERSION` 是產品版號來源**。Server 的 `webclock.__version__` 與 `/api/health.version` 讀取它；Docker 預設版本、HA App `config.yaml`、整合 `manifest.json`、`const.py` 與卡片 `www/webclock-cards.js` 的 `VERSION` 必須一致。`python tools/build_release.py --check --tag vX.Y.Z` 與 CI 會拒絕不一致的版號，發行包只讀取 Git 已提交內容，不會帶入本機 `.env`、TLS 私鑰或使用者資料。

採用 `X.Y.Z`：不相容變更增加 `X`，相容功能增加 `Y`，相容修正增加 `Z`；Git tag 使用 `vX.Y.Z`。產品版號與 `auth_schema`、裝置 schema、備份格式等相容性欄位分開管理。

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
