#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Load the updater before Git changes files in this directory.
exec python3 "$PROJECT_DIR/update_clock.py"
