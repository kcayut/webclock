#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER=false
MANAGED=false
BUILD=false
ENABLE_UPDATES=false
AUTO_UPDATE=""
TLS_CERT=""
TLS_KEY=""
TLS_HOST=""
TLS_CA=""
ORIGINAL_ARGS=("$@")
while [ "$#" -gt 0 ]; do
    case "$1" in
        --docker) DOCKER=true ;;
        --managed) MANAGED=true ;;
        --build) BUILD=true ;;
        --enable-updates) ENABLE_UPDATES=true ;;
        --auto-update)
            [ "$#" -ge 2 ] || { echo 'Missing on/off value' >&2; exit 1; }
            AUTO_UPDATE="$2"; shift ;;
        --tls-cert|--tls-key|--tls-host|--tls-ca)
            [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 1; }
            case "$1" in
                --tls-cert) TLS_CERT="$2" ;;
                --tls-key) TLS_KEY="$2" ;;
                --tls-host) TLS_HOST="$2" ;;
                --tls-ca) TLS_CA="$2" ;;
            esac
            shift ;;
        -h|--help)
            echo "Usage: bash setup.sh [--docker [--build]] [--managed] [--tls-cert FILE --tls-key FILE --tls-host NAME [--tls-ca FILE]]"
            echo "Fresh install: Linux/systemd by default; Docker pulls the release image. --build is for development."
            echo "Self mode is the default. Managed prefers HTTPS; without a certificate, two prompts let you explicitly choose HTTP for a trusted LAN."
            echo "Updates: --enable-updates opts Docker into a Linux host worker; --auto-update on|off explicitly sets automatic installation (default off)."
            echo "Failed new installs: correct the reported problem and repeat the same command; existing credentials are preserved."
            echo "Existing installations: see doc/installation.md for updates and mode changes."
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done
fail() { echo "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null || fail "Required command missing: $1. Install it and run this command again."; }
set_env() {
    local name="$1" value="$2" temporary
    case "$value" in *[[:space:]\"\'\\]*) fail "TLS settings must not contain whitespace, quotes or backslashes." ;; esac
    temporary="$(mktemp "$PROJECT_DIR/.env.install.XXXXXX")"
    awk -v key="$name" '$0 !~ "^(export[[:space:]]+)?" key "[[:space:]]*=" {print}' .env > "$temporary"
    printf '%s=%s\n' "$name" "$value" >> "$temporary"
    chmod 600 "$temporary"
    mv "$temporary" .env
}
$BUILD && ! $DOCKER && fail "--build requires --docker."
case "$AUTO_UPDATE" in ''|on|off) ;; *) fail '--auto-update must be on or off.' ;; esac
if $DOCKER; then
    [ -z "$AUTO_UPDATE" ] || $ENABLE_UPDATES || fail 'Docker --auto-update requires --enable-updates.'
    if $ENABLE_UPDATES; then
        [ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] || fail 'Use sudo on Linux for --enable-updates.'
        require systemctl
        require python3
        /usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail 'The Docker worker requires /usr/bin/python3 version 3.9+.'
        python3 -E -s - "$PROJECT_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from scripts.docker_update import root_owned
root_owned(__import__('pathlib').Path(sys.argv[1]))
PY
    fi
fi
[ -n "$TLS_CERT" ] && [ -z "$TLS_KEY" ] && fail "Use --tls-cert and --tls-key together."
[ -n "$TLS_KEY" ] && [ -z "$TLS_CERT" ] && fail "Use --tls-cert and --tls-key together."
for file in "$TLS_CERT" "$TLS_KEY" "$TLS_CA"; do
    [ -z "$file" ] || [ -r "$file" ] || fail "TLS file is not readable: $file"
done
# Resolve user-supplied paths before changing directory or elevating privileges.
[ -z "$TLS_CERT" ] || TLS_CERT="$(cd "$(dirname "$TLS_CERT")" && pwd)/$(basename "$TLS_CERT")"
[ -z "$TLS_KEY" ] || TLS_KEY="$(cd "$(dirname "$TLS_KEY")" && pwd)/$(basename "$TLS_KEY")"
[ -z "$TLS_CA" ] || TLS_CA="$(cd "$(dirname "$TLS_CA")" && pwd)/$(basename "$TLS_CA")"

