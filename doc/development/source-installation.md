# 原始碼安裝與本機執行

[正式版安裝](../installation.md) · [HTTPS 與帳號](../operations/accounts-and-https.md)

Linux 需 Debian／Ubuntu／Raspberry Pi OS、systemd 與 sudo 權限；Docker 需已啟動的 Docker Engine 與 Compose。預設為 self 模式，管理頁僅適合可信任區網。

<a id="source-install"></a>
## 從原始碼安裝與本機建置

適合需要檢查／修改程式，或已有完整原始碼的使用者。需先準備 Git；也可以下載 Release 的 **Source code (zip)**，完整解壓後進入包含 `app.py`、`setup.sh` 與 `requirements.txt` 的目錄。

```bash
git clone --branch v1.2.0 https://github.com/kcayut/webclock.git webclock
cd webclock
```

`v1.2.0` 是固定版本範例；要測試開發中程式可省略 `--branch v1.2.0`，但 `main` 不等於已公開驗收的版本。已有 checkout 者不必重新 clone，也不要為安裝而覆蓋本機修改。

選擇其中一種：

```bash
# Debian／Ubuntu／Raspberry Pi OS，建立 systemd 服務：
bash setup.sh
```

```bash
# 已有 Docker Compose，以這份原始碼建置並啟動：
bash setup.sh --docker --build
```

兩者預設為 self；加上 `--managed` 可啟用帳號管理，提供 [TLS 參數](../operations/accounts-and-https.md#https)，或在未配置憑證時經二次確認選擇內網 HTTP。`bash setup.sh --docker` 不加 `--build` 會取得預建映像，**不會把本機原始碼修改放進容器**。套件安裝與映像建置仍需網路，下載原始碼不等於離線安裝包。

原始碼 Linux 安裝保留原本 Git upstream，不會自動改成正式 Release 管道；ZIP 沒有 Git 歷史，不應假定可套用 Git 更新／回退流程。長期部署且希望跟隨正式版時，使用[正式版安裝器](../installation.md)。

<a id="manual-python"></a>
## 其他設定與手動 Python 執行

行事曆網址、顯示語言、亮度、鬧鐘與群組都在管理頁設定。管理側欄的語言只改目前瀏覽器的管理介面；「全體預設顯示語言」才會改時鐘的預設語言。

需要預先自訂原始碼安裝時，僅在 `.env` 尚不存在時複製 `.env.example`，再編輯 `.env`；安裝腳本保留已有設定。Linux 連接埠用 `PORT`，Docker 主機連接埠用 `WEBCLOCK_HTTP_PORT`，初始時鐘語言用 `WEBCLOCK_LANGUAGE=zh-TW`／`en`／`ja`。私人 iCal 網址在 `/admin` 設定，不必放到 `.env`。

不用 systemd 或 Docker 的開發／測試環境，先依[原始碼步驟](#source-install)取得程式。以下為 macOS／Linux 的 Bash 指令，需要已安裝的 Python 3、pip 與 venv；Python 依賴以 `requirements.txt` 為準，Docker 參考環境使用 Python 3.13。從專案根目錄執行：

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
# 只建立缺少的設定檔，保留既有內容：
if [ ! -e .env ]; then (umask 077; cp .env.example .env); fi
# 本機試用只監聽 loopback，避免 self 管理頁對區網開放：
HOST=127.0.0.1 ./venv/bin/python app.py
```

開啟 `http://127.0.0.1:5000/admin`；若 5000 已占用，在最後一行前加 `PORT=5001` 並改開 5001。要讓可信任區網裝置連線，改用 `HOST=0.0.0.0`，裝置開啟這台電腦的 IP，不能填 `localhost`。資料預設寫入專案的 `webclock_state`，請保留整個目錄。

按 `Ctrl+C` 停止；下次在同一目錄執行最後一行即可，不必重建環境。此方式不建立開機啟動、背景服務或更新器。若要 managed，先停止程式、備份資料，再以同一個 `./venv/bin/python` 執行[管理員設定](../operations/accounts-and-https.md#enable-managed)中的 `scripts/manage_auth.py` 命令並配置 [HTTPS 或明確確認內網 HTTP](../operations/accounts-and-https.md#https)；手動執行者不使用 `systemctl` 停止／啟動。Windows 請參考 [Docker 安裝](../installation.md#docker)；原生 Python 執行尚未驗收。

<a id="ha-local"></a>

<details>
<summary>開發測試／尚未發布的版本：本機建置</summary>

從可讀寫 `/addons` 的 Terminal／SSH App 執行，需有 Git 與 Bash：

```bash
git clone https://github.com/kcayut/webclock.git && cd webclock && bash homeassistant/prepare_local_app.sh
```

接著在 App 商店「檢查更新」→ **Local apps → WebClock → 安裝 → 啟動**。腳本只準備檔案，不會啟動 Server；會移除產物的 `image` 設定，讓 HA 自行建置。

也可在另一台電腦的專案根目錄執行 `bash homeassistant/prepare_local_app.sh /tmp/webclock-ha-app`，再透過 Samba 把產物複製為 HA 的 `addons/webclock`。目的地已存在時會停止，不會覆蓋。Local App 和商店 App 是不同安裝，資料不會自動搬移；可用[完整備份](../guides/guide.md#完整備份與搬家)搬到新 App，確認新 App 正常後才退役舊安裝。只更新既有 Local App 者依[本機更新流程](../operations/update-operations.md#日常更新)操作。

</details>

發行與驗收狀態見 [HA 發行說明](../ha-release.md)。官方依據：[App 來源](https://developers.home-assistant.io/docs/apps/repository/)、[預建映像](https://developers.home-assistant.io/docs/apps/publishing/)與[本機建置](https://developers.home-assistant.io/docs/apps/testing/)。
