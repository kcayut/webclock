#!/usr/bin/env bash
# Upgrade an existing installation using updater code from a verified release.
set -euo pipefail
RELEASE_VERSION=""
REPOSITORY="https://github.com/kcayut/webclock"
PROJECT_DIR="$PWD"
ACTION=update
ACTION_ARGS=()
OPERATION=""
CONFIRM=false
OFFLINE=false
ENABLE=false
MIGRATE_TO=""
fail() { echo "WebClock: $*" >&2; exit 1; }
select_action() {
    [[ "$ACTION" == update ]] || fail 'Select only one action.'
    ACTION="$1"
}
while (( $# )); do
    case "$1" in
        --project|--version|--migrate-to|--recover|--prune-backups|--operation)
            (( $# >= 2 )) || fail "Missing value for $1"
            case "$1" in
                --project) PROJECT_DIR="$2" ;;
                --version) RELEASE_VERSION="${2#v}" ;;
                --migrate-to) MIGRATE_TO="$2"; ENABLE=true ;;
                --recover|--prune-backups) select_action "${1#--}"; ACTION_ARGS+=("$1" "$2") ;;
                --operation) OPERATION="$2" ;;
            esac
            shift 2 ;;
        --enable-updates) ENABLE=true; shift ;;
        --refresh-worker) select_action worker; ENABLE=true; shift ;;
        --check|--diagnose) select_action "${1#--}"; ACTION_ARGS+=("$1"); shift ;;
        --yes) CONFIRM=true; shift ;;
        --offline) OFFLINE=true; shift ;;
        -h|--help)
            echo 'Usage: bash portable_docker_update.sh --project DIRECTORY [--version X.Y.Z] [--check | --refresh-worker] [--enable-updates]'
            echo 'Uses official release assets. Keeps installation data, credentials and host source files.'
            echo 'Requires host Python 3.9+, curl and local Docker. Host worker requires sudo, systemd and a protected installation path.'
            echo 'Existing user-owned installation: sudo ... --migrate-to /opt/webclock (cold copy; old data retained; enables worker).'
            echo 'Maintenance: --diagnose | --recover current|previous --operation ID --yes | --prune-backups KEEP [--yes]'
            echo 'Add --offline to maintain an installation using previously verified, cached tools without contacting GitHub.'
            exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done
[[ -z "$OPERATION" || "$ACTION" == recover ]] || fail '--operation requires --recover.'
if $CONFIRM; then
    [[ "$ACTION" == recover || "$ACTION" == prune-backups ]] || fail '--yes requires recovery or backup cleanup.'
    ACTION_ARGS+=(--yes)
fi
[[ -z "$OPERATION" ]] || ACTION_ARGS+=(--operation "$OPERATION")
[[ -z "$MIGRATE_TO" || "$ACTION" == update ]] || fail '--migrate-to is only supported with an update.'
if $ENABLE; then
    [[ "$ACTION" == update || "$ACTION" == worker || "$ACTION" == check ]] || fail 'Worker enrollment cannot be combined with recovery or cleanup.'
fi
if $OFFLINE; then
    [[ "$ACTION" == diagnose || "$ACTION" == recover || "$ACTION" == prune-backups ]] || fail '--offline is only for diagnosis, recovery or backup cleanup.'
else
    command -v curl >/dev/null || fail 'curl is required.'
fi
for cmd in python3 docker; do command -v "$cmd" >/dev/null || fail "$cmd is required. For Python on Debian/Ubuntu: sudo apt-get install python3"; done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail 'Python 3.9+ is required.'
[[ -d "$PROJECT_DIR" && ! -L "$PROJECT_DIR" ]] || fail 'Select the existing installation directory.'
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
if $ENABLE; then
    [[ "$EUID" = 0 && "$(uname -s)" = Linux ]] || fail 'Run with sudo on Linux to maintain the host worker.'
    command -v systemctl >/dev/null || fail 'systemd is required.'
    /usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail 'The host worker requires /usr/bin/python3 version 3.9+.'
fi
if [[ "$EUID" = 0 ]]; then
    CACHE_ROOT=/var/lib/webclock-docker-recovery
else
    CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/webclock-docker-recovery"
