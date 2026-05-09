#!/bin/bash

# Project Directory
PROJECT_DIR=$(pwd)

echo "=== 1. Pulling updates from Git... ==="
git pull

if [ $? -ne 0 ]; then
    echo "Git pull failed. Please check your network."
    exit 1
fi

echo "=== 2. Updating Python packages... ==="
./venv/bin/pip install -r requirements.txt

echo "=== 3. Restarting service... ==="
systemctl restart webclock

echo "Update Complete!"