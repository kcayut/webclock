# Proxmox 三台測試主機

在 amd64 Proxmox 節點以 root 執行 [`create_proxmox_lab.sh`](../../tools/create_proxmox_lab.sh)，建立 HA OS、Ubuntu 原生安裝及 Ubuntu Docker 三台 VM。腳本只建立作業系統；Docker Engine、WebClock、HA 首次設定及整合安裝依下方完成。

## 建立 VM

預設 VM ID 為 981～983、磁碟 storage 為 `local-lvm`、bridge 為 `vmbr0`。三台合計配置 6 vCPU、8 GiB RAM、至少 76 GiB 虛擬磁碟；Proxmox `/var/tmp` 另需約 10 GiB 下載及解壓空間。HA 映像若大於 32 GiB，保留原大小。需要可連外的 Proxmox、可通往手機區網的 bridge 及 DHCP。

先在 Mac 的專案目錄執行，將 `PVE-IP` 換成 Proxmox 位址；公鑰可換成自己的 `.pub`，不要傳私鑰：

```bash
scp tools/create_proxmox_lab.sh ~/.ssh/id_ed25519.pub root@PVE-IP:/root/
ssh root@PVE-IP
```

若尚無 SSH 金鑰，可先在 Mac 執行 `ssh-keygen -t ed25519`，依提示建立新金鑰，勿覆蓋既有檔案。

在 Proxmox 執行：

```bash
bash /root/create_proxmox_lab.sh \
  --storage local-lvm --bridge vmbr0 --base-id 981 \
  --ssh-key /root/id_ed25519.pub
```

可透過 Proxmox 介面確認 storage／bridge 名稱。VM ID 若在叢集中已被 VM 或 LXC 使用，腳本會在建立前停止。需要固定 HA OS 版本可加 `--ha-version 正式版tag`；預設從官方最新正式版解析。Ubuntu 使用官方 24.04 發行映像。兩者皆比對官方 HTTPS 來源的 SHA256；HA 資產無 digest 時停止。

若最新 HA OS Release 沒有 `haos_ova-*.qcow2.xz`，腳本會停止；請查官方 Release，指定含 KVM 映像的正式版本。2026-11-12 的 18.5 沒有該映像，本次測試使用 `--ha-version 18.4`。

腳本成功只代表三台 VM 已送出啟動命令。首次開機需等待初始化；在路由器 DHCP 租約或 Proxmox Console 查 IP，再設定 DHCP 保留。Ubuntu 使用 `ubuntu` 帳號與上傳公鑰，沒有預設登入密碼。VM 預設不隨 Proxmox 自動開機。

失敗時保留已建立的 VM 與暫存映像，並列出暫存路徑；不會自動刪除資源。檢查 Proxmox 工作日誌及 VM 設定後，可選擇修復該 VM，或確認它們只是本次新建測試資源後，手動移除再重跑。不要直接以不同 ID 重跑而留下未確認的資源。

## Linux 原生：安裝 WebClock

從 Mac 連入 Linux VM：

```bash
ssh ubuntu@LINUX-IP
```

在該 VM 執行（固定正式版 1.2.0，適用全新安裝）：

```bash
sudo cloud-init status --wait &&
sudo apt-get update &&
sudo apt-get install -y curl ca-certificates &&
curl -fsSL https://github.com/kcayut/webclock/releases/download/v1.2.0/install.sh -o /tmp/webclock-install.sh &&
bash /tmp/webclock-install.sh --version 1.2.0
```

手機管理頁：`http://LINUX-IP:5000/admin`；時鐘：`http://LINUX-IP:5000`。

## Docker：安裝 Engine、Compose 與 WebClock

從 Mac 連入 Docker VM：

```bash
ssh ubuntu@DOCKER-IP
```

在該 VM 執行，使用 Ubuntu 發行套件的 Docker Engine 與 Compose v2：

```bash
sudo cloud-init status --wait &&
sudo apt-get update &&
sudo apt-get install -y curl ca-certificates docker.io docker-compose-v2 &&
sudo systemctl enable --now docker &&
sudo docker compose version &&
curl -fsSL https://github.com/kcayut/webclock/releases/download/v1.2.0/install.sh -o /tmp/webclock-install.sh &&
sudo bash /tmp/webclock-install.sh --docker --version 1.2.0 --dir /opt/webclock
```

