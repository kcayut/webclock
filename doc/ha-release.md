# Home Assistant 安裝交付與發行

一般使用者請看[Server 安裝](installation.md#home-assistant)與[整合／卡片安裝](home-assistant.md#安裝整合)。本頁供維護者發行與記錄驗收使用。

## 目前狀態

- 本版 App 與 Integration 版本為 **1.1.0**。HA App 仍標示 `experimental`。
- 已提供 App 來源、HACS 標準目錄、安裝捷徑、整合換址、HA 專用測試與多架構映像發行 workflow。新增管理頁單一 `.webclock` 加密完整備份，可將 managed 帳號與資料匯入新 HA App；這項變更的實機搬家驗收仍待完成。
- **尚未完成：**本版 commit／push、GitHub Release、公開 GHCR 映像、遠端 CI、HACS 實際下載與 HA OS 商店安裝驗收。設定檔與本機測試不等於已發布。
- 使用者的 HA 主機、Docker／ARM 部署、冷備份還原、長時間運行與通知／揚聲器仍需實測；既有 macOS HA Core／Python 3.14 測試結束 SIGSEGV 另行追蹤。

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
| App 商店來源 | 根目錄 `repository.yaml` 與 `homeassistant/addon/config.yaml` |
| App 映像 | 從專案根目錄建置 `homeassistant/addon/Dockerfile`，發布 `ghcr.io/kcayut/webclock-addon:版本` |
| HACS 整合 | 根目錄 `hacs.json`、`custom_components/webclock/`；三種卡片、翻譯、圖示包含其中 |
| 回歸與發行 | `.github/workflows/home-assistant.yml` |

HACS 使用自訂儲存庫，無須等待加入預設清單；已有 HACS 的使用者只需加入來源與下載。沒有 HACS 的使用者仍可手動複製整合。Server 的私人資料不在整合安裝包裡。

## 發布順序

1. 同時更新 App `config.yaml`、整合 `manifest.json` 與 `const.py` 的版本，更新 App changelog。App 與整合使用同一個 `X.Y.Z` 發行版本。
2. 提交並推送變更。確認 **Home Assistant installation and release** CI 成功：HA 2026.9.4／Python 3.14、卡片、安裝包、Ingress，以及 amd64／aarch64 容器的啟動、入口隔離與重啟資料保存。
3. 由相同提交建立 `vX.Y.Z` GitHub Release。只有正式觸發 `release: published` 才會在全部檢查成功後發布多架構映像；一般 push／PR／手動執行只驗證，不會推送映像。tag、App 與整合版本不符時停止。
4. 首次發布後，在 GitHub Packages 確認 `webclock-addon` 為 **Public**，且連結至此 repository。用未登入 GHCR 的環境確認 `ghcr.io/kcayut/webclock-addon:X.Y.Z` 可下載、含 `linux/amd64` 與 `linux/arm64`。使用者不應需要 registry 帳密。
5. 在 HA OS 加入來源並安裝；在 HACS 加入來源、下載、重啟 HA，再用 App 日誌的整合網址＋六碼加入並新增三張卡片。核對網址的主機名稱與 App「資訊」相同、可由 HA 內部 DNS 解析；不要以普通 Docker 的容器名代替 Supervisor 主機名稱驗收。記錄 HA／Supervisor 版本、架構、映像 digest 與結果，再更新本頁及安裝指南的發行狀態。

workflow 使用標準公開 GitHub runner；沒有使用付費大型 runner 或保留 build cache／artifact。映像發布僅限原始 `kcayut/webclock` repository，PR 與 fork 不取得發布權限。

## 升級與復原驗收

- 安裝後重啟 App／HA 主機，確認 `/data`、群組與 HA 裝置身份仍在；原卡片不需重建。
- 商店 App 更新前做 HA 備份，更新後檢查整合、時間、行事曆、鬧鐘；在測試機驗證冷備份還原及回到前一版本。
- HACS 更新整合後重啟 HA、重新載入瀏覽器，確認卡片資源一起更新。
- 重新設定 Server 位址時，驗證失敗保留原設定、成功保留 HA 實體／卡片、舊裝置退出與離線清理提示；新的程式寫入憑證須另行設定。
- 完整搬家驗收：舊 Server 匯出加密 `.webclock` → 新 App 選檔／輸入密碼／預覽 → 停止來源並確認還原 → 原 managed 帳密登入。核對所有帳號、iCal（含 `ICAL_URL`）、顯示設定、提醒、鬧鐘、原生事件、群組、裝置與程式授權。
- 分別驗證全新目標保留裝置／程式憑證、已有資料目標撤銷兩者、所有 session／舊邀請失效；HA 登入不能越過 managed 帳號登入，managed 管理員可在 `/mode` 管理成員，但模式切換停用，App options 不變。
- 驗證密碼錯誤、檔案損壞、預覽後資料異動均不覆寫；中斷後重啟先處理 `.portable-restore-pending/`，保留私人的最近一次還原前副本。HA OS 實際斷電／冷備份與瀏覽器 Cookie 接續須另行實測。
- 本機 App 與商店 App 有不同的安裝身份與資料目錄，可用[完整備份流程](guide.md#完整備份與搬家)搬家；確認新 App 正常後才退役舊 App。只更新既有 Local App 者繼續用[本機更新流程](installation.md#update)，不要移除後重裝來更新。

官方依據：[App 發布](https://developers.home-assistant.io/docs/apps/publishing/)、[App 儲存庫](https://developers.home-assistant.io/docs/apps/repository/)、[HACS 整合結構](https://www.hacs.xyz/docs/publish/integration/)、[HACS manifest 與版本](https://www.hacs.xyz/docs/publish/start/)。
