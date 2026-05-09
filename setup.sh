#!/bin/bash

# Project Path (default to current directory)
PROJECT_DIR=$(pwd)
SERVICE_FILE="/etc/systemd/system/webclock.service"

# Ensure root privileges
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (sudo bash setup.sh)"
  exit
fi

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
read -p "Enter Port to run on (default 80): " user_port
user_port=${user_port:-80}

# Update Port in .env
sed -i "s|PORT=5000|PORT=$user_port|g" .env

cat > $SERVICE_FILE <<EOF
[Unit]
Description=WebClock Service
After=network.target

[Service]
User=$SUDO_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python3 $PROJECT_DIR/app.py
Restart=always
Environment=PORT=$user_port

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