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

第一次請連線開啟，等頁面顯示「已可離線開啟」後，即可在斷網時重新開啟或重新整理。瀏覽器清除網站資料或回收快取後，需要再次連線準備。也可下載原始碼，以支援本機網頁的瀏覽器開啟 `index.html`，並保留旁邊的 `static/` 資料夾。

### 選擇使用方式

| 功能 | 線上時鐘 | 自行架設 |
| --- | --- | --- |
| 時間、日期、星期 | ✓ | ✓ |
| 時區 | 跟隨裝置 | 後台指定，預設 UTC+8 |
| Google Calendar、手動提醒 | — | ✓ |
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

手動提醒可設定指定日期時間，或每週／每日固定顯示時段。固定時段可勾選星期；不勾選代表每天。跨午夜的時段歸屬開始的那一天，例如週一 22:00 至週二 06:00，只需勾選星期一。每天時段支援跨午夜，例如 22:00 至隔天 06:00。開始與結束不可相同；兩欄清空可取消時段限制。時段依後台時區計算，包含開始時間、不包含結束時間。到期提醒只隱藏，不會刪除；一般會在約 5 秒內更新畫面。

未設定時段的提醒，有日期時只在當天顯示，沒有日期則持續顯示。設定時段後，以時段決定顯示範圍。這些限制適用於後台手動提醒。「編輯提醒」可修改文字、日期、時間及顯示區間；「暫停」會保留內容，但停止顯示與倒數，按「恢復」即可啟用。

自架時鐘載入後若暫時失去伺服器連線，會使用可用的時間基準、瀏覽器保存的顯示設定及本機提醒繼續運作。Google Calendar 與伺服器提醒會在重新連線後恢復。畫面右下角的連線按鈕可設定伺服器網址並重新連線。

### 夜間模式、倒數與離線使用

在後台啟用「自動夜間模式」，設定開始、恢復日間時間與夜間亮度，也可選擇夜間黑畫面。排程依後台時區每天執行，包含開始、不包含結束；日間恢復原本亮度，手動黑畫面優先。這是網頁顯示調整，不會改變裝置背光或自動鎖定設定。斷線時會沿用瀏覽器保存的排程。

提醒區下方會顯示下一個行程還有幾分鐘。指定日期提醒使用其提醒時間（未填時間時可使用顯示區間的開始）；每週／每日提醒使用下一次顯示時段的開始；Google Calendar 使用當日有時間的行程。全天事項不以午夜倒數。暫停的提醒不參與倒數。

自架版的離線準備狀態在右下角連線面板中。離線重新開啟需要支援的瀏覽器，以及 HTTPS 或本機 localhost；一般 `http://區網IP` 不支援這項快取，但已載入的頁面仍可繼續計時。快取只包含時鐘頁面與顯示資源，不包含後台、API、私人日曆或伺服器提醒。斷線時仍使用原有瀏覽器本機提醒，重新連線才恢復伺服器資料。

### 備份與還原

在後台下載 JSON 備份，可保存伺服器顯示設定（含夜間排程）與手動提醒（含星期及暫停狀態）。選擇備份檔案並按「匯入並取代」，確認後會取代目前設定與提醒；系統先驗證完整資料才寫入。上限為 1 MiB、1,000 筆提醒，每筆內容最多 1,000 字元。

匯入前的資料會保留在 `webclock_state/before-import.json`，可用相同匯入功能還原；每次匯入會更新這份備份。寫入失敗時會嘗試回復原提醒。若突然斷電或回復失敗，請保留該檔案並在服務恢復後還原。

備份不包含 `.env` 中的私人行事曆網址，也不包含瀏覽器本機提醒；搬移主機時仍須另外保存 `.env`。

### 資料保存與更新

請備份以下檔案與目錄，搬移主機時也一併保留：

| 路徑 | 內容 |
| --- | --- |
| `.env` | 行事曆網址與伺服器設定 |
| `manual_notes.json` | 手動提醒 |
| `webclock_state/` | 顯示與夜間設定、匯入前備份，以及 Docker 版的手動提醒 |

Docker Compose 會將以上資料保存在主機。Docker 首次啟動新版時，會將舊 `manual_notes.json` 複製至 `webclock_state/manual_notes.json`，原檔保留；之後以新位置為準，不會重複覆蓋。Linux／手動安裝仍使用原本的 `manual_notes.json`。更新 Docker 安裝可在取得程式更新後，再執行 `docker compose up -d --build`。

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

In Safari on iPad, use **Share → Add to Home Screen** for quick access. Adjust Auto-Lock and brightness in the device settings as needed. Connect once and wait for the offline-ready indicator before reopening or reloading without a connection. Clearing site data or browser cache eviction requires another online visit. A downloaded `index.html` can also be opened in a browser that supports local pages, with the `static/` folder alongside it.

### Self-hosting

For Google Calendar, reminders, holiday highlighting, brightness and black-screen controls, run the full version on your own computer, NAS, or Raspberry Pi. The admin page at `/admin` supports Traditional Chinese, Simplified Chinese, English, and Japanese. It saves display settings across restarts and lets you select the timezone (default UTC+8).

