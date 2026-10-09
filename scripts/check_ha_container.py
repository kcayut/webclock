"""Smoke-test a running HA App from the trusted Ingress proxy address."""
import json
import sys
from http.cookiejar import CookieJar
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


host = sys.argv[1] if len(sys.argv) > 1 else 'local-webclock'
prefix = '/api/hassio_ingress/smoke-test'
client = build_opener(HTTPCookieProcessor(CookieJar()))


def request(port, path, headers=None, data=None):
    try:
        response = client.open(Request(f'http://{host}:{port}{path}', headers=headers or {}, data=data), timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read()


deadline = monotonic() + 60
while True:
    try:
        status, body = request(8100, '/api/health')
        if status == 200:
            break
    except (OSError, URLError):
        pass
    if monotonic() >= deadline:
        raise SystemExit('App did not become healthy within 60 seconds')
    sleep(1)

health = json.loads(body)
assert health['status'] == 'ok' and health['managed_devices_ready'] is True, health
assert request(8100, '/')[0] == 200
assert request(8100, '/api/time')[0] == 200
assert request(8100, '/admin')[0] == 404
assert request(8100, '/api/status')[0] == 404
assert request(8100, '/', {'X-Ingress-Path': prefix})[0] == 404
assert request(8099, '/admin')[0] == 403
headers = {'X-Ingress-Path': prefix,
           'X-Forwarded-Host': 'ha.example.test:8123', 'X-Forwarded-Proto': 'https',
           'Origin': 'https://ha.example.test:8123',
           'Referer': 'https://ha.example.test:8123' + prefix + '/admin'}
status, page = request(8099, '/admin', headers)
assert status == 200 and (prefix + '/static/').encode() in page, status
status, body = request(8099, '/api/v1/groups', headers)
assert status == 200, status
groups = json.loads(body)['groups']
if not groups:
    status, body = request(8099, '/api/csrf', headers)
    assert status == 200, status
    headers.update({'Content-Type': 'application/json', 'X-CSRF-Token': json.loads(body)['csrf_token']})
    status, body = request(8099, '/api/v1/groups', headers, b'{"name":"Installation smoke"}')
    assert status == 201, (status, body)
else:
    assert any(group['name'] == 'Installation smoke' for group in groups), groups
print('HA App health, trusted Ingress and LAN isolation passed')
