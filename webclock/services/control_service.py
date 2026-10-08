"""Restricted program edits using the same schedules and device assignments as the UI."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re

from .device_access_service import calendar_content_allows
from .event_service import read_events, save_events, validate_event
from .schedule_service import TAIPEI, next_occurrence, read_schedules, save_schedules, validate_schedule
from .storage import load_json, revision, save_json


class ControlError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def read_control_requests(directory):
    """Validate receipts shared by program ownership and legacy display isolation."""
    try:
        records = load_json(Path(directory) / 'control-requests.json', {})
    except (OSError, ValueError):
        raise ControlError('control_not_ready', 503) from None
    if not isinstance(records, dict) or len(records) > 10000:
        raise ControlError('control_not_ready', 503)
    for key, row in records.items():
        if (not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key)
                or not isinstance(row, dict)
                or set(row) != {'owner_id', 'client_id', 'kind', 'item_id', 'fingerprint', 'candidate', 'response'}
                or row['kind'] not in ('schedules', 'events')
                or any(not isinstance(row[field], str) or not row[field]
                       for field in ('owner_id', 'client_id', 'item_id', 'fingerprint'))
                or not isinstance(row['candidate'], dict) or row['candidate'].get('id') != row['item_id']
                or (row['response'] is not None and not isinstance(row['response'], dict))):
            raise ControlError('control_not_ready', 503)
        try:
            candidate = (validate_schedule if row['kind'] == 'schedules' else validate_event)(row['candidate'])
            if (candidate != row['candidate'] or not re.fullmatch(r'[0-9a-f]{64}', row['fingerprint'])
                    or (row['kind'] == 'events' and (candidate['owner_id'] != row['owner_id']
                        or candidate['creator_client_id'] != row['client_id']))):
                raise ValueError()
            result = row['response']
            if result is not None:
                field = 'schedule' if row['kind'] == 'schedules' else 'event'
                public = {k: v for k, v in candidate.items() if k not in ('owner_id', 'creator_client_id')}
                keys = {field, 'revision'} | ({'next_occurrence', 'next_occurrence_status'} if field == 'schedule' else set())
                if set(result) != keys or result[field] != public or result['revision'] != revision(candidate):
                    raise ValueError()
                if field == 'schedule':
                    if result['next_occurrence_status'] not in ('ready', 'not_ready'):
                        raise ValueError()
                    if result['next_occurrence'] is not None:
                        if datetime.fromisoformat(result['next_occurrence']).utcoffset() is None:
                            raise ValueError()
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ControlError('control_not_ready', 503) from None
    return records


class ControlService:
    # All callers hold storage_lock, including credential revalidation.
    def __init__(self, directory, client, access, holidays, calendar_events, source_ids):
        self.directory, self.client = Path(directory), client
        self.access, self.holidays = access, holidays
        self.calendar_events, self.source_ids = calendar_events, set(source_ids) | {'local', 'webclock'}
        self.path = self.directory / 'control-requests.json'
        self._receipts = None
        self._owned = None

    def requests(self):
        if self._receipts is None:
            self._receipts = read_control_requests(self.directory)
        return self._receipts

    def require(self, scope):
        if scope not in self.client['scopes']:
            raise ControlError('permission_denied', 403)

    def rows(self, kind):
        return read_schedules(self.directory) if kind == 'schedules' else read_events(self.directory)

    def allowed(self, kind, row):
        if kind == 'events' and row['owner_id'] != self.client['owner_id']:
            return False
        if row['id'] in self.client['schedule_ids' if kind == 'schedules' else 'event_ids']:
            return True
        if self._owned is None:
            self._owned = {(record['kind'], record['item_id']) for record in self.requests().values()
                           if record['owner_id'] == self.client['owner_id']
                           and record['client_id'] == self.client['id'] and record['response'] is not None}
        return (kind, row['id']) in self._owned

    def item(self, kind, item_id):
        row = next((row for row in self.rows(kind) if row['id'] == item_id), None)
        if row is None or not self.allowed(kind, row):
            raise ControlError('not_found', 404)
        return row

    def result(self, kind, row):
        key = 'schedule' if kind == 'schedules' else 'event'
        public = {k: v for k, v in row.items() if k not in ('owner_id', 'creator_client_id')}
        result = {key: public, 'revision': revision(row)}
        if kind == 'schedules':
            source_failed = False

            def strict_events(**query):
                nonlocal source_failed
                try:
                    if not callable(self.calendar_events):
                        raise ValueError('Calendar provider is unavailable')
                    events = self.calendar_events(**query, strict=True)
                    if not isinstance(events, list):
                        raise ValueError('Calendar provider returned invalid events')
                    return events
                except (ValueError, OSError, RuntimeError, OverflowError):
                    source_failed = True
                    raise

            try:
                upcoming = next_occurrence(row, self.holidays, datetime.now(TAIPEI), strict_events)
                result.update(next_occurrence=upcoming['datetime'] if upcoming else None,
                              next_occurrence_status='not_ready' if source_failed else 'ready')
            except (ValueError, OSError, RuntimeError, OverflowError):
                result.update(next_occurrence=None, next_occurrence_status='not_ready')
        return result

    def list(self, kind):
        self.require(kind + ':read')
        return {kind: [self.result(kind, row) for row in self.rows(kind) if self.allowed(kind, row)]}

    def get(self, kind, item_id):
        self.require(kind + ':read')
        return self.result(kind, self.item(kind, item_id))

    def validate(self, kind, data, old=None, item_id=None):
        if not isinstance(data, dict) or set(data) & {'id', 'owner_id', 'creator_client_id'}:
            raise ControlError('invalid_request')
        values = dict(old or {}, **data)
        values['id'] = item_id or old['id']
        if kind == 'events':
            values.update(owner_id=self.client['owner_id'],
                          creator_client_id=(old or {}).get('creator_client_id', self.client['id']))
            return validate_event(values)
        row = validate_schedule(values)
        if row['type'] != 'alarm':
            raise ControlError('invalid_request')
        link = row.get('calendar_link')
        if link and (old is None or 'calendar_link' in data):
            sources = set(link['source_ids'])
            if sources - self.source_ids:
                raise ControlError('invalid_request')
            ungranted = sources - set(self.client['calendar_source_ids'])
            if ungranted:
                target = link.get('target', {})
                if (ungranted != {'webclock'} or sources != {'webclock'}
                        or target.get('source_id') != 'webclock'):
                    raise ControlError('permission_denied', 403)
                self.item('events', target.get('uid'))
            target = link.get('target')
            if target and target['source_id'] not in sources:
                raise ControlError('invalid_request')
        return row

    def save(self, kind, rows):
        (save_schedules if kind == 'schedules' else save_events)(self.directory, rows)

    def create(self, kind, body):
        self.require(kind + ':write')
        key = 'schedule' if kind == 'schedules' else 'event'
        if (not isinstance(body, dict) or set(body) != {'request_id', key}
                or not isinstance(body['request_id'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', body['request_id'])):
            raise ControlError('invalid_request')
        request_key = revision([self.client['owner_id'], self.client['id'], body['request_id']])
        fingerprint = revision([kind, body[key]])
        records = self.requests()
        prior = records.get(request_key)
        if prior:
            if prior['fingerprint'] != fingerprint or prior['kind'] != kind:
                raise ControlError('idempotency_conflict', 409)
            if prior['response'] is None:
                current = next((row for row in self.rows(kind) if row['id'] == prior['item_id']), None)
                if current != prior['candidate']:
                    # Missing/changed data is ambiguous: never resurrect a deleted item.
                    raise ControlError('request_incomplete', 409)
                prior['response'] = self.result(kind, current)
                save_json(self.path, records)
            return dict(deepcopy(prior['response']), replayed=True), 200
        item_id = 'ctl_' + request_key[:48]
        rows = self.rows(kind)
        if any(row['id'] == item_id for row in rows):
            raise ControlError('idempotency_conflict', 409)
        row = self.validate(kind, body[key], item_id=item_id)
        if len(rows) >= 1000 or len(records) >= 10000:
            raise ControlError('capacity_reached', 409)
        # ponytail: bounded JSON receipts; migrate to SQLite for higher write volume/transactions.
        records[request_key] = dict(owner_id=self.client['owner_id'], client_id=self.client['id'],
                                   kind=kind, item_id=item_id, fingerprint=fingerprint, candidate=row, response=None)
        save_json(self.path, records)
        self.save(kind, rows + [row])
        result = self.result(kind, row)
        records[request_key]['response'] = result
        save_json(self.path, records)
        return result, 201

    def change(self, kind, item_id, body, delete=False):
        self.require(kind + ':write')
        key = 'schedule' if kind == 'schedules' else 'event'
        expected = {'revision'} if delete else {'revision', key}
        if not isinstance(body, dict) or set(body) != expected:
            raise ControlError('invalid_request')
        old = self.item(kind, item_id)
        if body['revision'] != revision(old):
            raise ControlError('revision_conflict', 409)
        rows = self.rows(kind)
        if delete:
            self.save(kind, [row for row in rows if row['id'] != item_id])
            return dict(status='deleted', id=item_id)
        updated = self.validate(kind, body[key], old=old)
        self.save(kind, [updated if row['id'] == item_id else row for row in rows])
        return self.result(kind, updated)

    def target(self, kind, item_id, target_kind, target_id, body=None):
        self.require('assignments:write')
        self.item(kind, item_id)
        if target_kind not in ('group', 'device'):
            raise ControlError('not_found', 404)
        if target_id not in self.client[target_kind + '_ids']:
            raise ControlError('permission_denied', 403)
        owner = self.client['owner_id']
        if target_kind == 'group':
            settings = self.access.get_group(owner, target_id)
            content = deepcopy(settings['content'])
        else:
            settings = self.access.get_device_content(owner, target_id)
            content = deepcopy(settings['effective_content'])
        target = dict(source_id='webclock', uid=item_id, scope='occurrence', recurrence_id='')
        assigned = (item_id in content['schedule_ids'] if kind == 'schedules'
                    else calendar_content_allows(content, target))
        result = dict(assigned=assigned, revision=settings['revision'])
        if body is None:
            return result
        if (not isinstance(body, dict) or set(body) != {'assigned', 'revision'}
                or type(body['assigned']) is not bool):
            raise ControlError('invalid_request')
        if body['revision'] != settings['revision']:
            raise ControlError('revision_conflict', 409)
        if body['assigned'] == assigned:
            return result
        catalog = self.access.content_catalog()
        sources = set(catalog.get('calendar_source_ids', []))
        available = dict(calendar_source_ids=sources,
                         manual_note_ids=set(catalog.get('manual_note_ids', [])),
                         schedule_ids={row['id'] for row in catalog.get('schedules', [])
                             if not set((row.get('calendar_link') or {}).get('source_ids', [])) - (sources | {'local'})})
        removed_events = {row['item_id'] for row in self.requests().values() if row['kind'] == 'events'} - {
            row['id'] for row in self.rows('events')}

        def retained(value):
            # Whole-content validators must not make unrelated deleted references
            # block this edit. Keep every other valid selection, including ungranted ones.
            value = deepcopy(value)
            for field, identifiers in available.items():
                if field in value:
                    value[field] = [identifier for identifier in value[field] if identifier in identifiers]
            for field in ('calendar_targets', 'calendar_exclusions'):
                if field in value:
                    value[field] = [row for row in value[field] if row['source_id'] in sources
                                   and not (row['source_id'] == 'webclock' and row['uid'] in removed_events)]
            return value

        content = retained(content)
        if kind == 'schedules':
            ids = set(content['schedule_ids'])
            ids.add(item_id) if body['assigned'] else ids.discard(item_id)
            patch = dict(schedule_ids=sorted(ids))
        else:
            patch = {key: deepcopy(content.get(key, [])) for key in
                     ('calendar_source_ids', 'calendar_targets', 'calendar_exclusions')}
            for field in ('calendar_targets', 'calendar_exclusions'):
                patch[field] = [row for row in patch[field]
                                if not (row['source_id'] == 'webclock' and row['uid'] == item_id)]
            patch['calendar_targets' if body['assigned'] else 'calendar_exclusions'].append(target)
        if target_kind == 'group':
            self.access.update_group(owner, target_id, dict(revision=settings['revision'],
                                     content=dict(retained(settings['content']), **patch)))
        else:
            overrides = dict(retained(settings['content_overrides']), **patch)
            self.access.update_device_content(owner, target_id,
                dict(revision=settings['revision'], content_overrides=overrides))
        return self.target(kind, item_id, target_kind, target_id)
