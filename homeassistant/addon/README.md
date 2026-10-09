# WebClock Home Assistant App

安裝入口：[完整安裝指南](https://github.com/kcayut/webclock/blob/main/doc/installation.md#home-assistant)。

**[加入 HA App 商店來源](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fkcayut%2Fwebclock)** → 選 WebClock → 安裝 → 啟動 → 開啟網頁介面。需要 HA OS（amd64／aarch64），一般安裝不需 SSH。首次公開映像發布與 HA OS 驗收狀態見[發行說明](https://github.com/kcayut/webclock/blob/main/doc/ha-release.md)。

要在 HA 儀表板顯示，另以 HACS 安裝 WebClock Integration；Server 填 App 日誌中 `Home Assistant integration URL:` 的網址，搭配管理頁產生的六碼。時間、行事曆、鬧鐘卡片包含在整合內，無須另外安裝。

開發測試才需要在專案根目錄執行 `bash scripts/prepare_ha_app.sh`，產生 `/addons/webclock` 本機 App。打包會補齊原始碼並移除產物的 `image` 設定，不會複製私人設定或覆蓋既有目的地。

維護者仍可從**專案根目錄**驗證發行用映像：

```bash
docker build -f homeassistant/addon/Dockerfile -t webclock-addon .
```

管理頁只經由 Home Assistant Ingress 的 `8099` 開啟；選用的 `8100/tcp` 提供區網顯示與配對，資料保存到 `/data`。全新 App 預設 self；在「備份與還原」載入加密 `.webclock` 完整備份，可保留原 managed 帳號與私人資料空間，再用原帳密登入。HA 登入仍保護外層入口，不會取代 WebClock 帳號驗證。
