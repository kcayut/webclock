# Changelog

## 1.1.0

- Server、Docker、App、整合與卡片統一為 1.1.0；沿用原有 App 版號作為首個公開 Release。
- 公開發行包提供固定版本安裝器、獨立離線時鐘 ZIP 與 SHA256 核對檔，`/api/health` 回報產品版本。
- 提供 App 商店來源與多架構映像發行流程；使用者不需 SSH 或複製原始碼。
- Integration 改用 HACS 標準目錄安裝與更新，三種卡片隨整合提供。
- 啟動日誌提供實際整合網址；支援 HA 使用 HTTPS 時的 Ingress 管理操作。
- 管理入口仍使用 HA Ingress；外部時鐘連接埠維持選用。
- 提供可選加密的完整備份，可將既有 Server 的帳號、私人行事曆與裝置資料搬入 App。

發行、CI 與 HA OS 實機驗收狀態見[維護者紀錄](https://github.com/kcayut/webclock/blob/main/doc/ha-release.md)。

## 0.1.0

- 首個實驗版本：Ingress 管理頁、`/data` 持久化、健康檢查與選用的顯示專用區網連接埠。
