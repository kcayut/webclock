#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "$*" >&2; exit 1; }
[ "$#" = 0 ] || fail "Usage: sudo bash scripts/enable_updates.sh"
[ "$(uname -s)" = Linux ] && command -v systemctl >/dev/null || fail "Bare metal updates require Linux and systemd."
[ "$(id -u)" = 0 ] || fail "Run: sudo bash scripts/enable_updates.sh"
case "$PROJECT_DIR" in *[[:space:]%\\]*) fail "Installation path must not contain whitespace, % or backslashes." ;; esac
[ "$(systemctl show webclock --property=WorkingDirectory --value)" = "$PROJECT_DIR" ] || fail "webclock.service uses another installation directory."
systemctl is-active --quiet webclock || fail "Start and verify webclock.service before enabling updates."
SERVICE_USER="$(systemctl show webclock --property=User --value)"
SERVICE_USER="$(id -un "${SERVICE_USER:-root}")"
SERVICE_GROUP="$(systemctl show webclock --property=Group --value)"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
[[ "$SERVICE_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]] || fail "Unsupported service user name."
[[ "$SERVICE_GROUP" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]] || fail "Unsupported service group name."
[ -x /usr/bin/systemctl ] && [ -x /usr/bin/python3 ] || fail "Expected /usr/bin/systemctl and /usr/bin/python3."
if [ ! -d "$PROJECT_DIR/.git" ] || [ -L "$PROJECT_DIR/.git" ]; then
    echo "Archive or non-Git installation: automatic release updates stay disabled."
    exit 0
fi
CHANNEL="$(git -c safe.directory="$PROJECT_DIR" -C "$PROJECT_DIR" config --get webclock.releaseChannel || true)"
if [ -z "$CHANNEL" ]; then
    echo "Developer checkout without a release channel: automatic release updates stay disabled."
    echo "To follow official releases instead, run: sudo bash update_clock.sh --channel stable"
    exit 0
fi
case "$CHANNEL" in stable|beta) ;; *) fail "Unknown release channel: $CHANNEL" ;; esac
for file in updater_service.py update_clock.py release_versions.py; do
    [ -f "$PROJECT_DIR/scripts/$file" ] && [ ! -L "$PROJECT_DIR/scripts/$file" ] || fail "Missing updater: scripts/$file"
done
for file in /etc/webclock-updater.json /etc/systemd/system/webclock-updater.service /etc/sudoers.d/webclock-updater "$PROJECT_DIR/venv" "$PROJECT_DIR/.webclock-update.lock"; do
    [ ! -L "$file" ] || fail "Updater path must not be a symlink: $file"
done
[ ! -e "$PROJECT_DIR/.webclock-update.lock" ] || [ -f "$PROJECT_DIR/.webclock-update.lock" ] || fail "Update lock must be a regular file."
if [ "$SERVICE_USER" != root ]; then
    command -v sudo >/dev/null && command -v visudo >/dev/null || fail "Install sudo before enabling updates."
    runuser -u "$SERVICE_USER" -- test -w "$PROJECT_DIR" || fail "The service user must own the Git installation directory."
    runuser -u "$SERVICE_USER" -- test -w "$PROJECT_DIR/.git" || fail "The service user must own the Git repository."
    # Earlier installations created the virtual environment as root.
    chown -hR "$SERVICE_USER:$SERVICE_GROUP" "$PROJECT_DIR/venv"
    [ ! -e "$PROJECT_DIR/.webclock-update.lock" ] || chown "$SERVICE_USER:$SERVICE_GROUP" "$PROJECT_DIR/.webclock-update.lock"
    sudoers="$(mktemp)"
    trap 'rm -f "$sudoers"' EXIT
    printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl start webclock, /usr/bin/systemctl stop webclock\n' "$SERVICE_USER" > "$sudoers"
    visudo -cf "$sudoers" >/dev/null
    install -o root -g root -m 440 "$sudoers" /etc/sudoers.d/webclock-updater
fi

# The service runs the updater shipped in this installation (same user as WebClock), so each
# release also upgrades its updater. Earlier builds copied a frozen version here; remove it.
rm -rf /usr/local/lib/webclock-updater
/usr/bin/python3 - "$PROJECT_DIR" "$CHANNEL" <<'PY'
import json
import os
from pathlib import Path
import sys
import tempfile

path = Path('/etc/webclock-updater.json')
value = {'project': sys.argv[1], 'channel': sys.argv[2], 'auto_update': True}
if path.exists():
    previous = json.loads(path.read_text())
    if previous.get('project') != value['project']:
        raise SystemExit('Another WebClock updater is already configured.')
    value = previous
descriptor, temporary = tempfile.mkstemp(prefix='.webclock-updater-', dir='/etc')
with os.fdopen(descriptor, 'w') as output:
    json.dump(value, output)
    output.write('\n')
os.replace(temporary, path)
PY
chown "root:$SERVICE_GROUP" /etc/webclock-updater.json
chmod 640 /etc/webclock-updater.json
cat > /etc/systemd/system/webclock-updater.service <<UNIT
[Unit]
Description=WebClock release updater
After=network-online.target webclock.service
Wants=network-online.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_GROUP
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/usr/bin/python3 $PROJECT_DIR/scripts/updater_service.py
Restart=always
RestartSec=3
RuntimeDirectory=webclock-updater
RuntimeDirectoryMode=0700
StateDirectory=webclock-updater
StateDirectoryMode=0700
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
chmod 644 /etc/systemd/system/webclock-updater.service
chown root:root /etc/systemd/system/webclock-updater.service
systemctl daemon-reload
systemctl enable webclock-updater
systemctl restart webclock-updater
systemctl is-active --quiet webclock-updater
echo "WebClock updates are enabled. Manage the release channel and automatic updates in the Update page."
