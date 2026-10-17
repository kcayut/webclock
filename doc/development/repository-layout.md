# 目錄分工與安裝相容性

根目錄保留使用者入口與部署工具預設尋找的檔案。程式、文件、維護工具和主機演練依用途分開；整理原始碼不搬移已安裝主機的私人資料。

`doc/installation.md`、`doc/home-assistant.md` 和 `doc/ha-release.md` 保留原位置，維持已公開安裝指令、HACS manifest 與 HA App 說明使用的連結。

舊版 HA App 說明中的 `scripts/prepare_ha_app.sh` 也保留為薄轉接入口，實作集中於 `homeassistant/prepare_local_app.sh`。

```text
WebClock/
├── README*.md、CHANGELOG.md、VERSION
├── install.sh、setup.sh                  # 新安裝的固定入口
├── update_clock.py                      # 舊版可獨立下載的 bootstrap
├── update_clock.sh、docker_update.sh     # 舊命令的薄轉接入口
├── Dockerfile、docker-compose.yml、.dockerignore
├── repository.yaml、hacs.json            # HA 商店／HACS 識別
├── app.py、requirements.txt、.env.example
├── index.html、sw.js                     # 離線時鐘與 Pages 的固定入口
├── webclock/                            # Server、API、服務及翻譯
├── templates/、static/                  # Server 畫面與共用靜態資產
├── scripts/                             # 已安裝系統需要的共用 helper
│   └── update/                          # 四支手動／可攜更新腳本
├── tools/                               # 開發／發佈工具
├── custom_components/webclock/          # HACS integration，包含卡片
├── homeassistant/
│   ├── addon/                           # App manifest、Dockerfile 與商店文件
│   ├── prepare_local_app.sh             # 完整的 Local App build context
│   └── tests/                          # HA 整合、卡片、容器檢查
├── firmware/                            # ESPHome 元件與硬體測試
├── tests/
│   ├── test_*.py、test_*.js、fixtures/   # 一般本機回歸
│   └── rehearsal/                      # 可丟棄主機上的安裝／升級演練
└── doc/                                 # 文件索引及分類
```

## 三種部署的路徑契約

| 部署 | 安裝／升級 | 程式與持久資料 |
| --- | --- | --- |
| 裸機 Linux/systemd | `install.sh` → `setup.sh` → `scripts/setup.sh`；既有安裝由 `update_clock.sh`／獨立入口升級 | 服務仍以安裝目錄為 `WorkingDirectory`，使用 `venv/bin/python app.py`。保留 `.env`、`webclock_state/`、舊 `manual_notes.json`、`tls/` 與自訂資料路徑 |
| Docker Compose | `install.sh --docker`；開發建置為 `setup.sh --docker --build`；更新使用宿主機入口 | Compose 與 build context 保留在根目錄。既有 bind mounts、備份與 `webclock_updater_run/` 保留；更新替換映像，不移動私人資料 |
| HA App | 商店依 `homeassistant/addon/config.yaml` 取版本化映像；Local App 由 `homeassistant/prepare_local_app.sh` 打包 | 容器程式在 `/app`，私人資料在 `/data`；管理入口仍為 Ingress 8099，LAN 8100 只供顯示／裝置。App 升級由 Supervisor 管理 |
| HA 整合／卡片 | HACS 管理 `custom_components/webclock/`，卡片隨整合安裝 | 與 App 分開升級；保留標準根目錄 `custom_components/` 及 `hacs.json` |

完整操作與限制以[安裝指南](../installation.md#update)和[更新維護](../operations/update-operations.md)為準。跨主機 `.webclock` 還原是搬家／復原，不是一般版本更新。

## 發佈與維護規則

- `tools/build_release.py` 只從 Git HEAD 白名單打包。Server 包保留根目錄入口、`scripts/`、HA Local App 準備入口及 App 檔案；不包含 `tools/`、`tests/`、HA 測試或私人資料。
- 普通 Dockerfile 只複製執行所需程式與 `scripts/`；HA Dockerfile 不需要宿主機更新 helper。兩者 build context 都仍從專案根目錄提供。Local App 準備工具則產生可獨立建置的平面目錄。
- 不更動既有 Release 資產名稱：`install.sh`、`portable_docker_update.sh`、`webclock-版本.tar.gz`、`webclock-clock-版本.zip` 與 `SHA256SUMS`。
- 原始碼的 portable 腳本集中於 [`scripts/update/`](../../scripts/update/README.md)；Server 壓縮檔仍從同一份來源產生根目錄的兩個同名檔案。原始碼與發佈包在這兩個相容路徑上有意不同。
- 新的開發工具放 `tools/`；安裝後的管理 helper 放 `scripts/`；HA 專用工具與測試放 `homeassistant/`。移動檔案須同步更新 caller、測試、Docker COPY、Release 白名單及 CI 指令與 paths filter。
- `.env`、`webclock_state/`、`manual_notes.json`、`tls/`、更新 socket／交易／備份目錄與 `venv/` 是本機或安裝資料，不納入 Git 或發行包，也不為了整理原始碼而刪除、搬移。
- 根目錄 `index.html` 與 `templates/index.html` 分別供無 Server 離線時鐘與 Flask 使用；`doc/images/` 和 `static/images/` 分別服務文件與網頁，不因檔名相同就合併。

## 驗證入口

在裝好測試依賴的原始碼 checkout 執行：

```bash
python3 tools/build_release.py --check
python3 -m unittest discover -s tests -p 'test_*.py'
for test in tests/test_*.js; do node "$test"; done
python3 -m unittest discover -s homeassistant/tests -p 'test_*.py'
node homeassistant/tests/test_cards.js
for script in *.sh scripts/*.sh scripts/update/*.sh homeassistant/*.sh tests/rehearsal/*.sh; do bash -n "$script"; done
```

HA Python 測試需安裝 CI 所列的 Home Assistant 依賴；需要監聽本機 HTTP/HTTPS 的測試應在允許本機連線的環境執行。完整發行包的入口與 Docker／HA build context 由 `tests/test_distribution_layout.py` 驗證。

真實 Docker／systemd 演練由 [CI](../../.github/workflows/home-assistant.yml)和 [Linux 演練](../../.github/workflows/linux-rehearsal.yml)執行；[公開 Release 測試](../../.github/workflows/release-smoke.yml)及 HA OS／ARM 實機驗收仍須分別記錄。
