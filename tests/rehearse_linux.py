"""Real systemd upgrade/backup/rollback rehearsal, only on disposable GitHub runners.

Run as sudo from the workflow. All services, Git remotes and data are synthetic;
this intentionally is not part of unittest discovery or a production-host tool.
"""
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, ProxyHandler, Request, build_opener


SOURCE = Path(__file__).resolve().parents[1]
BASELINE = '1ad7868ff7b51e581421f85fefccfef4e7520ddd'
UNIT = Path('/run/systemd/system/webclock.service')
FAKE_TOKEN = 'rehearsal-only-not-a-real-secret'
FAKE_PASSWORD = 'rehearsal-only-administrator-password'
PASSED = []


def run(*args, cwd=None, user=None, check=True, input=None):
    command = (['runuser', '-u', user, '--'] if user else []) + [str(arg) for arg in args]
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300, input=input)
    if check and result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(command) + '\n' + result.stdout)
    return result


def passed(message):
    PASSED.append(message)
    print('PASS: ' + message, flush=True)


def inventory(path):
    """Compare exact file bytes and symlink targets, including the real venv."""
    paths = [path, *sorted(path.rglob('*'))] if path.is_dir() else [path]
    return {str(item.relative_to(path)): ('link:' + os.readlink(item) if item.is_symlink()
            else hashlib.sha256(item.read_bytes()).hexdigest() if item.is_file() else 'directory')
            for item in paths if item.exists() or item.is_symlink()}


