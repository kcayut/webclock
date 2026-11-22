# 安裝 WebClock MCP，讓 AI 設鬧鐘與新增行程

**把 MCP 裝在執行 AI 助理的電腦。** 例如 WebClock 架在 NAS、Codex 跑在 Mac，就在 NAS 核發憑證，在 Mac 設定 MCP。之後每次助理需要工具時，會自行啟動本機 MCP，再透過網路呼叫 NAS 上的 WebClock API。NAS 只需維持 WebClock Server 運作。

## 1. 在 WebClock 授權給助理

1. 開啟自行架設的 WebClock 管理頁，進入「程式存取」（`/integrations`），建立名為「AI 助理」的專用憑證。
2. 若要使用全部工具，勾選「讀取鬧鐘」、「新增、修改及刪除鬧鐘」、「讀取事件」、「新增、修改及刪除事件」及「指派內容」。
3. 展開「接收對象與既有內容」，選取允許助理指派的群組或已配對裝置，例如「臥室」。複製新憑證，完整值只顯示一次。

## 2. 在助理的電腦準備檔案

使用支援本機 **stdio MCP** 的 AI 助理。Server 版本須提供 `/api/v1/control/targets`。從同版 WebClock 原始碼或 Server 套件取得 `scripts/webclock_mcp.py` 和 `scripts/control_clock.py`，在助理電腦上保留這兩個檔案相鄰的目錄結構。以下指令適用於 macOS／Linux，請先在終端機進入含有 `scripts/` 的 WebClock 目錄。

安裝 uv 後執行 `uv --version` 確認可用。使用 Homebrew 的 Mac 可執行 `brew install uv`。首次啟動時，uv 會依腳本要求準備 Python 環境並下載 MCP SDK。[uv 安裝方式](https://docs.astral.sh/uv/getting-started/installation/)

建立只有自己可讀寫的設定檔：

```sh
mkdir -p "$HOME/.config/webclock"
(umask 077 && touch "$HOME/.config/webclock/mcp.env")
chmod 600 "$HOME/.config/webclock/mcp.env"
nano "$HOME/.config/webclock/mcp.env"
```

填入助理電腦可連到的 **WebClock 網址** 和剛核發的憑證。網址填到主機與連接埠即可，請省略 `/admin`、`/integrations` 等路徑。將實際憑證保存在這個檔案，助理的 MCP 設定只需要檔案路徑。

```dotenv
WEBCLOCK_SERVER_URL=https://clock.example
WEBCLOCK_WRITE_TOKEN=請換成剛核發的程式憑證
```

## 3. 註冊 MCP，依助理選一種方式

### Codex CLI

從 WebClock 目錄複製執行：

```sh
codex mcp add webclock -- "$(command -v uv)" run --env-file "$HOME/.config/webclock/mcp.env" --script "$PWD/scripts/webclock_mcp.py"
```

執行 `codex mcp get webclock` 可檢查已登錄的命令和路徑。開啟新的 Codex 工作階段後，繼續下一節的連線測試。

### 使用 JSON 設定的桌面助理

在助理的 MCP 設定中，將 `webclock` 加到既有的 `mcpServers`。以下以 Mac 為例；請將三個絕對路徑換成自己的位置。`command -v uv` 可查出 uv 的實際路徑。

```json
{
  "mcpServers": {
    "webclock": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "run",
        "--env-file", "/Users/mei/.config/webclock/mcp.env",
        "--script", "/Users/mei/WebClock/scripts/webclock_mcp.py"
      ]
    }
  }
}
```

儲存後重新載入 MCP 或重啟助理。兩種設定都由助理管理 MCP 程序，平常無須開另一個終端機。

## 4. 先查詢，再試一次寫入

先問 **「我可以設定哪些 WebClock 時鐘？」**。助理應呼叫 `list_targets`，回傳已授權的群組或裝置名稱。這一步能確認助理、憑證和 Server 都已接通。接著把下方的「臥室」換成清單中的實際名稱。

| 你可以這樣說 | 預期結果 |
| --- | --- |
| 明天早上七點半在臥室叫我起床。 | 建立明天 07:30 的一次性鬧鐘，並指派給臥室。鬧鐘依台北時間排程。 |
| 明天下午兩點到三點，幫我在 WebClock 加個牙醫回診。 | 本地行事曆新增 14:00–15:00 的行程。單獨新增行程不會安排響鈴。 |
| 明天下午兩點到三點加個牙醫回診，提前十五分鐘在臥室提醒我。 | 一次建立行程和 13:45 的聯動鬧鐘。若之後將行程改為 15:00 開始，提醒也會移到 14:45。 |

可在 WebClock 管理頁查回行程、鬧鐘及指派。助理回覆「已指派」代表伺服器已記錄目標；實際響鈴還需要裝置完成同步。網頁時鐘的播放條件見[顯示裝置指南](display-devices.md)。

### 選用 Skill

四個工具都可以直接透過 MCP 使用。若助理也支援 Agent Skills，可把整個 [webclock Skill 資料夾](../../scripts/skills/webclock/) 複製到該助理的 skills 目錄，再重新載入。Skill 說明如何處理「明早」、同名房間與「加行程並提前提醒」等說法。

## 遇到問題時

| 現象 | 檢查方式 |
| --- | --- |
| 助理找不到 WebClock 工具 | 確認助理支援本機 stdio MCP，檢查 uv 和兩個腳本的位置，重新載入助理。首次啟動需要網路下載 SDK。 |
| 顯示 `cannot_connect` 或 `invalid_server_url` | 從助理電腦開啟 Server 網址。核對通訊協定、主機、連接埠與 HTTPS 憑證。 |
| 顯示 `missing_or_invalid_write_token` 或 `authentication_required` | 核對設定檔路徑及程式憑證。若憑證過期或已撤銷，重新核發、更新檔案並重啟助理。 |
| 時鐘清單為空或出現 `permission_denied` | 在「程式存取」核對權限與可指派對象，並確認群組已啟用、裝置已配對。 |
| 助理回報已建立，但無法確認指派 | 依回傳的項目 ID 到管理頁檢查。連線中斷後，請助理用原請求 ID 重試，可避免重複新增。 |

目前可寫入 WebClock 本地行事曆。Google／iCloud 訂閱的讀取與聯動範圍、憑證撤銷和重試行為見[程式寫入 API](../api/control-api.md)。