手機管理頁：`http://DOCKER-IP/admin`；時鐘：`http://DOCKER-IP`。此安裝使用 root 操作 Docker，後續維護也需 sudo。

## HA OS：首次設定與 WebClock App

1. 手機或電腦開啟 `http://HA-IP:8123`，完成 HA 首次設定。若 8123 無回應，HA OS 18.4／Core 2026.11 可能已在 port 80 提供前端，改開 `http://HA-IP`。
2. 在 App 商店加入 `https://github.com/kcayut/webclock`，安裝並啟動 WebClock。
3. 使用 App「開啟網頁介面」管理；App 網路設定將 `8100/tcp` 映射為 8100。
4. 在 WebClock 建立群組、指派內容並產生六碼；手機開啟 `http://HA-IP:8100` 加入。
5. 整合與三張卡片依 [HA 指南](../home-assistant.md)安裝；Server 位址取自 App 日誌的 `Home Assistant integration URL:`。

HACS 安裝方式須對照實際 HA Core 版本與 [HACS 官方文件](https://www.hacs.xyz/docs/marketplace/)；2026.10 及以前為自訂整合，官方目前將 2026.11 起列為內建 Marketplace。不能把 HA OS 版本當成 Core 版本，也不能把成功安裝 App 當作 HACS 驗收完成。

## 手機測試與驗證範圍

三台 VM 與手機須在可互通的區網，避免訪客 Wi-Fi 隔離。初次使用 self／HTTP 僅限可信任區網。手機分別測試載入、設定保存、配對、前景響鈴、斷線重連與 VM 重啟後資料保存；HA 卡片顯示與實際通知／喇叭分開驗收。

本腳本的自動檢查使用模擬 Proxmox 指令，涵蓋 ID 衝突、校驗失敗及中途失敗保留資源。2026-11-12 已在 amd64 Proxmox VE 實機以本腳本建立 981～983，並完成 HA OS 18.4、Ubuntu 24.04 開機與三平台安裝驗收（Linux／Docker 的 self 與 managed、HA App Ingress、整合與三張卡片）。實機驗收仍不代表實體 ARM、手機聲音、所有網路環境或後續版本；重跑後仍須重新確認。

實機觀察（2026-11）：HA OS 18.4／Core 2026.11.1 的前端在此環境監聽 port 80，8123 不一定有 redirect；onboarding 的 `/api/onboarding/users` 需要 `language` 欄位並跟隨 307 redirect；Supervisor 的 Local App 實際路徑是 `/data/apps/local`（`addons/local` 已更名），SSH／Samba 的 `/addons` 仍是入口。以上為 HA OS 行為，不是 WebClock 安裝器問題。

## 清理測試資源

先核對 VMID 與名稱，確認沒有誤刪叢集內其他 VM／LXC：

```bash
for vmid in 981 982 983; do printf '%s ' "$vmid"; qm config "$vmid" | sed -n 's/^name: //p'; done
```

關機後刪除；`--purge` 清除相關設定，`--destroy-unreferenced-disks` 一併移除未參照磁碟：

```bash
qm shutdown 981; qm shutdown 982; qm shutdown 983
qm destroy 981 --purge 1 --destroy-unreferenced-disks 1
qm destroy 982 --purge 1 --destroy-unreferenced-disks 1
qm destroy 983 --purge 1 --destroy-unreferenced-disks 1
rm -rf /var/tmp/webclock-lab.*
```

失敗時腳本保留的 `/var/tmp/webclock-lab.*` 可能含數百 MB 映像，確認不再需要再刪。若曾為 VM 設定 DHCP 保留，請另在路由器移除對應 MAC。刪除前務必確認名稱，叢集內可能有其他使用相近 ID 的服務。

官方依據：[Proxmox cloud-init](https://github.com/proxmox/pve-docs/blob/master/qm-cloud-init.adoc)、[Proxmox VM](https://github.com/proxmox/pve-docs/blob/master/qm.adoc)、[HA OS 虛擬機](https://www.home-assistant.io/installation/alternative/)、[Ubuntu cloud image](https://cloud-images.ubuntu.com/releases/noble/release/)、[Ubuntu Compose v2](https://packages.ubuntu.com/noble/docker-compose-v2)。
