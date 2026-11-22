#!/usr/bin/env bash
set -euo pipefail

UPSTREAM=false
REQUESTED_PROJECT_DIR=""

while (( $# )); do
    case "$1" in
        --upstream)
            UPSTREAM=true
            shift ;;
        -h|--help)
            echo "Usage: bash portable_update_clock.sh [--upstream] [webclock-project-directory]"
            echo "Defaults to /opt/webclock and official GitHub Releases (stable by default, preserving configured beta)."
            echo "Add --upstream to explicitly update from the checkout's already-configured Git tracking branch (such as Gitea) without changing releaseChannel."
            exit 0 ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--upstream] [webclock-project-directory]" >&2
            exit 2 ;;
        *)
            if [[ -n "$REQUESTED_PROJECT_DIR" ]]; then
                echo "Usage: $0 [--upstream] [webclock-project-directory]" >&2
                exit 2
            fi
            REQUESTED_PROJECT_DIR="$1"
            shift ;;
    esac
done

REQUESTED_PROJECT_DIR="${REQUESTED_PROJECT_DIR:-/opt/webclock}"

for command in git python3 mktemp; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command not found: $command" >&2
        exit 1
    fi
done

SUDO=()
if (( EUID != 0 )); then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Required command not found: sudo" >&2
        exit 1
    fi
    SUDO=(sudo)
fi

if ! PROJECT_DIR="$(cd "$REQUESTED_PROJECT_DIR" 2>/dev/null && pwd -P)"; then
    echo "WebClock project directory not found: $REQUESTED_PROJECT_DIR" >&2
    exit 1
fi

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    echo "Not a WebClock Git checkout: $PROJECT_DIR" >&2
    exit 1
fi

updater_supports() {
    local flag="$1"
    if [[ -f "$PROJECT_DIR/scripts/update_clock.py" ]]; then
        grep -q -- "$flag" "$PROJECT_DIR/scripts/update_clock.py"
    elif [[ -f "$PROJECT_DIR/update_clock.py" ]]; then
        grep -q -- "$flag" "$PROJECT_DIR/update_clock.py"
    else
        return 1
    fi
}

if ! $UPSTREAM; then
    CHANNEL="$(git -c safe.directory="$PROJECT_DIR" -C "$PROJECT_DIR" config --get webclock.releaseChannel || true)"
    case "$CHANNEL" in
        ''|stable) SELECTED_CHANNEL=stable ;;
        beta) SELECTED_CHANNEL=beta ;;
        *) echo "Unknown WebClock release channel: $CHANNEL" >&2; exit 1 ;;
    esac
    if ! updater_supports '--channel'; then
        echo "This checkout's updater does not support --channel official releases; upgrade it first or pass --upstream explicitly if using a configured Git upstream." >&2
        exit 1
    fi
    "${SUDO[@]}" python3 "$PROJECT_DIR/update_clock.py" --channel "$SELECTED_CHANNEL" "$PROJECT_DIR"
    if [[ -f "$PROJECT_DIR/scripts/enable_updates.sh" ]]; then
        "${SUDO[@]}" bash "$PROJECT_DIR/scripts/enable_updates.sh"
    fi
    exit 0
fi

if updater_supports '--upstream'; then
    "${SUDO[@]}" python3 "$PROJECT_DIR/update_clock.py" --upstream "$PROJECT_DIR"
    if [[ -f "$PROJECT_DIR/scripts/enable_updates.sh" ]]; then
        "${SUDO[@]}" bash "$PROJECT_DIR/scripts/enable_updates.sh"
    fi
    exit 0
fi

GIT_RUN=()
if (( EUID == 0 )) && command -v runuser >/dev/null 2>&1; then
    REPO_OWNER="$(python3 - "$PROJECT_DIR/.git" <<'PY'
import os, pwd, sys
print(pwd.getpwuid(os.stat(sys.argv[1]).st_uid).pw_name)
PY
)"
    if [[ -n "$REPO_OWNER" && "$REPO_OWNER" != root ]]; then
        GIT_RUN=(runuser -u "$REPO_OWNER" --)
    fi
fi

run_git() {
    ${GIT_RUN[@]+"${GIT_RUN[@]}"} git -c safe.directory="$PROJECT_DIR" -C "$PROJECT_DIR" "$@"
}

if ! run_git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    echo "No Git upstream tracking branch is configured; configure one or run without --upstream to use official releases." >&2
    exit 1
fi

echo "Fetching the configured upstream for: $PROJECT_DIR"
run_git fetch
HEAD_COMMIT="$(run_git rev-parse --verify 'HEAD^{commit}')"
UPSTREAM_COMMIT="$(run_git rev-parse --verify '@{upstream}^{commit}')"

if ! run_git merge-base --is-ancestor "$HEAD_COMMIT" "$UPSTREAM_COMMIT"; then
    echo "Upstream commit does not descend from the installed version; refusing non-fast-forward update or downgrade." >&2
    exit 1
fi

OLD_VERSION="$(run_git show "${HEAD_COMMIT}:VERSION" 2>/dev/null || true)"
NEW_VERSION="$(run_git show "${UPSTREAM_COMMIT}:VERSION" 2>/dev/null || true)"
if [[ -n "$OLD_VERSION" && -z "$NEW_VERSION" ]]; then
    echo "Upstream commit is missing VERSION; refusing downgrade." >&2
    exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RELEASE_VERSIONS_FILE=""
if [[ -f "$PROJECT_DIR/scripts/release_versions.py" ]]; then
    RELEASE_VERSIONS_FILE="$PROJECT_DIR/scripts/release_versions.py"
elif [[ -f "$SCRIPT_DIR/../release_versions.py" ]]; then
    RELEASE_VERSIONS_FILE="$SCRIPT_DIR/../release_versions.py"
fi
if [[ -n "$OLD_VERSION" && -n "$NEW_VERSION" && -n "$RELEASE_VERSIONS_FILE" ]]; then
    python3 - "$RELEASE_VERSIONS_FILE" "$OLD_VERSION" "$NEW_VERSION" <<'PY'
import importlib.util, sys

spec = importlib.util.spec_from_file_location('release_versions', sys.argv[1])
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)
old_v, new_v = sys.argv[2].strip(), sys.argv[3].strip()
try:
    if rv.parse_version(new_v) < rv.parse_version(old_v):
        raise SystemExit(f'Downgrades are unsupported ({old_v} -> {new_v}).')
except ValueError as error:
    raise SystemExit(str(error))
PY
fi

UPDATER_FILE="$(mktemp "${TMPDIR:-/tmp}/webclock-updater.XXXXXX")"
cleanup() {
    rm -f -- "$UPDATER_FILE"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

run_git show "${UPSTREAM_COMMIT}:update_clock.py" > "$UPDATER_FILE"
if [[ ! -s "$UPDATER_FILE" ]]; then
    echo "The upstream update_clock.py is empty or unavailable." >&2
    exit 1
fi

echo "Starting the guarded WebClock updater from upstream commit $UPSTREAM_COMMIT"
"${SUDO[@]}" python3 "$UPDATER_FILE" "$PROJECT_DIR" --upstream
if [[ -f "$PROJECT_DIR/scripts/enable_updates.sh" ]]; then
    "${SUDO[@]}" bash "$PROJECT_DIR/scripts/enable_updates.sh"
fi
