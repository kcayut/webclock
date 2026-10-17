# Docker／HA 更新實作與驗證紀錄

查核及修正日期：2026-10-15～2026-10-16。基準提交：`6f20cbd836fc7c8089c32b84f678ea4f7e84e518`；修改尚在本機工作目錄，未提交、推送、發布或部署。原始需求見 [實作計劃](../development/docker-ha-update-plan.md)。

**結論：已有本機實作與回歸證據，不能宣稱 P0～P5 全部完成。** Docker／systemd、HA OS、HACS、實體 ARM 與公開跨版本升級仍為 `not_ready`。

## 本次修正

| 原問題 | 修正後行為 | 主要位置 |
| --- | --- | --- |
| 回退直接覆蓋整份 state，可能丟失新版寫入或復活已撤銷 token | 不還原 live state；只有冷備份後資料內容完全未變才自動回退映像，否則保留新舊資料並回報 manual_recovery | `scripts/docker_update.py` |
| 記錄 image ID，實際仍按可變 tag 啟動／回退 | 正式切換與回退均固定本機不可變 image ID，禁止建置與再次拉取；健康檢查核對運行 image ID、版本及模式 | `scripts/docker_update.py` |
| 只用固定容器名稱和 Compose 字串辨識安裝 | 解析 Compose 結構，確認 project／service／working_dir／config_files、實際掛載、映像、CPU、連接埠及環境；拒絕未知 override、多服務與共用寫入者 | `scripts/docker_update.py` |
| `--version` 可略過 Release 查核，狀態從 `.env`／宿主機 VERSION 猜測 | 重新查核所選管道 Release，拒絕變更目標、降版與 stable 預發行版；版本以運行服務為準，不改宿主機 VERSION | `scripts/docker_update.py`、`scripts/updater_service.py`、`webclock/api/updates.py` |
| HTTP-only 健康檢查使 managed HTTPS 更新失敗 | 沿用憑證與主機名稱驗證，映射容器 CA 至宿主機；禁止 redirect 與略過驗證 | `scripts/docker_update.py`、`tests/test_update_tls.py` |
| 建立容器或落盤失敗不在原回退範圍；壞 journal 被忽略 | 破壞步驟納入共同錯誤處理；備份失敗須驗證原服務健康；中斷／損壞 journal 阻止自動重試 | `scripts/docker_update.py` |
| 宿主機 root worker 執行可修改的原始碼，socket 為 0666 | 明確啟用時檢查受保護安裝路徑，複製 worker 至 root 保護路徑；socket 0600、目錄 0700、容器唯讀掛載 | `scripts/docker_update_install.py`、`scripts/updater_service.py` |
| 啟用器覆寫 override、首次安裝偷偷啟用自動更新 | 不覆寫未知 override；全新 Docker 安裝不自動註冊服務；新註冊的自動安裝預設關閉，重跑保留偏好 | `scripts/setup.sh`、`scripts/docker_update_install.py` |
| Docker 可能連到裸機 helper；helper 暫停被當成未安裝 | Docker 命令前驗證 provider，拒絕不相符 worker；已配置 helper 中斷回 503；HA 仍不呼叫本機 worker | `webclock/api/updates.py` |
| 備份及 socket 目錄可能進 Git／建置內容；文件過度宣稱完成 | 加入 ignore 與 release 過濾；改寫支援範圍、資料復原與未發行狀態 | `.gitignore`、`.dockerignore`、`tools/build_release.py`、`doc/installation.md` |

另外補上設定競態檢查：冷備份期間若另一個操作修改 Compose／`.env`，更新停止，不以回退覆蓋對方設定。這種情況需由管理員核對實際容器狀態，不能假定所有停止要求都成功。

## 安裝與後續維護補修

以下已完成本機實作；完整指令見 [更新、復原與維護](../operations/update-operations.md)。

