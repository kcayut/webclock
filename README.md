# WebClock

**[開啟線上時鐘 / Open the clock](https://kcayut.github.io/webclock/)** · [自行架設 / Self-hosting](#self-hosting)

WebClock is a simple web clock for an iPad or wall-mounted screen. The public static version shows the device's own time, timezone, date, and weekday without an account or server setup. The self-hosted Flask version adds Google Calendar iCal events, manual reminders, holiday highlighting, brightness/black-screen controls, timezone selection, and UI language selection.

The public page uses 繁體中文. Self-hosted UI languages: English, 繁體中文, 简体中文, 日本語; default: 繁體中文.

The online link becomes available after the maintainer enables [GitHub Pages publishing](#github-pages).

<a id="github-pages"></a>

## GitHub Pages 發布與本機預覽

1. 將本次變更推送至 `kcayut/webclock` 的 `main` 分支。
2. 在 GitHub 儲存庫 **Settings → Pages → Build and deployment → Source** 選擇 **GitHub Actions**。
3. 在 **Actions → Deploy public clock to GitHub Pages → Run workflow** 執行首次發布。之後 `main` 的公開網頁資源有變更時會自動發布。
4. 發布成功後開啟 `https://kcayut.github.io/webclock/`。

發布流程僅複製 `index.html`、`static/clock.css`、`static/clock.js`。Python、`.env`、行事曆、提醒及設定檔皆不會放入 Pages 網站；GitHub 儲存庫本身也不應提交私人資料。公開版與自架版共用 `static/clock.css` 和 `static/clock.js`，自架入口仍是 `templates/index.html`。

本機預覽公開版時，只提供這三個公開檔案，避免把整份 server 專案暴露給瀏覽器：

```bash
preview_dir=$(mktemp -d)
mkdir -p "$preview_dir/static"
cp index.html "$preview_dir/"
cp static/clock.css static/clock.js "$preview_dir/static/"
python3 -m http.server 8000 --bind 127.0.0.1 --directory "$preview_dir"
```

開啟 `http://127.0.0.1:8000/`，按 `Ctrl+C` 結束預覽。驗證共用時鐘邏輯：`node tests/test_clock.js`；驗證自架版：`venv/bin/python -m unittest discover -s tests`。Node.js 只用於開發檢查，不是自架版執行需求。

## 繁體中文

### 最簡單使用方式：只用 iPad，不架 Docker、不架伺服器

直接開啟 [公開時鐘](https://kcayut.github.io/webclock/)，即顯示裝置目前的時間與時區。公開版不讀取行事曆、不使用外部校時、不連接自架 server，也不讀寫瀏覽器設定。裝置時間是否準確取決於裝置本身。需要行事曆或管理功能時，請使用[自行架設版](#self-hosting)的網址。

1. 在 iPad 打開 Safari，進入 WebClock 網址。
2. 點 Safari 分享按鈕，選「加入主畫面」。
3. 回到主畫面，點剛加入的 WebClock 圖示。它會用接近全螢幕的方式開啟。
4. 到 iPad「設定」>「螢幕顯示與亮度」>「自動鎖定」，選「永不」。如果你的 iPad 沒有「永不」，可改用「引導使用模式」限制畫面停留在 WebClock。
5. 想用快捷鍵快速開啟：打開「捷徑」App，新增捷徑，加入「打開 URL」動作，填入 WebClock 網址，再加入「設定亮度」動作，例如 80%，儲存後放到主畫面或小工具。
6. **僅自行架設版**提供 `/admin`，例如 `https://your-clock.example.com/admin`。可在後台調整亮度、黑畫面、時區、語言和手動提醒。

公開版首次載入與重新開啟需要網路；目前未提供 PWA 離線快取，加入主畫面不代表能離線重新開啟。下載原始碼後，也可用支援本機網頁的瀏覽器開啟根目錄 `index.html`，並保留旁邊的 `static/` 資料夾。自行架設完整版才需要電腦、NAS、Raspberry Pi 或其他主機執行 Flask。

### 離線備援模式

以下適用於自行架設的 Flask 版：時鐘頁面載入後，如果本機伺服器無法連線，頁面仍可繼續運作。這個備援模式會使用本機儲存的顯示設定、可用的時間基準及瀏覽器本機提醒。Google Calendar 事件與伺服器端 `manual_notes.json` 提醒會在伺服器重新連線後恢復。

### 提醒顯示區間

在 `/admin` 新增提醒時，可選擇「指定日期時間」（可跨日）或「每天固定時段」（例如每天 09:00 到 18:00），再填寫「開始顯示」與「結束顯示」。每天模式支援跨午夜，例如 22:00 到隔天 06:00；開始與結束不可相同。既有提醒可在列表展開「設定顯示區間」修改；兩欄同時清空即可取消限制。

區間使用後台的時區設定（預設 UTC+8），開始時間包含在內、結束時間不包含；正常連線時，畫面會在下一次更新（約 5 秒內）反映。設定區間後會取代原本的日期顯示限制，原有時間仍作為提醒標籤。未設定區間的舊資料維持原行為：有日期只在當天顯示，無日期則持續顯示。到期只隱藏，不刪除。

資料仍存於原本的 `manual_notes.json`，不需要搬移或重新部署服務設定。此功能適用後台手動提醒，不影響 Google Calendar 與瀏覽器離線提醒。

驗證提醒邏輯：`venv/bin/python -m unittest discover -s tests`。

使用時鐘畫面右下角的小按鈕，可以設定伺服器 URL 並重新嘗試連線。

<a id="self-hosting"></a>

### 自行架設：行事曆與完整功能

自行架設版保留既有 `/admin`、`/api/status`、設定與提醒儲存方式。可選 Docker 或下方的 Linux 安裝腳本；私人 iCal 網址只放在自己的 `.env` 中。

### Docker 執行

1. 複製環境設定：

```bash
cp .env.example .env
```

2. 編輯 `.env`。如果要讀 Google Calendar，把私人 iCal 網址填到 `ICAL_URL=` 後面；不需要日曆就留空。

3. 啟動：

```bash
docker compose up -d
```

舊版 Docker Compose 可用：

```bash
docker-compose up -d
```

4. 打開 `http://你的主機IP/`。後台是 `http://你的主機IP/admin`。

預設設定：容器內 Flask 使用 `5000` port，`docker-compose.yml` 對外映射到主機 `80` port。手動提醒存在 `manual_notes.json`，已透過 volume 保存到主機。

### 自架伺服器 / 腳本部署

適合 Raspberry Pi、Ubuntu、Debian 或其他 Linux 主機。

1. 安裝 Git 和 Python 3。
2. 下載專案：

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
```

3. 複製設定檔：

```bash
cp .env.example .env
```

4. 編輯 `.env`：

```env
ICAL_URL=
PORT=5000
HOST=0.0.0.0
```

5. 使用安裝腳本：

```bash
sudo bash setup.sh
```

腳本會建立 Python 虛擬環境、安裝套件、設定 `.env`，並建立 systemd 服務。完成後可用瀏覽器打開 `http://你的主機IP:5000/`，或依腳本/systemd 設定使用對外 port。

手動執行方式：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

更新程式：

```bash
sudo bash update_clock.sh
```

新版更新器會核對 systemd 與執行中程式的資料夾、虛擬環境，保留原有 port、`.env`、提醒資料及 service 設定。Git 安裝只接受乾淨工作目錄與 fast-forward 更新，Git 操作使用儲存庫擁有者的帳號。更新期間服務會短暫停止；開始前請保留足夠空間備份整個 `venv/`。

亮度、黑畫面、時區、語言現在保存於 `webclock_state/settings.json`，重啟後會還原。安裝與更新腳本會建立可供服務帳號寫入的目錄；Docker Compose 也會保存此目錄。檔案損壞時會報錯，不會默默覆寫成預設值。

更新器會備份套件環境與資料，並在更新後檢查套件相依性及 HTTP 狀態，連續確認同一個服務程序與設定正常才顯示成功。一般更新失敗會嘗試恢復原 Git 版本、套件環境與服務設定，失敗的更新會保留 `.webclock-update-*` 備份並以非零狀態結束。若自動復原也失敗，會顯示錯誤及備份路徑。突然斷電或強制終止程序仍須人工檢查。

只有複製資料夾、沒有 Git 的安裝會略過下載；可復原套件環境，但無法找回執行更新前就已被手動覆蓋的舊程式碼。覆蓋檔案前請先備份整個原資料夾，保留 `.env`、`manual_notes.json`、`webclock_state/` 和 `venv/`。

#### 第一次從舊版更新器升級

舊版設定只存在記憶體，請保持原服務執行，先在原安裝資料夾取得新版更新器，再由它完整執行更新。不要先執行舊版 `update_clock.sh` 或重新跑 `setup.sh`。以下命令適用追蹤 `origin/main` 的 Git 安裝，且需等這次修正已推送至遠端後使用：

```bash
git fetch origin
updater_file="$(mktemp /tmp/webclock-updater.XXXXXX)"
git show origin/main:update_clock.py > "$updater_file" &&
    sudo python3 "$updater_file" "$PWD"
```

這會在停止舊服務前讀取目前的設定並保存。若服務已經停止或重啟，先前只在記憶體中的設定無法事後找回，需先重新設定。首次升級完成後，日常更新仍使用 `sudo bash update_clock.sh`，不用重新安裝。

測試：`venv/bin/python -m unittest discover -s tests`。更新測試使用暫存 Git 儲存庫與模擬服務／套件安裝，不會操作已部署的服務。

## English

### Easiest iPad-only use, no Docker and no server setup

Open the [public clock](https://kcayut.github.io/webclock/) to see your device time and timezone. It does not connect to a backend, fetch external time, or read/write browser settings. For calendar and management features, use your own [self-hosted URL](#self-hosting).

1. Open the WebClock URL in Safari on the iPad.
2. Tap Share, then Add to Home Screen.
3. Open WebClock from the Home Screen icon for a near full-screen experience.
4. Go to iPad Settings > Display & Brightness > Auto-Lock, then choose Never. If Never is unavailable, use Guided Access to keep the iPad on WebClock.
5. To make a shortcut, open the Shortcuts app, create a shortcut with Open URL, enter the WebClock URL, optionally add Set Brightness, then save it to the Home Screen or a widget.
6. **Self-hosted version only:** admin settings are at `/admin`, for example `https://your-clock.example.com/admin`.

Opening or reopening the public website requires network access; this version does not include PWA offline caching. Adding it to the Home Screen does not guarantee offline reopening. A downloaded copy of root `index.html` also works in browsers that support local pages; keep its `static/` folder alongside it. The full Flask version requires a host.

### Offline fallback mode

The following applies to the self-hosted Flask version: After the clock page has loaded, it can keep running if the local server becomes unavailable. In that fallback mode it uses the available time reference, locally saved display settings, and browser-local reminders. Google Calendar events and server-side `manual_notes.json` reminders are restored after the server reconnects.

Use the small button in the bottom-right corner of the clock screen to set the server URL and retry the connection.

### Docker

```bash
cp .env.example .env
# Edit .env and set ICAL_URL if you want Google Calendar events.
docker compose up -d
```

Open `http://your-host-ip/`. Admin is `http://your-host-ip/admin`.

By default, Docker maps host port `80` to container port `5000`. Manual notes are persisted through `manual_notes.json`.

### Self-hosted Linux deployment

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
sudo bash setup.sh
```

Manual run:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Update:

```bash
sudo bash update_clock.sh
```

## 简体中文

### 最简单使用方式：只用 iPad，不架 Docker、不架服务器

直接打开[公开时钟](https://kcayut.github.io/webclock/)，即可显示设备时间与时区。公开版不连接后台、不使用外部校时，也不读写浏览器设置。需要日历和管理功能时，请使用[自架版](#self-hosting)网址。

1. 在 iPad 用 Safari 打开 WebClock 网址。
2. 点分享按钮，选择「添加到主屏幕」。
3. 从主屏幕打开 WebClock，它会以接近全屏的方式运行。
4. 到 iPad「设置」>「显示与亮度」>「自动锁定」，选择「永不」。如果没有「永不」，可使用「引导式访问」让画面停留在 WebClock。
5. 想用快捷指令快速打开：打开「快捷指令」App，新增「打开 URL」，填入 WebClock 网址，可再加入「设置亮度」，然后保存到主屏幕或小组件。
6. **仅自架版**提供 `/admin` 后台，例如 `https://your-clock.example.com/admin`。

公开网站首次加载和重新打开需要网络；当前没有 PWA 离线缓存，添加到主屏幕不代表能离线重新打开。下载后可用支持本地网页的浏览器打开根目录 `index.html`，并保留旁边的 `static/` 文件夹。完整版才需要主机运行 Flask。

### 离线备用模式

以下适用于自架 Flask 版：时钟页面载入后，如果本地服务器无法连接，页面仍可继续运行。这个备用模式会使用可用的时间基准、本地保存的显示设置，以及浏览器本地提醒。Google Calendar 事件和服务器端 `manual_notes.json` 提醒会在服务器重新连接后恢复。

使用时钟画面右下角的小按钮，可以设置服务器 URL 并重新尝试连接。

### Docker

```bash
cp .env.example .env
# 如需 Google Calendar，请编辑 .env 并填写 ICAL_URL。
docker compose up -d
```

打开 `http://你的主机IP/`。后台是 `http://你的主机IP/admin`。

默认把主机 `80` 端口映射到容器 `5000` 端口。手动提醒通过 `manual_notes.json` 保存。

### 自架 Linux 服务器

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
sudo bash setup.sh
```

手动运行：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

更新：

```bash
sudo bash update_clock.sh
```

## 日本語

### いちばん簡単な使い方：iPad だけ、Docker もサーバー構築もなし

[公開時計](https://kcayut.github.io/webclock/)を開くだけで、端末の時刻とタイムゾーンを表示します。公開版はバックエンドや外部時刻サービスに接続せず、ブラウザー設定の読み書きもしません。カレンダーや管理機能には[セルフホスト版](#self-hosting)を使います。

1. iPad の Safari で WebClock の URL を開きます。
2. 共有ボタンを押し、「ホーム画面に追加」を選びます。
3. ホーム画面の WebClock アイコンから開くと、ほぼ全画面で表示できます。
4. iPad の「設定」>「画面表示と明るさ」>「自動ロック」で「なし」を選びます。「なし」がない場合は、アクセスガイドで WebClock に固定します。
5. ショートカットで開きたい場合は、「ショートカット」App で「URL を開く」を追加し、WebClock の URL を入れます。必要なら「明るさを設定」も追加し、ホーム画面やウィジェットに置きます。
6. **セルフホスト版のみ**、管理画面は `/admin` です。例：`https://your-clock.example.com/admin`。

公開サイトを初めて開く場合や開き直す場合はネット接続が必要です。PWA のオフラインキャッシュは未実装で、ホーム画面への追加だけではオフライン起動できません。ダウンロード後はローカルページ対応ブラウザーでルートの `index.html` を開けます。隣の `static/` フォルダーも必要です。Flask 完全版にはホストが必要です。

### オフラインフォールバックモード

以下はセルフホストの Flask 版に適用されます。時計ページの読み込み後にローカルサーバーへ接続できなくなった場合でも、ページは動作を続けられます。このフォールバックモードでは、利用可能な時刻基準、ローカルに保存された表示設定、ブラウザー内のローカルリマインダーを使用します。Google Calendar の予定とサーバー側の `manual_notes.json` リマインダーは、サーバーへ再接続した後に復元されます。

時計画面の右下にある小さなボタンから、サーバー URL を設定し、再接続を試すことができます。

### Docker

```bash
cp .env.example .env
# Google Calendar を使う場合は .env の ICAL_URL を設定します。
docker compose up -d
```

`http://ホストのIP/` を開きます。管理画面は `http://ホストのIP/admin` です。

既定ではホストの `80` 番ポートをコンテナの `5000` 番ポートに割り当てます。手動メモは `manual_notes.json` に保存されます。

### Linux で自分でホストする

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
sudo bash setup.sh
```

手動実行：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

更新：

```bash
sudo bash update_clock.sh
```
