# WebClock

WebClock is a small Flask web clock for an iPad or wall-mounted screen. It shows a large clock, today's reminders, optional Google Calendar iCal events, holiday highlighting, brightness/black-screen controls, timezone selection, and UI language selection.

Supported UI languages: English, 繁體中文, 简体中文, 日本語. The default language is 繁體中文.

## 繁體中文

### 最簡單使用方式：只用 iPad，不架 Docker、不架伺服器

這個方式適合「已經有人幫你架好 WebClock 網址」的情境。你只需要 iPad 和網站網址，例如 `https://your-clock.example.com` 或家中區網網址 `http://192.168.1.10`。

1. 在 iPad 打開 Safari，進入 WebClock 網址。
2. 點 Safari 分享按鈕，選「加入主畫面」。
3. 回到主畫面，點剛加入的 WebClock 圖示。它會用接近全螢幕的方式開啟。
4. 到 iPad「設定」>「螢幕顯示與亮度」>「自動鎖定」，選「永不」。如果你的 iPad 沒有「永不」，可改用「引導使用模式」限制畫面停留在 WebClock。
5. 想用快捷鍵快速開啟：打開「捷徑」App，新增捷徑，加入「打開 URL」動作，填入 WebClock 網址，再加入「設定亮度」動作，例如 80%，儲存後放到主畫面或小工具。
6. 後台設定在 `/admin`，例如 `https://your-clock.example.com/admin`。可在後台調整亮度、黑畫面、時區、語言和手動提醒。

注意：如果你手上只有這份程式碼，iPad 本身不能直接執行 Flask 網站。至少需要一台電腦、NAS、Raspberry Pi、VPS，或雲端服務來提供網址。

### 離線備援模式

WebClock 仍然是由 Flask 主機提供的 app，不是單一靜態 `index.html` app。時鐘頁面載入後，如果本機伺服器無法連線，頁面仍可繼續運作。這個備援模式會使用裝置時間、本機儲存的顯示設定，以及瀏覽器本機提醒。Google Calendar 事件與伺服器端 `manual_notes.json` 提醒會在伺服器重新連線後恢復。

使用時鐘畫面右下角的小按鈕，可以設定伺服器 URL 並重新嘗試連線。

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
git clone https://github.com/yourusername/webclock.git
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

## English

### Easiest iPad-only use, no Docker and no server setup

This path assumes someone already hosts WebClock for you. You only need the website URL, for example `https://your-clock.example.com` or a LAN URL such as `http://192.168.1.10`.

1. Open the WebClock URL in Safari on the iPad.
2. Tap Share, then Add to Home Screen.
3. Open WebClock from the Home Screen icon for a near full-screen experience.
4. Go to iPad Settings > Display & Brightness > Auto-Lock, then choose Never. If Never is unavailable, use Guided Access to keep the iPad on WebClock.
5. To make a shortcut, open the Shortcuts app, create a shortcut with Open URL, enter the WebClock URL, optionally add Set Brightness, then save it to the Home Screen or a widget.
6. Admin settings are at `/admin`, for example `https://your-clock.example.com/admin`.

If you only have the source code, the iPad cannot run this Flask app by itself. You still need a computer, NAS, Raspberry Pi, VPS, or cloud host to provide the URL.

### Offline fallback mode

WebClock is still a Flask-hosted app, not a single static `index.html` app. After the clock page has loaded, it can keep running if the local server becomes unavailable. In that fallback mode it uses the device clock, locally saved display settings, and browser-local reminders. Google Calendar events and server-side `manual_notes.json` reminders are restored after the server reconnects.

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
git clone https://github.com/yourusername/webclock.git
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

这个方式适合「已经有人帮你架好 WebClock 网址」的情况。你只需要 iPad 和网站网址，例如 `https://your-clock.example.com` 或局域网网址 `http://192.168.1.10`。

1. 在 iPad 用 Safari 打开 WebClock 网址。
2. 点分享按钮，选择「添加到主屏幕」。
3. 从主屏幕打开 WebClock，它会以接近全屏的方式运行。
4. 到 iPad「设置」>「显示与亮度」>「自动锁定」，选择「永不」。如果没有「永不」，可使用「引导式访问」让画面停留在 WebClock。
5. 想用快捷指令快速打开：打开「快捷指令」App，新增「打开 URL」，填入 WebClock 网址，可再加入「设置亮度」，然后保存到主屏幕或小组件。
6. 后台设置在 `/admin`，例如 `https://your-clock.example.com/admin`。

如果你只有源码，iPad 不能直接运行 Flask 网站。仍然需要电脑、NAS、Raspberry Pi、VPS 或云服务提供网址。

### 离线备用模式

WebClock 仍然是由 Flask 主机提供的 app，不是单一静态 `index.html` app。时钟页面载入后，如果本地服务器无法连接，页面仍可继续运行。这个备用模式会使用设备时间、本地保存的显示设置，以及浏览器本地提醒。Google Calendar 事件和服务器端 `manual_notes.json` 提醒会在服务器重新连接后恢复。

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
git clone https://github.com/yourusername/webclock.git
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

この方法は、誰かがすでに WebClock を公開している場合に使えます。必要なのは iPad と URL だけです。例：`https://your-clock.example.com`、または LAN の `http://192.168.1.10`。

1. iPad の Safari で WebClock の URL を開きます。
2. 共有ボタンを押し、「ホーム画面に追加」を選びます。
3. ホーム画面の WebClock アイコンから開くと、ほぼ全画面で表示できます。
4. iPad の「設定」>「画面表示と明るさ」>「自動ロック」で「なし」を選びます。「なし」がない場合は、アクセスガイドで WebClock に固定します。
5. ショートカットで開きたい場合は、「ショートカット」App で「URL を開く」を追加し、WebClock の URL を入れます。必要なら「明るさを設定」も追加し、ホーム画面やウィジェットに置きます。
6. 管理画面は `/admin` です。例：`https://your-clock.example.com/admin`。

ソースコードだけを持っている場合、iPad 単体では Flask アプリを実行できません。PC、NAS、Raspberry Pi、VPS、クラウドなど、URL を提供する環境が必要です。

### オフラインフォールバックモード

WebClock は引き続き Flask でホストされる app であり、単一の静的な `index.html` app ではありません。時計ページの読み込み後にローカルサーバーへ接続できなくなった場合でも、ページは動作を続けられます。このフォールバックモードでは、端末の時刻、ローカルに保存された表示設定、ブラウザー内のローカルリマインダーを使用します。Google Calendar の予定とサーバー側の `manual_notes.json` リマインダーは、サーバーへ再接続した後に復元されます。

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
git clone https://github.com/yourusername/webclock.git
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
