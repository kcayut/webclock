# 主機安裝與升級演練

這些腳本會操作服務或容器，只供可丟棄的測試環境使用；不列入一般 unittest discovery。

| 腳本 | 執行環境與驗證內容 |
| --- | --- |
| `rehearse_install.sh` | GitHub-hosted Linux/systemd：全新 self／managed 安裝、健康檢查及重啟後資料保存 |
| `rehearse_linux.py` | GitHub-hosted Linux/systemd：舊版升級、完整備份還原、失敗回復與身份保存 |
| `rehearse_docker_update.py` | 可丟棄的 Docker 環境：映像切換、資料保存、失敗回退與 managed HTTPS |
| `rehearse_docker_worker.sh` | GitHub-hosted Linux/systemd + Docker：worker 啟用、偏好保存、socket 重建與 worker refresh |

執行參數與環境變數由 [安裝 CI](../../.github/workflows/home-assistant.yml)及 [Linux 演練 CI](../../.github/workflows/linux-rehearsal.yml)維護。HA 容器啟動檢查在 [`homeassistant/tests/check_container.py`](../../homeassistant/tests/check_container.py)。

公開下載後的新安裝／跨版本升級另由 [release-smoke](../../.github/workflows/release-smoke.yml) 驗證；本機測試通過不能替代公開 Release、HA OS 或實體 ARM 驗收。
