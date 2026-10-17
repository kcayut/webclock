#!/usr/bin/env bash
# Compatibility entry for existing Compose installations.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$PROJECT_DIR/scripts/update/docker_update.sh" "$@"
