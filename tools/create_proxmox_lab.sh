#!/usr/bin/env bash
# Run on an amd64 Proxmox node; creates hosts only, not WebClock installations.
set -Eeuo pipefail
umask 077

usage() {
    cat <<'EOF'
建立 HA OS、Ubuntu 原生安裝、Ubuntu Docker 測試 VM（不安裝 WebClock）。
用法：bash create_proxmox_lab.sh --ssh-key /root/lab.pub [選項]
  --storage NAME    VM 磁碟儲存區，預設 local-lvm
  --bridge NAME     可通往手機區網的 bridge，預設 vmbr0；需要 DHCP
  --base-id NUMBER  三個連續 VM ID，預設 981、982、983
  --ssh-key PATH    登入兩台 Ubuntu 的 SSH 公鑰，必填；使用者 ubuntu
  --ha-version TAG HA OS 正式版 tag，預設從官方 latest 解析
  --help           顯示說明
既有 VM 不覆寫。失敗時保留已建立的 VM，供檢查；不自動刪除或重設。
EOF
}
die() { echo "錯誤：$*" >&2; exit 1; }
storage=local-lvm
bridge=vmbr0
base_id=981
ssh_key=
ha_version=latest
while (($#)); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --storage|--bridge|--base-id|--ssh-key|--ha-version)
            (($# >= 2)) || die "$1 缺少值"
            case "$1" in
                --storage) storage=$2 ;;
                --bridge) bridge=$2 ;;
                --base-id) base_id=$2 ;;
                --ssh-key) ssh_key=$2 ;;
                --ha-version) ha_version=$2 ;;
            esac
            shift 2 ;;
        *) die "未知參數：$1" ;;
    esac
done
[[ $storage =~ ^[A-Za-z][A-Za-z0-9_-]*$ ]] || die 'storage 名稱不合法'
[[ $bridge =~ ^[A-Za-z][A-Za-z0-9_.-]*$ ]] || die 'bridge 名稱不合法'
[[ $base_id =~ ^[1-9][0-9]{2,8}$ ]] || die 'VM ID 必須介於 100 與 999999997'
((base_id <= 999999997)) || die 'VM ID 超出範圍'
[[ $ha_version =~ ^[A-Za-z0-9._-]+$ ]] || die 'HA OS tag 不合法'
[[ -f $ssh_key ]] || die '請用 --ssh-key 指定 SSH 公鑰檔案'
[[ $(id -u) == 0 ]] || die '請在 Proxmox 主機以 root 執行'
[[ $(uname -m) == x86_64 ]] || die '此腳本僅支援 amd64 Proxmox'
for command in qm pvesh pvesm ip curl python3 xz sha256sum ssh-keygen qemu-img; do
    command -v "$command" >/dev/null || die "缺少指令：$command"
done
ssh-keygen -lf "$ssh_key" >/dev/null || die '無效的 SSH 公鑰'
ip link show dev "$bridge" >/dev/null || die "找不到 bridge：$bridge"
storage_status=$(pvesm status --storage "$storage" --content images)
awk -v s="$storage" '$1 == s && $3 == "active" { ok=1 } END { exit !ok }' \
    <<<"$storage_status" || die 'storage 不可用或不支援 VM images'

# Check the entire cluster, including LXC IDs, before downloading or creating anything.
cluster=$(pvesh get /cluster/resources --type vm --output-format json)
python3 -c '
import json, sys
base = int(sys.argv[1])
used = {int(vm["vmid"]) for vm in json.load(sys.stdin)}
conflicts = used.intersection(range(base, base + 3))
if conflicts:
    sys.exit("VM ID 已被使用：" + ", ".join(map(str, sorted(conflicts))))
' "$base_id" <<<"$cluster"

work=$(mktemp -d /var/tmp/webclock-lab.XXXXXXXX)
trap 'rc=$?; if ((rc)); then echo "建立未完成；保留 VM 與下載檔：${work}。請檢查後再處理，不要直接重跑覆寫。" >&2; else rm -rf -- "$work"; fi' EXIT
echo "將建立 $base_id/$((base_id+1))/$((base_id+2))；storage=$storage bridge=$bridge"
echo '配置合計：6 vCPU、8 GiB RAM、至少 76 GiB 虛擬磁碟；下載暫存另需約 10 GiB。'
fetch() { curl --fail --location --retry 3 --connect-timeout 20 --proto '=https' --proto-redir '=https' "$1" -o "$2"; }
if [[ $ha_version == latest ]]; then
    release_url=https://api.github.com/repos/home-assistant/operating-system/releases/latest
else
    release_url="https://api.github.com/repos/home-assistant/operating-system/releases/tags/$ha_version"
fi
fetch "$release_url" "$work/ha-release.json"
python3 - "$work/ha-release.json" > "$work/ha-asset" <<'PY'
import json, re, sys
release = json.load(open(sys.argv[1]))
if release.get("draft") or release.get("prerelease"):
    sys.exit("只接受 HA OS 正式版")
