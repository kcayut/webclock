#!/usr/bin/env bash
# Real fresh installs only on disposable GitHub-hosted Linux runners.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted && "$EUID" == 0 ]] || {
    echo 'This rehearsal requires a disposable GitHub-hosted runner and sudo.' >&2; exit 1;
}
if systemctl cat webclock.service >/dev/null 2>&1; then
    echo 'Refusing to replace an existing WebClock service.' >&2; exit 1
fi
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPORARY="$(mktemp -d "$RUNNER_TEMP/webclock-fresh.XXXXXX")"
TARGET=""
cleanup_service() {
    if [[ -n "$TARGET" && "$(systemctl show webclock --property=WorkingDirectory --value)" == "$TARGET" ]]; then
        systemctl disable --now webclock
        rm /etc/systemd/system/webclock.service
        systemctl daemon-reload
    fi
}
cleanup() { cleanup_service; rm -rf -- "$TEMPORARY"; }
trap cleanup EXIT
chmod 755 "$TEMPORARY"
for mode in self managed; do
    TARGET="$TEMPORARY/$mode"
    mkdir "$TARGET"
    git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" archive HEAD | tar -x -C "$TARGET"
    owner=root
    args=()
    if [[ "$mode" == managed ]]; then
        owner="${SUDO_USER:-runner}"
        mkdir "$TEMPORARY/cert"
        openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost \
            -addext subjectAltName=DNS:localhost -keyout "$TEMPORARY/cert/key.pem" \
            -out "$TEMPORARY/cert/cert.pem" >/dev/null 2>&1
        args=(--managed --tls-cert "$TEMPORARY/cert/cert.pem" --tls-key "$TEMPORARY/cert/key.pem"
              --tls-host localhost --tls-ca "$TEMPORARY/cert/cert.pem")
    fi
    chown -R "$owner:$(id -gn "$owner")" "$TARGET"
    # Synthetic CI credentials only; getpass reads stdin on this non-interactive runner.
    printf '%s\n%s\n' WebClock-CI-only-password-2026 WebClock-CI-only-password-2026 | \
        SUDO_USER="$owner" bash "$TARGET/setup.sh" ${args[@]+"${args[@]}"}
    MODE="$mode" "$TARGET/venv/bin/python" - "$TARGET" <<'PY'
import hashlib, http.cookiejar, json, os, pathlib, ssl, subprocess, sys, time, urllib.request
project = pathlib.Path(sys.argv[1])
managed = os.environ['MODE'] == 'managed'
context = ssl.create_default_context(cafile=str(project / 'tls/install-ca.pem')) if managed else None
base = ('https' if managed else 'http') + '://localhost:5000'
url = base + '/api/health'
def health():
    with urllib.request.urlopen(url, context=context, timeout=5) as response:
        data = json.load(response)
    assert data['status'] == 'ok' and data['version'] == (project / 'VERSION').read_text().strip(), data
    assert data['deployment_mode'] == os.environ['MODE'], data
health()
state = project / 'webclock_state' / ('auth.json' if managed else 'settings.json')
if not managed:
    # Fresh self mode deliberately has no auth.json; exercise a real settings save.
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with client.open(base + '/admin', timeout=5) as response:
        assert response.status == 200
    with client.open(base + '/api/csrf', timeout=5) as response:
        token = json.load(response)['csrf_token']
    request = urllib.request.Request(base + '/api/control', data=b'{"brightness":73}',
        headers={'Content-Type': 'application/json', 'X-CSRF-Token': token, 'Origin': base})
    with client.open(request, timeout=5) as response:
        assert json.load(response)['settings']['brightness'] == 73
    assert json.loads(state.read_text())['brightness'] == 73
before = hashlib.sha256(state.read_bytes()).digest()
subprocess.run(['systemctl', 'restart', 'webclock'], check=True)
for attempt in range(30):
    try:
        health()
        break
    except OSError:
        time.sleep(1)
else:
    raise AssertionError('Service did not recover after restart')
assert hashlib.sha256(state.read_bytes()).digest() == before
if not managed:
    with urllib.request.urlopen(base + '/api/control', timeout=5) as response:
        assert json.load(response)['settings']['brightness'] == 73
assert not (project / '.webclock-install.json').exists()
print('Fresh install and restart passed:', os.environ['MODE'])
PY
    cleanup_service
done
