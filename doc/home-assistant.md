# Home Assistant

WebClock 可直接以 Home Assistant App 執行，不必另外架設 Server；自訂整合則把同一台 Server 的時間、行事曆與鬧鐘帶進 HA。HA 只允許一份 WebClock 整合及一個群組，三種卡片共用該身份；完整群組與裝置管理仍在 WebClock 管理頁進行。

**安裝順序：Server → Integration → Card。** Server 可放在 HA OS、bare metal 或 Docker；已經有 Server 就直接從[安裝整合](#安裝整合)開始。卡片包含在整合裡，不用另外下載或設定 JavaScript 資源。

## 安裝前確認

- Home Assistant **2026.9.4 或更新版本**；最低測試版本為 2026.9.4，後續版本仍須對應驗收。
- 已有可連線的 WebClock Server；要讓 HA 主機執行 Server，先安裝下面的 App。
- 已有 HACS 可直接用按鈕安裝；沒有 HACS 可照[官方步驟](https://www.hacs.xyz/docs/use/download/download/)安裝，或使用本文收合的手動方式。

## 在 Home Assistant 內執行 WebClock Server

安裝方式見[安裝指南：Home Assistant](installation.md#home-assistant)：加入 WebClock App 來源，安裝並啟動，再按「開啟網頁介面」。App 與整合對應同一個 [GitHub 正式 Release](https://github.com/kcayut/webclock/releases/latest)；公開映像與 HA OS 實機驗收狀態見[發行說明](ha-release.md)。

| 用途 | 入口與設定 |
| --- | --- |
| 管理 WebClock | App「開啟網頁介面」，由 HA 登入保護；匯入 managed 備份後仍須登入原 WebClock 帳號 |
| 連接同機 HA 整合 | 複製 App 日誌 `Home Assistant integration URL:` 後的完整網址，不需開放主機連接埠 |
| 平板／電腦顯示 | 映射 App 的 `8100/tcp`，開啟 `http://HA主機IP:8100` 並輸入群組六碼；此入口不提供管理頁 |
| 保存 App 資料 | `/data` 由 HA 冷備份保存；跨主機搬家使用完整 `.webclock` 備份 |

整合不能使用 Ingress 管理網址。若手動填 App 主機名稱，須包含商店來源前綴；本機 App 範例為 `http://local-webclock:8100`。外部顯示裝置可加入其他群組，設定全螢幕與恆亮見[裝置指南](guides/display-devices.md)。App 可管理成員，但不提供模式切換或首次 managed 啟用。

## 從既有 Server 搬進 HA App

1. 舊 Server「備份與還原」下載完整 `.webclock`，預設以至少 12 字元的密碼加密。
2. 新 App「備份與還原」選檔，加密檔輸入密碼，預覽並核對資料數量。
3. 停止舊 Server，確認使用最新備份，再確認取代並還原；managed 使用原 WebClock 帳密登入。

**已有資料的目標會撤銷裝置與程式憑證，須重新加入或建立。** 全新目標保留這兩類憑證，但登入 session 與舊邀請不延續。原瀏覽器要接續還須沿用相同 HTTPS 來源及 Cookie；TLS／DNS、系統服務、瀏覽器資料與 App options 不在還原範圍內。

未加密檔含私人行事曆及授權資料，須妥善保存。詳細範圍與失敗處理見[備份指南](guides/guide.md#完整備份與搬家)；HA OS 實機搬移仍待驗收。

## 自訂整合安裝前準備

1. WebClock Server 須更新至包含 `/api/v2/device/token/prepare`、`token/join`、`token/leave` 的版本。
2. 確認 HA 主機可以連到 WebClock Server。受管部署預設使用有效憑證的 HTTPS；可信任內網的 self 或已在主機明確啟用 HTTP 的 managed 可以使用 HTTP。HA App 的 Ingress 也可搭配沒有 TLS 的內網 HA。
3. WebClock Server 位址只填來源，例如 `https://clock.example`、`http://192.168.1.20:5000`，或上述 App 日誌中的整合網址。自訂整合目前不接受任意反向代理子路徑；App 的 Ingress 子路徑由 Server 自動處理。

## 安裝整合

**[在 HACS 開啟 WebClock](https://my.home-assistant.io/redirect/hacs_repository/?owner=kcayut&repository=webclock&category=integration)** → 確認加入自訂儲存庫 → **下載** → **重新啟動 Home Assistant**。

若按鈕未找到儲存庫：在 **HACS → 右上選單 → 自訂儲存庫**，填 `https://github.com/kcayut/webclock`，類型選 **Integration**，加入後下載 WebClock。這是 HACS 自訂來源，尚非 HACS 預設清單或 HA 官方內建整合。請選正式 Release 版本；HACS 依該版本取得 `hacs.json` 與 `custom_components/webclock`，卡片版本也一起更新。

重啟後，**[新增 WebClock 整合](https://my.home-assistant.io/redirect/config_flow_start/?domain=webclock)**，或進入 **設定 → 裝置與服務 → 新增整合 → WebClock**，依下節填 Server 位址與加入碼。

<details>
<summary>不使用 HACS：手動安裝</summary>

從 [GitHub 最新正式版](https://github.com/kcayut/webclock/releases/latest)下載 **Source code (zip)** 並解壓縮，將 `custom_components/webclock` 整個資料夾複製到 HA 的 `/config/custom_components/webclock`，然後重新啟動 HA。請保留 `webclock` 這層目錄，不要只複製其中的 Python 檔案。

若可在 HA 主機使用終端機，可從 WebClock 專案根目錄執行：

```bash
mkdir -p /config/custom_components
cp -R custom_components/webclock /config/custom_components/
```

若重啟後搜尋不到 WebClock，先檢查 `/config/custom_components/webclock/manifest.json` 是否存在，再查看 HA 日誌中的自訂整合載入錯誤。

</details>

## 用六位加入碼連接

1. 在 WebClock 管理頁的「裝置」區建立或選擇群組，指派要顯示的行事曆、提醒與鬧鐘。
2. 為該群組產生六位英數加入碼，例如 `A7K9M2`。加入碼有期限與名額限制，並不是長期密碼。
3. 在 HA 新增 **WebClock** 整合，輸入 Server 位址與加入碼。整合不要求 WebClock 管理員帳密。
4. 成功後，WebClock 裝置面板會出現類型 `homeassistant` 的裝置；HA 會建立時間、行事曆、鬧鐘三個 sensor。

| Server 裝在哪裡 | 整合的 Server 位址範例 |
| --- | --- |
| 同一台 HA 的 WebClock App | 複製 App 日誌的整合網址，無需開放主機連接埠 |
| Bare metal 預設安裝 | `http://192.168.1.20:5000`，換成 Server 的 IP |
| Docker 預設安裝 | `http://192.168.1.20`，自訂主機連接埠時加上 `:連接埠` |
| 已設定 HTTPS | `https://clock.example`，使用憑證對應的主機名稱與連接埠 |

三個 sensor 及其卡片共用同一裝置身份。重新啟動 HA、重新載入整合或增加卡片不會再次註冊，也不會重複消耗加入名額。HA 只允許一份 WebClock 整合；要改用另一個群組，請在 WebClock 管理頁把這個 HA 裝置移到目標群組。

加入失敗時先確認加入碼尚未過期、群組仍啟用且名額未滿。受管模式拒絕無效憑證的 HTTPS；本整合不提供略過 TLS 驗證的選項。

## 加入儀表板卡片

卡片 JavaScript 由整合自動提供及載入，無需另填 token 或卡片資源網址。安裝後若儀表板已開啟，重新載入瀏覽器，再從新增卡片清單選擇 **WebClock Time / Calendar / Alarms**；選取該整合對應的 sensor 即可。

也可以使用手動卡片設定（entity ID 請以自己 HA 顯示的名稱為準）：

```yaml
type: vertical-stack
cards:
  - type: custom:webclock-time-card
    entity: sensor.webclock_time
  - type: custom:webclock-calendar-card
    entity: sensor.webclock_calendar
  - type: custom:webclock-alarm-card
    entity: sensor.webclock_alarms
```

三種卡片支援繁體中文、English、日文，跟隨 Server 群組的顯示語言、時區與 12／24 小時制。HA 的整合設定頁則跟隨 HA 介面語言。卡片是唯讀顯示；需要從 HA 建立、修改或指派行事曆與鬧鐘，可設定獨立程式憑證並使用 [WebClock actions](api/control-api.md#home-assistant-操作)，或在 WebClock 管理頁操作。

## 卡片與同步

- **時間**：透過 HA 取得 WebClock Server 校時基準，瀏覽器使用單調時間持續走時；不以瀏覽器或 HA 主機時鐘當成 Server 時間。首次尚未校時時可顯示瀏覽器時間；校時後短暫斷線沿用最後基準。背景休眠後需重新校時，不保證 OS 暫停期間的精度。
- **行事曆**：呈現 Server 的授權顯示清單，包括目前顯示視窗內的行事曆與文字提醒。這是 WebClock 卡片，不建立可任意查詢日期範圍或編輯事件的 HA `calendar` entity；不下發私人 ICS 網址。
- **鬧鐘**：呈現已啟用數量與各鬧鐘下一次觸發時間。排程與假日／行事曆聯動由 Server 計算，顯示時區不改變既有排程時區。新增、編輯及停用鬧鐘可在 WebClock 管理頁或已授權的 WebClock actions 操作。
- **同步**：每個 HA 整合實例共用一次 15 秒輪詢，驗證顯示及鬧鐘快照版本一致後才更新並回報。後台的同步 ACK 表示資料已取得，不代表揚聲器已播放。
- **停用與撤銷**：停用後清除目前私人顯示並繼續檢查，恢復時可自動回來；撤銷憑證後透過 HA 的重新授權提示輸入新碼。離線資料只在 Server 授權租約內有效，期限到即清除行程與待執行鬧鐘。已校準時間可繼續顯示。
- **移組**：沿用同一身份，刷新後顯示新群組內容，舊清單不與新群組混合。HA 儀表板固定使用這一份整合選定的群組；區網瀏覽器與 ESP 可各自配對其他群組。
- **移除**：從 HA 刪除整合時會嘗試退出 WebClock。Server 離線時仍可移除 HA 設定，但須在 WebClock 後台手動清除該裝置記錄。

HA 設定儲存中包含裝置憑證，請保護 HA 設定與備份。卡片設定、sensor 屬性與一般日誌不包含憑證；行事曆與鬧鐘清單屬性不寫入 HA recorder。撤權會停止本整合使用目前私人資料，但不會刪除使用者自行建立的外部歷史或自動化紀錄。

## 到點觸發 HA 自動化

預設只顯示鬧鐘。需要 HA 執行通知或播放時，開啟 WebClock 整合的「選項」→「發出 `webclock_alarm` 事件」，並建立自己的自動化。事件不直接播放聲音，不需要保持卡片或瀏覽器開啟。

```yaml
alias: WebClock 到點通知
triggers:
  - trigger: event
    event_type: webclock_alarm
    event_data:
      entry_id: REPLACE_WITH_YOUR_ENTRY_ID
actions: []
```

`entry_id` 可從這份整合任一 sensor 的屬性取得。將範例中的 `actions` 改成所需通知或媒體播放動作；事件提供 `entry_id`、`device_id`、`occurrence_id`、`alarm_id`、`name`、`starts_at`（Unix 毫秒）。選擇 HA 作為執行端時，將內容指派給專用群組，避免同一鬧鐘也指派給會響鈴的網頁／ESP。

同一實例的同次鬧鐘在發事件前先記錄，不因重啟或重複快照再次發送；錯過時間不補發。若恰在保存後、發送前當機，該次可能漏發，採「最多一次」而非宣稱保證送達。鬧鐘只在有效租約內排程，撤權／租約到期／卸載會取消待發事件；暫時斷線仍可能在有效租約內發事件。實際通知、揚聲器播放及播放完成由 HA 自動化負責驗收。

## 管理、更新與移除

新版感測器屬性提供 `integration_version`、`server_version` 與 `version_alignment`；舊 Server 未回報時為 `unknown`，不同版本為 `mixed`。這是執行中的版本資訊，不代表跨版本驗收通過。HACS 更新後仍須重啟 HA；卡片與執行中的整合不同版時，會提示重新載入瀏覽器。完整順序及完成判定見[更新維護流程](operations/update-operations.md#ha-的完成判定)。

- **改名、移組、停用、恢復、要求同步**：在 WebClock 裝置管理頁操作。HA 最多約 15 秒後取得更新；要求同步的 ACK 代表資料已取得，不代表通知或揚聲器已實際執行。
- **憑證撤銷**：WebClock 撤銷裝置後，HA 會要求重新授權。請在 WebClock 產生新的加入碼，再從 HA 的修復提示輸入；原裝置憑證不會恢復。
- **更新整合與卡片**：在 HACS 選 WebClock → 更新，重新啟動 HA 並重新載入瀏覽器；卡片一起更新。手動安裝者以新版 `custom_components/webclock` 覆蓋 HA 的 `/config/custom_components/webclock`。不要刪除 HA 的整合項目。
- **更改 Server 位址／搬家**：在 HA「設定 → 裝置與服務 → WebClock」的項目選單選「重新設定」，輸入新位址及新 Server 管理頁產生的六碼。成功後保留 HA 實體與卡片設定，建立新的 Server 裝置身份；失敗保留原連線。舊 Server 可連線時會嘗試退出，離線時請之後手動撤銷舊裝置。獨立程式寫入憑證會清除；需要 actions 時，再到選項填入新 Server 的程式憑證。
- **移除整合**：在 HA「設定 → 裝置與服務 → WebClock」刪除該項目。HA 會嘗試通知 Server 移除裝置；若 Server 當時離線，請再到 WebClock 裝置管理頁手動撤銷殘留裝置。

## 常見問題

- **卡片清單找不到 WebClock**：重新啟動 HA 後強制重新載入瀏覽器，並確認整合已成功載入。卡片資源由整合自動註冊，不需要手動新增 JavaScript URL。
- **只有時間，沒有行事曆或鬧鐘**：檢查 WebClock 群組是否已指派內容、裝置是否啟用，以及授權租約是否有效。新建的空群組原本就只顯示時間。
- **暫時斷線**：已校準時間會繼續顯示；私人行事曆與鬧鐘僅保留到 Server 核發的租約到期，之後會清除。
- **事件沒有播放聲音**：`webclock_alarm` 只是一個 HA 事件。必須另建自動化並指定通知或 `media_player` 動作；整合本身不直接控制揚聲器。

## 驗證

測試環境：Home Assistant Core **2026.9.4**、Python **3.14**。其他 HA 版本尚未逐一驗收。

```bash
python -m unittest discover -s tests -p 'test_*.py'
# 下列測試另外需要 Home Assistant 與 WebClock 的 Python 依賴：
python -m unittest discover -s homeassistant/tests -p 'test_webclock.py' -v
node homeassistant/tests/test_cards.js
node --check custom_components/webclock/www/webclock-cards.js
```

本次安裝交付與完整備份的測試結果及待驗收項目見[發行說明](ha-release.md#完整備份本機驗證2026-10-09)。較早版本曾通過 Server 269 項、HA 6 項整合／HTTPS 斷言及 JavaScript／卡片回歸；在隔離的真實 HA 安裝中，也已操作錯碼重試保留輸入、六碼加入、三卡共用單一裝置、桌面／手機顯示、重啟保留身份及選項、到點只發一次事件、後台改名、停用／恢復、移組內容隔離與同步 ACK。這些既有紀錄不代替本版 App 容器映像、正式部署、使用者 HA 主機、實際通知／揚聲器及 ESP／舊 iPad 的驗收。

測試環境限制：macOS 上的隔離 HA Core 程序兩次在收到停止訊號後，以 SIGSEGV／139 結束；崩潰堆疊位於 Python 3.14.6 清理物件與模組階段，原因尚未定位。重新啟動後身份與資料仍可恢復，但不能據此宣稱主機穩定性已通過。該環境也未配置 FFmpeg／TTS，未進行聲音播放驗收。

官方介面參考：[設定流程](https://developers.home-assistant.io/docs/core/integration/config_flow/)、[DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/)、[自訂卡片](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)、[WebSocket 擴充](https://developers.home-assistant.io/docs/frontend/extending/websocket-api/)。
