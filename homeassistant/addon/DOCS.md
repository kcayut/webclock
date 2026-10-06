# WebClock App

啟動後按「開啟網頁介面」即可在 Home Assistant 側邊欄管理 WebClock。資料存放於 App 的 `/data`，會包含在 Home Assistant 的 App 備份中。

App 預設只開放 Ingress，不會把 WebClock 連接埠公開到區網。若要讓網頁時鐘、ESP 或其他區網裝置連線，請在 App 的「網路」設定將容器連接埠 `8099` 指定到一個主機連接埠，再使用 `http://HOME_ASSISTANT_IP:指定連接埠`。

若要在同一台 Home Assistant 安裝 WebClock 自訂整合，可把 Server 位址填為 `http://webclock:8099`，再使用 WebClock 管理頁產生的六位英數加入碼。

目前 App 是實驗版本。更新或復原前請先建立 Home Assistant 備份；App 必須停止後才能還原資料。
