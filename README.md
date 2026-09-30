# WebClock

**[開啟線上時鐘 · Open the clock](https://kcayut.github.io/webclock/)** · [自行架設 · Self-hosting](#self-hosting)

把 iPad、平板或閒置螢幕變成一座大時鐘。WebClock 以黑底白字顯示時間、日期與星期，開啟網頁即可使用，不需要帳號或安裝伺服器。

Turn an iPad, tablet, or spare screen into a large clock. Open the website to show your device's time, date, and weekday. No account or server installation required.

[繁體中文](#繁體中文) · [English](#english) · [简体中文](#简体中文) · [日本語](#日本語)

## 繁體中文

自架版提供分開的管理入口：`/admin` 設定時鐘顯示、行事曆與文字提醒；`/schedules` 設定網頁鬧鐘、跳過假日或下一次，以及裝置同步狀態。時鐘頁可播放內建音色並顯示紅邊提示。[裝置 API](doc/server-api.md) 供硬體取得共用排程與日曆、回報狀態；硬體韌體與獨立執行由後續裝置專案處理。

### 直接使用

開啟 **[WebClock 線上時鐘](https://kcayut.github.io/webclock/)**，將裝置橫放，便可當作桌面或壁掛時鐘。

- 時間與時區跟隨裝置設定，日期與星期使用繁體中文。
- 字體隨畫面大小調整，保持大字顯示。
- 不需要登入，也不需要填寫行事曆或其他私人資料。

在 iPad 的 Safari 中，可透過「分享 → 加入主畫面」建立入口。若希望持續顯示，請依裝置可用的設定調整自動鎖定與螢幕亮度。

WebClock 最初為初代 iPad mini 設計，時鐘頁持續以舊平板能簡單顯示時間為優先；管理設定可在另一台手機或電腦完成。離線重新開啟需要瀏覽器支援，舊 Safari 沒有這項能力時，仍可連線開啟時鐘，已載入的頁面在斷線後也會繼續計時。

支援離線快取的瀏覽器，第一次請連線開啟，等頁面顯示「已可離線開啟」後，即可在斷網時重新開啟或重新整理。瀏覽器清除網站資料或回收快取後，需要再次連線準備。也可下載原始碼，以支援本機網頁的瀏覽器開啟 `index.html`，並保留旁邊的 `static/` 資料夾。

### 選擇使用方式

| 功能 | 線上時鐘 | 自行架設 |
| --- | --- | --- |
| 時間、日期、星期 | ✓ | ✓ |
| 時區 | 跟隨裝置 | 後台指定，預設 UTC+8 |
| Google／Apple iCloud 行事曆、文字提醒 | — | ✓ |
| 網頁鬧鐘、音色選擇、假日跳過 | — | ✓（保持時鐘頁開啟） |
| 亮度、黑畫面、假日標示 | — | ✓ |
| 顯示語言 | 繁體中文 | 繁中、簡中、英文、日文 |
| 離線重新開啟 | ✓（先連線準備） | HTTPS 或 localhost，先連線準備 |
| 自動夜間模式、星期提醒、行程倒數、備份還原 | — | ✓ |
| 需要主機 | 不需要 | 電腦、NAS、Raspberry Pi 等 |

<a id="self-hosting"></a>

### 自行架設

需要行事曆、提醒或遠端調整顯示時，可在自己的主機執行完整版。先下載專案並建立設定檔，再選擇一種安裝方式：

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
```

`.env` 僅需依需要調整伺服器設定：

```env
PORT=5000
HOST=0.0.0.0
```

行事曆網址直接在管理頁填寫，不需要編輯 `.env`。舊安裝的 `ICAL_URL` 仍可沿用，直到你第一次在管理頁儲存行事曆設定。

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

### 行事曆、文字提醒與鬧鐘

自架版的 `/admin` 可調整亮度、黑畫面、時區、語言、行事曆及文字提醒。鬧鐘排程在獨立的 `/schedules` 管理；行事曆行程與文字提醒不會自動變成鬧鐘。設定會在重新啟動後保留。

管理介面共用固定導覽：顯示設定、行事曆與提醒、鬧鐘管理、裝置管理、備份與還原。手機版也會直接顯示這五個入口。每個鬧鐘列出下次響鈴時間：今天、明天、本週或下週的星期；更遠的時間顯示日期，跨年則帶年份。相對日期依伺服器的台灣時間判斷。

在「行事曆與提醒」下方展開「行事曆來源設定」，依 Apple iCloud、Google 或其他 ICS 服務新增來源，可同時訂閱多個行事曆並各自命名。網址預設遮蔽，按眼睛才會顯示；設定區預設收合，日常只需在「顯示來源」勾選要出現在時鐘上的來源，包含本地提醒。顯示選擇與網址編輯分開儲存。Apple 的 `webcal://` 連結可直接貼上，不必手動改寫。

鬧鐘編輯器可獨立選擇一個或多個行事曆來源，包含本地提醒，並使用「依行程時間響鈴」或「當天有行程才響」。「依行程時間」可提前 0–1440 分鐘，略過没有時間的全天事項；「當天有行程」則在所選來源有行程的日期，按鬧鐘設定的固定時間響鈴，全天與跨日行程也算。選到的任一來源符合即可，來源是否在時鐘上顯示不影響鬧鐘。

聯動仍套用鬧鐘的星期、指定日期與台灣假日條件，依**實際響鈴的台灣日期**判斷；預覽查詢未來 366 天。未設定日期或固定時段的常駐本地文字不當成行程。來源讀取失敗或移除時，該來源不產生響鈴；其他可讀取的來源仍可使用。來源約每 5 分鐘更新，並非即時同步。

**Apple iCloud 設定：**

1. 在平板或電腦開啟 [iCloud 行事曆](https://www.icloud.com/calendar/)，登入你的 Apple 帳號。
2. 開啟要顯示的行事曆旁的資訊按鈕，啟用「公開行事曆」，再按「複製」。
3. 將連結貼進 WebClock 的行事曆設定並儲存。WebClock 約每 5 分鐘重新讀取來源，並非即時同步。

這是唯讀訂閱，不需要把 Apple 帳號或密碼交給 WebClock。**拿到公開連結的任何人都能讀取該行事曆**，建議建立只放時鐘用行程的獨立行事曆；不再使用時可在 iCloud 停止公開共享。眼睛遮蔽只隱藏畫面上的文字，不會改變連結的存取權限。操作與共享範圍請參考 [Apple 官方說明](https://support.apple.com/zh-tw/guide/icloud/mm6b1a9479/icloud)與[公開連結的唯讀存取說明](https://support.apple.com/zh-tw/108306)。

目前讀取的是行事曆行程，不同步 Apple「提醒事項」App 的待辦，也不支援需要 Apple 帳號登入的私人共享邀請。行事曆網址保存在主機的 `webclock_state/calendar.json`，不要提交到公開儲存庫。

手動提醒可設定指定日期時間，或每週／每日固定顯示時段。固定時段可勾選星期；不勾選代表每天。跨午夜的時段歸屬開始的那一天，例如週一 22:00 至週二 06:00，只需勾選星期一。每天時段支援跨午夜，例如 22:00 至隔天 06:00。開始與結束不可相同；兩欄清空可取消時段限制。時段依後台時區計算，包含開始時間、不包含結束時間。到期提醒只隱藏，不會刪除；一般會在約 5 秒內更新畫面。

未設定時段的提醒，有日期時只在當天顯示，沒有日期則持續顯示。設定時段後，以時段決定顯示範圍。這些限制適用於後台手動提醒。「編輯提醒」可修改文字、日期、時間及顯示區間；「暫停」會保留內容，但停止顯示與倒數，按「恢復」即可啟用。

自架時鐘載入後若暫時失去伺服器連線，會使用可用的時間基準、瀏覽器保存的顯示設定及本機提醒繼續運作。訂閱行事曆與伺服器提醒會在重新連線後恢復。畫面右下角的連線按鈕可設定伺服器網址並重新連線。

### 在 iPad 上使用網頁鬧鐘

1. 在 `/schedules` 新增鬧鐘，設定時間、每天／星期／指定日期或工作日／假日規則，並選擇鈴聲、嗶聲、電子音或靜音。
2. 每天、星期與指定日期規則可再勾選「跳過假日」；依台灣政府行政機關辦公日曆判斷，補班日仍是工作日。「只在假日」不能同時「跳過假日」。排程採台灣時間，和時鐘顯示時區分開。
3. 在要播放聲音的 iPad 開啟時鐘頁，點小鈴鐺「啟用聲音」，聽到短音後保持頁面開啟。每次重新開啟或重新整理頁面，都要再啟用一次聲音。
4. 時間到時，時鐘頁顯示鬧鐘與紅邊提示；分兩次點擊關閉當次鬧鐘。這只停止目前顯示頁的這一次，不會刪除排程、停用下次或停止其他裝置。

紅邊每 2 秒明暗變化一次，不遮住時間。在右下角連線面板取消「閃爍紅邊」可改為常亮，不需依賴系統的動態效果設定；支援的瀏覽器會同時尊重系統「減少動態效果」。靜音鬧鐘仍顯示視覺提示。

**請保持 Safari 在前景、螢幕開啟，並確認裝置音量與靜音設定。** iOS 要求使用者操作才能啟用網頁音訊；鎖屏、切換 App 或分頁後，聲音與網頁計時可能中斷，WebClock 不保證在背景或鎖屏時響鈴。回到頁面若沒有聲音，請再點小鈴鐺啟用。[Apple 音訊說明](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/Using_HTML5_Audio_Video/PlayingandSynthesizingSounds/PlayingandSynthesizingSounds.html)、[iOS Safari 中斷行為](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/state#resuming_interrupted_play_states_in_ios_safari)

時鐘頁約每 15 秒更新每個鬧鐘的下次時間。短暫斷線時，已載入的下次鬧鐘仍可觸發；重新開頁或取得後續週期需恢復連線。超過 60 秒才恢復處理的過期鬧鐘不會補響。假日資料超出涵蓋範圍時，依賴假日的鬧鐘不猜測日期；可在管理頁查看資料範圍。

### 夜間模式、倒數與離線使用

在後台啟用「自動夜間模式」，設定開始、恢復日間時間與夜間亮度，也可選擇夜間黑畫面。排程依後台時區每天執行，包含開始、不包含結束；日間恢復原本亮度，手動黑畫面優先。這是網頁顯示調整，不會改變裝置背光或自動鎖定設定。斷線時會沿用瀏覽器保存的排程。

提醒區下方會顯示下一個行程還有幾分鐘。指定日期提醒使用其提醒時間（未填時間時可使用顯示區間的開始）；每週／每日提醒使用下一次顯示時段的開始；訂閱行事曆使用當日有時間的行程。全天事項不以午夜倒數。暫停的提醒不參與倒數。

自架版的離線準備狀態在右下角連線面板中。離線重新開啟需要支援的瀏覽器，以及 HTTPS 或本機 localhost；一般 `http://區網IP` 不支援這項快取，但已載入的頁面仍可繼續計時。快取只包含時鐘頁面與顯示資源，不包含後台、API、私人日曆或伺服器提醒。斷線時仍使用原有瀏覽器本機提醒，重新連線才恢復伺服器資料。

### 備份與還原

在後台下載 JSON 備份，可保存伺服器顯示設定（含夜間排程）與手動提醒（含星期及暫停狀態）。選擇備份檔案並按「匯入並取代」，確認後會取代目前設定與提醒；系統先驗證完整資料才寫入。上限為 1 MiB、1,000 筆提醒，每筆內容最多 1,000 字元。

匯入前的資料會保留在 `webclock_state/before-import.json`，可用相同匯入功能還原；每次匯入會更新這份備份。寫入失敗時會嘗試回復原提醒。若突然斷電或回復失敗，請保留該檔案並在服務恢復後還原。

下載的 JSON 備份不包含行事曆網址，也不包含瀏覽器本機提醒；搬移主機時請另外保存 `webclock_state/calendar.json` 與 `.env`。

### 資料保存與更新

請備份以下檔案與目錄，搬移主機時也一併保留：

| 路徑 | 內容 |
| --- | --- |
| `.env` | 伺服器設定，以及舊安裝可能仍使用的 `ICAL_URL` |
| `manual_notes.json` | 舊版提醒原檔（首次啟動遷移後保留） |
| `webclock_state/` | 行事曆網址（`calendar.json`）、顯示與夜間設定、提醒、排程、裝置狀態及備份 |

Docker Compose 會將以上資料保存在主機。所有安裝方式首次啟動新版時，會將舊 `manual_notes.json` 複製至 `webclock_state/manual_notes.json`，原檔保留；之後以新位置為準，不會重複覆蓋。自訂 `NOTES_FILE` 仍可指定提醒位置。更新 Docker 安裝可在取得程式更新後，再執行 `docker compose up -d --build`。

使用 Linux 安裝腳本的服務可執行：

```bash
sudo bash update_clock.sh
```

更新期間服務會短暫停止。更新器先備份 `venv/`、`.env`、舊提醒和整個狀態目錄，也涵蓋 `.env` 或服務環境指定的 `WEBCLOCK_STATE_DIR`、`NOTES_FILE`（包含專案外的路徑）。更新後會檢查顯示設定、提醒資料、管理 API 與裝置設定 API。執行前請預留足夠空間備份套件和所有資料，更新完成前暫停編輯後台。

Git 安裝要求工作目錄乾淨、遠端更新可直接向前套用，且資料不受 Git 追蹤。若舊新資料互相衝突、資料路徑是符號連結或與程式目錄重疊，更新器會拒絕更新，保留原資料。

更新失敗時會嘗試一起還原程式、套件環境和資料，再啟動舊服務。`.webclock-update-*` 內保留原始備份及 `manifest.json` 路徑對照；回復時被取代的新版資料另存 `failed-data/`，新版套件另存 `failed-venv/`。成功後才清除備份。若自動回復失敗、突然斷電或程序被強制結束，請保留整份備份，依錯誤訊息檢查服務；不保證斷電後自動續作。非 Git 安裝不會自動下載或還原程式；手動覆蓋檔案前應先備份整個資料夾。

<details>
<summary>第一次從舊版更新器升級</summary>

請保持舊服務執行，以便更新器讀取目前的設定。對追蹤 `origin/main` 的 Git 安裝，在原安裝資料夾執行：

```bash
git fetch origin
updater_file="$(mktemp /tmp/webclock-updater.XXXXXX)"
git show origin/main:update_clock.py > "$updater_file" &&
    sudo python3 "$updater_file" "$PWD"
```

此入口會讀取已取得的 upstream 版本中 `scripts/update_clock.py`，完成檢查和備份後才切換程式。不要先執行舊版更新腳本、`git pull` 或重新安裝。若舊服務已停止或重啟，僅存在記憶體中的設定需重新設定。首次升級完成後，使用一般更新命令即可。

</details>

## English

Self-hosting has separate management pages: `/admin` for clock display, calendar and text reminders; `/schedules` for browser alarms, holiday/next-occurrence skipping and device sync status. The clock page plays built-in tones and shows a red-border alert. [Device APIs](doc/server-api.md) provide shared schedules and calendars and accept status reports; hardware firmware and independent execution belong to a future device project.

### Use the online clock

Open **[WebClock](https://kcayut.github.io/webclock/)** on a tablet or spare screen. Landscape orientation makes the most of the large display. Time and timezone follow the device; the date and weekday are displayed in Traditional Chinese.

In Safari on iPad, use **Share → Add to Home Screen** for quick access. Adjust Auto-Lock and brightness in the device settings as needed. The clock was originally designed for the first-generation iPad mini and prioritizes simple time display on old tablets; manage settings from another phone or computer. Offline reopening requires a compatible browser. Old Safari can still open the clock online and keep a loaded page ticking after disconnection. In compatible browsers, connect once and wait for the offline-ready indicator before reopening or reloading without a connection. Clearing site data or browser cache eviction requires another online visit. A downloaded `index.html` can also be opened in a browser that supports local pages, with the `static/` folder alongside it.

### Self-hosting

For Google/Apple iCloud calendars, text reminders, holiday highlighting, brightness and black-screen controls, run the full version on your own computer, NAS, or Raspberry Pi. The admin page at `/admin` supports Traditional Chinese, Simplified Chinese, English, and Japanese. It saves settings across restarts and lets you select the timezone (default UTC+8). Alarm schedules have their own page at `/schedules`; calendar events and text reminders do not automatically become alarms.

Follow the shared [installation commands](#self-hosting): clone the repository and copy `.env.example` to `.env` for server settings. Choose Docker, the apt/systemd Linux installer, or a manual Python run. Docker uses host port `80`; the other methods default to `5000`.

In `/admin`, open **Calendar & text reminders**, expand **Calendar source settings**, and add named sources for Google private iCal URLs, Apple iCloud public calendar links or other ICS feeds. You can add multiple calendars; URLs stay masked until you press the eye button. Click **Save source settings** to save changes. Under **Sources shown on the clock**, select calendars and local reminders, then click **Save display selection**. To hide a source, uncheck it and save the display selection; to delete its URL, remove the source and save the source settings. These two save actions are separate, and display selection does not change alarm source selection. URLs are saved in `webclock_state/calendar.json`; legacy `ICAL_URL` remains a fallback until calendar settings are first saved. Keep URLs out of public repositories.

For Apple, open [iCloud Calendar](https://www.icloud.com/calendar/) on a tablet or computer, open the calendar information button, enable **Public Calendar**, and copy its link into WebClock. A `webcal://` link works without editing. This reads events only and needs no Apple credentials. Anyone with the public link can read the calendar, so use a separate calendar containing only items you intend to share; masking the URL does not change that access. See [Apple's sharing instructions](https://support.apple.com/guide/icloud/mm6b1a9479/icloud). WebClock refreshes about every five minutes; it does not sync Apple Reminders or accept private sharing invitations.

Reminders support a date/time range or a weekly/daily time window, including overnight windows. Select weekdays or leave all unchecked for every day. Overnight windows belong to their starting weekday. Edit text, dates and windows in place, or pause and resume without deleting. Windows use the admin timezone, include the start, and exclude the end. Expired reminders are hidden rather than deleted. While disconnected from the server, the loaded page uses cached display settings and browser-local reminders; calendar events and server reminders return after reconnection. The bottom-right button opens connection settings.

For browser alarms, use `/schedules` to select a time, recurrence and bell, beep, digital or silent mode. Daily, weekday and explicit-date rules can skip holidays according to Taiwan's government work calendar; make-up workdays remain workdays. Holiday-only rules cannot also skip holidays. Alarm times use Asia/Taipei independently of the displayed timezone.

On the iPad clock page, tap the bell to enable sound and hear a short confirmation tone. Enable it again after every reload. Keep Safari in the foreground with the screen on, and check device volume and mute settings: background tabs, app switching and screen locking can interrupt audio and timers, so background or locked-screen alarms are not guaranteed. Tap twice to dismiss the current alarm on this page only; the schedule and other devices remain active. The red border pulses once every two seconds; disable flashing in connection settings for a steady border. Supported browsers also honor reduced-motion settings. Silent mode still shows the alert.

The page refreshes each alarm's next occurrence about every 15 seconds. A loaded next occurrence can fire during a brief disconnection, but reopening the page or loading later occurrences requires a connection. Alarms processed over 60 seconds late are not replayed. Holiday-dependent alarms do not guess dates outside the available calendar coverage.

Automatic night mode dims or blacks out the page on a daily schedule in the admin timezone, then restores daytime brightness. Manual black screen takes priority. It changes page appearance, not the hardware backlight. The next-event countdown uses dated reminder times, the next recurring window start, or today's timed calendar events; paused reminders and all-day calendar events are excluded.

Offline reopening requires HTTPS or localhost and a completed online setup, shown in the connection panel. Plain LAN HTTP cannot prepare the offline cache. Only the clock shell is cached, never admin/API/calendar responses. Disconnected pages use cached display settings and browser-local reminders; server data returns on reconnection.

Download or import a JSON backup from the admin page. Import replaces server display settings and manual reminders after validation and confirmation. Limits: 1 MiB, 1,000 reminders, 1,000 characters per reminder. Calendar URLs and browser-local reminders are excluded. Pre-import data is retained in `webclock_state/before-import.json` (replaced on each import); failed writes attempt rollback. After interrupted or failed recovery, restore that file through the same import action. Keep `webclock_state/calendar.json` and `.env` separately when moving hosts.

All installation methods copy legacy reminders once into `webclock_state/manual_notes.json`, preserving the original file and using the new location thereafter. An explicit `NOTES_FILE` is still honored. Back up `.env`, legacy reminders, and the entire state directory. Update a Linux service with `sudo bash update_clock.sh`; allow space for backups of `venv/` and all data, and pause admin edits until it finishes. The updater also protects custom `WEBCLOCK_STATE_DIR` and `NOTES_FILE` paths, including external locations. It checks settings, reminders and management/device APIs, attempts source/package/data rollback on failure, and retains `.webclock-update-*` with a path manifest and failed-version data. Git must be clean and support a fast-forward update; conflicting or unsafe data paths are rejected. Copied-folder installations cannot recover overwritten source, and power-loss recovery is not automatic. For a first upgrade from the old updater, keep the service running and use the standalone updater command above before pulling source changes. For Docker, obtain the updated source and run `docker compose up -d --build`.

## 日本語

セルフホスト版は管理画面を分けています。`/admin` は時計表示・カレンダー・文字リマインダー、`/schedules` はブラウザーのアラーム、休日や次回のスキップ、端末の同期状態を管理します。時計ページは内蔵音と赤い枠で通知します。[端末 API](doc/server-api.md) で共通の予定とカレンダーを取得し、状態を報告できます。ハードウェアのファームウェアと独立した実行機能は、今後の端末プロジェクトで扱います。

### 公開時計を使う

**[WebClock](https://kcayut.github.io/webclock/)** を開くだけで、タブレットや使っていない画面を大きな時計にできます。横向きでの利用がおすすめです。時刻とタイムゾーンは端末の設定に従い、日付と曜日は繁体字中国語で表示します。

iPad の Safari では「共有 → ホーム画面に追加」で入口を作れます。自動ロックと明るさは端末の設定で調整してください。初代 iPad mini をきっかけに作られた時計として、古いタブレットでも時刻を簡単に表示することを優先しています。設定は別のスマートフォンやパソコンから行えます。オフラインで開き直す機能には対応ブラウザーが必要です。古い Safari でもオンラインで時計を開き、読み込み後は切断されても計時を続けられます。対応ブラウザーは初回にネット接続し、「已可離線開啟」の表示を待つと、オフラインでも開き直したり再読み込みできます。ブラウザーがサイトデータやキャッシュを削除した場合は、再度接続してください。ダウンロードした `index.html` は、隣の `static/` フォルダーを残したまま、ローカルページ対応ブラウザーで開くこともできます。

### セルフホスト

Google／Apple iCloud カレンダー、文字リマインダー、休日表示、明るさ・黒画面の切り替えには、パソコン、NAS、Raspberry Pi などで完全版を実行します。管理画面は `/admin` で、繁体字中国語、簡体字中国語、英語、日本語に対応しています。タイムゾーンの初期値は UTC+8 です。設定は再起動後も保持されます。アラーム設定は独立した `/schedules` にあり、カレンダー予定や文字リマインダーが自動でアラームになることはありません。

上記の[インストール手順](#self-hosting)でソースを取得し、サーバー設定用に `.env.example` を `.env` にコピーします。Docker、apt/systemd を使う Linux 用スクリプト、Python の手動実行から選べます。既定のホスト側ポートは Docker が `80`、その他は `5000` です。

`/admin` の「カレンダー・テキスト通知」で「カレンダーの参照元設定」を開き、Google の非公開 iCal URL、Apple iCloud の公開カレンダー URL、その他の ICS URL を名前付きの参照元として追加します。複数のカレンダーに対応し、URL は目のボタンを押すまで隠れています。編集後は「参照元設定を保存」を押してください。「時計に表示する参照元」ではカレンダーとローカルのリマインダーを選び、「表示する参照元を保存」を押します。表示を止める場合はチェックを外して表示選択を保存し、URL を削除する場合は参照元を削除して参照元設定を保存します。この二つの保存操作は独立しており、表示選択はアラームの参照元選択に影響しません。保存先は `webclock_state/calendar.json` です。旧 `ICAL_URL` はカレンダー設定を初めて保存するまで利用されます。URL を公開リポジトリに含めないでください。

Apple はタブレットかパソコンで [iCloud カレンダー](https://www.icloud.com/calendar/)を開き、カレンダーの情報ボタンから公開カレンダーを有効にしてリンクをコピーします。`webcal://` のまま貼り付けられます。Apple の認証情報は不要で、予定を読み取るだけです。リンクを持つ人は誰でも内容を読めるため、公開できる予定専用のカレンダーを推奨します。URL の目隠しはアクセス権を変更しません。[Apple の共有手順](https://support.apple.com/ja-jp/guide/icloud/mm6b1a9479/icloud)も参照してください。WebClock は約 5 分ごとに取得します。Apple「リマインダー」や非公開共有の招待には未対応です。

リマインダーは日時範囲または毎週・毎日の表示時間帯を指定できます。曜日未選択は毎日で、日付をまたぐ時間帯は開始日の曜日に従います。内容や日時を直接編集でき、削除せず一時停止・再開できます。管理画面のタイムゾーンを使い、開始を含み、終了は含みません。期限後は削除せず非表示にします。サーバーと切断された場合、読み込み済みのページは保存済み表示設定とブラウザー内のリマインダーで動作を続けます。カレンダーとサーバー側リマインダーは再接続後に戻ります。右下のボタンから接続設定を開けます。

ブラウザーのアラームは `/schedules` で時刻、繰り返し、ベル・ビープ・電子音・無音を選びます。毎日・曜日・指定日には、台湾の政府機関勤務日カレンダーに基づく休日スキップを追加できます。振替出勤日は勤務日です。「休日のみ」と「休日スキップ」は併用できません。アラーム時刻は表示タイムゾーンとは別に Asia/Taipei を使います。

iPad の時計ページでベルをタップして音を有効にし、短い確認音を聞いてください。再読み込みのたびに有効化が必要です。Safari を前面に表示して画面を点灯し、端末の音量と消音設定を確認してください。画面ロックや別の App・タブへの切り替えで音とタイマーが中断されるため、バックグラウンドやロック中の発音は保証しません。アラームは 2 回のタップで現在のページの今回分だけを止めます。予定や他の端末には影響しません。赤い枠は 2 秒周期で明暗を変えます。接続設定で点滅を無効にすると常時表示になり、対応ブラウザーはシステムの動きを減らす設定にも従います。無音でも表示による通知は続きます。

各アラームの次回時刻を約 15 秒ごとに更新します。短い切断中は読み込み済みの次回分を実行できますが、ページの開き直しやその後の予定取得には接続が必要です。処理が 60 秒を超えて遅れたアラームは再生しません。休日資料の対象期間外では、休日に依存するアラームの日付を推測しません。

自動ナイトモードは管理画面のタイムゾーンで毎日暗くするか黒画面にし、終了後は昼間の明るさに戻します。手動の黒画面が優先され、ハードウェアのバックライトは変更しません。次の予定までの分数は、日時付きリマインダー、繰り返し時間帯の次の開始、当日の時刻付きカレンダー予定から表示します。停止中の項目と終日のカレンダー予定は対象外です。

オフラインで開き直すには HTTPS または localhost と、接続中の準備完了が必要です。接続パネルで状態を確認できます。通常の LAN の HTTP はキャッシュに対応しません。時計ページと表示リソースのみを保存し、管理画面・API・カレンダー応答は保存しません。切断中は保存済み設定とブラウザー内のリマインダーを使用し、再接続後にサーバーデータが戻ります。

管理画面から JSON バックアップを保存・読み込みできます。検証と確認後、サーバーの表示設定と手動リマインダーを置き換えます。上限は 1 MiB、1,000 件、1 件あたり 1,000 文字です。カレンダー URL とブラウザー内のリマインダーは含みません。読み込み前のデータは `webclock_state/before-import.json` に保存され、読み込みごとに更新されます。書き込み失敗時は復元を試みます。中断や復元失敗の場合はサービス復旧後に同じ画面からこのファイルを読み込んでください。ホスト移行時は `webclock_state/calendar.json` と `.env` も別途保存してください。

すべてのインストール方法で旧リマインダーを一度だけ `webclock_state/manual_notes.json` にコピーし、元ファイルを保持したまま新しい保存先を使います。既存の移行先は上書きしません。明示的な `NOTES_FILE` 設定も有効です。`.env`、旧リマインダー、状態ディレクトリ全体をバックアップしてください。Linux サービスの更新は `sudo bash update_clock.sh` で行います。`venv/` と全データのバックアップ容量を確保し、更新完了まで管理画面の編集を控えてください。外部の場所を含む `WEBCLOCK_STATE_DIR` と `NOTES_FILE` も保護します。設定・リマインダー・管理／装置 API を検査し、失敗時はコード・パッケージ・データの復元を試みます。パス一覧と失敗時のデータは `.webclock-update-*` に保持します。Git は変更のない作業ツリーと fast-forward 更新が必要で、競合や危険なデータパスは拒否します。非 Git 環境の上書き済みコードや停電後の自動復旧は保証しません。旧更新スクリプトから初めて移行する場合は、旧サービスを動かしたまま、ソースを取得して置き換える前に上記の単独更新コマンドを実行してください。Docker はソースを更新した後、`docker compose up -d --build` を実行します。

## Support WebClock

All WebClock features are currently free to use. If you enjoy the project, you're welcome to support its development. Thank you!

<!-- Brand assets: https://www.paypalobjects.com/paypal-ui/logos/svg/paypal-mark-color.svg | https://storage.ko-fi.com/cdn/cup-border.png | O’Pay and ECPay logos supplied by the project owner -->
<table>
  <tr>
    <td align="center" width="160">
      <a href="https://www.paypal.com/paypalme/oilstuck">
        <img src="doc/images/support/paypal.svg" height="48" alt="Support development via PayPal"><br>
        <strong>PayPal</strong>
      </a>
    </td>
    <td align="center" width="160">
      <a href="https://ko-fi.com/kcayut">
        <img src="doc/images/support/ko-fi.png" height="48" alt="Support development via Ko-fi"><br>
        <strong>Ko-fi</strong>
      </a>
    </td>
    <td align="center" width="220">
      <a href="https://payment.opay.tw/Broadcaster/Donate/6CF8CF9E519E0ED13E244399607ADDD7">
        <img src="doc/images/support/opay.png" height="48" alt="Support development via O’Pay"><br>
        <strong>O’Pay (歐付寶)</strong>
      </a><br>
      O’Pay member ID: 2218408
    </td>
    <td align="center" width="160">
      <a href="https://p.ecpay.com.tw/A2FA21C">
        <img src="doc/images/support/ecpay.png" height="48" alt="Support development via ECPay"><br>
        <strong>ECPay (綠界科技)</strong>
      </a>
    </td>
  </tr>
</table>

## 問題與建議 · Feedback

歡迎透過 [Issues](https://github.com/kcayut/webclock/issues) 回報問題或提出建議。
