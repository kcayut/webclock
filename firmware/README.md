# WebClock ESPHome 韌體

這是 ESP 鬧鐘韌體的開發入口。**目前只有開發準備文件，尚無可編譯 YAML、可燒錄檔案、網頁安裝頁或 OTA 更新。** 板型、腳位及播放器尚未選定，不提供猜測接線的範本。

- [ESPHome 接入、預計使用流程與驗收](../doc/esp-home.md)
- [現有 Server API 契約](../doc/server-api.md#裝置-api)

目標使用 ESPHome 建立韌體，並以 ESP Web Tools 安裝預編譯檔；裝置透過 HTTP 主動同步，不要求 Home Assistant。現有 schema 2 只能取得全域固定規則排程，行事曆聯動的多日清單仍待擴充。

先選定一套 ESP32 硬體並驗證 API，再新增實際可編譯的硬體 YAML；只有共用同步與排程邏輯需要時，才加入 ESPHome 外部元件。等產物可重現編譯及實機驗收後，再加入網頁安裝 manifest 與發布流程，不預先建立空目錄或假韌體。

Wi-Fi 密碼、裝置 token 及私人伺服器位置使用本機設定，不提交到 Git 或編入公開韌體。此目錄的 `.gitignore` 排除 ESPHome 暫存、編譯產物與本機 `secrets*.yaml`；未來需要分享設定欄位時，可建立只有假值的 `secrets.example.yaml`。正式發布的二進位檔由後續發布流程提供。
