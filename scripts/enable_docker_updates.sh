#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$#" = 0 ] || { echo 'Usage: sudo bash scripts/enable_docker_updates.sh' >&2; exit 1; }
[ "$(uname -s)" = Linux ] && command -v systemctl >/dev/null || { echo 'Linux/systemd is required.' >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'Run with sudo on the Docker host.' >&2; exit 1; }
/usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo 'The host worker requires /usr/bin/python3 version 3.9 or newer.' >&2; exit 1; }
exec /usr/bin/python3 -E -s "$PROJECT_DIR/scripts/docker_update_install.py" "$PROJECT_DIR"
