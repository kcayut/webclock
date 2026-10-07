#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER=false
MANAGED=false
for argument in "$@"; do
    case "$argument" in
        --docker) DOCKER=true ;;
        --managed) MANAGED=true ;;
        -h|--help)
            echo "Usage: bash setup.sh [--docker] [--managed]"
            echo "Fresh install: Linux/systemd by default; --docker uses Docker Compose."
            echo "Self mode is the default. --managed creates admin and requires HTTPS."
            echo "Existing installations: see doc/installation.md for updates and mode changes."
            exit 0 ;;
        *) echo "Unknown option: $argument" >&2; exit 1 ;;
    esac
done

cd "$PROJECT_DIR"
if $DOCKER; then
    docker compose version >/dev/null
    docker info >/dev/null
else
    if [ "$(uname -s)" != Linux ] || ! command -v apt-get >/dev/null || ! command -v systemctl >/dev/null; then
        echo "Use Debian/Ubuntu/Raspberry Pi OS with systemd, or --docker." >&2
        exit 1
    fi
    if [ "$(id -u)" -ne 0 ]; then
        exec sudo bash "$PROJECT_DIR/scripts/setup.sh" "$@"
    fi
    SERVICE_FILE="/etc/systemd/system/webclock.service"
    SERVICE_USER="${SUDO_USER:-root}"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
    if systemctl cat webclock.service >/dev/null 2>&1; then
        echo "WebClock is already installed. Use update_clock.sh; see doc/installation.md for mode changes." >&2
        exit 1
    fi
    # systemd paths must not be interpreted as argument separators/specifiers.
    case "$PROJECT_DIR" in
        *[[:space:]%\\]*) echo "Install in a path without spaces, % or backslashes." >&2; exit 1 ;;
    esac
fi

umask 022
if [ ! -e .env ]; then
    (umask 077; cp .env.example .env)
fi

if $DOCKER; then
    # Keep the old read-only notes mount for migration, without a manual touch step.
    if [ ! -e manual_notes.json ]; then
        (umask 077; printf '[]\n' > manual_notes.json)
    fi
    if [ ! -f manual_notes.json ]; then
        echo "manual_notes.json must be a file. See doc/installation.md." >&2
        exit 1
    fi
    (umask 077; mkdir -p webclock_state tls)
    if $MANAGED; then
        state_entries="$(ls -A webclock_state)"
        if [ -n "$state_entries" ]; then
            echo "Existing state found. Stop and back up WebClock before changing mode; see doc/installation.md." >&2
            exit 1
        fi
    fi
    containers="$(docker compose ps -aq)"
    if [ -n "$containers" ]; then
        echo "Existing containers found. Use docker compose up -d --build for updates." >&2
        exit 1
    fi
    docker compose build
    if $MANAGED; then
        docker compose run --rm --no-deps webclock python scripts/manage_auth.py setup --username admin --enable-managed
    fi
    docker compose up -d
    docker compose ps
else
    apt-get update
    apt-get install -y git python3 python3-pip python3-venv
    if [ ! -d venv ]; then
        python3 -m venv venv
    fi
    venv/bin/python -m pip install -r requirements.txt
    venv/bin/python -m pip check
    state_dir="$(venv/bin/python -c 'from dotenv import load_dotenv; import os; load_dotenv(".env"); print(os.getenv("WEBCLOCK_STATE_DIR", "webclock_state"))')"
    user_port="$(venv/bin/python -c 'from dotenv import load_dotenv; import os; load_dotenv(".env"); p=int(os.getenv("PORT", "5000")); assert 1 <= p <= 65535, "Invalid PORT"; print(p)')"
    if $MANAGED && [ -d "$state_dir" ]; then
        state_entries="$(ls -A "$state_dir")"
        if [ -n "$state_entries" ]; then
            echo "Existing state found. Stop and back up WebClock before changing mode; see doc/installation.md." >&2
            exit 1
        fi
    fi
    chown "$SERVICE_USER:$SERVICE_GROUP" .env
    chmod 600 .env
    if [ ! -d "$state_dir" ]; then
        install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 700 "$state_dir"
    fi
    runuser -u "$SERVICE_USER" -- test -w "$state_dir"
    if $MANAGED; then
        runuser -u "$SERVICE_USER" -- venv/bin/python scripts/manage_auth.py setup --username admin --enable-managed
    fi
    cat > "$SERVICE_FILE" <<UNIT
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
UNIT
    systemctl daemon-reload
    systemctl enable --now webclock
    systemctl is-active --quiet webclock
    echo "WebClock service started on port $user_port."
fi

if $MANAGED; then
    echo "Managed mode initialized (username: admin). HTTPS is required for login and device enrollment."
    echo "Configure TLS as described in doc/installation.md before opening /admin."
else
    echo "Self mode is the default; existing authorization is preserved. Open /admin to configure WebClock."
fi
