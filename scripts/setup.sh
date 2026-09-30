#!/bin/bash
set -euo pipefail

# Project Path (script directory)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_FILE="/etc/systemd/system/webclock.service"
SERVICE_USER="${SUDO_USER:-root}"

# Ensure root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo bash setup.sh)"
  exit
fi

cd "$PROJECT_DIR"

echo "=== 1. Updating system and installing dependencies ==="
apt update
apt install -y git python3 python3-pip python3-venv

echo "=== 2. Creating Python virtual environment ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created."
else
    echo "Virtual environment already exists, skipping."
fi

echo "=== 3. Installing Python packages ==="
./venv/bin/pip install -r requirements.txt

echo "=== 4. Configuring environment variables (.env) ==="
if [ ! -f ".env" ]; then
    echo ".env not found, creating one."
    cp .env.example .env

    read -p "Please paste your Google Calendar Private URL (ICAL_URL): " user_ical_url
    # Replace value in .env
    sed -i "s|ICAL_URL=|ICAL_URL=$user_ical_url|g" .env

    echo ".env created."
else
    echo ".env already exists, skipping."
fi

echo "=== 5. Setting up Systemd service ==="
# Ask for Port
read -p "Enter Port to run on (default 5000): " user_port
user_port=${user_port:-5000}

# Update Port in .env
if grep -q '^PORT=' .env; then
    sed -i "s|^PORT=.*|PORT=$user_port|g" .env
else
    echo "PORT=$user_port" >> .env
fi

chown "$SERVICE_USER":"$SERVICE_USER" .env
if [ -f manual_notes.json ]; then
    chown "$SERVICE_USER":"$SERVICE_USER" manual_notes.json
fi
install -d -o "$SERVICE_USER" -g "$(id -gn "$SERVICE_USER")" -m 700 webclock_state
if [ -f webclock_state/settings.json ]; then
    chown "$SERVICE_USER:$(id -gn "$SERVICE_USER")" webclock_state/settings.json
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=WebClock Service
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python3 $PROJECT_DIR/app.py
Restart=always
EnvironmentFile=$PROJECT_DIR/.env
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable webclock
systemctl restart webclock

echo "==========================================="
echo "  Installation Complete!  "
echo "  Service running on Port: $user_port"
echo "==========================================="