fi
cache_tools() {
    python3 -E -s - "$1" "$CACHE_ROOT" "$RELEASE_VERSION" "${2:-}" <<'PY'
import hashlib, json, os, re, shutil, sys, tempfile
from pathlib import Path

action, root, version, source = sys.argv[1:]
root, source = Path(root), Path(source)
names = ['VERSION', 'portable_docker_update.sh'] + ['scripts/' + name for name in (
    'docker_update.py', 'docker_update_install.py', 'docker_update_migrate.py',
    'updater_service.py', 'release_versions.py', 'update_clock.py', 'update_settings.py')]
def safe(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise SystemExit('Unsafe recovery cache path.')
        if part.exists() and os.geteuid() == 0:
            info = part.stat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise SystemExit('Recovery cache must be protected by root.')
    if path.exists() and path.stat().st_mode & 0o022:
        raise SystemExit('Recovery cache must not be writable by other accounts.')
def write(path, data):
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
def sync(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
def verify(bundle):
    safe(bundle)
    safe(bundle / 'manifest.json')
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if set(manifest) != set(names):
        raise SystemExit('Incomplete recovery cache.')
    for name in names:
        path = bundle / name
        safe(path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name]:
            raise SystemExit('Recovery cache checksum mismatch; nothing executed.')
    if (bundle / 'VERSION').read_text().strip() != version:
        raise SystemExit('Recovery cache version mismatch.')
    return manifest
safe(root)
if action == 'load' and not version:
    safe(root / 'current')
    version = (root / 'current').read_text().strip()
if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?', version):
    raise SystemExit('Invalid recovery cache version.')
bundle = root / version
if action == 'store':
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe(root)
    sync(root.parent)
    payload = {name: (source / name).read_bytes() for name in names}
    payload['portable_docker_update.sh'] = re.sub(rb'^RELEASE_VERSION=""$',
        ('RELEASE_VERSION="' + version + '"').encode(), payload['portable_docker_update.sh'], flags=re.M)
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    if bundle.exists():
        if verify(bundle) != manifest:
            raise SystemExit('This version already has different cached tools; choose an immutable release.')
    else:
        temporary = Path(tempfile.mkdtemp(prefix='.prepare-', dir=root))
        try:
            (temporary / 'scripts').mkdir(mode=0o700)
            for name, data in payload.items():
                write(temporary / name, data)
            write(temporary / 'manifest.json', (json.dumps(manifest) + '\n').encode())
            sync(temporary / 'scripts')
            sync(temporary)
            os.rename(temporary, bundle)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    descriptor, pointer = tempfile.mkstemp(prefix='.current-', dir=root)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write((version + '\n').encode())
            output.flush()
            os.fsync(output.fileno())
        os.replace(pointer, root / 'current')
        sync(root)
    finally:
        if os.path.exists(pointer):
            os.unlink(pointer)
else:
    verify(bundle)
print(bundle)
PY
}
if $OFFLINE; then
    source_dir="$(cache_tools load)" || fail 'Verified offline tools are unavailable; keep the installation stopped and restore network access.'
else
download() { curl --proto '=https' --proto-redir '=https' -fsSL --retry 2 --connect-timeout 15 "$@"; }
if [[ -z "$RELEASE_VERSION" ]]; then
    release_url="$(download -o /dev/null -w '%{url_effective}' "$REPOSITORY/releases/latest")"
    case "$release_url" in "$REPOSITORY/releases/tag/v"*) RELEASE_VERSION="${release_url##*/v}" ;; *) fail 'No official release found.' ;; esac
fi
[[ ${#RELEASE_VERSION} -le 128 && "$RELEASE_VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$ ]] || fail 'Invalid release version.'
temporary="$(mktemp -d "${TMPDIR:-/tmp}/webclock-docker-update.XXXXXX")"
trap 'rm -rf -- "$temporary"' EXIT
base="$REPOSITORY/releases/download/v$RELEASE_VERSION"
archive="webclock-$RELEASE_VERSION.tar.gz"
download "$base/SHA256SUMS" -o "$temporary/SHA256SUMS"
download "$base/$archive" -o "$temporary/$archive"
python3 - "$temporary" "$RELEASE_VERSION" <<'PY'
import hashlib
from pathlib import Path, PurePosixPath
import sys
import tarfile

root, version = Path(sys.argv[1]), sys.argv[2]
name = 'webclock-' + version + '.tar.gz'
rows = [row.split() for row in (root / 'SHA256SUMS').read_text().splitlines()]
expected = [row[0] for row in rows if len(row) == 2 and row[1] == name]
digest = hashlib.sha256()
with (root / name).open('rb') as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
if expected != [digest.hexdigest()]:
    raise SystemExit('Release checksum mismatch; nothing changed.')
with tarfile.open(root / name) as archive:
    members = archive.getmembers()
    prefix = 'webclock-' + version
    seen = set()
    for item in members:
        path = PurePosixPath(item.name)
        if (path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != prefix
                or not (item.isfile() or item.isdir()) or item.name in seen):
            raise SystemExit('Unsafe release archive; nothing changed.')
        seen.add(item.name)
    for item in members:
        target = root.joinpath(*PurePosixPath(item.name).parts)
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as source, target.open('xb') as output:
                import shutil
                shutil.copyfileobj(source, output)
            target.chmod(0o600)
source = root / prefix
if (source / 'VERSION').read_text().strip() != version:
    raise SystemExit('Release version mismatch.')
for entry in ('docker_update.py', 'docker_update_install.py', 'docker_update_migrate.py', 'updater_service.py', 'release_versions.py', 'update_clock.py', 'update_settings.py'):
    if not (source / 'scripts' / entry).is_file():
        raise SystemExit('This release does not contain the Docker updater. Choose a newer published release.')
PY
source_dir="$temporary/webclock-$RELEASE_VERSION"
cached_tools="$(cache_tools store "$source_dir")" || fail 'Could not preserve verified recovery tools; no installation changes made.'
printf 'Offline recovery tools saved: %s/portable_docker_update.sh\n' "$cached_tools"
fi
if [[ -n "$MIGRATE_TO" ]]; then
    python3 -E -s "$source_dir/scripts/docker_update_migrate.py" "$PROJECT_DIR" "$MIGRATE_TO"
    PROJECT_DIR="$MIGRATE_TO"
fi
# Validate enrollment before any application downtime.
if $ENABLE; then
    python3 -E -s - "$source_dir" "$PROJECT_DIR" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.docker_update import root_owned
for path in (Path(sys.argv[2]), Path(sys.argv[2]) / '.env', Path(sys.argv[2]) / 'docker-compose.yml'):
    root_owned(path)
PY
fi
channel=stable
[[ "$RELEASE_VERSION" != *-* ]] || channel=beta
if [[ "$ACTION" == update ]]; then
    python3 -E -s "$source_dir/scripts/docker_update.py" --project "$PROJECT_DIR" --channel "$channel" --version "$RELEASE_VERSION"
elif [[ "$ACTION" != worker ]]; then
    python3 -E -s "$source_dir/scripts/docker_update.py" --project "$PROJECT_DIR" --channel "$channel" "${ACTION_ARGS[@]}"
fi
if $ENABLE && [[ "$ACTION" != check ]]; then
    python3 -E -s "$source_dir/scripts/docker_update_install.py" "$PROJECT_DIR"
fi
