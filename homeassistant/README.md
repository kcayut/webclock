# WebClock for Home Assistant

App 位於 [`addon`](addon)，自訂整合位於專案根目錄的 [`custom_components/webclock`](../custom_components/webclock)，測試位於 [`tests`](tests)。整合使用 HACS 標準目錄，不需另外安裝卡片。

開發用 Local App 由 [`prepare_local_app.sh`](prepare_local_app.sh) 產生，請在專案根目錄執行 `bash homeassistant/prepare_local_app.sh /tmp/webclock-ha-app`。容器啟動檢查放在 [`tests/check_container.py`](tests/check_container.py)。

App 可讓使用者直接在 HA 內執行 WebClock Server；自訂整合則提供六位加入碼、三種卡片與鬧鐘事件。安裝、使用、更新及移除方式請見 [`../doc/home-assistant.md`](../doc/home-assistant.md)。

一般使用者：**[安裝 Server](../doc/installation.md#home-assistant) → [安裝整合](../doc/home-assistant.md#安裝整合) → [加入卡片](../doc/home-assistant.md#加入儀表板卡片)**。發行狀態與維護者操作見[發行說明](../doc/ha-release.md)。
