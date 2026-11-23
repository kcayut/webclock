import base64
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import app as clock
from webclock.services import portable_backup, ringtones


def wave(samples=16):
    return ringtones.HEADER.pack(b'RIFF', 36 + 2 * samples, b'WAVE', b'fmt ', 16, 1,
                                 1, 16000, 32000, 2, 16, b'data', 2 * samples) + bytes(2 * samples)


class RingtoneTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for key, value in [('SETTINGS_FILE', str(self.root / 'settings.json')),
                           ('NOTES_FILE', str(self.root / 'notes.json'))]:
            p = patch.object(clock, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = clock.app.test_client()
        self.url = '/api/ringtones'
        self.csrf = self.client.get('/api/csrf').json['csrf_token']

    def post(self, body, **kwargs):
        return self.client.post(self.url, data=body, content_type='audio/wav',
                                headers={'X-CSRF-Token': self.csrf, 'X-Ringtone-Name': quote('午休')}, **kwargs)

    def test_invalid_uploads_do_not_write(self):
        valid = wave()
        self.assertIn(self.post(b'').status_code, (413, 415))
        for data in [b'not audio', valid[:-1], valid + b'junk', valid[:22] + b'xx' + valid[24:]]:
            self.assertEqual(self.post(data).status_code, 415)
        self.assertEqual(self.post(wave(4800001)).status_code, 413)
        self.assertEqual(self.client.post(self.url, data=valid, content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.post(self.url, data=valid, content_type='audio/wav').status_code, 403)
        self.assertFalse((self.root / 'ringtones.json').exists())

    def test_commit_playback_delete_and_backup(self):
        raw = wave(4800000)
        created = self.post(raw)
        self.assertEqual(created.status_code, 201)
        key = created.json['id']
        self.assertEqual(self.client.get('/api/ringtones').json['ringtones'], [created.json])
        self.assertEqual(self.client.get('/api/ringtones/' + key).data, raw)
        public = '/api/v1/ringtones/' + key
        self.assertEqual(self.client.get(public).status_code, 404)
        headers = {'X-CSRF-Token': self.csrf}
        row = dict(name='test', time='07:30', custom_sound=key)
        saved = self.client.post('/api/v1/schedules', json=row, headers=headers)
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(self.client.get(public).data, raw)
        self.assertEqual(self.client.delete('/api/ringtones/' + key, headers=headers).status_code, 409)
        self.assertEqual(self.client.get('/api/v1/browser-alarms').json['alarms'][0]['custom_sound'], key)
        self.assertNotIn('custom_sound', self.client.get('/api/v1/device/schedules').json['schedules'][0])
        backup = portable_backup.capture(self.root, self.root / 'notes.json')
        with tempfile.TemporaryDirectory() as new:
            portable_backup.restore(backup, Path(new), Path(new) / 'notes.json')
            self.assertEqual(ringtones.audio(Path(new), key), raw)
        self.client.delete('/api/v1/schedules/' + saved.json['id'], headers=headers)
        self.assertEqual(self.client.delete('/api/ringtones/' + key, headers=headers).status_code, 204)
        self.assertEqual(self.client.get(public).status_code, 404)
        self.assertEqual(self.client.post('/api/v1/schedules', json=row, headers=headers).status_code, 400)

    def test_rename_copy_and_atomic_bulk_delete(self):
        source = self.post(wave()).json['id']
        headers = {'X-CSRF-Token': self.csrf}
        url = self.url + '/' + source
        self.assertEqual(self.client.patch(url, json={'name': '  '}, headers=headers).status_code, 400)
        used = (self.root / 'ringtones.json').stat().st_size
        with patch.object(ringtones, 'MAX_LIBRARY_BYTES', used):
            too_long = self.client.patch(url, json={'name': '🎵' * 60}, headers=headers)
            self.assertEqual(too_long.json['code'], 'ringtone_storage_full')
            self.assertEqual(self.client.get(self.url).json['ringtones'][0]['name'], '午休')
        renamed = self.client.patch(url, json={'name': '上課'}, headers=headers)
        self.assertEqual(renamed.json, {'id': source, 'name': '上課'})
        copied = self.client.post(url + '/copy', json={'name': '上課（副本）'}, headers=headers)
        self.assertEqual(copied.status_code, 201)
        second = copied.json['id']
        self.assertNotEqual(source, second)
        self.assertEqual(self.client.get(self.url + '/' + second).data, self.client.get(url).data)

        alarm = self.client.post('/api/v1/schedules', json=dict(name='morning', time='09:00',
                                 enabled=False, custom_sound=source), headers=headers).json
        def remove(keys):
            return self.client.delete(self.url, json={'ids': keys}, headers=headers)
        self.assertEqual(remove([second, second]).status_code, 400)
        self.assertEqual(remove([second, '0' * 32]).status_code, 404)
        blocked = remove([second, source])
        self.assertEqual((blocked.status_code, blocked.json['ids']), (409, [source]))
        self.assertEqual(self.client.get(self.url + '/' + second).status_code, 200)
        self.client.delete('/api/v1/schedules/' + alarm['id'], headers=headers)
        self.assertEqual(remove([source, second]).status_code, 204)
        self.assertEqual(self.client.get(self.url).json, {'ringtones': []})

    def test_upload_name_and_concurrency(self):
        for name in ('', '%FF', 'bad%0Aname', 'a' * 61):
            response = self.client.post(self.url, data=wave(), content_type='audio/wav',
                headers={'X-CSRF-Token': self.csrf, 'X-Ringtone-Name': name})
            self.assertEqual(response.json['code'], 'invalid_ringtone_name')
        with ringtones.upload_slot(), ringtones.upload_slot():
            self.assertEqual(self.post(wave()).status_code, 429)

    def test_owner_and_shared_disk_limits(self):
        for i in range(ringtones.MAX_CLIPS):
            ringtones.add(self.root, str(i), wave(), self.root)
        with self.assertRaisesRegex(ringtones.RingtoneError, 'ringtone_quota'):
            ringtones.add(self.root, 'ninth', wave(), self.root)
        other = self.root / 'owners' / ('0' * 32)
        with patch.object(ringtones, 'MAX_LIBRARY_BYTES', (self.root / 'ringtones.json').stat().st_size + 10):
            with self.assertRaisesRegex(ringtones.RingtoneError, 'ringtone_storage_full'):
                ringtones.add(other, 'other owner', wave(), self.root)
        self.assertFalse((other / 'ringtones.json').exists())

    def test_restore_ringtone_backup_larger_than_one_mib(self):
        raw = wave(240000)
        for name in ('one', 'two'):
            ringtones.add(self.root, name, raw, self.root)
        exported = self.client.post('/api/backup/complete/export', json={'encrypted': False},
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(exported.status_code, 200)
        archive = exported.data
        self.assertGreater(len(archive), 1024 * 1024)
        def upload(action, **fields):
            return self.client.post('/api/backup/complete/' + action,
                                    data=dict(file=(BytesIO(archive), 'clips.webclock'), **fields),
                                    headers={'X-CSRF-Token': self.csrf})
        ticket = upload('preview')
        self.assertEqual(ticket.status_code, 200, ticket.get_data(as_text=True))
        restored = upload('restore', ticket=ticket.json['ticket'], confirm='yes')
        self.assertEqual(restored.status_code, 200, restored.get_data(as_text=True))

    def test_untrusted_backup_wave(self):
        row = {'name': 'bad', 'wav': base64.b64encode(wave() + b'extra').decode()}
        backup = portable_backup.capture(self.root, self.root / 'notes.json')
        backup['files']['ringtones.json'] = {'1' * 32: row}
        original = ringtones.add(self.root, 'Original', wave(), self.root)
        with self.assertRaises(portable_backup.BackupError):
            portable_backup.restore(backup, self.root, self.root / 'notes.json')
        self.assertEqual(ringtones.catalog(self.root), [original])
