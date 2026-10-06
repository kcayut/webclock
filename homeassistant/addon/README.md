# WebClock Home Assistant App

此目錄包含 Home Assistant App 的設定與映像建置檔。映像需從專案根目錄建置：

```bash
docker build -f homeassistant/addon/Dockerfile -t webclock-addon .
```

App 使用 Home Assistant Ingress 開啟 `/admin`，並將所有可變狀態保存到 `/data`。
