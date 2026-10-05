"""Legacy fixture remains byte-for-byte intact during explicit B0/B1 migration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as clock


class AccessMigrationTest(unittest.TestCase):
    def test_legacy_read_and_explicit_default_group_do_not_promote_old_device_ids(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' / 'legacy-b0-state.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in fixture.items():
                (root / name).write_text(json.dumps(data))
            original = {name: (root / name).read_bytes() for name in fixture}
            with patch.object(clock, 'SETTINGS_FILE', str(root / 'settings.json')), \
                 patch.object(clock, 'NOTES_FILE', str(root / 'manual_notes.json')), \
                 patch.dict(clock.display_settings, fixture['settings.json'], clear=True):
                client = clock.app.test_client()
                self.assertEqual(client.get('/api/v1/groups').json, {'groups': []})
                self.assertFalse((root / 'auth.json').exists())
                self.assertFalse((root / 'device-access.json').exists())
                token = client.get('/api/csrf').json['csrf_token']
                headers = {'X-CSRF-Token': token}
                response = client.post('/api/v1/groups/initialize', json={}, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                group = response.json
                self.assertEqual(group['content'], {'calendar_source_ids': ['visible'],
                                                  'manual_note_ids': [7], 'schedule_ids': ['legacy-alarm']})
                self.assertEqual(group['effective_settings']['brightness'], 60)
                self.assertEqual(group['display_overrides'], {})
                self.assertEqual(client.post('/api/v1/groups/initialize', json={}, headers=headers).json['id'], group['id'])
                access = json.loads((root / 'device-access.json').read_text())
                self.assertEqual(access['devices'], {})
                self.assertEqual(access['attempts'], {})
                self.assertEqual(access['invites'], {})
                self.assertEqual(clock.auth_service().mode(), 'self')
                self.assertFalse((root / 'auth-required').exists())
                fresh = client.post('/api/v1/groups', json={'name': 'Empty'}, headers=headers).json
                self.assertEqual(fresh['content'], {'calendar_source_ids': [], 'manual_note_ids': [], 'schedule_ids': []})
            self.assertEqual({name: (root / name).read_bytes() for name in fixture}, original)


if __name__ == '__main__':
    unittest.main()
