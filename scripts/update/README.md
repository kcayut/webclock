# 主機手動與可攜式更新工具

根目錄保留日常就地執行的更新入口，這裡保留可單獨複製使用的可攜式更新腳本。預設的 Linux 手動更新與網頁更新服務（`webclock-updater`）皆走官方 GitHub Releases（預設 `stable`、保留既有 `beta` 設定，並維持交易鎖、冷備份、健康檢查與降版防護）；若要從已設定的 Gitea tracking branch 更新，必須明確加上 `--upstream`。

| 工具 | 位置 | 用途 | 能否單獨複製 |
| --- | --- | --- | --- |
| [`update_clock.sh`](../../update_clock.sh) | 根目錄 | 裸機 Git 安裝的手動更新，預設走官方 GitHub Releases（未設 `webclock.releaseChannel` 時預設 `stable`，保留既有 `beta`）；加 `--upstream` 才改抓已設 Gitea／Git tracking branch | 否，需留在安裝目錄內 |
| [`docker_update.sh`](../../docker_update.sh) | 根目錄 | Docker 宿主機的更新、診斷及復原入口；走官方 GitHub Releases 與 `ghcr.io/kcayut/webclock` | 否，需留在安裝目錄內 |
| [`portable_update_clock.sh`](portable_update_clock.sh) | `scripts/update/` | 可攜式裸機工具：預設 `/opt/webclock` 與官方 GitHub Releases（明確傳入 `--channel stable` 或既有 `beta`，不回退無參數舊版抓 Gitea；遇不支援 `--channel` 的更早版本直接中止提示），加 `--upstream` 時當代安裝直接呼叫已安裝更新器，僅舊版相容時才經 fast-forward 祖先與共用版本檢查後執行 bootstrap，並支援既有的私人內網 HTTP Gitea tracking branch | 是，root 直接執行，一般帳號由腳本使用 sudo |
| [`portable_docker_update.sh`](portable_docker_update.sh) | `scripts/update/` | Docker 獨立更新／救援工具；下載並驗證指定 GitHub Release 的工具，支援既有版本缺少更新器的情況 | 是，正式版仍以同名 Release 資產提供 |

## 平常在自己的主機上使用（官方 GitHub Releases）

在安裝根目錄執行：

```bash
# 裸機 Linux/systemd（預設走官方 stable，保留既有 beta）
sudo bash update_clock.sh

# Docker 宿主機：先檢查，再更新
sudo bash docker_update.sh --check
sudo bash docker_update.sh
```

自己的裸機工具可單獨複製到安裝目錄外，例如 `/root/bin/portable_update_clock.sh`，再從任意目錄執行：

```bash
bash /root/bin/portable_update_clock.sh /opt/webclock
```

最後一個參數請換成真正的安裝目錄；省略時才使用 `/opt/webclock`。不要把同一份工具另存回受更新器管理的 Git 安裝目錄，造成未追蹤檔案阻擋升級。

Docker 的獨立工具、離線救援、worker 啟用與遷移操作見[更新維護](../../doc/operations/update-operations.md)。HA App 由 Supervisor 更新，HACS 整合／卡片由 HACS 更新，不使用這些宿主機工具。

## 明確使用 Gitea upstream 更新

當主機原本已設定 Gitea tracking branch（`@{upstream}`），且希望明確從該上游更新時，加上 `--upstream`：

```bash
# 在安裝根目錄
sudo bash update_clock.sh --upstream

# 或使用單獨複製的 portable 工具
bash /root/bin/portable_update_clock.sh --upstream /opt/webclock
```

`--upstream` 會保留原本的 `webclock.releaseChannel` 與網頁更新服務設定（不會改成 Gitea），並仍透過共用更新器驗證 fast-forward 祖先關係與 `VERSION` 非降版、建立冷備份及執行健康檢查。若處於 detached HEAD 或尚未設定 tracking branch，請先配置 tracking branch 或改用官方 GitHub Releases。

## 相容入口與實作分工

- 原本重複的 `scripts/update/update_clock.sh` 與 `scripts/update/docker_update.sh` 已整併回根目錄 `update_clock.sh` 與 `docker_update.sh`，保留公開與舊版命令。
- 根目錄 `update_clock.py` 必須保留：舊版與 `--upstream` 獨立更新流程會透過 `git show upstream:update_clock.py` 取得它，且會單獨複製到 `/tmp` 執行。它載入共用的 `scripts/update_clock.py`，不是另一套更新器。
- 原始碼根目錄不再放兩支 portable 腳本。正式 Server 壓縮檔仍會由同一份來源產生根目錄同名檔案，保留舊檔案布局與離線復原契約；公開 `portable_docker_update.sh` 資產與 checksum 名稱也不變。
- `scripts/update_clock.py`、`scripts/docker_update.py`、`scripts/updater_service.py` 等是安裝後共用的更新邏輯與系統服務，保留原路徑。未在此資料夾加入私人主機位址或帳密。
