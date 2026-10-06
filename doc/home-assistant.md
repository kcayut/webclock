# Home Assistant

WebClock 可作為 Home Assistant（HA）的受管顯示來源。一次加入建立一個裝置身份，時間、行事曆、鬧鐘三種卡片共用該身份；群組與內容仍由 WebClock 後台管理。

## 安裝與加入

1. 更新 WebClock Server 至包含 `/api/v2/device/token/prepare`、`token/join`、`token/leave` 的版本。本次程式須先部署至你的 Server；只有安裝 HA 整合不會更新 Server。
2. 將本專案的 `custom_components/webclock` 整個資料夾複製到 HA 的 `/config/custom_components/webclock`，重新啟動 HA。這是自訂整合，目前使用手動安裝。
3. 在 WebClock「裝置」管理頁建立群組、勾選要顯示的行事曆／提醒／鬧鐘，產生六位英數加入碼。新群組沒有指派內容時只顯示時間。
4. HA → 設定 → 裝置與服務 → 新增整合 → 搜尋 **WebClock**，輸入 Server 位址及加入碼，例如 `A7K9M2`。位址使用 `https://clock.example` 或可信任自用區網的 `http://192.168.1.20:5000`；目前不支援反向代理子路徑。
5. 帳密／受管部署必須使用有效憑證的 HTTPS；整合不提供略過 TLS 驗證的選項。Server 位址必須從 HA 主機可達。
6. 加入後，在 WebClock 裝置面板可看到類型 `homeassistant` 的裝置。HA 建立時間、行事曆、鬧鐘三個 sensor。HA 重啟、重新載入及增加卡片會沿用原身份，不再消耗加入名額。

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

三種卡片支援繁體中文、English、日文，跟隨 Server 群組的顯示語言、時區與 12／24 小時制。HA 的整合設定頁則跟隨 HA 介面語言。

## 卡片與同步

- **時間**：透過 HA 取得 WebClock Server 校時基準，瀏覽器使用單調時間持續走時；不以瀏覽器或 HA 主機時鐘當成 Server 時間。首次尚未校時時可顯示瀏覽器時間；校時後短暫斷線沿用最後基準。背景休眠後需重新校時，不保證 OS 暫停期間的精度。
- **行事曆**：呈現 Server 的授權顯示清單，包括目前顯示視窗內的行事曆與文字提醒。這是 WebClock 卡片，不建立可任意查詢日期範圍或編輯事件的 HA `calendar` entity；不下發私人 ICS 網址。
- **鬧鐘**：呈現已啟用數量與各鬧鐘下一次觸發時間。排程與假日／行事曆聯動由 Server 計算，顯示時區不改變既有排程時區。新增、編輯及停用鬧鐘仍在 WebClock 管理頁操作。
- **同步**：每個 HA 整合實例共用一次 15 秒輪詢，驗證顯示及鬧鐘快照版本一致後才更新並回報。後台的同步 ACK 表示資料已取得，不代表揚聲器已播放。
- **停用與撤銷**：停用後清除目前私人顯示並繼續檢查，恢復時可自動回來；撤銷憑證後透過 HA 的重新授權提示輸入新碼。離線資料只在 Server 授權租約內有效，期限到即清除行程與待執行鬧鐘。已校準時間可繼續顯示。
- **移組**：沿用同一身份，刷新後顯示新群組內容，舊清單不與新群組混合。不同群組可新增不同 HA 整合實例；不要為三張相同群組卡片各加一份整合。
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

## 驗證

測試環境：Home Assistant Core **2026.9.4**、Python **3.14**。其他 HA 版本尚未逐一驗收。

```bash
python -m unittest discover -s tests -p 'test_*.py'
# 下列測試另外需要 Home Assistant 與 WebClock 的 Python 依賴：
python -m unittest discover -s homeassistant_tests -v
node tests/test_homeassistant_cards.js
node --check custom_components/webclock/www/webclock-cards.js
```

本機驗證已通過 Server 266 項測試、既有 JavaScript 回歸、HA 6 項整合／HTTPS 測試及卡片測試。在隔離的真實 HA 安裝中，也已操作錯碼重試保留輸入、六碼加入、三卡共用單一裝置、桌面／手機顯示、重啟保留身份及選項、到點只發一次事件、後台改名、停用／恢復、移組內容隔離與同步 ACK。正式環境部署、使用者的 HA 主機、實際通知／揚聲器及 ESP／舊 iPad 實機尚未驗收。

測試環境限制：macOS 上的隔離 HA Core 程序兩次在收到停止訊號後，以 SIGSEGV／139 結束；崩潰堆疊位於 Python 3.14.6 清理物件與模組階段，原因尚未定位。重新啟動後身份與資料仍可恢復，但不能據此宣稱主機穩定性已通過。該環境也未配置 FFmpeg／TTS，未進行聲音播放驗收。

官方介面參考：[設定流程](https://developers.home-assistant.io/docs/core/integration/config_flow/)、[DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/)、[自訂卡片](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)、[WebSocket 擴充](https://developers.home-assistant.io/docs/frontend/extending/websocket-api/)。