| 原缺口 | 現在的行為與界線 |
| --- | --- |
| v1.1.0 沒有新更新入口 | 新增獨立 `portable_docker_update.sh`，下載官方版本並驗證雜湊、壓縮檔路徑與版本；同一入口支援診斷、復原與清理，不依賴舊目錄具有新腳本；由新版 Release 打包交付，尚未公開發布 |
| Docker 家目錄安裝不能安全註冊 root worker | 新安裝明確選擇 `--enable-updates` 時預設 `/opt/webclock`；舊安裝可選 `--migrate-to` 冷搬移，保留原目錄；目的地已產生新資料時不重新啟動舊副本 |
| Python／systemd 條件不清楚 | Docker 執行本身仍不需要宿主機 Python；宿主機更新 CLI 要求 Python 3.9+，背景 worker 另外要求 Linux/systemd、系統 Python 與受保護路徑 |
| 裸機預設自動安裝，self 沒有設定入口 | 裸機與 Docker 新 worker 均預設關閉自動安裝、保留每日檢查；安裝參數及私有 socket 的宿主機設定 CLI 可明確開關；既有偏好保留 |
| manual_recovery 只有錯誤文字 | 新增診斷、交易 ID 核對與明確確認的復原指令；沿用現有資料，只在資料未變時允許原映像回退 |
| 宿主機 worker 長期停留在舊版 | 分別顯示 worker／Server 版本；提供相同 Release 的 `--refresh-worker`，保留前一份程式與設定；鎖持有到服務重啟或回復完成，失敗復原舊程式與註冊檔 |
| 備份容量與清理缺少入口 | 診斷顯示占用與剩餘空間；清理先預覽，確認後僅刪除可識別的已完成備份，保留最新與未解決交易 |
| HA 元件更新完成判定不清楚 | Integration 提供執行中的 Server／Integration 版號與 unknown／matched／mixed；卡片版號不同時提示重新載入；沿用 HA／HACS 原生更新順序 |

## 第二輪可靠性補修（2026-10-16）

| 再審查發現 | 修正與證據 |
| --- | --- |
| Compose／環境檔已切換但 journal 尚未更新，突然中斷後兩種復原都拒絕 | 替換任一檔案前先持久化原始、中間及完成的設定指紋；模擬兩個寫入中斷點，原／目標映像復原均通過；未知外部修改仍拒絕 |
| manual_recovery 的停止容器可能因 Docker 重啟再次啟動 | 停止前關閉實際容器的重啟策略，候選設定也使用 `restart: "no"`；健康檢查成功後恢復交易保存的原策略。單元測試驗證失敗容器維持關閉及檢查前不恢復策略 |
| 更新頁假設固定路徑、下載檔案與工具版本 | 由運行中的版本產生完整下載及維護指令，使用暫存檔；已註冊的管理員帶入實際路徑，其餘需輸入。測試涵蓋自訂路徑、引號、拒絕換行與匿名不公開主機路徑 |
| worker 只檢查 systemd active 就回報成功 | 10 秒內等待控制 socket，核對 provider、版本、安裝路徑；缺少回覆或身分不符會進入原有回復流程。另將系統 Python 版本檢查提前至 Docker 新安裝前 |
| 舊安裝救援需要再次連 GitHub | 停機前保存版本固定、附雜湊的工具副本；`--offline` 僅供診斷、復原與清理，重新驗證本機副本。測試切斷下載命令後仍可救援，修改過的工具會拒絕執行 |

重啟保護目前有命令與狀態模擬證據，**沒有本輪真實主機斷電／Docker daemon 重啟證據**。尚未使用新版線上入口建立過副本的舊安裝，也不具備離線救援工具。

## 本機證據

