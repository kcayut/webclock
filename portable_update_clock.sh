#!/usr/bin/env bash
set -euo pipefail

REQUESTED_PROJECT_DIR="${1:-/opt/webclock}"

if (( $# > 1 )); then
    echo "Usage: $0 [webclock-project-directory]" >&2
    exit 2
fi

if (( EUID == 0 )); then
    echo "Run this script without sudo; it will request sudo only for the updater." >&2
    exit 1
fi

for command in git python3 sudo mktemp; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command not found: $command" >&2
        exit 1
    fi
done

if ! PROJECT_DIR="$(cd "$REQUESTED_PROJECT_DIR" 2>/dev/null && pwd -P)"; then
    echo "WebClock project directory not found: $REQUESTED_PROJECT_DIR" >&2
    exit 1
fi

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    echo "Not a WebClock Git checkout: $PROJECT_DIR" >&2
    exit 1
fi

echo "Fetching the configured upstream for: $PROJECT_DIR"
git -C "$PROJECT_DIR" fetch
UPSTREAM_COMMIT="$(git -C "$PROJECT_DIR" rev-parse --verify '@{upstream}^{commit}')"

UPDATER_FILE="$(mktemp "${TMPDIR:-/tmp}/webclock-updater.XXXXXX")"
cleanup() {
    rm -f -- "$UPDATER_FILE"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

git -C "$PROJECT_DIR" show "${UPSTREAM_COMMIT}:update_clock.py" > "$UPDATER_FILE"
if [[ ! -s "$UPDATER_FILE" ]]; then
    echo "The upstream update_clock.py is empty or unavailable." >&2
    exit 1
fi

echo "Starting the guarded WebClock updater from upstream commit $UPSTREAM_COMMIT"
sudo python3 "$UPDATER_FILE" "$PROJECT_DIR"