def main():
    if (platform.system() != 'Linux' or os.geteuid() != 0
            or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or Path('/proc/1/comm').read_text().strip() != 'systemd'):
        raise RuntimeError('Only root on a disposable GitHub-hosted Linux systemd runner is supported.')
    account = pwd.getpwnam(os.environ['SUDO_USER'])
    if account.pw_uid == 0:
        raise RuntimeError('The test service must run as the non-root runner account.')
    if (UNIT.exists() or UNIT.is_symlink() or
            run('systemctl', 'show', 'webclock.service', '--property=LoadState', '--value', check=False).stdout.strip() != 'not-found'):
        raise RuntimeError('An existing webclock service was found; refusing to modify it.')
    temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    if any(char in str(temp) for char in '\n\r"\\%'):
        raise RuntimeError('Unsupported runner temporary path.')
    root = Path(tempfile.mkdtemp(prefix='webclock-rehearsal-', dir=temp))
    root.chmod(0o755)
    os.chown(root, account.pw_uid, account.pw_gid)
    installed, remote, injector = root / 'installed', root / 'remote.git', root / 'injector'
    state, notes = root / 'effective-state', root / 'effective-notes' / 'reminders.json'
    baseline_backup, before_restore = root / 'cold-backup', root / 'before-restore'
    user = account.pw_name
    git = lambda *args, cwd=installed: run('git', *args, cwd=cwd, user=user).stdout.strip()
    target = git('rev-parse', 'HEAD', cwd=SOURCE)
    git('cat-file', '-e', BASELINE + '^{commit}', cwd=SOURCE)
    git('merge-base', '--is-ancestor', BASELINE, target, cwd=SOURCE)
    print('Platform: ' + platform.platform(), flush=True)
    print('Python: ' + sys.version.replace('\n', ' '), flush=True)
    print(run('systemctl', '--version').stdout.splitlines()[0], flush=True)
    print('Baseline: ' + BASELINE + '\nCandidate: ' + target, flush=True)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = 'http://127.0.0.1:' + str(port)
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def request(path, data=None, *, method=None, headers=None, expected=200, client=None, base=None):
        payload = None if data is None else json.dumps(data).encode()
        req = Request((base or url) + path, data=payload, method=method,
                      headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = (client or opener).open(req, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            assert response.code == expected, (path, response.code, expected, body.decode(errors='replace'))
            content = json.loads(body) if body and 'application/json' in response.headers.get('Content-Type', '') else body
            return content, response.headers

    def healthy(expected_settings=None):
        deadline = time.monotonic() + 30
        while True:
            try:
                current, _ = request('/api/status')
                assert isinstance(current['events'], list)
                if expected_settings is not None:
                    assert current['settings'] == expected_settings
                pid = int(run('systemctl', 'show', 'webclock', '--property=MainPID', '--value').stdout)
                assert pid > 0 and (Path('/proc') / str(pid)).stat().st_uid == account.pw_uid
                return current
            except (OSError, ValueError, AssertionError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)

    def management(path, data=None, expected=200, *, method=None, client=None, base=None):
        token = request('/api/csrf', client=client, base=base)[0]['csrf_token']
        return request(path, data, method=method, headers={'X-CSRF-Token': token}, expected=expected,
                       client=client, base=base)[0]

    def data_hashes():
        return {'state': inventory(state), 'notes': inventory(notes), 'env': inventory(installed / '.env')}

    def backup(operation, directory, *options):
        return run(installed / 'venv/bin/python3', SOURCE / 'scripts/backup_clock.py', operation, directory,
                   '--project', installed, '--state-dir', state, '--notes-file', notes,
                   *options, user=user)

    def update():
        # Load the candidate updater before changing the installed checkout.
        result = run(sys.executable, SOURCE / 'scripts/update_clock.py', installed, check=False)
        print(result.stdout, flush=True)
        return result

    def device_checks():
        auth = {'Authorization': 'Bearer ' + FAKE_TOKEN}
        request('/api/v1/device/config', expected=401)
        for endpoint in ('config', 'schedules', 'holidays'):
            value, headers = request('/api/v1/device/' + endpoint, headers=auth)
            assert headers['Cache-Control'] == 'private, no-cache'
            request('/api/v1/device/' + endpoint, headers={**auth, 'If-None-Match': headers['ETag']}, expected=304)
            if endpoint == 'config':
                assert value['schema_version'] == 2 and value['timezone'] == 'Asia/Taipei'
            elif endpoint == 'schedules':
                assert value['schedules'][0]['browser_volume'] == 0
                assert value['schedules'][0]['skipped_occurrences'] == [skip]

    created_unit = False
    try:
        git('clone', '--bare', str(SOURCE), str(remote), cwd=root)
        git('--git-dir=' + str(remote), 'update-ref', 'refs/heads/rehearsal', BASELINE, cwd=root)
        git('clone', '--branch', 'rehearsal', str(remote), str(installed), cwd=root)
        run('/usr/bin/python3', '-m', 'venv', installed / 'venv', user=user)
        run(installed / 'venv/bin/python3', '-m', 'pip', 'install', '-r', installed / 'requirements.txt', user=user)
        run(installed / 'venv/bin/python3', '-m', 'pip', 'check', user=user)
        print('Installed packages:\n' + run(installed / 'venv/bin/python3', '-m', 'pip', 'freeze', user=user).stdout, flush=True)
        for directory in (state, notes.parent, root / 'dotenv-state'):
            directory.mkdir(mode=0o700)
            os.chown(directory, account.pw_uid, account.pw_gid)
        notes.write_text('[]', encoding='utf-8')
        decoy = root / 'dotenv-state' / 'sentinel.json'
        decoy.write_text('{"dotenv_paths_must_not_be_used":true}', encoding='utf-8')
        dotenv_notes = root / 'dotenv-notes.json'
        dotenv_notes.write_text('[]', encoding='utf-8')
        env_file = installed / '.env'
        env_file.write_text('ICAL_URL=\nHOST=0.0.0.0\nPORT=7\nDEVICE_API_TOKEN=' + FAKE_TOKEN +
                            '\nWEBCLOCK_STATE_DIR=' + str(root / 'dotenv-state') +
                            '\nNOTES_FILE=' + str(dotenv_notes) + '\n', encoding='utf-8')
        for path in (notes, env_file, decoy, dotenv_notes):
            path.chmod(0o600)
            os.chown(path, account.pw_uid, account.pw_gid)
        decoy_hashes = inventory(decoy), inventory(dotenv_notes)
        with UNIT.open('x', encoding='utf-8') as stream:
            created_unit = True
            stream.write('[Unit]\nDescription=Disposable WebClock upgrade rehearsal\n'
                         '[Service]\nType=simple\nUser=' + user + '\nGroup=' + str(account.pw_gid) +
                         '\nWorkingDirectory=' + str(installed) + '\nExecStart=' + str(installed / 'venv/bin/python3') +
                         ' -B app.py\nEnvironment="HOST=127.0.0.1" "PORT=' + str(port) +
                         '" "WEBCLOCK_STATE_DIR=' + str(state) + '" "NOTES_FILE=' + str(notes) +
                         '" "PYTHONDONTWRITEBYTECODE=1"\nRestart=no\n')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'webclock')
        healthy()
        settings = dict(mode='black', brightness=0, timezone_offset=0, language='ja', time_format='12h',
                        night=dict(enabled=True, start='21:30', end='06:45', brightness=0, black=False))
        reminders = [dict(id=1, text='Synthetic reminder', due_date='', display_start='', display_end='',
                          display_mode='range', weekdays=[], enabled=True)]
        request('/api/backup', dict(version=1, settings=settings, notes=reminders))
        skip = (datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)).replace(
            hour=7, minute=30, second=0, microsecond=0).isoformat()
        schedule = dict(id='wake', name='Synthetic alarm', type='alarm', time='07:30', rule={}, enabled=True,
                        skipped_occurrences=[skip], browser_sound='bell', browser_volume=0, skip_holidays=False)
        request('/api/v1/schedules', schedule, expected=201)
        request('/api/v1/device/register', dict(id='fixture', name='Synthetic device'),
                headers={'Authorization': 'Bearer ' + FAKE_TOKEN}, expected=201)
        request('/api/calendar', dict(sources=[dict(id='fixture', name='Synthetic calendar', provider='ics',
                url='https://calendar.invalid/rehearsal-only.ics', display_enabled=False)], local_display_enabled=False))
        healthy(settings)
        original = data_hashes()
        assert (inventory(decoy), inventory(dotenv_notes)) == decoy_hashes
        assert all(path.stat().st_uid == account.pw_uid for path in [notes, *state.glob('*.json')])
        passed('Baseline service runs as non-root; management writes use systemd data/port overrides over .env')
        run('systemctl', 'stop', 'webclock')
        backup('create', baseline_backup, '--stopped')
        backup('verify', baseline_backup)
        run('systemctl', 'start', 'webclock')
        healthy(settings)
        passed('Cold full-data backup created and integrity verified')

        git('--git-dir=' + str(remote), 'update-ref', 'refs/heads/rehearsal', target, cwd=root)
        assert update().returncode == 0
        assert git('rev-parse', 'HEAD') == target
        assert data_hashes() == original
        device_checks()
        request('/api/control', {'brightness': 47}, expected=403)
        request('/delete/1', expected=405)
        assert data_hashes() == original
        management('/api/control', {'brightness': 37})
        changed_settings = dict(settings, brightness=37)
        run('systemctl', 'restart', 'webclock')
        healthy(changed_settings)
        assert json.loads((state / 'settings.json').read_text()) == changed_settings
        assert (state / 'settings.json').stat().st_uid == account.pw_uid
        assert (inventory(decoy), inventory(dotenv_notes)) == decoy_hashes
        passed('Real Git/pip/systemd upgrade preserves all data bytes; device schema 2 and ETag/304 work')
        passed('Missing CSRF is rejected, GET deletion is 405, valid management write survives service restart')

        changed = data_hashes()
        run('systemctl', 'stop', 'webclock')
        backup('restore', baseline_backup, '--stopped', '--yes', '--rollback-dir', before_restore)
        backup('verify', before_restore)
        assert inventory(before_restore / 'data/state') == changed['state']
        assert inventory(before_restore / 'data/notes') == changed['notes']
        assert inventory(before_restore / 'data/env') == changed['env']
        assert inventory(state) == original['state'] and inventory(notes) == original['notes']
        # Restore deliberately remaps .env paths to the selected effective layout.
        from dotenv import dotenv_values
        restored_env = dotenv_values(env_file)
        assert restored_env['WEBCLOCK_STATE_DIR'] == str(state) and restored_env['NOTES_FILE'] == str(notes)
        assert restored_env['DEVICE_API_TOKEN'] == FAKE_TOKEN and restored_env['PORT'] == '7'
        run('systemctl', 'start', 'webclock')
        healthy(settings)
        assert git('rev-parse', 'HEAD') == target
        device_checks()
        passed('Cold restore recovers original data hashes, remaps .env paths, and retains before-restore backup')

        rollback_data = data_hashes()
        rollback_venv = inventory(installed / 'venv')
        git('clone', '--branch', 'rehearsal', str(remote), str(injector), cwd=root)
        # The failure exists only in the disposable local remote, never in SOURCE.
        (injector / 'app.py').write_text('import os\nfrom pathlib import Path\n'
            'Path(os.environ["WEBCLOCK_STATE_DIR"], "settings.json").write_text("{\\"fault\\": true}")\n'
            'Path(os.environ["NOTES_FILE"]).write_text("[]")\n'
            'Path(".env").write_text("REHEARSAL_FAULT=1\\n")\n'
            'Path("venv/rehearsal-fault").write_text("failed environment")\n'
            'raise SystemExit(17)\n', encoding='utf-8')
        os.chown(injector / 'app.py', account.pw_uid, account.pw_gid)
        git('add', 'app.py', cwd=injector)
        git('-c', 'user.name=Rehearsal', '-c', 'user.email=rehearsal@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-m', 'Fixture only: fail after corrupting synthetic data', cwd=injector)
        git('push', 'origin', 'rehearsal', cwd=injector)
        fault_sha = git('rev-parse', 'HEAD', cwd=injector)
        print('Injected fixture-only failure: ' + fault_sha, flush=True)
        result = update()
        assert result.returncode != 0 and 'Previous service and data restored.' in result.stdout
        assert git('rev-parse', 'HEAD') == target
        healthy(settings)
        assert data_hashes() == rollback_data
        assert inventory(installed / 'venv') == rollback_venv
        retained = list(installed.glob('.webclock-update-*/manifest.json'))
        assert len(retained) == 1
        manifest = json.loads(retained[0].read_text())
        assert manifest['old_head'] == target
        failed = retained[0].parent
        assert (failed / 'failed-venv/rehearsal-fault').read_text() == 'failed environment'
        for index, entry in enumerate(manifest['data']):
            damaged = failed / 'failed-data' / str(index)
            if entry['path'] == str(state):
                assert json.loads((damaged / 'settings.json').read_text()) == {'fault': True}
            elif entry['path'] == str(notes):
                assert damaged.read_text() == '[]'
            elif entry['path'] == str(env_file):
                assert damaged.read_text() == 'REHEARSAL_FAULT=1\n'
        run(installed / 'venv/bin/python3', '-m', 'pip', 'check', user=user)
        run('systemctl', 'restart', 'webclock')
        healthy(settings)
        device_checks()
        management('/api/control', settings)
        assert data_hashes() == rollback_data
        passed('Startup failure restores exact prior Git revision, venv and data; failed-data/venv and manifest retained')
        passed('Recovered service survives another restart, device reads and authenticated management writes')

        # Continue from the same installation/data. Only the local fixture remote
        # is reset; SOURCE and the published candidate never receive test commits.
        git('reset', '--hard', target, cwd=injector)
        git('push', '--force', 'origin', 'rehearsal', cwd=injector)
        management('/api/v1/devices/fixture', {'name': 'Managed migration desk'}, method='PATCH')
        command = management('/api/v1/devices/fixture/commands', {'action': 'sync'}, expected=202)['command']
        request('/api/v1/device/status', dict(id='fixture', device_type='browser',
                capabilities={'display': True, 'audio': False}, acknowledged_commands=[command['id']]),
                headers={'Authorization': 'Bearer ' + FAKE_TOKEN})
        group = management('/api/v1/groups/initialize', {})
        group = management('/api/v1/groups/' + group['id'], {'content': {'manual_note_ids': [1]}}, method='PATCH')
        original_auth = json.loads((state / 'auth.json').read_text())
        migration_data = data_hashes()
        run('systemctl', 'stop', 'webclock')
        backup('create', root / 'before-managed-enable', '--stopped')
        backup('verify', root / 'before-managed-enable')
        # Exercise the real interactive CLI using a private stdin pipe. The
        # synthetic password is never in argv/environment or command output.
        run(installed / 'venv/bin/python3', installed / 'scripts/manage_auth.py', '--state-dir', state,
            'setup', '--username', 'owner', '--enable-managed', user=user,
            input=FAKE_PASSWORD + '\n' + FAKE_PASSWORD + '\n')
        managed_auth = json.loads((state / 'auth.json').read_text())
        assert managed_auth['mode'] == 'managed' and (state / 'auth-required').exists()
        for key in ('owner_id', 'invite_secret'):
            assert managed_auth[key] == original_auth[key]
        for name, digest in migration_data['state'].items():
            if name != 'auth.json':
                assert inventory(state)[name] == digest
        assert inventory(notes) == migration_data['notes']
        assert json.loads((state / 'device-access.json').read_text())['devices'] == {}

        certificate, private_key = root / 'localhost.crt', root / 'localhost.key'
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
            '-keyout', private_key, '-out', certificate, user=user)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            tls_port = listener.getsockname()[1]
        tls_url = 'https://127.0.0.1:' + str(tls_port)
        tls_runner = root / 'serve-test-https.py'
        # One application process serves both actual TLS enrollment and the
        # unchanged HTTP loopback health endpoint expected by the updater.
        tls_runner.write_text('import os, sys\nfrom pathlib import Path\nfrom threading import Thread\n'
            'assert sys.argv[1] == "app.py"\nsys.path.insert(0, str(Path.cwd()))\nimport app\n'
            'from werkzeug.serving import make_server\n'
            'tls = make_server("127.0.0.1", ' + str(tls_port) + ', app.app, threaded=True, ssl_context=' +
            repr((str(certificate), str(private_key))) + ')\n'
            'Thread(target=tls.serve_forever, daemon=True).start()\n'
            'make_server("127.0.0.1", int(os.environ["PORT"]), app.app, threaded=True).serve_forever()\n', encoding='utf-8')
        os.chown(tls_runner, account.pw_uid, account.pw_gid)
        UNIT.write_text(UNIT.read_text().replace(' -B app.py\n', ' -B ' + str(tls_runner) + ' app.py\n'))
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'webclock')

        def managed_healthy():
            healthy()  # Public managed status intentionally has no settings.
            health = request('/api/health')[0]
            assert health['deployment_mode'] == 'managed' and health['managed_devices_ready'] is True
            assert request('/api/status')[0]['events'] == []

        def browser():
            jar = CookieJar()
            return build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(certificate))),
                                HTTPCookieProcessor(jar)), jar

        def login(client):
            return management('/login', {'username': 'owner', 'password': FAKE_PASSWORD}, client=client, base=tls_url)

        def enroll(client, code):
            attempt = management('/api/v2/device/join/prepare', {}, expected=201, client=client, base=tls_url)
            return management('/api/v2/device/join', {'attempt_id': attempt['attempt_id'], 'code': code},
                              expected=201, client=client, base=tls_url)['identity']

        def denied(client, expected=401):
            for endpoint in ('identity', 'display', 'browser-alarms'):
                _, headers = request('/api/v2/device/' + endpoint, headers={'If-None-Match': '*'},
                                     expected=expected, client=client, base=tls_url)
                assert 'ETag' not in headers

        managed_healthy()
        anonymous, _ = browser()
        request('/api/v1/devices', expected=401, client=anonymous, base=tls_url)
        for endpoint in ('config', 'schedules', 'holidays'):
            request('/api/v1/device/' + endpoint, expected=403, client=anonymous, base=tls_url,
                    headers={'Authorization': 'Bearer ' + FAKE_TOKEN})
        assert json.loads((state / 'devices.json').read_text())['fixture']['name'] == 'Managed migration desk'
        admin, _ = browser()
        login(admin)
        invitation = management('/api/v1/groups/' + group['id'] + '/invite', {'capacity': 2}, expected=201, client=admin, base=tls_url)
        assert len(invitation['code']) == 6
        display, display_cookies = browser()
        denied(display)
        identity = enroll(display, invitation['code'])
        assert identity['group_id'] == group['id'] and identity['device_id'] != 'fixture'
        cookie = next(cookie for cookie in display_cookies if cookie.name == 'webclock_device')
        assert cookie.secure and cookie.has_nonstandard_attr('HttpOnly')
        payload, etag_headers = request('/api/v2/device/display', client=display, base=tls_url)
        assert payload['schema_version'] == 3 and payload['identity'] == identity
        assert payload['events'] == [{'text': 'Synthetic reminder', 'time': ''}]
        request('/api/v2/device/display', client=display, base=tls_url,
                headers={'If-None-Match': etag_headers['ETag']}, expected=304)
        passed('Explicit CLI migration preserves owner, invite secret, legacy names/capabilities/ACK and source references; no legacy IDs gain authority')
        passed('Real HTTPS six-character enrollment uses Secure/HttpOnly cookies; anonymous/shared-token private reads are denied')

        # A genuine next local commit exercises managed Git/pip/systemd success.
        with (injector / 'app.py').open('a') as stream:
            stream.write('\n# Synthetic managed upgrade candidate\n')
        git('add', 'app.py', cwd=injector)
        git('-c', 'user.name=Rehearsal', '-c', 'user.email=rehearsal@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-m', 'Fixture only: next managed release', cwd=injector)
        git('push', 'origin', 'rehearsal', cwd=injector)
        managed_head = git('rev-parse', 'HEAD', cwd=injector)
        managed_before = data_hashes()
        assert update().returncode == 0
        assert git('rev-parse', 'HEAD') == managed_head and data_hashes() == managed_before
        managed_healthy()
        assert request('/api/v2/device/identity', client=display, base=tls_url)[0]['identity'] == identity
        passed('Managed update succeeds through public health only and preserves every authorization/data byte')

        # Revoke a second real enrollment during failed startup. Protected
        # rollback must retain that latest revocation, not restore an old grant.
        doomed, _ = browser()
        doomed_identity = enroll(doomed, invitation['code'])
        managed_venv = inventory(installed / 'venv')
        (injector / 'app.py').write_text('from pathlib import Path\nimport os\n'
            'from webclock import app as clock\n'
            'with clock.app.test_request_context("/"):\n'
            '    clock.group_service().revoke(clock.auth_service().owner_id(), ' + repr(doomed_identity['device_id']) + ')\n'
            'Path("venv/rehearsal-managed-fault").write_text("failed managed environment")\n'
            'raise SystemExit(17)\n', encoding='utf-8')
        git('add', 'app.py', cwd=injector)
        git('-c', 'user.name=Rehearsal', '-c', 'user.email=rehearsal@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-m', 'Fixture only: fail after managed revocation', cwd=injector)
        git('push', 'origin', 'rehearsal', cwd=injector)
        result = update()
        assert result.returncode != 0 and 'Previous service and data restored.' in result.stdout
        assert git('rev-parse', 'HEAD') == managed_head and inventory(installed / 'venv') == managed_venv
        managed_healthy()
        denied(doomed)
        assert request('/api/v2/device/identity', client=display, base=tls_url)[0]['identity'] == identity
        passed('Failed managed startup restores prior Git/venv while retaining a revocation committed before failure')

        managed_backup, managed_rollback = root / 'managed-backup', root / 'managed-before-restore'
        run('systemctl', 'stop', 'webclock')
        backup('create', managed_backup, '--stopped')
        backup('verify', managed_backup)
        run('systemctl', 'start', 'webclock')
        managed_healthy()
        management('/api/v1/devices/' + identity['device_id'], method='DELETE', client=admin, base=tls_url)
        denied(display)
        run('systemctl', 'stop', 'webclock')
        backup('restore', managed_backup, '--stopped', '--yes', '--rollback-dir', managed_rollback)
        backup('verify', managed_rollback)
        run('systemctl', 'start', 'webclock')
        managed_healthy()
        denied(display)
        request('/api/v1/groups', expected=401, client=admin, base=tls_url)
        restored = json.loads((state / 'device-access.json').read_text())
        member = restored['devices'][identity['device_id']]
        assert member['credential_digest'] is None and member['rejoin_required'] is True
        assert member['status'] == 'revoked' and restored['invites'] == {} and restored['attempts'] == {}
        assert json.loads((state / 'auth.json').read_text())['owner_id'] == original_auth['owner_id']
        login(admin)
        invitation = management('/api/v1/groups/' + group['id'] + '/invite', {'capacity': 1}, expected=201, client=admin, base=tls_url)
        replacement, _ = browser()
        replacement_identity = enroll(replacement, invitation['code'])
        assert replacement_identity['device_id'] != identity['device_id']
        assert request('/api/v2/device/display', client=replacement, base=tls_url)[0]['events'] == payload['events']
        passed('Managed backup → revoke → restore never revives old device/admin cookies; a new code and new identity are required')
        print('Final service: ' + run('systemctl', 'is-active', 'webclock').stdout.strip(), flush=True)
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as stream:
                stream.write('## WebClock Linux upgrade rehearsal\n\nCandidate: `' + target + '`\n\n')
                stream.write('Platform: ' + platform.platform() + '\n\n')
                stream.write('\n'.join('- PASS: ' + item for item in PASSED) + '\n')
                stream.write('\nSynthetic data only; this does not certify Raspberry Pi or physical device behavior.\n')
    except BaseException:
        if created_unit:
            print(run('journalctl', '-u', 'webclock', '--no-pager', '-n', '100', check=False).stdout, flush=True)
        raise
    finally:
        if created_unit:
            run('systemctl', 'stop', 'webclock', check=False)
            UNIT.unlink()
            run('systemctl', 'daemon-reload')
            run('systemctl', 'reset-failed', 'webclock', check=False)
            print('Cleanup: removed rehearsal service; temporary fixtures expire with this runner.', flush=True)


if __name__ == '__main__':
    main()
