# WebClock App

啟動後按「開啟網頁介面」即可在 Home Assistant 側邊欄管理 WebClock。資料存放於 App 的 `/data`，會包含在 Home Assistant 的 App 備份中。

App 預設只開放 Ingress，不會把 WebClock 連接埠公開到區網。若要讓網頁時鐘、ESP 或其他區網裝置連線，請在 App 的「網路」設定將容器連接埠 `8100` 指定到一個主機連接埠，再使用 `http://HOME_ASSISTANT_IP:指定連接埠`。此連接埠只提供顯示、六碼配對與裝置同步；管理功能只能從 HA 的「開啟網頁介面」進入。

## 搬家與完整備份

1. 舊 WebClock 管理頁「備份與還原」預設以至少 12 字元的密碼加密；也可取消「以密碼加密（建議）」並下載未加密的完整 `.webclock` 檔。
2. 新 App 按「開啟網頁介面」，到「備份與還原」選檔；加密檔才須輸入備份密碼，再預覽資料數量。
3. 停止舊 Server，確認使用最後匯出的檔案，再確認取代並還原。managed 備份以原 WebClock 帳密重新登入。

兩種檔案都包含所有帳號、私人 iCal 網址、提醒、鬧鐘、原生事件、群組、裝置與程式授權。加密檔與密碼請分開保存，忘記密碼無法還原；未加密檔可被持有者直接讀取。管理員驗證不因未加密而略過。新 App 預設 self；匯入 managed 會保留原模式與帳號，HA 登入不會略過 WebClock 授權。managed 管理員可在「模式與帳號」(`/mode`) 管理成員，App 仍不提供模式切換。

只有全新、尚無資料的 App 會保留裝置與程式憑證；已有資料的 App 會撤銷兩者，需重新加入／建立。所有登入 session 與舊加入碼失效。原瀏覽器裝置要接續，須沿用相同 HTTPS 網域、協定與連接埠；換址仍需更新連線或重新加入。備份不包含 TLS／DNS、系統服務、瀏覽器本機資料，也不覆寫 App options。

完整還原會先保留私人復原紀錄，失敗回復原資料；中斷後啟動先處理復原。詳細範圍與保護見[完整備份指南](https://github.com/kcayut/webclock/blob/main/doc/guide.md#完整備份與搬家)。舊 JSON 部分備份仍在管理頁收合區；HA 冷備份則保存整個 App。HA OS 實機搬家驗收仍待完成。

## 儀表板卡片

1. **[在 HACS 開啟 WebClock](https://my.home-assistant.io/redirect/hacs_repository/?owner=kcayut&repository=webclock&category=integration)**，下載後重新啟動 HA。
2. 在 WebClock 管理頁「裝置」建立群組，指派內容並產生六位英數加入碼。
3. **[新增 WebClock 整合](https://my.home-assistant.io/redirect/config_flow_start/?domain=webclock)**：從本 App「日誌」複製 `Home Assistant integration URL:` 後面的網址，填入 Server 並貼上加入碼。同機連線不需開放 App 主機連接埠。也可從 App「資訊」頁的「主機名稱」組成 `http://主機名稱:8100`。
4. 儀表板「新增卡片」選 WebClock Time／Calendar／Alarms，選取對應 sensor。無需自行設定卡片資源或 token。

沒有 HACS 可見[手動整合安裝](https://github.com/kcayut/webclock/blob/main/doc/home-assistant.md#安裝整合)。HA 只建立一份整合並顯示一個群組；其他網頁或 ESP 可用各自的加入碼連到不同群組。

目前 App 是實驗版本。商店通知新版時，先建立 Home Assistant 備份，再按「更新」；整合與卡片在 HACS 更新，兩者分別管理。不要移除 App 來更新。HA 冷備份還原須停止 App；管理頁完整 `.webclock` 還原則由正在執行的新 App 接收檔案並處理復原。
