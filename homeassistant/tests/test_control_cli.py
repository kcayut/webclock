"""Standard-library CLI contract checks; no HA installation required."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('control_clock', Path(__file__).resolve().parents[2] / 'scripts/control_clock.py')
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class ControlCliTest(unittest.TestCase):
    def test_fixed_destination_payload_revision_and_no_redirect(self):
        args = argparse.Namespace(resource='schedules', action='create', id=None, target_kind=None, target_id=None)
        env = {'WEBCLOCK_SERVER_URL': 'https://clock.example', 'WEBCLOCK_WRITE_TOKEN': 'program-secret'}
        payload = {'request_id': 'stable-1', 'schedule': {'name': 'Wake', 'time': '07:00'}}
        request = client.build_request(args, env, io.StringIO(json.dumps(payload)))
        self.assertEqual(request.full_url, 'https://clock.example/api/v1/control/schedules')
        self.assertEqual(request.get_header('Authorization'), 'Bearer program-secret')
        self.assertEqual(json.loads(request.data), payload)
        for url in ('https://user:secret@host', 'https://host/path', 'https://host?secret=x', 'file:///tmp'):
            with self.assertRaises(ValueError):
                client.build_request(args, dict(env, WEBCLOCK_SERVER_URL=url), io.StringIO(json.dumps(payload)))
        args.action, args.id = 'update', '../events'
        with self.assertRaises(ValueError):
            client.build_request(args, env, io.StringIO('{}'))
        args.id = 'alarm'
        with self.assertRaises(ValueError):
            client.build_request(args, env, io.StringIO('{"schedule":{}}'))
        payload = {'revision': 'a' * 64, 'schedule': {'enabled': False}}
        request = client.build_request(args, env, io.StringIO(json.dumps(payload)))
        self.assertEqual(request.method, 'PATCH')
        self.assertIsNone(client.NoRedirects().redirect_request(request, None, 307, '', {}, 'https://elsewhere'))
        args.action, args.resource, args.id = 'list', 'calendar-events', None
        args.source_id = ['local', 'work']
        request = client.build_request(args, env, io.StringIO(''))
        self.assertEqual(request.full_url, 'https://clock.example/api/v1/control/calendar-events?source_id=local&source_id=work')
        args.resource, args.source_id = 'identity', None
        self.assertEqual(client.build_request(args, env, io.StringIO('')).method, 'GET')


if __name__ == '__main__':
    unittest.main()
