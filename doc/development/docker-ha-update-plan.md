# Docker 與 Home Assistant 更新架構

Docker 更新由宿主機程序執行；Home Assistant App 由 Supervisor 管理，整合與卡片由 HACS 管理。更新保留設定、帳號、裝置與有效憑證，並記錄進度及失敗復原狀態。

操作指令見[更新、復原與維護](../operations/update-operations.md)，測試環境與結果見[更新驗證紀錄](../acceptance/docker-ha-update-acceptance.md)。

## 支援範圍

| 安裝方式 | 更新入口 | 執行位置與限制 |
| --- | --- | --- |
| 官方 Docker Compose | `portable_docker_update.sh`；啟用 worker 後，managed 管理員可使用更新頁 | 宿主機 CLI；背景 worker 另需 Linux／systemd 與受保護安裝路徑 |
| Docker Desktop、NAS、Portainer、rootless 或客製 Compose | 原安裝平台 | 不在自動更新支援範圍 |
| HA OS 商店 App | HA 原生更新頁 | Supervisor 更新 Server App，不連帶更新 HA OS／Core |
| HACS Integration | HACS 更新項目 | 整合與三張卡片一起更新，完成後須重新啟動 HA 並重新載入瀏覽器 |
| HA Container | Server 與整合各自的安裝入口 | 沒有 Supervisor App 商店；Server 使用 Docker 或原安裝方式，整合使用 HACS 或手動安裝 |
| HA Local App | 本機建置流程 | 保留 `/data`，不自動轉為商店 App |

WebClock 不提供同一次操作更新 App、Integration 並重新啟動 HA 的跨元件協調功能。HA OS、HACS 與實體 ARM 的驗收狀態以驗證紀錄為準。

## 元件分工

路徑相對於 repository 根目錄；根目錄與 `scripts/` 的入口保留相容路徑，實作分工見[目錄說明](repository-layout.md)。

| 元件 | 職責 |
| --- | --- |
| `portable_docker_update.sh` | 下載並驗證正式版更新工具；提供更新、診斷、復原及備份清理入口 |
| `scripts/docker_update.py` | Docker 更新交易、安裝預檢、冷備份、固定映像切換與失敗復原 |
| `scripts/docker_update_install.py` | 啟用受保護的宿主機 worker、安裝路徑檢查與 worker 維護 |
| `scripts/updater_service.py` | 狀態保存、排程、更新鎖、失敗暫停與私有控制 socket |
| `scripts/release_versions.py` | 官方 Release 解析、資產完整性、stable／beta 與 SemVer 比較 |
| `webclock/api/updates.py` | 安裝類型與 provider 判斷、管理權限及固定更新操作 |
| `static/updates.js`、`templates/updates.html` | 版本、管道、進度、重連、結果與平台操作入口 |
| `homeassistant/addon/config.yaml` | App 映像、Ingress、顯示入口與冷備份設定 |
| `custom_components/webclock/` | HACS 整合、卡片與執行中版本資訊 |
| `tools/build_release.py`、`.github/workflows/home-assistant.yml` | 統一版號、打包、映像與發行檢查 |

## 資料與權限

- 正常更新保留模式、帳號、群組、行事曆、提醒、裝置與有效程式憑證，不切換部署模式。
- Docker 回退不覆蓋 live state。只有冷備份後資料未變時才允許自動回退映像；資料有變或相容性不明時保留資料與備份，回報 `manual_recovery`。
- 更新前停止指定服務並建立一致冷備份。備份失敗時不切換目標映像；冷備份期間會短暫停機。
- WebClock 容器不掛載 Docker socket。Flask 只提交固定操作，宿主機路徑、Compose 與映像來源由受信任設定決定。
- self 模式使用宿主機 CLI；managed 網頁操作需管理員、CSRF 與來源驗證。HA 管理操作使用 HA 原生權限。
- root worker 的安裝目錄與設定須受保護；控制 socket 權限為 `0600`，目錄為 `0700`。
- `.env`、私人 iCal URL、token、TLS 私鑰及備份內容不得出現在公開狀態 API 或 CI 產物。

