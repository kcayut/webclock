# 安裝與維護程式

此目錄只放安裝後需要的 helper 與管理指令。一般使用者從根目錄的 `install.sh`、`setup.sh`、`update_clock.sh`、`docker_update.sh` 操作；完整指令見[安裝指南](../doc/installation.md)與[更新維護](../doc/operations/update-operations.md)。

自己在主機上執行的手動／可攜式更新腳本集中於 [`update/`](update/README.md)；根目錄的兩支一般更新指令保留為相容轉接。

| 用途 | 檔案 |
| --- | --- |
| 新安裝與健康檢查 | `setup.sh`、`install_check.py` |
| 手動／可攜式更新入口 | [`update/`](update/README.md) 中的四支 shell 腳本 |
| 裸機安全升級 | `update_clock.py`、`enable_updates.sh` |
| Docker 升級、worker 啟用與受保護目錄遷移 | `docker_update.py`、`docker_update_install.py`、`docker_update_migrate.py`、`enable_docker_updates.sh` |
| 共用版本選擇、更新服務與設定 | `release_versions.py`、`updater_service.py`、`update_settings.py` |
| 停機備份／還原、帳號管理、控制 API CLI | `backup_clock.py`、`manage_auth.py`、`control_clock.py` |
| 舊版 HA 文件的相容入口 | `prepare_ha_app.sh` 轉交 `homeassistant/prepare_local_app.sh` |

這些 helper 的相對路徑也是舊版 bootstrap、系統服務與救援工具使用的介面；調整時必須同時驗證舊版升級與失敗回復。維護者發佈工具放 [`tools/`](../tools/README.md)，HA 專用工具放 [`homeassistant/`](../homeassistant/README.md)，不要再混入此目錄。
