#!/bin/bash
# Keep the command printed in previously published HA App documentation working.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$PROJECT_DIR/homeassistant/prepare_local_app.sh" "$@"
