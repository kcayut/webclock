# 安裝 WebClock

[文件索引](README.md) · [使用指南](guides/guide.md) · [更新與復原](operations/update-operations.md)

只看時間可直接開啟 **[線上時鐘](https://kcayut.github.io/webclock/)**；需要行事曆、提醒與鬧鐘，再選一種 Server 安裝方式。

| 環境 | 安裝方式 | 預設管理入口 |
| --- | --- | --- |
| Raspberry Pi OS／Debian／Ubuntu | [Linux](#bare-metal) | `http://主機IP:5000/admin` |
| 已有 Docker Compose | [Docker](#docker) | `http://主機IP/admin` |
| Home Assistant OS | [HA App](#home-assistant) | App「開啟網頁介面」 |
| 不需要 Server | [線上／離線時鐘](#no-server) | 無管理頁 |

以下指令用於**全新安裝**，預設目錄為目前位置下的 `webclock`，版本取自 GitHub 最新正式 Release。已有安裝請使用[更新流程](#update)，不要覆蓋原目錄。

Linux／Docker 預設為 **self**：區網內可直接管理，請勿對 Internet 開放。需要帳號登入時，使用 [managed 安裝](#https)：預設 HTTPS，可信任內網可經二次確認選擇 HTTP。

<a id="bare-metal"></a>
## 1. Linux／Raspberry Pi

需要 systemd、Bash、curl 與 sudo 權限（root 可直接執行）。缺少 curl 時先安裝：`sudo apt-get update && sudo apt-get install -y curl`。

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh
```

安裝器會準備 Python 環境並啟用開機啟動。完成後開啟 **`http://主機IP:5000/admin`**，進行[首次設定](#first-run)。

<a id="docker"></a>
## 2. Docker

需要 Bash、curl、tar，以及已啟動的 Docker Engine／Docker Desktop；目前帳號須可執行 `docker compose`。

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --docker
```

安裝器下載並校驗正式版，使用 amd64／arm64 預建映像。完成後開啟 **`http://主機IP/admin`**。

若主機的 80 埠已被占用，下載腳本後改執行下列指令，管理入口為 `http://主機IP:8080/admin`：

```bash
WEBCLOCK_HTTP_PORT=8080 bash /tmp/webclock-install.sh --docker
```

資料保存在安裝目錄的 `webclock_state`，模式備份在 `.webclock-mode-backups-webclock_state`；請保留兩者及既有 `manual_notes.json`。自訂資料路徑時，須同步調整 Compose 掛載，不能只改 `.env`。

<a id="home-assistant"></a>
## 3. Home Assistant OS

適用 amd64／aarch64。HA Container／Core 請用 Linux 或 Docker 安裝 Server。

1. **[加入 WebClock App 來源](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fkcayut%2Fwebclock)**。
2. App 商店選 **WebClock → 安裝 → 啟動**，啟用「開機啟動」及「顯示於側邊欄」。
3. 按 **開啟網頁介面**，設定行事曆、提醒與群組。

按鈕無法使用時，在 **設定 → Apps → App 商店 → 儲存庫**加入 `https://github.com/kcayut/webclock`，再檢查更新。舊介面可能稱為「附加元件」。

| 需求 | 下一步 |
| --- | --- |
| 在 HA 儀表板顯示 | [安裝整合與卡片](home-assistant.md#安裝整合)；Server 欄位填 App 日誌 `Home Assistant integration URL:` 後的網址 |
| 平板直接顯示時鐘 | App「網路」將 `8100/tcp` 映射到主機 8100，再開啟 `http://HA主機IP:8100`，輸入群組六碼 |
| 從其他主機搬入 | [匯入完整備份](home-assistant.md#從既有-server-搬進-ha-app) |

管理入口由 HA 登入及 Ingress 保護；8100 不提供管理頁。匯入 managed 備份後仍須登入原 WebClock 帳號。App 資料位於 `/data`，請納入 HA 備份。HA OS／ARM 實機狀態見[發行驗證](ha-release.md)。

<a id="first-run"></a>
## 安裝完成後

1. 開啟管理頁，設定顯示語言、時區、行事曆與提醒，儲存後重載確認。
2. 需要群組授權時，在「裝置」建立群組、指派內容並產生六碼，再由顯示裝置開啟時鐘網址加入。
3. 依[裝置指南](guides/display-devices.md)設定主畫面入口、全螢幕與恆亮。網頁鬧鐘需保持前景，並在實際裝置測試聲音。
4. 在「備份與還原」下載完整 `.webclock` 備份，妥善保存備份密碼；TLS、DNS 與主機設定須另行備份。

<a id="install-options"></a>
## 自訂安裝

參數加在已下載的 `bash /tmp/webclock-install.sh` 後。目的地須尚不存在；Linux 服務路徑不能含空白、`%` 或反斜線。

| 需求 | 參數／設定 |
| --- | --- |
| 指定新目錄 | `--dir /絕對/安裝路徑` |
| 固定正式版本 | `--version 1.2.0`（範例） |
| Linux 改用 8080 | `PORT=8080 bash /tmp/webclock-install.sh` |
| Docker 改用 8080 | `WEBCLOCK_HTTP_PORT=8080 bash /tmp/webclock-install.sh --docker` |
| 管理員登入 | `--managed`；提供 HTTPS 憑證或互動確認內網 HTTP |
| 自動更新／網頁更新 | [啟用更新服務](operations/update-operations.md#新安裝)（v1.2.0 起） |
| 查看版本支援的參數 | `bash /tmp/webclock-install.sh --help` |

<a id="https"></a>
### managed：HTTPS 或內網 HTTP

使用含此功能的安裝器時，加上 `--managed` 即可；若未設定 TLS 憑證，會先詢問是否啟用 TLS。需要 TLS 就先準備下列憑證再重試；只在可信任內網使用時，回答 `n`，再輸入 `HTTP` 二次確認。確認後才允許明文 HTTP，仍保留帳號登入與裝置授權。取消或直接 Enter 不會啟用 HTTP。

本機原始碼可執行 `bash setup.sh --managed`，Docker 原始碼測試加 `--docker --build`。已發布版本是否包含此選項，請依該版本說明確認。既有安裝的操作與切回 HTTPS 見[連線設定](operations/accounts-and-https.md#https)。

先準備主機名稱及裝置信任的對應憑證，替換下列路徑與 `clock.example`。安裝器會要求設定 `admin` 密碼，至少 12 字元。

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --managed --tls-cert /absolute/path/fullchain.pem --tls-key /absolute/path/privkey.pem --tls-host clock.example
```

Docker 加 `--docker`；私人 CA 加 `--tls-ca /absolute/path/ca.pem`，並在每台裝置信任該 CA。安裝器不申請憑證。完成後使用顯示的 HTTPS 網址；既有安裝及反向代理設定見 [HTTPS 設定](operations/accounts-and-https.md#https)。

<a id="no-server"></a>
## 線上與離線時鐘

公開版只顯示時間、日期與星期，使用裝置本身的時間與時區，沒有行事曆、提醒或鬧鐘。

<a id="offline-download"></a>
### 電腦下載使用

1. 從[正式 Release](https://github.com/kcayut/webclock/releases/latest)下載 `webclock-clock-版本.zip`。
2. 解壓縮整個 ZIP，用瀏覽器開啟最外層的 `index.html`。
3. 保留同層 `static` 資料夾；斷網後關閉並重新開啟，確認時鐘正常。

不需執行安裝腳本。更新時另下載新版、解壓至新資料夾；勿只保存 HTML、PDF 或截圖。本機 `file://` 開啟不受頁腳網站快取提示影響。

<a id="offline-cache"></a>
### 平板／瀏覽器離線重開

1. 連線開啟[線上時鐘](https://kcayut.github.io/webclock/)，使用一般瀏覽模式。
2. 若要使用主畫面圖示，先[加入主畫面](guides/display-devices.md)，再從該圖示開啟。
3. 等頁腳顯示 **「已可離線開啟」**，再斷網、關閉頁面，從相同入口重新開啟確認。

快取被清除或系統回收後須重新連線準備；不同瀏覽器／主畫面入口可能不共用快取。平板的檔案預覽不能代替瀏覽器執行。

**iPad mini 1／iOS 9 不支援快取離線重開**，只能先連線載入並保持前景；關閉或重新開機後需連網。各平台全螢幕與恆亮設定見[裝置指南](guides/display-devices.md)。

<a id="install-troubleshooting"></a>
## 安裝排錯

| 問題 | 處理方式 |
| --- | --- |
| 目的地已存在 | 已安裝者使用更新流程；全新安裝改用不存在的 `--dir` |
| 安裝中斷 | 排除錯誤後，在原目錄以相同參數重跑 `bash setup.sh`；若留有 `.webclock-bootstrap`，可用原版本、原目錄重跑下載入口 |
| 下載失敗／校驗不符 | 檢查 GitHub／GHCR 連線、磁碟空間及 Release 資產；不要略過校驗 |
| `Unknown option` | 查看該腳本的 `--help`；`--dir`／`--version` 屬於 `install.sh`，`--build` 屬於 `setup.sh --docker` |
| 連接埠占用 | Linux 改 `PORT`，Docker 改 `WEBCLOCK_HTTP_PORT`；已有 `.env` 時編輯該檔，容器內維持 5000 |
| Docker 無法連線 | 啟動 Docker，確認目前帳號可執行 `docker compose version` 及操作 daemon |
| `manual_notes.json` 是目錄 | 停止容器並確認目錄為空，才用 `rmdir manual_notes.json` 移除；非空內容須保留 |
| 平板無法連線 | 使用主機區網 IP，勿填 `localhost`；檢查防火牆、訪客網路隔離與埠映射 |
| managed TLS／登入失敗 | 使用憑證對應名稱，檢查有效期、完整憑證鏈及裝置信任；內網 HTTP 須先明確啟用，不會因 TLS 錯誤自動降級 |
| HA 找不到 App／整合／卡片 | [HA 安裝與排錯](home-assistant.md#安裝整合) |

排錯時保留原目錄、`webclock_state`、`auth.json`、狀態標記與 Docker volume；不要以刪除資料強迫重裝。回報日誌前移除私人網址、token、加入碼及憑證內容。

<a id="update"></a>
## 更新與維護

[日常更新指令](operations/update-operations.md#日常更新) · [舊 Docker 首次升級](operations/update-operations.md#舊-docker-第一次升級) · [備份搬家](guides/guide.md#完整備份與搬家) · [故障復原](operations/update-operations.md#docker-復原)

<a id="enable-managed"></a>
<a id="web-setup"></a>
<a id="mode-switch"></a>
<a id="owner-data"></a>
<a id="account-recovery"></a>
### 帳號與模式

- [既有 self 啟用 managed](operations/accounts-and-https.md#enable-managed)／[一次性設定碼](operations/accounts-and-https.md#web-setup)
- [切換模式與管理成員](operations/accounts-and-https.md#mode-switch)
- [多帳號備份還原](operations/accounts-and-https.md#owner-data)／[管理員密碼復原](operations/accounts-and-https.md#account-recovery)

<a id="source-install"></a>
<a id="manual-python"></a>
<a id="ha-local"></a>
### 開發與其他裝置

[原始碼安裝](development/source-installation.md#source-install) · [手動 Python](development/source-installation.md#manual-python) · [HA 本機建置](development/source-installation.md#ha-local) · [ESP32-S3 韌體](../firmware/README.md)
