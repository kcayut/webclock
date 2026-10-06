# WebClock Home Assistant App

此目錄包含 Home Assistant App 的設定與映像建置檔。映像需從專案根目錄建置：

```bash
docker build -f homeassistant/addon/Dockerfile -t webclock-addon .
```

App 使用 Home Assistant Ingress 開啟完整管理頁，另以選用的 `8100/tcp` 提供區網顯示與裝置配對；所有可變狀態保存到 `/data`。
