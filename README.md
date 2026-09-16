# WebClock

**[開啟線上時鐘 · Open the clock](https://kcayut.github.io/webclock/)** · [自行架設 · Self-hosting](#self-hosting)

把 iPad、平板或閒置螢幕變成一座大時鐘。WebClock 以黑底白字顯示時間、日期與星期，開啟網頁即可使用，不需要帳號或安裝伺服器。

Turn an iPad, tablet, or spare screen into a large clock. Open the website to show your device's time, date, and weekday. No account or server installation required.

[繁體中文](#繁體中文) · [English](#english) · [简体中文](#简体中文) · [日本語](#日本語)

## 繁體中文

### 直接使用

開啟 **[WebClock 線上時鐘](https://kcayut.github.io/webclock/)**，將裝置橫放，便可當作桌面或壁掛時鐘。

- 時間與時區跟隨裝置設定，日期與星期使用繁體中文。
- 字體隨畫面大小調整，保持大字顯示。
- 不需要登入，也不需要填寫行事曆或其他私人資料。

在 iPad 的 Safari 中，可透過「分享 → 加入主畫面」建立入口。若希望持續顯示，請依裝置可用的設定調整自動鎖定與螢幕亮度。

開啟或重新載入線上時鐘需要網路；已載入的頁面可繼續計時。加入主畫面不提供離線快取。也可下載原始碼，以支援本機網頁的瀏覽器開啟 `index.html`，並保留旁邊的 `static/` 資料夾。

### 選擇使用方式

| 功能 | 線上時鐘 | 自行架設 |
| --- | --- | --- |
| 時間、日期、星期 | ✓ | ✓ |
| 時區 | 跟隨裝置 | 後台指定，預設 UTC+8 |
| Google Calendar、手動提醒 | — | ✓ |
| 亮度、黑畫面、假日標示 | — | ✓ |
| 顯示語言 | 繁體中文 | 繁中、簡中、英文、日文 |
| 需要主機 | 不需要 | 電腦、NAS、Raspberry Pi 等 |

<a id="self-hosting"></a>

### 自行架設

需要行事曆、提醒或遠端調整顯示時，可在自己的主機執行完整版。先下載專案並建立設定檔，再選擇一種安裝方式：

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
```

編輯 `.env`：

```env
ICAL_URL=
PORT=5000
HOST=0.0.0.0
```

若要顯示 Google Calendar，在 `ICAL_URL` 填入日曆的私人 iCal 網址；不需要行事曆就留空。請將私人網址保留在自己的 `.env`，不要提交至公開儲存庫。

#### Docker

先建立提醒檔案，避免 Docker 將檔案掛載路徑建立成目錄：

```bash
touch manual_notes.json
mkdir -p webclock_state
docker compose up -d --build
```

瀏覽器開啟 `http://主機IP/`；管理畫面為 `http://主機IP/admin`。預設使用主機的 `80` 連接埠，對應容器內的 `5000`。

#### Linux 安裝腳本

適用於使用 apt 與 systemd 的 Raspberry Pi OS、Ubuntu、Debian：

```bash
sudo bash setup.sh
```

依提示選擇連接埠，預設為 `5000`。腳本會安裝相依套件、建立 Python 虛擬環境，並設定開機啟動服務。完成後開啟 `http://主機IP:5000/`，管理畫面為 `/admin`；若選了其他連接埠，請替換網址中的 `5000`。

#### 手動執行

已安裝 Python 3 的環境也可直接執行：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

### 行事曆、提醒與顯示設定

自架版的 `/admin` 可調整亮度、黑畫面、時區、語言及手動提醒。設定會在重新啟動後保留。

手動提醒可設定指定日期時間，或每天固定顯示時段。每天時段支援跨午夜，例如 22:00 至隔天 06:00。開始與結束不可相同；兩欄清空可取消時段限制。時段依後台時區計算，包含開始時間、不包含結束時間。到期提醒只隱藏，不會刪除；一般會在約 5 秒內更新畫面。

未設定時段的提醒，有日期時只在當天顯示，沒有日期則持續顯示。設定時段後，以時段決定顯示範圍。這些限制適用於後台手動提醒。

自架時鐘載入後若暫時失去伺服器連線，會使用可用的時間基準、瀏覽器保存的顯示設定及本機提醒繼續運作。Google Calendar 與伺服器提醒會在重新連線後恢復。畫面右下角的連線按鈕可設定伺服器網址並重新連線。

### 資料保存與更新

請備份以下檔案與目錄，搬移主機時也一併保留：

| 路徑 | 內容 |
| --- | --- |
| `.env` | 行事曆網址與伺服器設定 |
| `manual_notes.json` | 手動提醒 |
| `webclock_state/` | 亮度、黑畫面、時區與語言設定 |

Docker Compose 會將以上資料保存在主機。更新 Docker 安裝可在取得程式更新後，再執行 `docker compose up -d --build`。

使用 Linux 安裝腳本的服務可執行：

```bash
sudo bash update_clock.sh
```

更新期間服務會短暫停止。更新器保留既有設定與資料，備份套件環境，並在更新後檢查服務狀態。Git 安裝要求工作目錄乾淨，且遠端更新可以直接向前套用。執行前請預留足夠空間備份 `venv/`。

更新失敗時會嘗試回復程式、套件環境與服務設定，並保留 `.webclock-update-*` 備份供檢查。若自動回復失敗、突然斷電或程序被強制結束，請依錯誤訊息與備份檢查服務。非 Git 安裝不會自動下載程式；手動覆蓋檔案前應先備份整個資料夾。

<details>
<summary>從尚未保存顯示設定的舊版本升級</summary>

請保持舊服務執行，以便更新器讀取目前的設定。對追蹤 `origin/main` 的 Git 安裝，在原安裝資料夾執行：

```bash
git fetch origin
updater_file="$(mktemp /tmp/webclock-updater.XXXXXX)"
git show origin/main:update_clock.py > "$updater_file" &&
    sudo python3 "$updater_file" "$PWD"
```

不要先執行舊版更新腳本或重新安裝。若舊服務已停止或重啟，僅存在記憶體中的設定需重新設定。首次升級完成後，使用一般更新命令即可。

</details>

## English

### Use the online clock

Open **[WebClock](https://kcayut.github.io/webclock/)** on a tablet or spare screen. Landscape orientation makes the most of the large display. Time and timezone follow the device; the date and weekday are displayed in Traditional Chinese.

In Safari on iPad, use **Share → Add to Home Screen** for quick access. Adjust Auto-Lock and brightness in the device settings as needed. Opening or reloading the website requires a connection; an already loaded page keeps ticking. There is no offline cache. A downloaded `index.html` can also be opened in a browser that supports local pages, with the `static/` folder alongside it.

### Self-hosting

For Google Calendar, reminders, holiday highlighting, brightness and black-screen controls, run the full version on your own computer, NAS, or Raspberry Pi. The admin page at `/admin` supports Traditional Chinese, Simplified Chinese, English, and Japanese. It saves display settings across restarts and lets you select the timezone (default UTC+8).

Follow the shared [installation commands](#self-hosting): clone the repository, copy `.env.example` to `.env`, and optionally set `ICAL_URL` to your private calendar URL. Choose Docker, the apt/systemd Linux installer, or a manual Python run. Docker uses host port `80`; the other methods default to `5000`. Keep private calendar URLs out of the public repository.

Reminders support a date/time range or a daily time window, including overnight windows. Windows use the admin timezone, include the start, and exclude the end. Expired reminders are hidden rather than deleted. While disconnected from the server, the loaded page uses cached display settings and browser-local reminders; calendar events and server reminders return after reconnection. The bottom-right button opens connection settings.

Back up `.env`, `manual_notes.json`, and `webclock_state/`. Update a Linux service with `sudo bash update_clock.sh`; updates briefly stop the service and require space to back up `venv/`. Failed updates attempt recovery and retain backup files. For Docker, obtain the updated source and run `docker compose up -d --build`.

## 简体中文

### 使用在线时钟

打开 **[WebClock](https://kcayut.github.io/webclock/)**，即可把平板或闲置屏幕变成大时钟，建议横向摆放。时间和时区跟随设备，日期与星期使用繁体中文。

在 iPad 的 Safari 中可选择「分享 → 添加到主屏幕」，并按需调整自动锁定与亮度。打开或重新加载网站需要网络；已加载的页面可以继续计时，但不提供离线缓存。也可下载 `index.html`，保留旁边的 `static/` 文件夹，以支持本地网页的浏览器打开。

### 自行部署

如需 Google Calendar、手动提醒、节假日标记、亮度和黑屏控制，可在电脑、NAS 或 Raspberry Pi 上运行完整版。管理页面为 `/admin`，支持繁中、简中、英文和日文，时区默认 UTC+8，也可自行选择。显示设置在重启后保留。

按上方[安装步骤](#self-hosting)下载项目，将 `.env.example` 复制为 `.env`；需要日历时填写 `ICAL_URL`，否则留空。可选择 Docker、适用于 apt/systemd 的 Linux 安装脚本，或手动运行 Python。Docker 默认使用主机端口 `80`，其他方式默认为 `5000`。私人日历网址请只保存在自己的配置中。

手动提醒可指定日期时间范围或每天显示时段，支持跨午夜；按管理页面的时区计算，包含开始、不包含结束，到期只隐藏、不删除。服务器暂时断开时，已加载的页面使用缓存的显示设置与浏览器本地提醒继续运行，日历和服务器提醒在重连后恢复。右下角按钮可打开连接设置。

请备份 `.env`、`manual_notes.json` 和 `webclock_state/`。Linux 服务使用 `sudo bash update_clock.sh` 更新，期间会短暂停机，需要预留备份 `venv/` 的空间。更新失败时会尝试恢复并保留备份。Docker 在取得更新后的源代码后，执行 `docker compose up -d --build`。

## 日本語

### 公開時計を使う

**[WebClock](https://kcayut.github.io/webclock/)** を開くだけで、タブレットや使っていない画面を大きな時計にできます。横向きでの利用がおすすめです。時刻とタイムゾーンは端末の設定に従い、日付と曜日は繁体字中国語で表示します。

iPad の Safari では「共有 → ホーム画面に追加」で入口を作れます。自動ロックと明るさは端末の設定で調整してください。サイトを開く場合や再読み込みにはネット接続が必要です。読み込み済みのページは動作を続けますが、オフラインキャッシュはありません。ダウンロードした `index.html` は、隣の `static/` フォルダーを残したまま、ローカルページ対応ブラウザーで開くこともできます。

### セルフホスト

Google Calendar、手動リマインダー、休日表示、明るさ・黒画面の切り替えには、パソコン、NAS、Raspberry Pi などで完全版を実行します。管理画面は `/admin` で、繁体字中国語、簡体字中国語、英語、日本語に対応しています。タイムゾーンの初期値は UTC+8 です。表示設定は再起動後も保持されます。

上記の[インストール手順](#self-hosting)でソースを取得し、`.env.example` を `.env` にコピーします。カレンダーを使う場合のみ `ICAL_URL` を設定してください。Docker、apt/systemd を使う Linux 用スクリプト、Python の手動実行から選べます。既定のホスト側ポートは Docker が `80`、その他は `5000` です。非公開のカレンダー URL を公開リポジトリに含めないでください。

リマインダーは日時範囲または毎日の表示時間帯を指定でき、日付をまたぐ時間帯にも対応します。管理画面のタイムゾーンを使い、開始を含み、終了は含みません。期限後は削除せず非表示にします。サーバーと切断された場合、読み込み済みのページは保存済み表示設定とブラウザー内のリマインダーで動作を続けます。カレンダーとサーバー側リマインダーは再接続後に戻ります。右下のボタンから接続設定を開けます。

`.env`、`manual_notes.json`、`webclock_state/` をバックアップしてください。Linux サービスの更新は `sudo bash update_clock.sh` で行います。更新中は一時停止し、`venv/` のバックアップ容量が必要です。失敗時は復元を試み、バックアップを保持します。Docker はソースを更新した後、`docker compose up -d --build` を実行します。

## 問題與建議 · Feedback

歡迎透過 [Issues](https://github.com/kcayut/webclock/issues) 回報問題或提出建議。
