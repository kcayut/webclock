"""Run with the optional MCP SDK installed. Uses a private loopback WebClock instance."""
import asyncio
from datetime import datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from werkzeug.serving import make_server

import app as clock


@unittest.skipUnless(find_spec('mcp'), 'install mcp>=1.12,<2 for the stdio integration test')
class WebClockMcpTest(unittest.TestCase):
    def test_stdio_tools_against_control_api(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for setting, value in [('SETTINGS_FILE', str(root / 'settings.json')),
                               ('NOTES_FILE', str(root / 'notes.json')), ('ICAL_URL', '')]:
            self.enterContext(patch.object(clock, setting, value))
        admin = clock.app.test_client()
        admin.environ_base['HTTP_X_CSRF_TOKEN'] = admin.get('/api/csrf').json['csrf_token']
        bootstrap = admin.post('/api/v1/control-clients', json=dict(name='setup', scopes=['events:read']))
        self.assertEqual(bootstrap.status_code, 201)
        with clock.app.test_request_context('/'):
            owner = clock.auth_service().owner_id()
            group = clock.group_service().create_group(owner, {'name': '臥室'})
            clock.group_service().create_group(owner, {'name': '私人書房'})
        issued = admin.post('/api/v1/control-clients', json=dict(name='MCP test', group_ids=[group['id']],
                            scopes=['schedules:write', 'schedules:read', 'events:write', 'events:read',
                                    'assignments:write']))
        self.assertEqual(issued.status_code, 201, issued.json.get('code'))
        token = issued.json['client']['token']
        headers = {'Authorization': 'Bearer ' + token}
        httpd = make_server('127.0.0.1', 0, clock.app)
        self.addCleanup(httpd.server_close)
        worker = Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(httpd.shutdown)
        server = StdioServerParameters(command=sys.executable,
            args=[str(Path(__file__).resolve().parents[1] / 'scripts/webclock_mcp.py')],
            env={'WEBCLOCK_SERVER_URL': f'http://127.0.0.1:{httpd.server_port}', 'WEBCLOCK_WRITE_TOKEN': token})
        base = '/api/v1/control/'
        program = clock.app.test_client()
        denied = program.get(base + 'targets', headers={'Authorization': 'Bearer ' + bootstrap.json['client']['token']})
        self.assertEqual(denied.status_code, 403)

        async def exercise():
            async with stdio_client(server) as streams, ClientSession(*streams) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertEqual(names, {'list_targets', 'create_alarm', 'create_calendar_event',
                                         'create_event_alarm'})

                async def call(name, arguments):
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.isError, result.content)
                    return result.structuredContent

                catalog = await call('list_targets', {})
                target = 'group:' + group['id']
                self.assertEqual(catalog['targets'], [{'target': target, 'name': '臥室'}])
                tomorrow = (datetime.fromisoformat(catalog['now']).date() + timedelta(days=1)).isoformat()
                args = dict(request_id='test-alarm-once', date=tomorrow, time='07:30', name='起床', target=target)
                invalid = await client.call_tool('create_alarm', dict(args, target='group:missing'))
                self.assertTrue(invalid.isError)
                self.assertEqual(program.get(base + 'schedules', headers=headers).json['schedules'], [])

                alarm = await call('create_alarm', args)
                item_id = alarm['saved']['schedule']['id']
                self.assertTrue(alarm['assigned'])
                self.assertEqual(alarm['saved']['schedule']['rule']['dates'], [tomorrow])
                self.assertEqual(alarm['saved']['next_occurrence'], tomorrow + 'T07:30:00+08:00')
                replay = await call('create_alarm', args)
                self.assertTrue(replay['replayed'])
                self.assertEqual(replay['saved']['schedule']['id'], item_id)
                self.assertEqual(len(program.get(base + 'schedules', headers=headers).json['schedules']), 1)

                event = await call('create_calendar_event', dict(request_id='test-dentist-event', title='牙醫回診',
                    start=tomorrow+'T14:00:00+08:00', end=tomorrow+'T15:00:00+08:00'))
                event_id = event['saved']['event']['id']
                self.assertEqual(program.get(base + 'events/' + event_id, headers=headers).json['event']['title'], '牙醫回診')
                linked = await call('create_event_alarm', dict(request_id='test-dentist-reminder', name='出發',
                                    event_id=event_id, minutes_before=15, target=target))
                self.assertEqual(linked['saved']['next_occurrence'], tomorrow + 'T13:45:00+08:00')
                self.assertTrue(linked['assigned'])

                route = base + 'schedules/' + item_id + '/targets/group/' + group['id']
                state = program.get(route, headers=headers).json
                self.assertTrue(state['assigned'])
                cleared = program.put(route, json=dict(assigned=False, revision=state['revision']), headers=headers)
                self.assertEqual(cleared.status_code, 200)
                replay = await call('create_alarm', args)
                self.assertFalse(replay['assigned'])  # Replaying must respect an intervening unassignment.
                changed_target = await client.call_tool('create_alarm', dict(args, target='group:other'))
                self.assertTrue(changed_target.isError)
                self.assertIn('idempotency_conflict', changed_target.content[0].text)
                program.delete(base + 'schedules/' + item_id, headers=headers,
                               json={'revision': replay['saved']['revision']})
                deleted = await call('create_alarm', args)
                self.assertIsNone(deleted['saved'])
                self.assertEqual(deleted['current_error'], 'not_found')

                with patch('webclock.services.control_service.ControlService.target', side_effect=OSError()):
                    partial = await call('create_alarm', dict(args, request_id='test-partial-save'))
                self.assertIsNone(partial['assigned'])
                self.assertEqual(partial['assignment_error'], 'assignment_failed')
                partial_replay = await call('create_alarm', dict(args, request_id='test-partial-save'))
                self.assertEqual(partial['saved']['schedule']['id'], partial_replay['saved']['schedule']['id'])
                self.assertFalse(partial_replay['assigned'])
                admin.delete('/api/v1/control-clients/' + issued.json['client']['id'])
                self.assertTrue((await client.call_tool('list_targets', {})).isError)

        asyncio.run(exercise())
