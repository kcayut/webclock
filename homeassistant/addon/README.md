# WebClock Home Assistant App

安裝入口：[完整安裝指南](https://github.com/kcayut/webclock/blob/main/doc/installation.md#home-assistant)。

在專案根目錄執行 `bash scripts/prepare_ha_app.sh`，產生 `/addons/webclock` 本機 App，再於 HA App 商店檢查更新、安裝及啟動。打包會補齊 Dockerfile 所需原始碼，並移除產物的 `image` 設定以使用本機建置；不會複製私人設定或覆蓋既有目的地。

維護者仍可從**專案根目錄**驗證發行用映像：

```bash
docker build -f homeassistant/addon/Dockerfile -t webclock-addon .
```

管理頁只經由 Home Assistant Ingress 的 `8099` 開啟；選用的 `8100/tcp` 提供區網顯示與配對，資料保存到 `/data`。App 使用 HA 登入保護管理入口，WebClock 保持 self，不提供獨立 managed 登入選項。
