#!/usr/bin/env bash
# Public release bootstrap. The release packager pins this value in its asset.
set -euo pipefail
RELEASE_VERSION=""
REPOSITORY="https://github.com/kcayut/webclock"
DESTINATION="$PWD/webclock"
DOCKER=false
ENABLE_UPDATES=false
EXPLICIT_DIR=false
SETUP_ARGS=()

fail() { echo "WebClock: $*" >&2; exit 1; }
while (( $# )); do
    case "$1" in
        --docker) DOCKER=true; SETUP_ARGS+=(--docker); shift ;;
        --enable-updates) ENABLE_UPDATES=true; SETUP_ARGS+=(--enable-updates); shift ;;
        --managed) SETUP_ARGS+=(--managed); shift ;;
        --dir|--version|--tls-cert|--tls-key|--tls-host|--tls-ca|--auto-update)
            (( $# >= 2 )) || fail "Missing value for $1"
            case "$1" in
                --dir) DESTINATION="$2"; EXPLICIT_DIR=true ;;
                --version) RELEASE_VERSION="${2#v}" ;;
                *) SETUP_ARGS+=("$1" "$2") ;;
            esac
            shift 2 ;;
        -h|--help)
            echo 'Usage: bash install.sh [--docker] [--dir DIRECTORY] [--version X.Y.Z[-beta.N]]'
            echo 'Managed: add --managed; without TLS certificates, confirm HTTP twice for trusted LAN use.'
            echo 'HTTPS: add --tls-cert FILE --tls-key FILE --tls-host HOST [--tls-ca FILE]'
            echo 'Docker host worker: sudo bash install.sh --docker --enable-updates (defaults to /opt/webclock; requires Python 3.9+ and systemd).'
            echo 'Automatic installation is off by default; explicitly select --auto-update on|off.'
            echo 'Installs an official GitHub release; existing installations are never replaced.'
            exit 0 ;;
        *) fail "Unknown option: $1 (see --help)" ;;
    esac
done

if $ENABLE_UPDATES && $DOCKER; then
    $EXPLICIT_DIR || DESTINATION=/opt/webclock
    [[ "$EUID" = 0 && "$(uname -s)" = Linux ]] || fail 'Docker host updates require sudo on Linux.'
    command -v systemctl >/dev/null || fail 'systemd is required for the Docker host worker.'
    command -v python3 >/dev/null || fail 'Install Python 3.9+ first (Debian/Ubuntu: sudo apt-get install python3).'
    /usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail 'The Docker worker requires /usr/bin/python3 version 3.9+.'
fi

if [[ -e "$DESTINATION" || -L "$DESTINATION" ]]; then
    if [[ -d "$DESTINATION" && ! -L "$DESTINATION" && -f "$DESTINATION/.webclock-bootstrap" && ! -L "$DESTINATION/.webclock-bootstrap" ]]; then
        installed_version="$(cat "$DESTINATION/VERSION")"
        [[ "$(cat "$DESTINATION/.webclock-bootstrap")" == "$installed_version" ]] || fail 'Unrecognized unfinished installation.'
        [[ -z "$RELEASE_VERSION" || "$RELEASE_VERSION" == "$installed_version" ]] || fail 'Retry with the original installer/version; an unfinished install cannot change versions.'
        echo "Resuming WebClock v$installed_version in $DESTINATION (keeping its data)."
        bash "$DESTINATION/setup.sh" ${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}
        rm "$DESTINATION/.webclock-bootstrap"
        exit 0
    fi
    fail "Destination already exists: $DESTINATION. Use its update instructions, or --dir with a new directory."
fi

for port_value in "${PORT:-5000}" "${WEBCLOCK_HTTP_PORT:-80}"; do
    [[ "$port_value" =~ ^[1-9][0-9]{0,4}$ ]] && (( port_value <= 65535 )) || fail 'PORT / WEBCLOCK_HTTP_PORT must be between 1 and 65535.'
done

command -v curl >/dev/null || fail 'curl is required to download a release.'
if $DOCKER; then
    command -v docker >/dev/null || fail 'Install and start Docker first, then run this command again.'
    docker compose version >/dev/null || fail 'Docker Compose is required.'
    docker info >/dev/null || fail 'Docker is not running or this account cannot access it.'
else
    [[ "$(uname -s)" == Linux ]] && command -v apt-get >/dev/null && command -v systemctl >/dev/null \
        || fail 'Use Debian/Ubuntu/Raspberry Pi OS with systemd, or add --docker.'
    case "$DESTINATION" in *[[:space:]%\\]*) fail 'Use an installation path without spaces, % or backslashes.' ;; esac
    if ! command -v git >/dev/null; then
        SUDO=()
        if (( EUID != 0 )); then
            command -v sudo >/dev/null || fail 'Git is missing; install it as root, then retry.'
            SUDO=(sudo)
        fi
        ${SUDO[@]+"${SUDO[@]}"} apt-get update
        ${SUDO[@]+"${SUDO[@]}"} apt-get install -y git ca-certificates
    fi