EXISTING=()
KIND=systemd
MODE=self
$MANAGED && MODE=managed
if $DOCKER; then
    KIND=docker
    require docker
    docker compose version >/dev/null || fail "Docker Compose v2 is required."
    docker info >/dev/null || fail "Start Docker and confirm your user can access it."
else
    if [ "$(uname -s)" != Linux ] || ! command -v apt-get >/dev/null || ! command -v systemctl >/dev/null; then
        fail "Use Debian/Ubuntu/Raspberry Pi OS with systemd, or --docker."
    fi
    if [ "$(id -u)" -ne 0 ]; then
        require sudo
        exec sudo bash "$PROJECT_DIR/scripts/setup.sh" ${ORIGINAL_ARGS[@]+"${ORIGINAL_ARGS[@]}"}
    fi
    require runuser
    SERVICE_FILE="/etc/systemd/system/webclock.service"
    SERVICE_USER="${SUDO_USER:-root}"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
    if systemctl cat webclock.service >/dev/null 2>&1; then
        [ -f "$PROJECT_DIR/.webclock-install.json" ] || fail "WebClock is already installed. Use update_clock.sh; see doc/installation.md for mode changes."
        [ "$(systemctl show webclock --property=WorkingDirectory --value)" = "$PROJECT_DIR" ] || fail "Existing service uses another installation directory."
        EXISTING=(--existing)
    fi
    case "$PROJECT_DIR" in
        *[[:space:]%\\]*) fail "Install in a path without spaces, % or backslashes." ;;
    esac
fi

cd "$PROJECT_DIR"
umask 022
[ ! -L .env ] || fail ".env must not be a symlink."
if [ ! -e .env ]; then
    (umask 077; cp .env.example .env)
fi
[ -f .env ] || fail ".env must be a file."

if $DOCKER; then
    containers="$(docker compose ps -aq)"
    [ -z "$containers" ] || EXISTING=(--existing)
    if [ ! -f .webclock-install.json ] && { [ -n "$containers" ] || { [ -d webclock_state ] && [ -n "$(ls -A webclock_state)" ]; }; }; then
        fail "Existing installation/data found. Use docker_update.sh (older releases: portable_docker_update.sh); see doc/installation.md."
    fi
    # Compose gives shell variables priority; persist the selected port for checks and retries.
    [ -z "${WEBCLOCK_HTTP_PORT:-}" ] || set_env WEBCLOCK_HTTP_PORT "$WEBCLOCK_HTTP_PORT"
    if $BUILD; then docker compose build; else docker compose pull webclock; fi
    IMAGE="$(docker compose config --images)"
    [ -n "$IMAGE" ] && [ "$(printf '%s\n' "$IMAGE" | wc -l | tr -d ' ')" = 1 ] || fail "Expected one WebClock Compose image."
    # Run checks using Python already present in the release image, not on the host.
    CHECK=(docker run --rm --add-host host.docker.internal:host-gateway --entrypoint python
           --env "WEBCLOCK_INSTALL_HOST=$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
           --mount "type=bind,src=$PROJECT_DIR,dst=/install" --workdir /install "$IMAGE" scripts/install_check.py)
    # Only the confirmation step may consume stdin; other checks must not eat queued answers.
    TRANSPORT_CHECK=(docker run -i "${CHECK[@]:2}")
else
    apt-get update
    apt-get install -y git python3 python3-pip python3-venv
    [ ! -L venv ] || fail "venv must not be a symlink."
    [ -d venv ] || python3 -m venv venv
    venv/bin/python -m pip install -r requirements.txt
    venv/bin/python -m pip check
    CHECK=(venv/bin/python scripts/install_check.py)
    TRANSPORT_CHECK=("${CHECK[@]}")
fi
"${CHECK[@]}" guard --kind "$KIND" --mode "$MODE" --project-id "$PROJECT_DIR" ${EXISTING[@]+"${EXISTING[@]}"}

if [ -n "$TLS_CERT" ]; then
    [ ! -L tls ] || fail "tls must not be a symlink."
    (umask 077; mkdir -p tls)
    for target in tls/install-cert.pem tls/install-key.pem tls/install-ca.pem; do
        [ ! -L "$target" ] || fail "TLS destination must not be a symlink: $target"
    done
    for pair in cert key; do
        if [ "$pair" = cert ]; then source="$TLS_CERT"; else source="$TLS_KEY"; fi
        cmp -s "$source" "tls/install-$pair.pem" || (umask 077; cp "$source" "tls/install-$pair.pem")
    done
    TLS_PREFIX="$PROJECT_DIR/tls"
    $DOCKER && TLS_PREFIX=/app/tls
    set_env WEBCLOCK_TLS_CERT "$TLS_PREFIX/install-cert.pem"
    set_env WEBCLOCK_TLS_KEY "$TLS_PREFIX/install-key.pem"
