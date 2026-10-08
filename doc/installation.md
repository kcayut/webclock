# 安裝 WebClock

[回到 README](../README.md) · [使用指南](guide.md) · [裝置顯示設定](display-devices.md) · [Home Assistant 卡片與整合](home-assistant.md)

**只看時間，不用安裝 Server：**直接開啟 [GitHub 線上時鐘](https://kcayut.github.io/webclock/)，或照下方[下載與離線使用](#no-server)操作。需要行事曆、提醒與管理功能，再選擇自架方式與授權模式。

安裝完成後，要讓平板／電腦點圖示就顯示時鐘，請照[裝置顯示設定](display-devices.md)建立主畫面入口、開啟全螢幕與螢幕恆亮；包含 iPad mini 1／iOS 9。

## 一眼選擇

| 安裝方式 | 適合環境 | 安裝入口（取得專案後執行） | 預設入口 |
| --- | --- | --- | --- |
| [免 Server：線上／離線時鐘](#no-server) | 只想看時間的平板或電腦 | 開啟網頁；電腦也可下載 ZIP 後直接使用 | [GitHub 線上時鐘](https://kcayut.github.io/webclock/) |
| [Bare metal](#bare-metal)：直接安裝 | Raspberry Pi OS、Debian、Ubuntu，使用 systemd | `bash setup.sh` | `http://主機IP:5000` |
| [Docker](#docker) | 已安裝 Docker Compose 的電腦、NAS、Linux | `bash setup.sh --docker` | `http://主機IP` |
| [Home Assistant](#home-assistant) | 有 App 商店的 HA OS，amd64／aarch64 | `bash scripts/prepare_ha_app.sh`，再到 App 商店安裝 | HA 側邊欄／開啟網頁介面 |

以下授權模式只適用自行架設；公開版與下載的靜態時鐘不需選擇 self／managed。

| 模式 | 如何啟用 | 管理與顯示方式 |
| --- | --- | --- |
| **self（自用，預設）** | 一般安裝即可，不加參數 | 可信任區網內直接開啟 `/admin`；不要求 WebClock 管理員登入 |
| **managed（受管）** | 全新 Linux／Docker 安裝加 `--managed`，並[設定 HTTPS](#https) | 管理員登入後管理；每台顯示端用六碼加入群組，取得自己的授權 |
| **Home Assistant App** | 安裝後從 HA 開啟 | WebClock 保持 self，由 HA 登入與 Ingress 保護管理入口；區網顯示仍須六碼加入，與 WebClock managed 模式不同 |

模式保存在私人資料目錄的 `auth.json`，**不是 `.env` 中的開關**。一般安裝與更新不會把既有 managed 改回 self，也不要刪除 `auth.json`／`auth-required` 來切換模式。self 的管理頁不適合直接開放至 Internet。

<a id="no-server"></a>

## 免安裝：GitHub 線上時鐘與離線使用

**[直接開啟 WebClock →](https://kcayut.github.io/webclock/)**　**[下載離線使用的 ZIP →](https://github.com/kcayut/webclock/archive/refs/heads/main.zip)**

公開時鐘只顯示**時間、日期與星期**，使用裝置本身的時間與時區，不向 WebClock Server 校時；離線時仍依靠裝置時鐘。先確認系統時間正確即可，不需 GitHub 帳號、Python、Docker 或 WebClock 管理員帳號。這個版本不提供自架版的行事曆、提醒、鬧鐘或群組管理。

| 想怎麼使用 | 選這個方式 |
| --- | --- |
| 有網路，開了就看時間 | 直接開啟上面的 GitHub 網址 |
| 電腦要保存一份，關掉後也能斷網重開 | [下載 ZIP，解壓縮後開啟檔案](#offline-download) |
| 平板想從原本網址／主畫面圖示離線開啟 | [先連線準備瀏覽器快取](#offline-cache)，再做斷網重開檢查 |
| iPad mini 1／iOS 9 | 先連線載入並保持前景；不支援下面的快取重開方式 |

<a id="offline-download"></a>

### 電腦：下載後直接開啟，不用架 Server

1. 點[下載 ZIP](https://github.com/kcayut/webclock/archive/refs/heads/main.zip)。也可到 [GitHub 專案](https://github.com/kcayut/webclock)，選 **Code → Download ZIP**。
2. **先解壓縮整個 ZIP**：Windows 按右鍵選「解壓縮全部」，Mac 雙擊 ZIP，Linux 使用系統壓縮檔工具。不要直接在壓縮檔預覽裡開 HTML。
3. 打開解壓後的 `webclock-main` 資料夾，用 Chrome、Edge、Firefox 或電腦版 Safari 開啟**最外層的 `index.html`**。通常雙擊即可；若被文字編輯器開啟，改用右鍵「開啟方式」選瀏覽器。不要開 `templates/index.html`。
4. **保留整個資料夾**，尤其是同一層的 `static`；不能只把 `index.html` 單獨移到桌面。想快速開啟時，替它建立桌面捷徑／替身即可。
5. 中斷網路，關閉時鐘分頁，再從該檔案重新開啟，確認時間與日期出現；接著依[裝置指南](display-devices.md)設定全螢幕與恆亮。

下載步驟依據 [GitHub 原始碼 ZIP 說明](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)。ZIP 內也包含 Server 程式，但使用這個靜態時鐘**不用執行任何安裝腳本**。若換電腦，複製整個解壓資料夾；要更新時另下載新版並解壓到新資料夾。

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

以下快速指令用於**全新 Server 安裝**，請在沒有 `webclock` 子目錄的位置執行。已安裝者請看[更新](#update)或[既有安裝啟用 managed](#enable-managed)。

<a id="bare-metal"></a>
## 1. Bare metal

前提：Debian／Ubuntu／Raspberry Pi OS、systemd、Git；一般使用者需可使用 `sudo`，root 可直接執行。缺少 Git 時先安裝：`sudo apt-get update && sudo apt-get install -y git`（root 去掉 `sudo`）。

**一行安裝 self：**

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash setup.sh
```

腳本會安裝 Python 相依套件、建立虛擬環境與 `.env`，並啟用開機自動執行的 `webclock` 服務。不再詢問行事曆網址、語言或連接埠；預設為繁體中文、連接埠 `5000`，完成後開啟 `http://主機IP:5000/admin` 設定內容。

**一行安裝並初始化 managed：**

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash setup.sh --managed
```

管理員帳號為 `admin`，密碼互動輸入兩次，至少 12 字元，不會寫入指令或 `.env`。接著完成下方 [HTTPS 設定](#https)並重啟服務，才能登入與加入裝置。初始化失敗不會啟動新服務。

已取得原始碼者直接執行 `bash setup.sh` 或 `bash setup.sh --managed` 即可。腳本遇到已存在的 systemd 服務會停止，避免把更新當成重新安裝。

<a id="docker"></a>
## 2. Docker

前提：Git、已啟動的 Docker Engine／Docker Desktop，以及可執行 `docker compose` 的帳號。Docker 本身請依[官方安裝文件](https://docs.docker.com/engine/install/)安裝。

**一行安裝 self：**

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash setup.sh --docker
```

**一行安裝並初始化 managed：**

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash setup.sh --docker --managed
```

腳本會建立缺少的 `.env`、舊提醒相容檔及資料目錄，再建置和啟動容器；不需手動 `touch`、`mkdir` 或安裝主機 Python。managed 先互動設定 `admin` 密碼，成功後才啟動容器；仍須完成 [HTTPS 設定](#https)才能登入。

self 預設開啟 `http://主機IP/admin`。若主機 `80` 已被占用，可在安裝前加環境變數：

```bash
WEBCLOCK_HTTP_PORT=8080 bash setup.sh --docker
```

要讓後續重建也使用相同連接埠，請在 `.env` 儲存 `WEBCLOCK_HTTP_PORT=8080`。不要改容器內的 `PORT`；容器固定監聽 `5000`。

資料保存在主機的 `./webclock_state`，容器中是 `/app/webclock_state`；整個目錄都要保留／備份。`./manual_notes.json` 僅供舊提醒遷移，腳本不會覆寫既有內容。這些快速指令使用預設掛載；若自行改 `WEBCLOCK_STATE_DIR`／`NOTES_FILE`，也必須修改 Compose 掛載及初始化指令，不能只改 `.env`。

若以前直接啟動 Compose，造成 `manual_notes.json` 被建立成空目錄，先停止容器，確認裡面沒有資料，再以 `rmdir manual_notes.json` 移除空目錄；保留任何非空內容，勿直接刪除。

<a id="home-assistant"></a>
## 3. Home Assistant

**目前提供本機 App 建置流程；加入 GitHub 儲存庫後的預建映像安裝尚未驗證。** 專案的 App 設定仍指向預建映像；此流程會準備完整原始碼並移除本機設定中的 `image`，由 HA 在自己的主機上建置，不依賴該映像先發布。

前提：有 App 商店的 HA OS、amd64 或 aarch64。從可讀寫 `/addons` 的 Terminal／SSH App 執行，需有 Git 與 Bash。HA Container／單獨 Core 沒有 App 商店，請用前面的 bare metal／Docker 架設 Server，再安裝[自訂整合](home-assistant.md#安裝整合)。

**一行準備 App：**

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash scripts/prepare_ha_app.sh
```

接著在 HA：**設定 → Apps → App 商店 → 右上選單「檢查更新」→ Local apps → WebClock → 安裝 → 啟動 → 開啟網頁介面**。舊版介面可能稱為「附加元件」。這裡仍需 HA 商店完成安裝；準備指令本身不會啟動 Server。

無法使用 SSH 時，可在另一台有 Bash 的電腦、專案根目錄執行 `bash scripts/prepare_ha_app.sh /tmp/webclock-ha-app`，再透過 Samba 把產物資料夾複製為 HA 的 `addons/webclock`。目的地已存在時腳本會停止，不會覆蓋。

- **管理頁：**經由 HA Ingress 的 `8099`，不對區網開放。直接使用 HA 登入，不需另建 WebClock 管理員。
- **外部時鐘：**需要時，在 App「網路」將 `8100/tcp` 對應至主機的 `8100`，開啟 `http://HA主機IP:8100`，用管理頁產生的六碼加入。此入口不提供管理頁。
- **HA 儀表板：**App 與自訂整合是兩個步驟；需要時間／行事曆／鬧鐘卡片，再安裝[自訂整合](home-assistant.md#安裝整合)，Server 填 `http://webclock:8100`。
- **資料：**保存在 App 的 `/data`，由 HA 冷備份保存。

**App 目前不提供 WebClock managed 的啟用選項。** 它使用「HA 登入 + Ingress 管理 + 個別裝置加入」流程；不要在 App 內直接執行 `--enable-managed`，否則 HTTP 裝置通道與 Ingress 的登入流程不符合 managed 的 HTTPS 要求。需要 WebClock 獨立管理員登入時，使用 bare metal／Docker managed + HTTPS，HA 自訂整合連到該 HTTPS Server。

本機 App 流程依據 [HA 官方安裝教學](https://developers.home-assistant.io/docs/apps/tutorial/)與[本機建置說明](https://developers.home-assistant.io/docs/apps/testing/)。App 實際建置、HA OS 安裝與實機驗收仍需在目標主機確認。

<a id="https"></a>
## managed 必要的 HTTPS 設定

managed 的管理員登入與裝置加入／同步都拒絕 HTTP。`--managed` 只建立授權資料，**不會申請網域、取得憑證或自動設定 HTTPS**。

最直接的方式是讓 WebClock 自己使用已有的憑證。請準備與使用網址相符、且所有顯示裝置信任的憑證與私鑰；自簽憑證需先在各裝置信任，不能靠略過驗證代替。

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
| Bare metal（HTTP） | 安裝目錄執行 `sudo bash update_clock.sh`；`systemctl status webclock` 查看服務 |
| Docker | 備份後取得新版原始碼，再 `docker compose up -d --build`；`docker compose logs --tail=50` 查看啟動結果 |
| HA 本機 App | 先做 HA 備份；用新版原始碼產生至新的暫存目錄，核對後替換 `/addons/webclock` 的程式檔，再於 App 頁重建／啟動；不要移除 App 或 `/data` |

目前 Linux 安全更新器的健康檢查只支援 HTTP；原生 HTTPS 安裝不適用這個一行更新指令，需另外安排停止服務、完整備份、程式與相依套件更新、啟動及 HTTPS 驗證，保留可還原版本。不要為更新刪除授權資料或切回 self。

開啟 `/api/health` 可確認服務與授權模式；managed 安裝應回報 `deployment_mode: managed`。HA App 的儲存模式仍是 self，管理入口由 HA 保護。程序啟動不代表容器、Raspberry Pi、HA OS 或 iPad mini 1／iOS 9 已完成實機驗收。
