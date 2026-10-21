# 安裝後的更新、復原與維護

本文件適用於 **v1.2.0 起**的更新入口與選項；v1.1.0 安裝需先使用下方的獨立 Docker 入口。各環境的 CI、公開下載及實機證據見[發行驗證](../ha-release.md)。

原始碼中的手動與可攜式更新腳本已集中到 [`scripts/update/`](../../scripts/update/README.md)。根目錄一般更新指令保留轉接；以下公開下載資產名稱及離線救援路徑不變。

## 日常更新

更新前先下載完整備份。以下指令在安裝目錄執行；更新失敗且要求人工復原時，保留資料與交易紀錄，依[復原流程](#docker-復原)處理。

| 環境 | 操作 |
| --- | --- |
| Linux | `sudo bash update_clock.sh && [ -f scripts/enable_updates.sh ] && sudo bash scripts/enable_updates.sh`；已啟用更新服務的 managed 管理員也可使用 `/updates` |
| Docker v1.2.0 起 | `sudo bash docker_update.sh --check`，確認後執行 `sudo bash docker_update.sh`；僅支援官方單一 Compose、本機系統 Docker |
| HA 商店 App | App 頁建立備份後按「更新」，再更新 HACS 整合並重啟 HA |
| HA 本機 App | 備份後用新版原始碼產生至新暫存目錄，核對後替換 `/addons/webclock` 程式檔，再重建／啟動；保留 `/data` |

| 環境 | 狀態與日誌 |
| --- | --- |
| Linux | `systemctl status webclock`；`sudo journalctl -u webclock -n 100 --no-pager` |
| Docker | `docker compose ps`；`docker compose logs --tail=100 webclock` |
| HA App | App「資訊」與「日誌」 |

更新後以 `/api/health` 核對運行版本及模式，再確認管理設定與顯示內容。Docker Desktop、NAS、rootless／遠端 daemon 不在更新器支援範圍。

## 新安裝

預設只每日檢查，不自動安裝。既有更新服務的選擇保留，不因重新啟用而改動。

- 裸機：新版 `install.sh` 可加 `--auto-update on` 或 `--auto-update off`；managed 管理員可在更新頁設定。
- Docker 單純執行：仍不要求宿主機 Python，不註冊 root worker。
- Docker 網頁更新：Linux/systemd、系統 Docker、`/usr/bin/python3` 3.9+；執行 `sudo bash install.sh --docker --enable-updates`，預設使用受保護的 `/opt/webclock`。自訂 `--dir` 必須同樣受保護。明確加 `--auto-update on` 才自動安裝。
- Docker 宿主機 CLI：需要 Python 3.9+ 以及讀寫安裝資料、操作 Docker 的權限；Docker 建立的私有檔案通常需要 sudo。Debian/Ubuntu 缺 Python 時先執行 `sudo apt-get install python3`。

## 舊 Docker 第一次升級

下載 v1.2.0 或更新正式版的獨立入口到安裝目錄外。它只從官方 GitHub Release 下載壓縮檔，驗證 SHA256SUMS、檔案類型、路徑與版本，再執行該版更新器；不覆蓋既有宿主機原始碼、不還原舊資料。

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/portable_docker_update.sh -o /tmp/webclock-docker-update.sh
sudo bash /tmp/webclock-docker-update.sh --project /實際安裝路徑 --check
sudo bash /tmp/webclock-docker-update.sh --project /實際安裝路徑
```

已位於受保護目錄時，加 `--enable-updates` 啟用網頁控制。舊版 Server 沒有更新 API 也能先由此宿主機入口升級，再啟用 worker。

使用者家目錄中的安裝可在明確選擇後遷移：

```bash
sudo bash /tmp/webclock-docker-update.sh --project /home/使用者/webclock --migrate-to /opt/webclock
```

目的地必須不存在，父目錄由 root 保護。流程確認官方單一 Compose、停止原容器、複製資料並比對雜湊、使用原 image ID 在新位置重建並確認健康，之後才繼續更新與啟用 worker。原目錄與私人資料保留，不修改整個家目錄的權限。舊目錄的 `.docker-migration.json` 會阻擋誤用舊更新入口；日後只操作新目錄。

客製絕對掛載、另一個已註冊 worker、未完成交易、目的地已有內容等情況會拒絕接管。遷移後的新位置若已寫入資料但未通過健康檢查，保留兩份資料並停止，原目錄紀錄 `manual_recovery`。請保留兩份目錄；核對紀錄中的來源映像與版本後，只在新目錄重啟已固定的同一映像（`sudo docker compose up -d --no-build --pull never`），驗證健康與資料後再跑獨立入口。不要啟動舊副本或把舊資料覆蓋回去。

## self 模式與宿主機設定

設定指令透過私有 socket 修改 worker 的持久設定，避免直接編輯正在使用的 state.json。輸出會列出目前偏好、版本與暫停狀態。

```bash
# 裸機，在安裝目錄執行：
sudo python3 scripts/update_settings.py --auto-update off
sudo python3 scripts/update_settings.py --channel stable --auto-update on

# Docker，已啟用 worker：
sudo python3 /usr/local/lib/webclock-docker-updater/update_settings.py --kind docker --auto-update off
sudo python3 /usr/local/lib/webclock-docker-updater/update_settings.py --kind docker
```

關閉自動安裝仍保留每日檢查。失敗後的暫停旗標不會被切換設定或重開服務清除；完成復原後，下一次成功的手動升級才會解除暫停。self 匿名網頁仍不能取得主機更新權限。

## Docker 更新器本身的更新

容器版本與 worker 版本分開顯示。更新頁會依執行中的 Server 版號產生完整下載指令；受管模式管理員可自動取得已註冊的宿主機路徑，無法取得時需自行填入實際絕對路徑。self 匿名頁面不公開宿主機路徑。由與執行中 Server **相同版本**的公開資產更新 worker：

```bash
# VERSION 換成 /api/health 的實際版本；先下載該版本的獨立入口：
curl -fsSL https://github.com/kcayut/webclock/releases/download/vVERSION/portable_docker_update.sh -o /tmp/webclock-docker-update.sh
sudo bash /tmp/webclock-docker-update.sh --project /opt/webclock --version VERSION --refresh-worker
```

更新器在交易鎖內確認沒有進行中的更新，停止舊 worker，保留上一份程式於 `/usr/local/lib/webclock-docker-updater/previous/`，再替換並重新啟動；保留原有設定與狀態。10 秒內必須由控制 socket 回覆正確 provider、worker 版本及安裝路徑，才算啟用成功。複製、啟動或此項檢查失敗時會嘗試恢復先前程式。這是明確執行的維護操作，不會在容器升級時自動更新宿主機程式。

## Docker 復原

以下在具有 `docker_update.sh` 的安裝目錄執行；舊版安裝沒有此檔時，改用已下載的 `sudo bash /tmp/webclock-docker-update.sh --project /實際安裝路徑`，接上相同的 `--diagnose`、`--recover` 或 `--prune-backups` 參數即可。線上入口會驗證下載的更新器，停機前保留救援副本；維護操作不會順便升級容器或註冊 worker。

更新器在替換 Compose／`.env` 前先保存每個可到達階段的設定指紋，因此中途突然停止後仍可辨識自己的變更。更新期間容器的自動重啟暫時關閉；通過健康檢查後才恢復原策略。進入人工復原時保持關閉，即使 Docker／主機重啟也不應自行啟動問題容器。不要自行執行 `compose up` 繞過復原檢查。

先停止背景更新，保留 journal 與所有資料，再診斷：

```bash
sudo systemctl stop webclock-docker-updater
sudo bash docker_update.sh --diagnose
```

未註冊背景 worker 時略過 `systemctl stop`。舊安裝可直接診斷：

```bash
sudo bash /tmp/webclock-docker-update.sh --project /實際安裝路徑 --diagnose
```

診斷提供交易 ID、原／目標版本、備份位置、備份占用與可用空間。確認 ID 與預期一致後選擇：

```bash
# 以交易目前設定的映像重試；保留全部現有資料：
sudo bash docker_update.sh --recover current --operation '貼上診斷中的完整交易ID' --yes
# 回退原映像：僅資料與冷備份完全一致時允許：
sudo bash docker_update.sh --recover previous --operation '貼上診斷中的完整交易ID' --yes
```

實際 ID 格式為 `up-` 加 32 位十六進位字元，請完整複製，不要使用範例佔位字串。復原不接受任意映像、不覆蓋 live state；會核對 Compose 身分、交易設定指紋與實際健康狀態，並封存原交易紀錄。設定被外部修改、journal 損壞、資料已變而要求舊映像等情況仍需人工處理，不得刪 journal 強迫重試。復原成功後可重新啟動 `webclock-docker-updater`；自動安裝仍維持暫停。

資料相容契約採保守規則：一般升級保留現有資料；原映像自動回退只允許持久資料未變。尚未宣告任何「舊程式可讀取新版 schema」的跨版能力。後續加入 migration 時，必須先提供相容矩陣與憑證撤銷測試，才能放寬此條件。

## 離線救援

線上入口會在停機前保存同一份已驗證工具，並印出位置。以 sudo 執行時固定存於 `/var/lib/webclock-docker-recovery/VERSION/`；非 root 執行時使用 `${XDG_CACHE_HOME:-$HOME/.cache}/webclock-docker-recovery/VERSION/`。`VERSION` 是當次工具的發行版號。副本只含程式、版本與雜湊，不含使用者設定或憑證。

```bash
# VERSION 換成當次印出的工具版號；不需要原本 /tmp 下載檔案：
sudo bash /var/lib/webclock-docker-recovery/VERSION/portable_docker_update.sh --offline --project /實際安裝路徑 --diagnose
sudo bash /var/lib/webclock-docker-recovery/VERSION/portable_docker_update.sh --offline --project /實際安裝路徑 --recover current --operation '貼上完整交易ID' --yes
```

`--offline` 僅供診斷、復原與備份清理，不聯絡 GitHub、不拉取映像，也不啟用 worker。每次使用前重新核對副本的版本、雜湊與路徑；root 不會採用其他帳號可寫入的快取。工具副本或原映像缺失時仍需先補回，不能略過驗證。未經此新版入口建立過副本的舊安裝，不會憑空具備離線救援能力。

## 備份容量與清理

```bash
sudo bash docker_update.sh --diagnose
sudo bash docker_update.sh --prune-backups 3       # 只預覽
sudo bash docker_update.sh --prune-backups 3 --yes # 確認刪除預覽中的舊備份
```

至少保留一份；清理只處理本更新器標記為已完成／已回退的備份，保留最新交易、舊格式及未解決的備份。進行中或需要復原時拒絕清理。沒有全域 image／volume prune。備份含私人資料與 TLS 私鑰，權限限制不等於加密。

## HA 的完成判定

1. 先備份 App 與 HA 設定；依發行說明指定順序更新。沒有不相容公告時，先 Server App，再 HACS Integration＋卡片。
2. HACS 下載後重新啟動 HA，檢查感測器的 `integration_version`、`server_version`、`version_alignment`；這些是實際執行中的資訊。
3. 舊 Server 沒有回報版本時顯示 `unknown`；不同版本顯示 `mixed`，不憑版號差異破壞現有連線。相同版本僅代表版號對齊，不代表實機相容驗收通過。
4. 瀏覽器仍載入舊卡片時會顯示重新載入提示。重載後確認時鐘、行事曆、鬧鐘與原裝置身份仍正常。

App／Integration 繼續使用 HA／HACS 原生更新，不新增可控制整個 HA 的 WebClock 後門。跨版本組合目前的實機驗收仍為 `not_ready`。

## 發行驗收

- 本機：Server 回歸、更新 CLI／故障注入、首次入口雜湊與壓縮檔拒絕、HA 卡片與版號檢查。
- CI：amd64／arm64 Docker 替換與回退、managed HTTPS／帳號資料保持；Linux worker 啟用、私有 socket 重建、偏好保留及 worker refresh。
- 公開資產：手動執行 `release-smoke`，設定新 `version` 與舊 `from_version`，驗證公開 Docker 首次跨版本升級。空白 `from_version` 只測全新安裝，不能算升級證據。
- 實機：HA OS 商店備份／還原、HACS pending restart、主機重開機、真實 session／裝置／control token、ARM／音訊與舊瀏覽器，須另外留下證據。

以上 CI 腳本已加入不代表已執行成功；發布前須記錄實際 SHA、版本、CI run、映像與公開 smoke 結果。

## 更新器設定參考

### Docker 更新器（v1.2.0 起）

目前支援官方單一服務 Compose、本機 `/var/run/docker.sock`、Linux amd64／arm64 映像。客製 override、多服務、非預設資料掛載、遠端 Docker、rootless／user namespace remapping 會拒絕自動接管。Docker Desktop／NAS 不在已驗收範圍；不能將 CLI 視為所有平台的替代保證。

在包含新版更新器的宿主機安裝目錄執行：

```bash
bash docker_update.sh --check
bash docker_update.sh
# beta 是明確選擇，切回 stable 不會降版：
bash docker_update.sh --channel beta
# 查看最近交易；--version 只能確認目前管道提供的目標，不能任選舊版：
bash docker_update.sh --status
```

CLI 需要可操作本機 Docker 及讀寫安裝資料的帳號。一般升級依序確認運行中版本、映像與 Compose 身分，先拉映像，再停機、冷備份、固定不可變 image ID、重建及確認健康。更新會保存 `.env` 的其他設定與權限，並把安裝目錄的 Compose `image` 固定為實際 image ID；後續更新繼續使用此 CLI，不能只改 `.env` 的版號或執行 `compose pull`。

完整冷備份位於 `.docker-update-backups/<operation ID>/`，含 state、模式備份、legacy notes、`.env`、Compose 與 TLS。備份包含私人資料及私鑰，**未加密**，以目錄權限限制存取；不要公開上傳。正常更新不改寫宿主機程式碼的 `VERSION`，運行版本以映像與 `/api/health` 為準。

**失敗回退：**如果新版尚未改寫任何持久資料，可固定原 image ID 回退，且重新確認健康。若新版已改寫資料、憑證或 schema，保留目前資料與冷備份、停止容器並回報 `manual_recovery`；不會直接覆蓋整包舊 state，也不會復活已撤銷憑證。交易紀錄損壞或中斷也會阻止下一次自動更新。

**網頁控制需另外明確啟用：**Linux＋systemd 宿主機可執行：

```bash
sudo bash scripts/enable_docker_updates.sh
```

背景模式要求安裝目錄、Compose、`.env` 及祖先目錄由 root 擁有且不可由其他帳號寫入，建議使用獨立受保護的 `/opt/webclock` 安裝。使用者家目錄可用新版獨立入口的 `--migrate-to /opt/webclock` 明確遷移，詳見[完整操作流程](../operations/update-operations.md)。客製安裝仍需先核對；勿直接對整個家目錄遞迴變更權限。

啟用器把 worker 程式複製到 root 保護的 `/usr/local/lib/webclock-docker-updater/`，不以 root 執行應用程式可修改的原始碼。WebClock 只掛載專用的唯讀 socket 目錄，socket 權限為 `0600`；容器不掛載 Docker socket。更新頁會顯示 worker 版本，可用已驗證公開入口 `--refresh-worker` 更新與運行服務同版的 worker，保留上一份程式與偏好；不會自動更新宿主機 worker。

新註冊的**自動安裝預設關閉**，既有偏好保留；managed 管理員可於 `/updates` 啟用，self 的匿名頁面無法觸發主機更新。首次補 socket 掛載可能重建容器並短暫中斷服務。Docker 全新安裝不會自動註冊 root worker。

原生 HTTPS 使用容器的 TLS 設定，保留憑證與主機名稱驗證。若使用私人 CA，將 CA 放入宿主機 `tls/` 並設定容器路徑，例如 `WEBCLOCK_UPDATE_CA=/app/tls/ca.pem`；`WEBCLOCK_UPDATE_HOST` 填憑證名稱。健康檢查連到本機映射連接埠，不跟隨 redirect，也不略過驗證。

### Linux 更新與發行管道

`webclock-updater.service` 每日檢查版本，自動安裝預設關閉。managed 管理員可在 `/updates` 設定；self 使用[宿主機設定指令](#self-模式與宿主機設定)。升級流程包含備份、套件更新、重啟及健康檢查；失敗時嘗試回復原版本並暫停自動安裝。成功後背景服務會重新載入新版程式。

- `stable`：正式 Release，忽略預先發行版。
- `beta`：正式版與測試版；切回 stable 不降版，等待更高版號的正式版。

```bash
sudo bash update_clock.sh --channel stable && [ -f scripts/enable_updates.sh ] && sudo bash scripts/enable_updates.sh
```

測試管道將 `stable` 換成 `beta`。正式安裝以 Git 的 `webclock.releaseChannel` 記錄來源；開發 checkout 保留原 upstream。

原生 HTTPS 的健康檢查在 `.env` 設定 `WEBCLOCK_UPDATE_HOST=clock.example`（憑證名稱）；私人 CA 另設 `WEBCLOCK_UPDATE_CA=/絕對路徑/ca.pem`。檢查連至本機服務，仍驗證憑證且不跟隨重新導向。

舊更新器若顯示「Native HTTPS is not supported」，先備份，改用[獨立更新入口](../guides/guide.md#更新程式)。將入口存至安裝目錄外，保留原程式供失敗還原；不要先覆寫更新器或執行 `git pull`。