- 完整 Server Python suite：`venv/bin/python -m unittest discover -s tests -p 'test_*.py'`，**525 項通過**，49.390 秒。測試使用暫存安裝與本機 HTTP(S) 伺服器，沒有更新正式服務。
- Docker 交易、worker 啟用／換版、冷搬移、公開入口、API／背景更新與 Release 打包集中回歸 **94 項通過**，後續完整 suite 包含所有最終修改。涵蓋兩個設定切換中斷點的兩種復原、重啟策略、worker 身分／逾時、離線快取校驗、設定競態與資料保持。
- `tests/test_update_tls.py` 使用真實暫存 HTTPS server 驗證 Docker 健康檢查成功、拒絕錯誤主機名稱及拒絕轉址。
- `tests/test_*.js` 全部通過；`node homeassistant/tests/test_cards.js` 與 `venv/bin/python -m unittest homeassistant.tests.test_control_cli` 通過。
- Shell 語法、Python 編譯、兩份 CI workflow 的 YAML 解析、`git diff --check`、`python tools/build_release.py --check` 通過。產品版本仍為 `1.1.0`，未宣稱已產出新版 Release。
- 本機 `venv` 未安裝完整 HA Core；新增的感測器版號測試尚未執行，已納入既有真實 HA 的 CI job。卡片 JavaScript 測試通過不能代替此項。

Docker 單元測試使用依命令回覆的 fake daemon，包含真實暫存檔案、權限、鎖、冷備份、原子替換與故障注入；**不等於真實 Docker engine、systemd 或 HA OS 測試**。

## 已加入但尚未執行的 CI 演練

`tests/rehearsal/rehearse_docker_update.py` 已接入既有 `.github/workflows/home-assistant.yml` 的 amd64／arm64 Server job，使用可丟棄的 Compose 安裝測試真實 image 替換、資料保存及故意啟動失敗的回退；另加入 managed HTTPS、帳號檔案保持、設定切換中斷後復原與實際重啟策略核對。此腳本不會重啟 Docker daemon。

`tests/rehearsal/rehearse_docker_worker.sh` 僅允許一次性 GitHub-hosted Linux runner，以受保護安裝目錄檢查真實 worker 啟用、預設關閉自動安裝、偏好保留、重啟後私有 socket 與 worker refresh。`.github/workflows/release-smoke.yml` 新增 `from_version`，可從舊公開 Docker Release 安裝後，經新版公開入口跨版本升級並核對資料保持，再以保存的工具執行離線診斷；不填此參數仍只是新安裝驗證。

此演練的 Release discovery／pull 使用本地候選映像替代；即使 CI 通過，也只證明容器交易，不代表正式 GitHub Release／GHCR 匿名拉取或 HA 商店升級通過。本機沒有 Docker CLI／daemon，未執行此演練；也未推送啟動遠端 CI。

## 尚待完成

| 項目 | 狀態與後續 |
| --- | --- |
| 真實 Linux Docker／systemd | `not_ready`：需執行上述 CI、實際啟用 worker、驗證 socket 重建及主機重開機 |
| managed Docker 完整升級 | `not_ready`：本機 TLS 通過，但仍需真實映像、帳號、session、裝置與 control token 跨版本驗收 |
| HA OS 商店／HACS | `not_ready`：目前只有原生入口及既有整合／卡片，需商店更新、冷備份還原、HACS pending restart 與真實 HA restart 驗證 |
| schema 向後相容 | 採保守預設：資料有變便不自動回退；尚未建立 release 級相容矩陣與可逆 migration 契約 |
| 宿主機 worker 自身更新 | 本機程式與失敗回復測試通過，明確使用相同版本公開資產 refresh；真實 systemd／公開資產驗收為 `not_ready` |
| 舊 Docker 冷搬移 | 暫存資料與故障注入通過；真實 Docker engine 與主機重開機為 `not_ready` |
| v1.1.0 一次性公開 bootstrap | 本機入口、校驗與打包已實作；`not_ready`：v1.1.0 公開資產沒有新入口，需新版發布及跨公開版本 smoke |
| 版本／發行／公開 smoke | `not_ready`：沒有新 tag、公開資產、image digest、CI run 或跨公開版本證據 |
| Docker Desktop／NAS／rootless／遠端 daemon | 非首版支援範圍，不能宣稱 CLI 可直接接管 |
| 實體 ARM／舊 iPad／音訊／長期運行 | `not_ready`：沒有此次實機證據 |
| P6 跨 App＋Integration 更新 | 未執行，維持原計劃的獨立進階工作 |

發行前必須完成對應環境驗收、更新產品版號及公開資產，不可將本文件中的本機測試數字當作正式交付證據。