fi
if [ -n "$TLS_CA" ]; then
    [ ! -L tls ] && [ ! -L tls/install-ca.pem ] || fail "TLS destination must not be a symlink."
    (umask 077; mkdir -p tls)
    cmp -s "$TLS_CA" tls/install-ca.pem || (umask 077; cp "$TLS_CA" tls/install-ca.pem)
    TLS_PREFIX="$PROJECT_DIR/tls"
    $DOCKER && TLS_PREFIX=/app/tls
    set_env WEBCLOCK_UPDATE_CA "$TLS_PREFIX/install-ca.pem"
fi
[ -z "$TLS_HOST" ] || set_env WEBCLOCK_UPDATE_HOST "$TLS_HOST"
if $MANAGED; then
    "${TRANSPORT_CHECK[@]}" transport --kind "$KIND"
fi
state_dir="$("${CHECK[@]}" prepare --kind "$KIND" --mode "$MODE" --project-id "$PROJECT_DIR" ${EXISTING[@]+"${EXISTING[@]}"})"
trap 'echo "Install incomplete. Correct the error and repeat the same command. New-install state and credentials are preserved. See doc/installation.md for recovery." >&2' ERR

if $DOCKER; then
    if [ "${#EXISTING[@]}" = 0 ]; then
        user_port="$("${CHECK[@]}" port)"
        docker run --rm -p "$user_port:5000" --entrypoint true "$IMAGE" || fail "Port $user_port is unavailable. Stop the conflicting service or change WEBCLOCK_HTTP_PORT in .env before retrying."
    fi
    [ -e manual_notes.json ] || (umask 077; printf '[]\n' > manual_notes.json)
    [ -f manual_notes.json ] && [ ! -L manual_notes.json ] || fail "manual_notes.json must be a regular file."
    (umask 077; mkdir -p webclock_state tls .webclock-mode-backups-webclock_state webclock_updater_run)
    if $MANAGED && [ "$("${CHECK[@]}" auth-needed)" = yes ]; then
        docker compose run --rm --no-deps --pull never webclock python scripts/manage_auth.py setup --username admin --enable-managed
    fi
    docker compose up -d --no-build
else
    chown "$SERVICE_USER:$SERVICE_GROUP" .env
    chmod 600 .env
    if [ -n "$TLS_CERT" ] || [ -n "$TLS_CA" ]; then
        chown "$SERVICE_USER:$SERVICE_GROUP" tls tls/install-*.pem
        chmod 700 tls
        chmod 600 tls/install-*.pem
    fi
    while IFS= read -r tls_file; do
        runuser -u "$SERVICE_USER" -- test -r "$tls_file" || fail "Service user cannot read TLS file: $tls_file"
    done < <("${CHECK[@]}" tls-files)
    [ -d "$state_dir" ] || install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 700 "$state_dir"
    runuser -u "$SERVICE_USER" -- test -w "$state_dir"
    if $MANAGED && [ "$("${CHECK[@]}" auth-needed)" = yes ]; then
        runuser -u "$SERVICE_USER" -- venv/bin/python scripts/manage_auth.py setup --username admin --enable-managed
    fi
    if [ "${#EXISTING[@]}" = 0 ]; then
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
    fi
    systemctl daemon-reload
    systemctl enable webclock
    systemctl restart webclock
    systemctl is-active --quiet webclock
fi
"${CHECK[@]}" wait
if ! $DOCKER; then
    bash "$PROJECT_DIR/scripts/enable_updates.sh"
elif $ENABLE_UPDATES; then
    bash "$PROJECT_DIR/scripts/enable_docker_updates.sh"
fi
if [ -n "$AUTO_UPDATE" ]; then
    /usr/bin/python3 "$PROJECT_DIR/scripts/update_settings.py" --kind "$KIND" --project "$PROJECT_DIR" --auto-update "$AUTO_UPDATE"
fi
"${CHECK[@]}" complete
trap - ERR
echo "WebClock is ready ($MODE mode)."
