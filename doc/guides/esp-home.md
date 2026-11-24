# ESPHome 桌鐘

| 板型 | 螢幕與操作 | 文件 |
|---|---|---|
| 微雪 ESP32-S3-RLCD-4.2 | 400 × 300 全反射 LCD、頂部三鍵、電池電壓、microSD 自訂鬧鈴 | [刷機](../../firmware/rlcd-clock/README.md) · [專屬畫面與操作手冊](../../firmware/rlcd-clock/使用手冊.md) |
| EE04 | 800 × 480 電子紙、背面三鍵、蜂鳴器 | [刷機](../../firmware/ee04-clock/README.md) · [使用手冊](../../firmware/ee04-clock/使用手冊.md) |

## EE04 電子紙桌鐘

[USB 刷機與 OTA](../../firmware/ee04-clock/README.md#刷入韌體) · [首次配網與服務配對](../../firmware/ee04-clock/使用手冊.md) · [Server API](../api/server-api.md)

## 顯示、聲音與按鍵

4.26 吋電子紙以大字顯示時分。背面三鍵用來選擇、確定及取消，響鈴畫面可確認停鈴。逐頁操作請見[使用手冊](../../firmware/ee04-clock/使用手冊.md)。

## 已實作的同步流程

配對後，桌鐘使用程式存取憑證雙向同步本機的每日鬧鐘，依顯示權限讀取行事曆跑馬燈。雙向編輯、刪除及離線衝突的處理見[斷網行為](../../firmware/ee04-clock/使用手冊.md#斷網後會怎樣)。

## 時間、斷網、斷電與認證

桌鐘可單機設定日期、時間與每日鬧鐘。RTC 備援電池可在主電源中斷時保時；響鈴需要 USB 或主電池供電。實體按鍵耐久、續航與整機驗收進度見[韌體驗證](../../firmware/ee04-clock/README.md#驗證)。
