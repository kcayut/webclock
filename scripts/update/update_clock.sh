#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$PROJECT_DIR/update_clock.py" "$@"
if [[ -f "$PROJECT_DIR/scripts/enable_updates.sh" ]]; then
    bash "$PROJECT_DIR/scripts/enable_updates.sh"
fi