## Docker 更新交易

1. 取得安裝鎖，固定目標 Release，記錄來源版本、映像 ID、設定指紋與交易 ID。
2. 預檢 Compose 安裝、掛載、權限、磁碟空間、CPU 架構及健康檢查設定；拒絕未知 override、多服務與共用寫入者。
3. 下載目標映像後才停止服務；下載失敗保留運行中的容器。
4. 持久化交易紀錄，再停止指定服務並建立冷備份。核對資料與備份副本，以及 Compose／環境設定是否一致。
5. 切換受控設定，以固定映像 ID 重建指定服務；不執行本機 build、全專案 `down` 或 volume prune。
6. 核對容器映像、`/api/health` 版本與模式。HTTPS 檢查保留憑證及主機名稱驗證，不接受轉址。
7. 健康檢查通過後恢復原重啟策略並記錄完成；保留復原所需的映像、備份與工具副本。

設定切換前保存原始、中間及完成狀態的指紋。外部設定變更、中斷或損壞的交易紀錄會阻止自動重試，交由管理員診斷。

| 失敗狀態 | 處理方式 |
| --- | --- |
| Release、下載或預檢失敗 | 保持目前版本與服務，回報失敗原因 |
| 停機後備份失敗 | 嘗試恢復原服務並驗證健康；無法恢復時保留復原資訊 |
| 目標容器建立或健康檢查失敗 | 資料未變時以原映像及設定回退，再次檢查健康 |
| 持久資料已變或無法確認相容性 | 停止容器、保留資料與冷備份，回報 `manual_recovery` |
| 回退成功 | 回報 `rolled_back` 並暫停自動更新，不視為升級成功 |
| 回退失敗 | 保留錯誤紀錄，使用宿主機診斷與復原入口 |

## worker 與更新頁

自動安裝預設關閉，每日版本檢查保留；重跑啟用流程保留偏好。手動與排程更新共用交易鎖，失敗後暫停自動安裝。更新頁在 Server 重啟期間重連並查詢同一交易，不自動重送安裝要求。

Docker 操作前核對 worker provider；已配置的 worker 無法連線時回報不可用，不改用裸機 worker。啟用或更新 worker 後須確認控制 socket、版本與安裝路徑，不能只以 systemd active 判定成功。

Server 與 worker 版本分別顯示。`--refresh-worker` 使用同一 Release 的工具，保留復原所需的程式與設定。離線診斷、復原與清理須先由線上入口保存工具副本；`--offline` 不下載映像，也不啟用 worker。

## Home Assistant 更新

App 更新使用 HA 原生備份與更新入口，保留 `/data`、App options、LAN port 與 Ingress 設定。App 停止期間由 HA 顯示進度，重新連線後核對實際版本。App 備份不涵蓋全部 HA Core／HACS 設定。

HACS 更新整合與卡片後須重新啟動 HA。感測器提供 `integration_version`、`server_version` 與 `version_alignment`；版本未回報時為 `unknown`，不同版時為 `mixed`。卡片與運行中整合不同版時提示重新載入瀏覽器。原 config entry、群組、Server URL 與憑證保留。

## 驗證與維護

- 本機回歸涵蓋交易鎖、設定競態、備份一致性、權限、TLS、狀態寫入失敗、worker 更新與復原。
- Docker CI 使用可丟棄的 Compose 安裝測試映像切換、self／managed HTTPS、資料保存、中斷復原與故障回退；systemd worker 演練核對啟用、socket 重建與更新。
- 公開安裝驗證的 `from_version` 指定來源版本，測試下載、跨版本升級、資料保存與離線診斷；省略時只測新安裝。
- 發行版號、資產、匿名映像下載與 CI 證據見[發行流程](../ha-release.md)。本機測試、CI、公開下載與實機驗收分別記錄。
- 真實主機斷電、HA OS 冷備份還原、HACS 更新、實體 ARM、iPad 與音訊須使用對應環境驗收。模擬測試或交叉編譯不代表實機通過。