fi

download() { curl --proto '=https' --proto-redir '=https' -fsSL --retry 2 --connect-timeout 15 "$@"; }
if [[ -z "$RELEASE_VERSION" ]]; then
    release_url="$(download -o /dev/null -w '%{url_effective}' "$REPOSITORY/releases/latest")" \
        || fail 'No published release is available, or GitHub could not be reached. No installation was created.'
    case "$release_url" in "$REPOSITORY/releases/tag/v"*) RELEASE_VERSION="${release_url##*/v}" ;; *) fail 'GitHub did not return an official release.' ;; esac
fi
[[ ${#RELEASE_VERSION} -le 128 && "$RELEASE_VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$ ]] \
    || fail 'Version must be X.Y.Z or a prerelease such as X.Y.Z-beta.1.'
RELEASE_CHANNEL=stable
if [[ "$RELEASE_VERSION" == *-* ]]; then
    RELEASE_CHANNEL=beta
    IFS='.' read -ra identifiers <<< "${RELEASE_VERSION#*-}"
    for identifier in "${identifiers[@]}"; do
        [[ ! "$identifier" =~ ^0[0-9]+$ ]] || fail 'Numeric prerelease identifiers cannot have leading zeros.'
    done
fi
base="$REPOSITORY/releases/download/v$RELEASE_VERSION"
temporary="$(mktemp -d "${TMPDIR:-/tmp}/webclock-install.XXXXXX")"
trap 'rm -rf -- "$temporary"' EXIT
echo "Installing WebClock v$RELEASE_VERSION into $DESTINATION"
# A published asset must exist even for Git installations; tags alone are not releases.
download "$base/SHA256SUMS" -o "$temporary/SHA256SUMS"
if $DOCKER; then
    archive="webclock-$RELEASE_VERSION.tar.gz"
    download "$base/$archive" -o "$temporary/$archive"
    expected="$(awk -v name="$archive" '$2 == name { print $1 }' "$temporary/SHA256SUMS")"
    [[ "$expected" =~ ^[a-f0-9]{64}$ ]] || fail 'Release checksum is missing or invalid.'
    if command -v sha256sum >/dev/null; then
        actual="$(sha256sum "$temporary/$archive" | awk '{print $1}')"
    elif command -v shasum >/dev/null; then
        actual="$(shasum -a 256 "$temporary/$archive" | awk '{print $1}')"
    else
        fail 'sha256sum or shasum is required to verify the download.'
    fi
    [[ "$actual" == "$expected" ]] || fail 'Release checksum mismatch. Nothing installed; download again.'
    tar -tzf "$temporary/$archive" > "$temporary/contents"
    while IFS= read -r name; do
        case "$name" in "webclock-$RELEASE_VERSION/"*) ;; *) fail 'Unexpected archive layout.' ;; esac
        case "/$name/" in */../*|*/./*) fail 'Unsafe archive path.' ;; esac
    done < "$temporary/contents"
    tar -xzf "$temporary/$archive" -C "$temporary"
    source_dir="$temporary/webclock-$RELEASE_VERSION"
else
    source_dir="$temporary/source"
    git clone --quiet --branch "v$RELEASE_VERSION" "$REPOSITORY.git" "$source_dir"
    git -C "$source_dir" config webclock.releaseChannel "$RELEASE_CHANNEL"
fi
[[ "$(cat "$source_dir/VERSION")" == "$RELEASE_VERSION" ]] || fail 'Downloaded product version does not match the release.'
(umask 077
 cp "$source_dir/.env.example" "$source_dir/.env"
 printf '\nWEBCLOCK_VERSION=%s\n' "$RELEASE_VERSION" >> "$source_dir/.env"
 if [[ -n "${PORT:-}" ]]; then printf 'PORT=%s\n' "$PORT" >> "$source_dir/.env"; fi
 if [[ -n "${WEBCLOCK_HTTP_PORT:-}" ]]; then printf 'WEBCLOCK_HTTP_PORT=%s\n' "$WEBCLOCK_HTTP_PORT" >> "$source_dir/.env"; fi
 printf '%s\n' "$RELEASE_VERSION" > "$source_dir/.webclock-bootstrap")
mkdir -p "$(dirname "$DESTINATION")"
# Never merge downloaded files into an existing directory, including concurrent installs.
[[ ! -e "$DESTINATION" && ! -L "$DESTINATION" ]] || fail 'Destination appeared during download; nothing replaced.'
mv "$source_dir" "$DESTINATION"
echo "Source ready. If setup stops, retry: bash \"$DESTINATION/setup.sh\" (with the same options)."
bash "$DESTINATION/setup.sh" ${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}
rm "$DESTINATION/.webclock-bootstrap"
