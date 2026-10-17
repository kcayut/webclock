# 主機手動與可攜式更新工具

原本散在根目錄的四支 shell 更新腳本集中在這裡，保留原來的功能、參數及保護檢查。這是整理後的原始碼布局；舊版安裝仍使用原來的根目錄指令，升級到含此目錄的版本後才能使用新路徑。

| 工具 | 用途 | 能否單獨複製 |
| --- | --- | --- |
| [`update_clock.sh`](update_clock.sh) | 裸機 Git 安裝的手動更新，呼叫共用安全更新器 | 否，需留在安裝目錄內 |
| [`docker_update.sh`](docker_update.sh) | Docker 宿主機的更新、診斷及復原入口 | 否，需留在安裝目錄內 |
| [`portable_update_clock.sh`](portable_update_clock.sh) | 自用裸機工具：預設 `/opt/webclock`，也可指定實際安裝路徑；支援從任意工作目錄執行 | 是，root 直接執行，一般帳號由腳本使用 sudo |
| [`portable_docker_update.sh`](portable_docker_update.sh) | Docker 獨立更新／救援工具；下載並驗證指定 Release 的工具，支援既有版本缺少更新器的情況 | 是，正式版仍以同名 Release 資產提供 |

## 平常在自己的主機上使用

在整理後的安裝根目錄執行：

```bash
# 裸機 Linux/systemd
sudo bash scripts/update/update_clock.sh

# Docker 宿主機：先檢查，再更新
sudo bash scripts/update/docker_update.sh --check
sudo bash scripts/update/docker_update.sh
```

自己的裸機工具可單獨複製到安裝目錄外，例如 `/root/bin/portable_update_clock.sh`，再從任意目錄執行：

```bash
bash /root/bin/portable_update_clock.sh /opt/webclock
```

最後一個參數請換成真正的安裝目錄；省略時才使用 `/opt/webclock`。stable／beta 安裝沿用原管道，開發用 Git checkout 則取得已設定的 upstream，仍由共用更新器執行檢查、備份及更新。不要把同一份工具另存回受更新器管理的 Git 安裝目錄，造成未追蹤檔案阻擋升級。

Docker 的獨立工具、離線救援、worker 啟用與遷移操作見[更新維護](../../doc/operations/update-operations.md)。HA App 由 Supervisor 更新，HACS 整合／卡片由 HACS 更新，不使用這些宿主機工具。

## 相容入口與實作分工

- 根目錄 `update_clock.sh` 與 `docker_update.sh` 只有轉接，舊命令繼續可用，實作以此目錄為準。
- 根目錄 `update_clock.py` 必須保留：舊版獨立更新流程會透過 `git show upstream:update_clock.py` 取得它，且會單獨複製到 `/tmp` 執行。它載入共用的 `scripts/update_clock.py`，不是另一套更新器。
- 原始碼根目錄不再放兩支 portable 腳本。正式 Server 壓縮檔仍會由同一份來源產生根目錄同名檔案，保留舊檔案布局與離線復原契約；公開 `portable_docker_update.sh` 資產與 checksum 名稱也不變。
- `scripts/update_clock.py`、`scripts/docker_update.py`、`scripts/updater_service.py` 等是安裝後共用的更新邏輯與系統服務，保留原路徑。未在此資料夾加入私人主機位址或帳密。