Follow the shared [installation commands](#self-hosting): clone the repository, copy `.env.example` to `.env`, and optionally set `ICAL_URL` to your private calendar URL. Choose Docker, the apt/systemd Linux installer, or a manual Python run. Docker uses host port `80`; the other methods default to `5000`. Keep private calendar URLs out of the public repository.

Reminders support a date/time range or a weekly/daily time window, including overnight windows. Select weekdays or leave all unchecked for every day. Overnight windows belong to their starting weekday. Edit text, dates and windows in place, or pause and resume without deleting. Windows use the admin timezone, include the start, and exclude the end. Expired reminders are hidden rather than deleted. While disconnected from the server, the loaded page uses cached display settings and browser-local reminders; calendar events and server reminders return after reconnection. The bottom-right button opens connection settings.

Automatic night mode dims or blacks out the page on a daily schedule in the admin timezone, then restores daytime brightness. Manual black screen takes priority. It changes page appearance, not the hardware backlight. The next-event countdown uses dated reminder times, the next recurring window start, or today's timed calendar events; paused reminders and all-day calendar events are excluded.

Offline reopening requires HTTPS or localhost and a completed online setup, shown in the connection panel. Plain LAN HTTP cannot prepare the offline cache. Only the clock shell is cached, never admin/API/calendar responses. Disconnected pages use cached display settings and browser-local reminders; server data returns on reconnection.

Download or import a JSON backup from the admin page. Import replaces server display settings and manual reminders after validation and confirmation. Limits: 1 MiB, 1,000 reminders, 1,000 characters per reminder. Private calendar URLs and browser-local reminders are excluded. Pre-import data is retained in `webclock_state/before-import.json` (replaced on each import); failed writes attempt rollback. After interrupted or failed recovery, restore that file through the same import action. Keep `.env` separately when moving hosts.

Docker copies legacy reminders once into `webclock_state/manual_notes.json`, preserving the original file and using the new location thereafter. Linux/manual installations retain `manual_notes.json`. Back up `.env`, `manual_notes.json`, and `webclock_state/`. Update a Linux service with `sudo bash update_clock.sh`; updates briefly stop the service and require space to back up `venv/`. Failed updates attempt recovery and retain backup files. For Docker, obtain the updated source and run `docker compose up -d --build`.

## 日本語

### 公開時計を使う

**[WebClock](https://kcayut.github.io/webclock/)** を開くだけで、タブレットや使っていない画面を大きな時計にできます。横向きでの利用がおすすめです。時刻とタイムゾーンは端末の設定に従い、日付と曜日は繁体字中国語で表示します。

iPad の Safari では「共有 → ホーム画面に追加」で入口を作れます。自動ロックと明るさは端末の設定で調整してください。初回はネット接続し、「已可離線開啟」の表示を待つと、オフラインでも開き直したり再読み込みできます。ブラウザーがサイトデータやキャッシュを削除した場合は、再度接続してください。ダウンロードした `index.html` は、隣の `static/` フォルダーを残したまま、ローカルページ対応ブラウザーで開くこともできます。

### セルフホスト

Google Calendar、手動リマインダー、休日表示、明るさ・黒画面の切り替えには、パソコン、NAS、Raspberry Pi などで完全版を実行します。管理画面は `/admin` で、繁体字中国語、簡体字中国語、英語、日本語に対応しています。タイムゾーンの初期値は UTC+8 です。表示設定は再起動後も保持されます。

上記の[インストール手順](#self-hosting)でソースを取得し、`.env.example` を `.env` にコピーします。カレンダーを使う場合のみ `ICAL_URL` を設定してください。Docker、apt/systemd を使う Linux 用スクリプト、Python の手動実行から選べます。既定のホスト側ポートは Docker が `80`、その他は `5000` です。非公開のカレンダー URL を公開リポジトリに含めないでください。

リマインダーは日時範囲または毎週・毎日の表示時間帯を指定できます。曜日未選択は毎日で、日付をまたぐ時間帯は開始日の曜日に従います。内容や日時を直接編集でき、削除せず一時停止・再開できます。管理画面のタイムゾーンを使い、開始を含み、終了は含みません。期限後は削除せず非表示にします。サーバーと切断された場合、読み込み済みのページは保存済み表示設定とブラウザー内のリマインダーで動作を続けます。カレンダーとサーバー側リマインダーは再接続後に戻ります。右下のボタンから接続設定を開けます。

自動ナイトモードは管理画面のタイムゾーンで毎日暗くするか黒画面にし、終了後は昼間の明るさに戻します。手動の黒画面が優先され、ハードウェアのバックライトは変更しません。次の予定までの分数は、日時付きリマインダー、繰り返し時間帯の次の開始、当日の時刻付きカレンダー予定から表示します。停止中の項目と終日のカレンダー予定は対象外です。

オフラインで開き直すには HTTPS または localhost と、接続中の準備完了が必要です。接続パネルで状態を確認できます。通常の LAN の HTTP はキャッシュに対応しません。時計ページと表示リソースのみを保存し、管理画面・API・カレンダー応答は保存しません。切断中は保存済み設定とブラウザー内のリマインダーを使用し、再接続後にサーバーデータが戻ります。

管理画面から JSON バックアップを保存・読み込みできます。検証と確認後、サーバーの表示設定と手動リマインダーを置き換えます。上限は 1 MiB、1,000 件、1 件あたり 1,000 文字です。非公開カレンダー URL とブラウザー内のリマインダーは含みません。読み込み前のデータは `webclock_state/before-import.json` に保存され、読み込みごとに更新されます。書き込み失敗時は復元を試みます。中断や復元失敗の場合はサービス復旧後に同じ画面からこのファイルを読み込んでください。ホスト移行時は `.env` も別途保存してください。

Docker は旧リマインダーを一度だけ `webclock_state/manual_notes.json` にコピーし、元ファイルを保持したまま新しい保存先を使います。既存の移行先は上書きしません。Linux・手動インストールは従来の `manual_notes.json` を使います。`.env`、`manual_notes.json`、`webclock_state/` をバックアップしてください。Linux サービスの更新は `sudo bash update_clock.sh` で行います。更新中は一時停止し、`venv/` のバックアップ容量が必要です。失敗時は復元を試み、バックアップを保持します。Docker はソースを更新した後、`docker compose up -d --build` を実行します。

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
