#!/bin/bash
# Prepare a complete local App build context; never copy private runtime data.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINATION="${1:-/addons/webclock}"
if [ "$#" -gt 1 ]; then
    echo "Usage: bash scripts/prepare_ha_app.sh [new-directory]" >&2
    exit 1
fi
if [ -e "$DESTINATION" ] || [ -L "$DESTINATION" ]; then
    echo "Destination exists; choose a new directory: $DESTINATION" >&2
    exit 1
fi
mkdir -p "$(dirname "$DESTINATION")"
DESTINATION="$(cd "$(dirname "$DESTINATION")" && pwd)/$(basename "$DESTINATION")"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
cd "$PROJECT_DIR"
cp app.py sw.js requirements.txt .dockerignore "$staging/"
cp -R webclock templates static "$staging/"
cp homeassistant/addon/Dockerfile homeassistant/addon/README.md "$staging/"
sed '/^image:/d' homeassistant/addon/config.yaml > "$staging/config.yaml"
mv "$staging" "$DESTINATION"
echo "Local App prepared: $DESTINATION"
echo "In Home Assistant: App store > Check for updates > Local apps > WebClock > Install > Start."
