# 安裝 WebClock

[回到 README](../README.md) · [使用指南](guide.md) · [裝置顯示設定](display-devices.md) · [Home Assistant 卡片與整合](home-assistant.md)

**只看時間，不用安裝 Server：**直接開啟 [GitHub 線上時鐘](https://kcayut.github.io/webclock/)，或照下方[下載與離線使用](#no-server)操作。需要行事曆、提醒與管理功能，再選擇自架方式與授權模式。

安裝完成後，要讓平板／電腦點圖示就顯示時鐘，請照[裝置顯示設定](display-devices.md)建立主畫面入口、開啟全螢幕與螢幕恆亮；包含 iPad mini 1／iOS 9。

## 一眼選擇

| 安裝方式 | 適合環境 | 安裝入口 | 預設入口 |
| --- | --- | --- | --- |
| [免 Server：線上／離線時鐘](#no-server) | 只想看時間的平板或電腦 | 開啟網頁；電腦也可下載 ZIP 後直接使用 | [GitHub 線上時鐘](https://kcayut.github.io/webclock/) |
| [Bare metal](#bare-metal)：直接安裝 | Raspberry Pi OS、Debian、Ubuntu，使用 systemd | 下方一行指令，自動取得最新正式版 | `http://主機IP:5000` |
| [Docker](#docker) | 已安裝 Docker Compose 的電腦、NAS、Linux | 下方一行指令加 `--docker`，下載正式映像 | `http://主機IP` |
| [Home Assistant](#home-assistant) | 有 App 商店的 HA OS，amd64／aarch64 | 加入 App 來源 → 安裝 WebClock | HA 側邊欄／開啟網頁介面 |

三種方式只決定 **Server 跑在哪裡**，選一種即可。要在 HA 儀表板顯示，再[安裝 WebClock 整合](home-assistant.md#安裝整合)，輸入 Server 位址與六碼；時間、行事曆、鬧鐘卡片會一起提供，不必分別安裝。

以下授權模式只適用自行架設；公開版與下載的靜態時鐘不需選擇 self／managed。

| 模式 | 如何啟用 | 管理與顯示方式 |
| --- | --- | --- |
| **self（自用，預設）** | 一般安裝即可，不加參數 | 可信任區網內直接開啟 `/admin`；不要求 WebClock 管理員登入 |
| **managed（受管）** | 全新 Linux／Docker 安裝加 `--managed` 與 [TLS 參數](#https) | 管理員登入後管理；每台顯示端用六碼加入群組，取得自己的授權 |
| **Home Assistant App** | 安裝後從 HA 開啟；搬家可匯入完整備份 | 預設 self，由 HA 登入與 Ingress 保護；匯入 managed 備份後保留原 WebClock 帳號登入與裝置配對 |

模式保存在私人資料目錄的 `auth.json`，**不是 `.env` 中的開關**。已有管理員的安裝可在 [`/mode` 雙向切換](#mode-switch)，第一次建立管理員也可使用[主機一次性設定碼](#web-setup)。一般安裝與更新保留原模式；不要刪除 `auth.json`／`auth-required`。self 的管理頁不適合直接開放至 Internet。

<a id="no-server"></a>

## 免安裝：GitHub 線上時鐘與離線使用

**[直接開啟 WebClock →](https://kcayut.github.io/webclock/)**　**[下載離線使用的 ZIP →](https://github.com/kcayut/webclock/releases/download/v1.1.0/webclock-clock-1.1.0.zip)**

公開時鐘只顯示**時間、日期與星期**，使用裝置本身的時間與時區，不向 WebClock Server 校時；離線時仍依靠裝置時鐘。先確認系統時間正確即可，不需 GitHub 帳號、Python、Docker 或 WebClock 管理員帳號。這個版本不提供自架版的行事曆、提醒、鬧鐘或群組管理。

| 想怎麼使用 | 選這個方式 |
| --- | --- |
| 有網路，開了就看時間 | 直接開啟上面的 GitHub 網址 |
| 電腦要保存一份，關掉後也能斷網重開 | [下載 ZIP，解壓縮後開啟檔案](#offline-download) |
| 平板想從原本網址／主畫面圖示離線開啟 | [先連線準備瀏覽器快取](#offline-cache)，再做斷網重開檢查 |
| iPad mini 1／iOS 9 | 先連線載入並保持前景；不支援下面的快取重開方式 |

<a id="offline-download"></a>

### 電腦：下載後直接開啟，不用架 Server

1. 點[下載 v1.1.0 離線 ZIP](https://github.com/kcayut/webclock/releases/download/v1.1.0/webclock-clock-1.1.0.zip)，或到[最新正式版](https://github.com/kcayut/webclock/releases/latest)下載 `webclock-clock-版本.zip`。
2. **先解壓縮整個 ZIP**：Windows 按右鍵選「解壓縮全部」，Mac 雙擊 ZIP，Linux 使用系統壓縮檔工具。不要直接在壓縮檔預覽裡開 HTML。
3. 打開解壓後的 `webclock-clock-版本` 資料夾，用 Chrome、Edge、Firefox 或電腦版 Safari 開啟**最外層的 `index.html`**。通常雙擊即可；若被文字編輯器開啟，改用右鍵「開啟方式」選瀏覽器。不要開 `templates/index.html`。
4. **保留整個資料夾**，尤其是同一層的 `static`；不能只把 `index.html` 單獨移到桌面。想快速開啟時，替它建立桌面捷徑／替身即可。
5. 中斷網路，關閉時鐘分頁，再從該檔案重新開啟，確認時間與日期出現；接著依[裝置指南](display-devices.md)設定全螢幕與恆亮。

離線 ZIP 只包含靜態時鐘與所需顯示檔案，**不用執行任何安裝腳本**。同一個 Release 提供 `SHA256SUMS` 供核對下載完整性。若換電腦，複製整個解壓資料夾；要更新時另下載新版並解壓到新資料夾。

開啟後網址會以 `file://` 開頭，時鐘使用隨資料夾附帶的顯示檔案，不需網路。頁腳若顯示「離線開啟需要支援的瀏覽器與 HTTPS」或「離線準備未完成」，指的是下方的**網站快取機制**，不影響這種本機檔案用法；以斷網重開的結果確認。

不要只另存「HTML 原始碼」、列印成 PDF 或截圖：單獨 HTML 缺少樣式與計時程式，PDF／圖片也不會繼續走時。

<a id="offline-cache"></a>

### 平板／瀏覽器：讓同一網址可以離線重開

1. 先保持網路連線，以一般瀏覽模式開啟 [GitHub 線上時鐘](https://kcayut.github.io/webclock/)，不要使用私密／無痕模式。
2. 要使用主畫面圖示時，先依[裝置指南](display-devices.md)加入主畫面，再**從該圖示重新開啟**。後續準備與測試都在同一個入口進行。
3. 等時鐘頁底部顯示 **「已可離線開啟」**。若仍顯示不支援或準備失敗，先不要斷線；更新瀏覽器或檢查連線後再試。
4. 關閉 Wi-Fi／行動網路，關閉時鐘分頁或網頁 App，再開啟同一個網址／圖示，確認仍可顯示並持續計時。**只讓原本分頁留著走時，不算通過離線重開測試。**

| 裝置 | 適用方式與限制 |
| --- | --- |
| Windows／Mac／Linux | 可用瀏覽器快取；要保留不依賴網站快取的副本，使用上面的 ZIP 檔案方式 |
| Android | 優先使用瀏覽器快取。ZIP 開本機 HTML 取決於瀏覽器與檔案管理器，若只看到預覽或 `--:--`，不代表已啟動時鐘；本頁不把它列為通用做法 |
| 較新 iOS／iPadOS | 必須在最終使用的 Safari 分頁或主畫面 App 準備快取並實測；不同入口不一定共用快取。把 ZIP／HTML 存進「檔案」App 不等於可在 Safari 執行離線時鐘 |
| iOS 9，包括 iPad mini 1 | Safari 沒有此快取機制。先在線載入後，頁面在前景可繼續計時；關閉、重開機或被系統回收後需重新連線，不能承諾飛航模式冷啟動 |

Safari 從 iOS 11.3 才加入 Service Worker 與 Cache API；這只是瀏覽器功能的起點，**不是 WebClock 全功能的最低支援版本或實機認證**。請以本機的準備結果與斷網重開測試為準。[WebKit 官方版本說明](https://webkit.org/blog/8216/new-webkit-features-in-safari-11-1/)

網站快取由瀏覽器管理，清除網站資料、儲存空間不足或系統回收後可能消失；之後需重新連線準備。加入主畫面、書籤或 Safari 閱讀列表本身，都不能代替上述檢查。下載與快取也不會自動防止螢幕休眠，仍需設定[全螢幕與恆亮](display-devices.md)。

以下快速指令用於**全新 Server 安裝**，預設安裝到目前位置的 `webclock` 子目錄；可加 `--dir /安裝路徑`。安裝器先查 GitHub 最新正式 Release，再固定使用該版本的程式與映像，不會安裝開發中的 `main`。要指定版本，加 `--version 1.1.0`。已安裝者請看[更新](#update)或[既有安裝啟用 managed](#enable-managed)。

<a id="bare-metal"></a>
## 1. Bare metal

前提：Debian／Ubuntu／Raspberry Pi OS、systemd、Bash 與 `curl`；一般使用者需可使用 `sudo`，root 可直接執行。缺少 curl 時先執行 `sudo apt-get update && sudo apt-get install -y curl`（root 去掉 `sudo`）。Git、Python 與虛擬環境由安裝器準備。

**一行安裝 self：**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh
```

腳本會取得正式版本、建立虛擬環境與 `.env`、檢查連接埠，再啟用開機自動執行的 `webclock` 服務。預設為繁體中文、連接埠 `5000`；完成網頁健康檢查後，才顯示時鐘與管理頁完整網址。通常開啟 `http://主機IP:5000/admin` 即可設定內容。

**需要帳號登入的 managed 安裝：**先準備與主機名稱相符、顯示裝置信任的憑證，使用[一次完成 HTTPS 的指令](#https)。管理員帳號為 `admin`，密碼互動輸入兩次，至少 12 字元，不放在指令或 `.env`；缺少 TLS 參數時不會先建立管理員或啟動無法登入的服務。

開發者已有原始碼時可直接執行 `bash setup.sh`；一般使用者使用上面正式 Release 入口。既有安裝請使用更新流程，避免把重新安裝當成更新。

<a id="docker"></a>
## 2. Docker

前提：Bash、`curl`、`tar`、已啟動的 Docker Engine／Docker Desktop，以及可執行 `docker compose` 的帳號。Docker 本身請依[官方安裝文件](https://docs.docker.com/engine/install/)安裝；WebClock 不會代替使用者安裝 Docker 或變更 Docker 權限。

**一行安裝 self：**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --docker
```

安裝器下載該正式 Release 的程式壓縮檔並核對 `SHA256SUMS`，再取得 `ghcr.io/kcayut/webclock:版本` 的預建映像，支援 amd64／arm64。主機不需 Git 或 Python，也不需自行建置映像。腳本建立缺少的 `.env`、舊提醒相容檔與資料目錄，啟動容器並通過健康檢查後提供完整網址。

self 預設開啟 `http://主機IP/admin`。若主機 `80` 已被占用，可在安裝前指定其他連接埠：

```bash
WEBCLOCK_HTTP_PORT=8080 bash /tmp/webclock-install.sh --docker
```

managed 安裝請加上 `--managed` 與[完整 TLS 參數](#https)。不要改容器內的 `PORT`；容器固定監聽 `5000`。已取原始碼且需要自行建置的開發者使用 `bash setup.sh --docker --build`。

資料保存在安裝目錄的 `webclock_state`，容器中是 `/app/webclock_state`；整個目錄都要保留／備份。模式切換前的完整副本另存 `.webclock-mode-backups-webclock_state`，Compose 已獨立掛載，重建容器仍保留。`manual_notes.json` 僅供舊提醒遷移，腳本不會覆寫既有內容。這些快速指令使用預設掛載；若自行改 `WEBCLOCK_STATE_DIR`／`NOTES_FILE` 或模式備份路徑，也必須修改 Compose 掛載及初始化指令，不能只改 `.env`。

若以前直接啟動 Compose，造成 `manual_notes.json` 被建立成空目錄，先停止容器，確認裡面沒有資料，再以 `rmdir manual_notes.json` 移除空目錄；保留任何非空內容，勿直接刪除。

<a id="home-assistant"></a>
## 3. Home Assistant

**HA OS 使用者：加入來源、安裝、啟動即可，不需要 SSH、Git 或手動複製 Server。** 適用 amd64／aarch64。HA Container／單獨 Core 請用前面的 bare metal／Docker 架設 Server，再安裝相同的整合與卡片。

> App 使用與 [GitHub 正式 Release](https://github.com/kcayut/webclock/releases/latest)一致的版本及公開 GHCR 映像。發行流程會先驗證映像與下載檔，再公開 Release；HA OS 商店、ARM 實機及搬家驗收另外記錄於[發行狀態](ha-release.md)。

1. **[將 WebClock 加入 HA App 商店](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fkcayut%2Fwebclock)**。首次使用按鈕時，輸入你自己的 HA 網址，再確認加入來源。
2. 在商店選 **WebClock → 安裝 → 啟動**，開啟「開機啟動」與「顯示於側邊欄」。
3. 按 **開啟網頁介面** 設定行事曆、提醒與群組。需要儀表板卡片，再[安裝整合](home-assistant.md#安裝整合)。

按鈕無法開啟時，在 HA 的 **設定 → Apps → App 商店 → 右上選單 → 儲存庫**，貼上 `https://github.com/kcayut/webclock`；儲存後「檢查更新」。舊版介面可能稱為「附加元件」。

- **管理頁：**經由 HA Ingress 的 `8099`，不對區網開放。新安裝使用 HA 登入；匯入 managed 備份後，還須使用原 WebClock 帳密登入。
- **外部時鐘：**需要時，在 App「網路」將 `8100/tcp` 對應至主機的 `8100`，開啟 `http://HA主機IP:8100`，用管理頁產生的六碼加入。此入口不提供管理頁。
- **HA 儀表板：**再安裝[自訂整合](home-assistant.md#安裝整合)。App 啟動後，在「日誌」複製 `Home Assistant integration URL:` 後面的網址，填入整合的 Server 欄位；同機連線不必開放主機連接埠。
- **資料：**保存在 App 的 `/data`；HA 冷備份保存整個 App，管理頁完整備份則用於跨主機搬家，可選擇是否加密。

**從 bare metal／Docker 搬進 App，只需一個完整備份檔：**

1. 舊 Server「備份與還原」預設以至少 12 字元的密碼加密；不需加密時取消「以密碼加密（建議）」，下載 `.webclock` 檔。
2. 新 App「開啟網頁介面」→「備份與還原」，選檔，加密檔才須輸入備份密碼，再預覽資料數量。
3. 停止舊 Server，確認是最後匯出的檔案，再確認取代並還原。managed 使用原 WebClock 帳密登入，所有帳號及私人行事曆一併保留。

未加密檔內的私人 iCal、帳號與授權資料可被持有者直接讀取；管理員驗證仍保留。全新目標保留裝置與程式憑證；已有資料的目標會撤銷兩者，須重新加入／建立。原瀏覽器裝置要接續，須沿用相同 HTTPS 網域、協定與連接埠；備份不設定 TLS／DNS、不搬移瀏覽器本機資料，也不覆寫 App options。範圍與失敗復原見[完整備份指南](guide.md#完整備份與搬家)。

App 支援匯入 managed 備份，HA 登入不會替代原 WebClock 帳號。新 App 仍預設 self，不提供 `/mode` 切換或首次 managed 啟用；不要自行修改 `/data/auth.json`。HA 專用顯示通道維持管理路徑隔離與逐台憑證檢查，普通 bare metal／Docker 的 managed HTTPS 要求不變。

<details>
<summary>開發測試／尚未發布的版本：本機建置</summary>

從可讀寫 `/addons` 的 Terminal／SSH App 執行，需有 Git 與 Bash：

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash scripts/prepare_ha_app.sh
```

接著在 App 商店「檢查更新」→ **Local apps → WebClock → 安裝 → 啟動**。腳本只準備檔案，不會啟動 Server；會移除產物的 `image` 設定，讓 HA 自行建置。

也可在另一台電腦的專案根目錄執行 `bash scripts/prepare_ha_app.sh /tmp/webclock-ha-app`，再透過 Samba 把產物複製為 HA 的 `addons/webclock`。目的地已存在時會停止，不會覆蓋。Local App 和商店 App 是不同安裝，資料不會自動搬移；可用上述完整備份搬到新 App，確認新 App 正常後才退役舊安裝。只更新既有 Local App 者依下方本機更新流程操作。

</details>

發行與驗收狀態見 [HA 發行說明](ha-release.md)。官方依據：[App 來源](https://developers.home-assistant.io/docs/apps/repository/)、[預建映像](https://developers.home-assistant.io/docs/apps/publishing/)與[本機建置](https://developers.home-assistant.io/docs/apps/testing/)。

<a id="https"></a>
## managed 必要的 HTTPS 設定

自行架設的 managed 管理員登入與裝置加入／同步都拒絕 HTTP；HA App 使用經驗證的 Ingress 管理入口與獨立裝置通道。新安裝可把已有的憑證一起交給安裝器，驗證 HTTPS 成功後才完成安裝；**不會代為申請網域、取得憑證或讓裝置信任自簽憑證**。

先讓 `clock.example` 指向你的主機，換成實際名稱，準備名稱相符且所有顯示裝置信任的憑證與私鑰：

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

使用憑證對應的名稱開啟 `https://你的主機名稱:5000/admin`。兩個欄位必須同時設定；檔案無效或不完整時啟動失敗，不會悄悄退回 HTTP。

**Docker：**把憑證及私鑰放在安裝目錄的 `tls/fullchain.pem`、`tls/privkey.pem`，在 `.env` 設定：

```dotenv
WEBCLOCK_HTTP_PORT=443
WEBCLOCK_TLS_CERT=/app/tls/fullchain.pem
WEBCLOCK_TLS_KEY=/app/tls/privkey.pem
```

```bash
docker compose up -d --force-recreate
```

開啟 `https://你的主機名稱/admin`。`tls/` 唯讀掛載至容器，已排除 Git 與映像建置；請另行安全保存憑證，主機完整資料備份不包含這個目錄。憑證更新後重啟服務／容器。

若前方已有反向代理，可轉送至上述 HTTPS 入口，並保留原本的 Host。WebClock 不會因任意 `X-Forwarded-Proto` 標頭就信任請求是 HTTPS；只在代理端終止 TLS、後端仍用 HTTP，無法通過目前 managed 的 HTTPS 檢查。

<a id="enable-managed"></a>
## 既有 self 安裝啟用 managed

不要重新執行全新安裝指令。先配置上述 HTTPS、停止所有寫入者，並依[完整備份流程](guide.md#主機端完整資料備份與還原)保存現有資料。舊資料會保留，但舊顯示裝置須用六碼重新加入。

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

初始化失敗時保持停止，先排除問題。首次登入 `/admin` 後，前往「裝置」建立群組、指派內容、產生六位加入碼；在每台時鐘首頁選「加入顯示群組」。完整操作見[群組設定與裝置加入](guide.md#群組設定與裝置加入)。

<a id="web-setup"></a>
## 用一次性設定碼建立第一位管理員

要在網頁輸入第一位管理員的帳密，可先在主機發出設定碼。已有管理員時不能再發碼或重新綁定；改用[密碼復原](#account-recovery)。先完成 HTTPS、停止寫入並建立完整備份，再選擇下列指令。

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

開啟 `https://你的主機名稱/setup`，貼上終端機顯示的設定碼，輸入帳號與至少 12 字元的密碼。成功後進入 managed，再到 `/login` 登入。設定碼預設 10 分鐘到期、只可使用一次；主機可加 `--expires-in 300` 改為 5 分鐘，有效範圍為 1 至 3600 秒。重新發碼會使前一個碼失效；碼不由匿名 API 發放，請勿貼到公開訊息或日誌。

<a id="mode-switch"></a>
## 雙向切換與主要使用者

已有管理員後，以 HTTPS 開啟 `/mode`。managed 下須以 admin 登入；self 下日常管理仍免登入，但切換時必須輸入既有 admin 的帳密。

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

自訂資料位置須另外傳 `--state-dir`／`--notes-file`，保持原包含關係；Docker 先停容器，使用已安裝相依套件的主機 Python 與主機掛載路徑執行。完整步驟見[主機備份與還原](guide.md#主機端完整資料備份與還原)。

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

## 其他設定與手動執行

行事曆網址、顯示語言、亮度、鬧鐘與群組都在管理頁設定。管理側欄的語言只改目前瀏覽器的管理介面；「全體預設顯示語言」才會改時鐘的預設語言。

需在安裝前自訂設定時，先 `cp .env.example .env` 再編輯；安裝腳本保留已有 `.env`。Linux 連接埠用 `PORT`，Docker 主機連接埠用 `WEBCLOCK_HTTP_PORT`，初始時鐘語言用 `WEBCLOCK_LANGUAGE=zh-TW`／`en`／`ja`。

不使用 systemd 或 Docker 的開發／測試環境，可在專案根目錄手動執行：

```bash
python3 -m venv venv && ./venv/bin/python -m pip install -r requirements.txt && ./venv/bin/python app.py
```

這個方式在前景執行，關閉終端機便停止，不會自動設定開機啟動。預設 self；若要 managed，先停止程式，使用同一個 `venv/bin/python scripts/manage_auth.py ... --enable-managed` 流程及 HTTPS 設定。

<a id="update"></a>
## 更新與確認

| 環境 | 更新／確認 |
| --- | --- |
| Bare metal（HTTP／HTTPS） | 網頁端於「更新」頁面（`/updates`）點擊一鍵升級；或在安裝目錄執行 `sudo bash update_clock.sh && [ -f scripts/enable_updates.sh ] && sudo bash scripts/enable_updates.sh`（首次從 v1.1.0 升級時會一併啟用背景更新服務；亦可執行[新版獨立入口](installation.md#portable-updater) `sudo bash portable_update_clock.sh`）。正式版安裝自動選最新正式 Release；`systemctl status webclock` 查看服務 |
| Docker | 備份後在 `.env` 將 `WEBCLOCK_VERSION` 改為[最新 Release](https://github.com/kcayut/webclock/releases/latest)的 `X.Y.Z`，執行 `docker compose pull && docker compose up -d --no-build`，再確認 `/api/health` 的版本 |
| HA 商店 App | HA 顯示新版後，在 App 頁先建立備份，再按「更新」；不要移除 App |
| HA 本機 App | 先做 HA 備份；用新版原始碼產生至新的暫存目錄，核對後替換 `/addons/webclock` 的程式檔，再於 App 頁重建／啟動；不要移除 App 或 `/data` |

### Bare Metal 自動升級與發行管道

Bare metal 安裝由獨立的背景服務 `webclock-updater.service` 定期檢查 GitHub Releases，支援自動無人值守升級或由受管模式管理員在「更新」（`/updates`）頁面手動一鍵升級：

- **自動升級與自我維護**：`webclock-updater.service` 預設啟用，每日檢查一次版本。若開啟自動升級，偵測到新版本時會自動建立備份、升級程式與套件、重啟並執行健康檢查；升級成功後更新服務會自動重新載入使用新版代碼，無須人工額外維護更新器。若升級檢查或健康檢查失敗，會自動復原先前版本並暫停自動升級，避免反覆失敗重試。
- **發行管道（Release Channels）**：
  - **正式版（`stable`，建議）**：僅安裝正式發布的 Release，忽略預先發行版（prerelease）。
  - **測試版（`beta`）**：可接收正式版與 `-beta.N` 等測試版 Release。若從測試版切換回正式版，系統不會自動降級，而是保留目前版本並等待版本號更高的正式發布版。
- **手動切換管道或更新**：
  - 網頁介面：受管模式管理員在「更新」分頁可直接切換 Release 管道與設定自動升級。
  - 命令列：在安裝目錄執行 `sudo bash update_clock.sh --channel stable && [ -f scripts/enable_updates.sh ] && sudo bash scripts/enable_updates.sh` 或 `sudo bash update_clock.sh --channel beta && [ -f scripts/enable_updates.sh ] && sudo bash scripts/enable_updates.sh`，亦會同步更新 Git 配置與背景服務管道。

正式版 Linux 安裝以 Git 的 `webclock.releaseChannel=stable` 記錄更新來源；更新器從 GitHub 解析正式 Release，再固定更新至該 tag。既有開發 checkout 保留原本 upstream，不會被安裝器悄悄改成別的來源。Docker 固定 `.env` 中的版本，不因容器重啟自動更新；更新前先備份資料。

原生 HTTPS 同樣可用安全更新器。若憑證只包含網域名稱，在 `.env` 加上 `WEBCLOCK_UPDATE_HOST=clock.example`，換成憑證上的名稱；使用私有 CA 時另設 `WEBCLOCK_UPDATE_CA=/絕對路徑/ca.pem`。更新器仍連本機服務位址，只用該名稱驗證 TLS；不會略過憑證驗證或跟隨重新導向。憑證已包含本機檢查 IP 時無須加主機名。更新前、更新後及失敗還原都使用相同設定；不要為更新刪除授權資料或切回 self。

舊版更新器若顯示「Native HTTPS is not supported」，先備份並使用新版的[獨立更新入口](guide.md#更新程式)：將入口存到安裝目錄外，從已 fetch 的上游載入新版更新器。不要直接覆蓋安裝目錄中的更新器，或先 `git pull` 改動整套程式；安全更新需要保留原版本供失敗還原。

開啟 `/api/health` 可確認 `version`、服務與授權模式；managed 安裝應回報 `deployment_mode: managed`。HA App 新安裝為 self；匯入 managed 備份後應回報 managed，管理入口仍經 HA Ingress 並要求原 WebClock 登入。程序啟動不代表容器、Raspberry Pi、HA OS 或 iPad mini 1／iOS 9 已完成實機驗收。
