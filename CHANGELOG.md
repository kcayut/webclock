# WebClock 發行紀錄

## 1.1.0 — 首次公開版本

- Linux／Raspberry Pi 一行安裝取得 GitHub 正式 Release；Docker 使用同版預建映像，主機不需 Git 或 Python。
- 安裝前檢查環境、連接埠與 TLS；完成 HTTP／HTTPS 健康檢查後提供時鐘與管理網址，未完成的新安裝可保留資料重試。
- 提供 Server 壓縮檔、獨立離線時鐘 ZIP、固定版本安裝器與 `SHA256SUMS`。
- 根目錄 `VERSION` 統一 Server、Docker、HA App、HACS 整合與卡片版本；`/api/health` 回報產品版本。
- Linux 正式安裝的安全更新器跟隨最新正式 Release；Docker 與 HA 依各自的更新流程選擇正式版。
- 包含多語管理、self／managed、群組與裝置授權、行事曆／提醒／鬧鐘，以及可選加密的完整備份與跨主機還原。

GitHub 發布、公開映像、CI 與實機驗收分開記錄於[發行狀態](doc/ha-release.md)。本紀錄列出交付內容，不代表 HA OS、ARM 或舊 iPad 已完成實機驗收。

## 版本規則

採用 `X.Y.Z`，Git tag 為 `vX.Y.Z`：不相容變更增加 `X`；相容的新功能增加 `Y`；相容修正增加 `Z`。正式安裝不跟隨 `main` 或預先發行版。

第一次公開 Release 使用 **1.1.0**，因 HA App、整合與卡片原有版本已為 1.1.0；沿用可避免既有安裝被要求降版。之後同一批交付物使用相同版本；版本來源與發行檢查見[維護者說明](doc/ha-release.md#版本來源與規則)。

產品版本不等於 API、授權、裝置或備份的資料格式版本；`auth_schema`、`device_schema`、`schema_version` 等仍各自表示相容性，不能跟著產品版號一併改動。
