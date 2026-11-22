#!/bin/bash
# Compatibility and main entry point for bare-metal Linux/systemd updates.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$PROJECT_DIR/update_clock.py" "$@"
