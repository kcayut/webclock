#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v python3 >/dev/null || { echo 'Docker updates require Python 3.9+ on the host. Debian/Ubuntu: sudo apt-get install python3' >&2; exit 1; }
exec python3 "$PROJECT_DIR/scripts/docker_update.py" --project "$PROJECT_DIR" "$@"
