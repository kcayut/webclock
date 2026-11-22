---
name: webclock
description: 使用 WebClock MCP，依繁中或其他語言的文字指令設定指定時鐘的一次性鬧鐘、新增 WebClock 本地行程，或建立隨行程改期的提前提醒。
---

「明早七點半在臥室叫我」：先用 `list_targets` 的台北時間換算確切日期，從已授權清單取得「臥室」的目標值，再呼叫 `create_alarm`。目標缺漏或名稱對應多個目標時先詢問。使用者要求「每天」時，告知本工具目前支援一次性鬧鐘。

「週五下午兩點到三點加個回診，提前十五分鐘在臥室叫我」：先確認日期、時區、起訖和響鈴目標，再以 `create_calendar_event` 寫入 WebClock 本地行事曆。將回傳的 `saved.event.id` 交給 `create_event_alarm`，設定 `minutes_before=15`。只有使用者也要求在臥室顯示行程時，才將 target 傳給建立行程的工具。使用者點名 Google 或 iCloud 時，告知可寫入的目的地並等候選擇。

每次新建產生不同的 request_id，包括同一句話中的事件和聯動鬧鐘。連線中斷後用原 ID 與相同參數查回結果。重送只讀回現況。若 saved 為 null，說明目前無法確認該筆內容。若指派失敗或已取消，告知使用者可在 WebClock 管理頁依回傳的 item_id 檢查或重新指派。

回報實際保存的日期、時間和目標。assigned 為 null 表示尚無法確認指派，false 表示未指派。事件成功但鬧鐘失敗時，分別說明，保留事件 ID。只有裝置端的證據才能確認同步或實際響鈴。