assets = [a for a in release["assets"]
          if re.fullmatch(r"haos_ova-[A-Za-z0-9._-]+\.qcow2\.xz", a["name"])]
if len(assets) != 1:
    sys.exit("無法唯一識別 HA OS KVM 映像")
a = assets[0]
digest = a.get("digest") or ""
if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
    sys.exit("HA OS 資產缺少 SHA256 digest；停止，不略過校驗")
url = a["browser_download_url"]
if not url.startswith("https://github.com/home-assistant/operating-system/releases/download/"):
    sys.exit("非預期的 HA OS 下載來源")
print(url)
print(digest.removeprefix("sha256:"))
print(release["tag_name"])
PY
{ read -r ha_url; read -r ha_hash; read -r ha_tag; } < "$work/ha-asset"
echo "HA OS 版本：$ha_tag"
fetch "$ha_url" "$work/ha.qcow2.xz"
echo "$ha_hash  $work/ha.qcow2.xz" | sha256sum --check -
xz --decompress "$work/ha.qcow2.xz"

ubuntu_url=https://cloud-images.ubuntu.com/releases/noble/release
ubuntu_image=ubuntu-24.04-server-cloudimg-amd64.img
fetch "$ubuntu_url/SHA256SUMS" "$work/SHA256SUMS"
fetch "$ubuntu_url/$ubuntu_image" "$work/$ubuntu_image"
ubuntu_hash=$(awk -v f="$ubuntu_image" '$2 == f || $2 == "*" f { print $1 }' "$work/SHA256SUMS")
[[ $ubuntu_hash =~ ^[0-9a-f]{64}$ ]] || die 'Ubuntu SHA256 不存在或不唯一'
echo "$ubuntu_hash  $work/$ubuntu_image" | sha256sum --check -

# Reject backing files and check both images before mutating Proxmox.
for image in "$work/ha.qcow2" "$work/$ubuntu_image"; do
    qemu-img info --output=json "$image" | python3 -c '
import json, sys
i = json.load(sys.stdin)
if i.get("format") != "qcow2" or i.get("backing-filename"):
    sys.exit("映像必須為獨立 qcow2")
'
done

create_vm() {
    local vmid=$1 name=$2 memory=$3 image=$4 size=$5 kind=$6 volume current_size
    qm create "$vmid" --name "$name" --ostype l26 --cores 2 --memory "$memory" \
        --net0 "virtio,bridge=$bridge" --scsihw virtio-scsi-pci --onboot 0
    qm importdisk "$vmid" "$image" "$storage"
    volume=$(qm config "$vmid" | sed -n 's/^unused0: //p')
    [[ -n $volume && $volume != *$'\n'* ]] || die "VM $vmid 匯入後找不到唯一 unused0"
    qm set "$vmid" --scsi0 "$volume" --boot order=scsi0
    current_size=$(qemu-img info --output=json "$image" | python3 -c 'import json,sys; print(json.load(sys.stdin)["virtual-size"])')
    if ((current_size < size * 1024 * 1024 * 1024)); then
        qm resize "$vmid" scsi0 "${size}G"
    fi
    if [[ $kind == ha ]]; then
        qm set "$vmid" --bios ovmf --machine q35 \
            --efidisk0 "$storage:1,efitype=4m,pre-enrolled-keys=0"
    else
        qm set "$vmid" --ide2 "$storage:cloudinit" --ciuser ubuntu \
            --sshkeys "$ssh_key" --ipconfig0 ip=dhcp --serial0 socket --vga serial0
        qm cloudinit update "$vmid"
    fi
}
create_vm "$base_id" webclock-ha 4096 "$work/ha.qcow2" 32 ha
create_vm "$((base_id+1))" webclock-linux 2048 "$work/$ubuntu_image" 20 linux
create_vm "$((base_id+2))" webclock-docker 2048 "$work/$ubuntu_image" 24 linux
for vmid in "$base_id" "$((base_id+1))" "$((base_id+2))"; do
    qm start "$vmid"
done
cat <<EOF

三台 VM 已送出啟動命令（不代表系統／應用已就緒）：
  $base_id       webclock-ha       HA OS ${ha_tag}，等首次初始化完成後開啟 http://HA-IP:8123
  $((base_id+1))       webclock-linux    Ubuntu 24.04，ssh ubuntu@LINUX-IP
  $((base_id+2))       webclock-docker   Ubuntu 24.04，ssh ubuntu@DOCKER-IP

請在路由器 DHCP 租約或 Proxmox Console 查看 IP，並設定 DHCP 保留。
Ubuntu 只使用指定公鑰登入，沒有預設密碼；Docker Engine 與 WebClock 尚未安裝。
下一步見 doc/development/proxmox-lab.md；HA 首次設定、App 與 HACS 需另行完成。
測試 VM 未啟用宿主機開機自動啟動；確認後可在 Proxmox Options 調整。
EOF
