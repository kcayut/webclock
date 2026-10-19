#!/usr/bin/env bash
# Destructive only inside a disposable GitHub-hosted runner; never a host setup tool.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" = true && "${RUNNER_ENVIRONMENT:-}" = github-hosted && "$EUID" = 0 ]]
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Hosted runners allow non-root tooling under /opt; use a protected parent.
PROJECT=/var/lib/webclock-worker-rehearsal
for path in "$PROJECT" /etc/webclock-docker-updater.json /etc/systemd/system/webclock-docker-updater.service /usr/local/lib/webclock-docker-updater /var/lib/webclock-docker-updater; do
    [[ ! -e "$path" && ! -L "$path" ]] || { echo "Refusing existing path: $path" >&2; exit 1; }
done
cleanup() {
    systemctl disable --now webclock-docker-updater 2>/dev/null || true
    if [[ -f "$PROJECT/docker-compose.yml" ]]; then (cd "$PROJECT" && docker compose down); fi
    rm -f /etc/webclock-docker-updater.json /etc/systemd/system/webclock-docker-updater.service
    rm -rf "$PROJECT" /usr/local/lib/webclock-docker-updater /var/lib/webclock-docker-updater
    systemctl daemon-reload
}
trap cleanup EXIT
mkdir -m 700 "$PROJECT"
cp -R "$REPO/scripts" "$PROJECT/scripts"
cp "$REPO/VERSION" "$REPO/.env.example" "$PROJECT/"
cp "$REPO/.env.example" "$PROJECT/.env"
sed 's/container_name: webclock/container_name: webclock-worker-rehearsal/' "$REPO/docker-compose.yml" > "$PROJECT/docker-compose.yml"
printf '\nWEBCLOCK_HTTP_PORT=18502\nWEBCLOCK_VERSION=%s\n' "$(cat "$PROJECT/VERSION")" >> "$PROJECT/.env"
chmod 600 "$PROJECT/.env"
mkdir "$PROJECT/webclock_state" "$PROJECT/tls" "$PROJECT/.webclock-mode-backups-webclock_state" "$PROJECT/webclock_updater_run"
printf '[]\n' > "$PROJECT/manual_notes.json"
cd "$PROJECT"
namei -l "$PROJECT/.env" /usr/local/lib /etc/systemd/system
docker compose up -d --no-build --pull never
curl --fail --silent --show-error --retry 30 --retry-delay 1 --retry-all-errors http://127.0.0.1:18502/api/health > /dev/null
bash scripts/enable_docker_updates.sh
python3 scripts/update_settings.py --kind docker --project "$PROJECT" > status.json
python3 - <<'PY'
import json
from pathlib import Path
state = json.loads(Path('status.json').read_text())
assert state['auto_update'] is False, state
assert state['worker_version'] == Path('VERSION').read_text().strip(), state
assert Path('webclock_updater_run/control.sock').stat().st_mode & 0o777 == 0o600
PY
python3 scripts/update_settings.py --kind docker --auto-update off --channel beta > /dev/null
systemctl restart webclock-docker-updater
python3 scripts/update_settings.py --kind docker > status.json
python3 - <<'PY'
import json
from pathlib import Path
state = json.loads(Path('status.json').read_text())
assert state['channel'] == 'beta' and state['auto_update'] is False, state
PY
docker compose exec -T webclock python - <<'PY'
import json, socket
with socket.socket(socket.AF_UNIX) as connection:
    connection.connect('/run/webclock-updater/control.sock')
    connection.sendall(b'{"action":"status"}\n')
    with connection.makefile('rb') as response:
        assert json.loads(response.readline())['status']['update_provider'] == 'docker'
PY
bash scripts/enable_docker_updates.sh
test -f /usr/local/lib/webclock-docker-updater/previous/VERSION
echo 'Real Docker worker activation, settings persistence, socket recreation and refresh passed.'
