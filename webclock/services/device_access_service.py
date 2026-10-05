"""Groups, invitations and atomic enrollment; one process owns the JSON file."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import math
from pathlib import Path
import re
import secrets
import time
from uuid import uuid4

from .device_service import DeviceService, _identifier
from .storage import load_json, revision, save_json, storage_lock
from .schedule_service import validate_calendar_target, calendar_target_matches


CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
INVITE_SECONDS = 600
ATTEMPT_SECONDS = 600
PENDING_ATTEMPT_LIMIT = 200
DEVICE_LIMIT = 100
GROUP_LIMIT = 100
SOURCE_LIMIT = 10
GLOBAL_LIMIT = 100
RATE_SECONDS = 60
_RATE_WINDOWS = {}
CONTENT_FIELDS = {'calendar_source_ids', 'manual_note_ids', 'schedule_ids'}
CALENDAR_FIELDS = {'calendar_targets', 'calendar_exclusions'}


class AccessError(ValueError):
    def __init__(self, message, status=400, code='invalid_request', retry_after=None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


def _stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def _epoch(stamp):
    value = datetime.fromisoformat(stamp)
    if value.tzinfo is None:
        raise ValueError('Timestamp must include its timezone')
    return value.timestamp()


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ValueError('Name must contain 1-100 characters')
    return value.strip()


def _reference_ids(key, values):
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError('Invalid content IDs: ' + key)
    if key == 'manual_note_ids':
        invalid = any(type(value) is not int or value <= 0 for value in values)
    else:
        invalid = any(not isinstance(value, str) or not value or len(value) > 128 for value in values)
    if invalid:
        raise ValueError('Invalid content IDs: ' + key)
    return values


def _calendar_targets(values, sources, whole_sources, exclusions=(), canonical=True):
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError('Invalid calendar targets')
    targets = [validate_calendar_target(value, sources) for value in values]
    series = {(row['source_id'], row['uid']) for row in targets if row['scope'] == 'series'}
    unique = {}
    for row in targets:
        overrides_denied_series = row['scope'] == 'occurrence' and any(
            denied['scope'] == 'series' and calendar_target_matches(row, denied) for denied in exclusions)
        if canonical and not overrides_denied_series and (row['source_id'] in whole_sources
                or (row['scope'] == 'occurrence' and (row['source_id'], row['uid']) in series)):
            continue
        key = (row['source_id'], row['uid'], row['scope'], row['recurrence_id'])
        unique[key] = row
    return [unique[key] for key in sorted(unique)]


def calendar_content_allows(content, event):
    """Exact exceptions override the inherited series/source without expanding a feed."""
    allowed = [target for target in content.get('calendar_targets', []) if calendar_target_matches(event, target)]
    denied = [target for target in content.get('calendar_exclusions', []) if calendar_target_matches(event, target)]
    if any(target['scope'] == 'occurrence' for target in denied):
        return False
    if any(target['scope'] == 'occurrence' for target in allowed):
        return True
    if denied:
        return False
    return bool(allowed) or event.get('source_id') in content['calendar_source_ids']


def _assignment_membership(content, item):
    kind = item['kind']
    if kind != 'calendar':
        return item['id'] in content['manual_note_ids' if kind == 'manual_note' else 'schedule_ids'], False
    target = item['target']
    if target['scope'] == 'occurrence':
        return calendar_content_allows(content, target), False
    same_series = lambda row: row['source_id'] == target['source_id'] and row['uid'] == target['uid']
    grants = [row for row in content.get('calendar_targets', []) if same_series(row)]
    denies = [row for row in content.get('calendar_exclusions', []) if same_series(row)]
    base = (target['source_id'] in content['calendar_source_ids'] or any(row['scope'] == 'series' for row in grants)) and not any(
        row['scope'] == 'series' for row in denies)
    exceptions = {row['recurrence_id'] for row in grants + denies if row['scope'] == 'occurrence'}
    values = [calendar_content_allows(content, dict(target, scope='occurrence', recurrence_id=value)) for value in exceptions]
    full = base and all(values)
    return full, not full and (base or any(values))


class DeviceAccessService:
    def __init__(self, state_path, invite_secret, validate_settings, default_settings,
                 content_catalog, clock=None):
        self.path = Path(state_path)
        self.secret = invite_secret
        self.validate_settings = validate_settings
        self.default_settings = default_settings
        self.content_catalog = content_catalog
        self.clock = clock or time.time

    def _load(self):
        try:
            data = load_json(self.path, dict(version=1, groups={}, invites={}, devices={}, attempts={}))
            if (not isinstance(data, dict) or set(data) != {'version', 'groups', 'invites', 'devices', 'attempts'}
                    or type(data.get('version')) is not int or data['version'] != 1
                    or any(not isinstance(data.get(field), dict)
                           for field in ('groups', 'invites', 'devices', 'attempts'))
                    or len(data['groups']) > GROUP_LIMIT or len(data['devices']) > DEVICE_LIMIT):
                raise ValueError('Invalid state envelope')
            group_fields = {'id', 'owner_id', 'name', 'enabled', 'display_overrides', 'content',
                            'content_version', 'created_at', 'updated_at', 'is_default'}
            default_owners = set()
            for group_id, row in data['groups'].items():
                if (not isinstance(row, dict) or set(row) != group_fields or row['id'] != group_id
                        or not isinstance(group_id, str) or not group_id or len(group_id) > 128
                        or not isinstance(row['owner_id'], str) or not row['owner_id'] or len(row['owner_id']) > 128
                        or type(row['enabled']) is not bool or type(row['is_default']) is not bool
                        or type(row['content_version']) is not int or row['content_version'] < 1
                        or not isinstance(row['content'], dict)
                        or not CONTENT_FIELDS <= set(row['content'])
                        or set(row['content']) - (CONTENT_FIELDS | CALENDAR_FIELDS)):
                    raise ValueError('Invalid stored group')
                _name(row['name'])
                self._settings(row['display_overrides'])
                for key in CONTENT_FIELDS:
                    _reference_ids(key, row['content'][key])
                # Stored selections may outlive a source or the catalog's time window.
                for field in CALENDAR_FIELDS:
                    targets = row['content'].get(field, [])
                    sources = {value.get('source_id') for value in targets
                               if isinstance(value, dict) and isinstance(value.get('source_id'), str)} if isinstance(targets, list) else set()
                    for source in sources:
                        _reference_ids('calendar_source_ids', [source])
                    _calendar_targets(targets, sources, [], canonical=False)
                _epoch(row['created_at'])
                _epoch(row['updated_at'])
                if row['is_default']:
                    if row['owner_id'] in default_owners:
                        raise ValueError('Duplicate default group')
                    default_owners.add(row['owner_id'])
            invite_fields = {'id', 'group_id', 'owner_id', 'code_digest', 'created_at', 'expires_at',
                             'capacity', 'used', 'closed'}
            invite_ids = set()
            for group_id, row in data['invites'].items():
                if (not isinstance(row, dict) or set(row) != invite_fields or row['group_id'] != group_id
                        or group_id not in data['groups'] or row['owner_id'] != data['groups'][group_id]['owner_id']
                        or not isinstance(row['id'], str) or not row['id'] or len(row['id']) > 128
                        or row['id'] in invite_ids or row['id'] in data['groups']
                        or not isinstance(row['code_digest'], str)
                        or not re.fullmatch(r'[a-f0-9]{64}', row['code_digest'])
                        or type(row['capacity']) is not int or not 1 <= row['capacity'] <= 100
                        or type(row['used']) is not int or not 0 <= row['used'] <= row['capacity']
                        or type(row['closed']) is not bool
                        or _epoch(row['expires_at']) <= _epoch(row['created_at'])):
                    raise ValueError('Invalid stored invitation')
                invite_ids.add(row['id'])
            device_fields = {'id', 'owner_id', 'group_id', 'enabled', 'status', 'credential_digest',
                             'credential_generation', 'created_at', 'assignment_revision', 'rejoin_required'}
            digests = set()
            for device_id, row in data['devices'].items():
                if (not isinstance(row, dict) or set(row) != device_fields or row['id'] != device_id
                        or not isinstance(device_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', device_id)
                        or row['group_id'] not in data['groups']
                        or row['owner_id'] != data['groups'][row['group_id']]['owner_id']
                        or type(row['enabled']) is not bool or type(row['rejoin_required']) is not bool
                        or row['status'] not in ('active', 'disabled', 'revoked')
                        or type(row['credential_generation']) is not int or row['credential_generation'] < 1
                        or type(row['assignment_revision']) is not int or row['assignment_revision'] < 1):
                    raise ValueError('Invalid stored device identity')
                digest = row['credential_digest']
                if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
                                           or digest in digests):
                    raise ValueError('Invalid stored credential')
                if digest is not None:
                    digests.add(digest)
                if row['status'] == 'active' and (digest is None or row['rejoin_required']):
                    raise ValueError('Invalid active credential')
                _epoch(row['created_at'])
            attempt_fields = {'id', 'owner_id', 'credential_digest', 'created_at', 'expires_at', 'device_id'}
            completed = set()
            pending_count = 0
            attempt_digests = set()
            for attempt_id, row in data['attempts'].items():
                if (not isinstance(row, dict) or set(row) != attempt_fields or row['id'] != attempt_id
                        or not isinstance(attempt_id, str) or not re.fullmatch(r'[a-f0-9]{32}', attempt_id)
                        or not isinstance(row['owner_id'], str) or not row['owner_id']
                        or not isinstance(row['credential_digest'], str)
                        or not re.fullmatch(r'[a-f0-9]{64}', row['credential_digest'])
                        or row['credential_digest'] in attempt_digests
                        or _epoch(row['expires_at']) <= _epoch(row['created_at'])):
                    raise ValueError('Invalid stored join attempt')
                attempt_digests.add(row['credential_digest'])
                device_id = row['device_id']
                if device_id is None:
                    pending_count += 1
                    if row['credential_digest'] in digests:
                        raise ValueError('Pending credential already in use')
                elif (not isinstance(device_id, str) or device_id in completed
                      or device_id not in data['devices']
                      or data['devices'][device_id]['owner_id'] != row['owner_id']
                      or (data['devices'][device_id]['credential_digest'] is not None
                          and data['devices'][device_id]['credential_digest'] != row['credential_digest'])):
                    raise ValueError('Invalid completed join attempt')
                else:
                    completed.add(device_id)
            if pending_count > PENDING_ATTEMPT_LIMIT or len(completed) > DEVICE_LIMIT:
                raise ValueError('Too many join attempts')
            return data
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise AccessError('Invalid stored device access data', 503, 'access_not_ready') from error

    def _owner(self, owner_id):
        if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 128:
            raise AccessError('Management identity required', 401, 'unauthorized')
        return owner_id

    def _group(self, state, owner_id, group_id):
        self._owner(owner_id)
        row = state['groups'].get(group_id)
        if not isinstance(row, dict) or row.get('owner_id') != owner_id:
            raise AccessError('Group not found', 404, 'not_found')
        return row

    def _defaults(self):
        return deepcopy(self.default_settings())

    def _settings(self, overrides):
        if not isinstance(overrides, dict):
            raise ValueError('Display overrides must be an object')
        merged = self._defaults()
        for key, value in overrides.items():
            if key == 'night':
                if not isinstance(value, dict) or not isinstance(merged.get('night'), dict):
                    raise ValueError('Invalid night overrides')
                merged[key] = dict(merged[key], **value)
            else:
                merged[key] = value
        validated = self.validate_settings(merged)
        # Store only the explicit leaves, including False and 0. An empty object
        # resets all overrides to inheritance rather than copying today's defaults.
        patch = {key: ({field: validated[key][field] for field in value}
                       if key == 'night' else validated[key])
                 for key, value in overrides.items()}
        return patch, validated

    def _content(self, value):
        if not isinstance(value, dict) or set(value) - (CONTENT_FIELDS | CALENDAR_FIELDS):
            raise ValueError('Invalid content selections')
        catalog = self.content_catalog()
        schedules = {row['id']: row for row in catalog.get('schedules', [])}
        available = {key: set(catalog.get(key, [])) for key in CONTENT_FIELDS}
        available['schedule_ids'] = set(schedules)
        result = {}
        for key in CONTENT_FIELDS:
            ids = _reference_ids(key, value.get(key, []))
            if set(ids) - available[key]:
                raise ValueError('Select existing content IDs: ' + key)
            result[key] = sorted(set(ids))
        exclusions = _calendar_targets(value.get('calendar_exclusions', []), available['calendar_source_ids'], [], canonical=False)
        targets = _calendar_targets(value.get('calendar_targets', []), available['calendar_source_ids'],
                                    result['calendar_source_ids'], exclusions)
        if targets:
            result['calendar_targets'] = targets
        if exclusions:
            result['calendar_exclusions'] = exclusions
        for schedule_id in result['schedule_ids']:
            link = schedules[schedule_id].get('calendar_link')
            if link and set(link['source_ids']) - (available['calendar_source_ids'] | {'local'}):
                raise ValueError('Selected alarm depends on a missing calendar source')
        return result

    def _assignment_item(self, item, catalog):
        if not isinstance(item, dict) or item.get('kind') not in ('manual_note', 'schedule', 'calendar'):
            raise ValueError('Invalid assignment item')
        kind = item['kind']
        if kind == 'calendar':
            if set(item) != {'kind', 'target'}:
                raise ValueError('Invalid calendar assignment')
            return dict(kind=kind, target=validate_calendar_target(item['target'], catalog.get('calendar_source_ids', [])))
        if set(item) != {'kind', 'id'}:
            raise ValueError('Invalid content assignment')
        key = 'manual_note_ids' if kind == 'manual_note' else 'schedule_ids'
        _reference_ids(key, [item['id']])
        available = catalog.get(key, []) if kind == 'manual_note' else [row['id'] for row in catalog.get('schedules', [])]
        if item['id'] not in available:
            raise AccessError('Content item not found', 404, 'not_found')
        return dict(item)

    def _assignment_result(self, groups, item):
        assigned, partial = [], []
        for group in groups:
            full, mixed = _assignment_membership(group['content'], item)
            if full:
                assigned.append(group['id'])
            elif mixed:
                partial.append(group['id'])
        return dict(group_ids=assigned, partial_group_ids=partial)

    def _assignment_groups(self, state, owner_id):
        self._owner(owner_id)
        return [row for row in state['groups'].values() if row['owner_id'] == owner_id]

    def get_assignments(self, owner_id):
        with storage_lock:
            groups = self._assignment_groups(self._load(), owner_id)
            catalog = self.content_catalog()
            return dict(groups=[{key: group[key] for key in ('id', 'name', 'enabled')} for group in groups],
                        manual_notes={str(identifier): self._assignment_result(groups, dict(kind='manual_note', id=identifier))
                                      for identifier in catalog.get('manual_note_ids', [])},
                        schedules={row['id']: self._assignment_result(groups, dict(kind='schedule', id=row['id']))
                                   for row in catalog.get('schedules', [])})

    def item_assignments(self, owner_id, items):
        """Batch projection for calendar cards; read access state once for the list."""
        with storage_lock:
            groups = self._assignment_groups(self._load(), owner_id)
            catalog = self.content_catalog()
            return [self._assignment_result(groups, self._assignment_item(item, catalog)) for item in items]

    def set_assignments(self, owner_id, data):
        with storage_lock:
            state = self._load()
            groups = self._assignment_groups(state, owner_id)
            catalog = self.content_catalog()
            if (not isinstance(data, dict) or set(data) - {'item', 'group_ids', 'all', 'keep_partial_group_ids'}
                    or ('group_ids' in data) == ('all' in data)):
                raise ValueError('Expected a complete group assignment')
            item = self._assignment_item(data.get('item'), catalog)
            if 'all' in data:
                if data['all'] is not True or 'keep_partial_group_ids' in data:
                    raise ValueError('Invalid all-groups assignment')
                requested = [row['id'] for row in groups]
            else:
                requested = _reference_ids('group_ids', data['group_ids'])
            keep = _reference_ids('group_ids', data.get('keep_partial_group_ids', []))
            if (len(requested) > GROUP_LIMIT or len(keep) > GROUP_LIMIT or set(requested) & set(keep)
                    or (keep and (item['kind'] != 'calendar' or item['target']['scope'] != 'series'))):
                raise ValueError('Invalid partial group assignment')
            for group_id in set(requested) | set(keep):
                self._group(state, owner_id, group_id)
            selected = set(requested)
            changed = False
            for group in groups:
                if group['id'] in keep:
                    continue
                content = deepcopy(group['content'])
                assign = group['id'] in selected
                if item['kind'] != 'calendar':
                    field = 'manual_note_ids' if item['kind'] == 'manual_note' else 'schedule_ids'
                    values = set(content[field])
                    values.add(item['id']) if assign else values.discard(item['id'])
                    content[field] = sorted(values)
                    _reference_ids(field, content[field])
                else:
                    target = item['target']
                    def covered(row):
                        if row['source_id'] != target['source_id'] or row['uid'] != target['uid']:
                            return False
                        return target['scope'] == 'series' or (row['scope'] == 'occurrence'
                                                              and row['recurrence_id'] == target['recurrence_id'])
                    for field in CALENDAR_FIELDS:
                        content[field] = [row for row in content.get(field, []) if not covered(row)]
                    currently, _ = _assignment_membership(content, item)
                    if assign and not currently:
                        content['calendar_targets'].append(target)
                    elif not assign and currently:
                        content['calendar_exclusions'].append(target)
                    # Existing stale references stay intact; only the requested item was validated above.
                    sources = set(content['calendar_source_ids']) | {row['source_id'] for field in CALENDAR_FIELDS for row in content[field]}
                    excluded = _calendar_targets(content['calendar_exclusions'], sources, [], canonical=False)
                    allowed = _calendar_targets(content['calendar_targets'], sources, content['calendar_source_ids'], excluded)
                    for field, values in (('calendar_targets', allowed), ('calendar_exclusions', excluded)):
                        if values:
                            content[field] = values
                        else:
                            content.pop(field, None)
                if content != group['content']:
                    group['content'] = content
                    group['content_version'] += 1
                    group['updated_at'] = _stamp(self.clock())
                    changed = True
            if changed:
                save_json(self.path, state)
            return dict(groups=[{key: group[key] for key in ('id', 'name', 'enabled')} for group in groups],
                        assignment=self._assignment_result(groups, item))

    def _public_group(self, row):
        result = deepcopy(row)
        result['effective_settings'] = self._settings(row['display_overrides'])[1]
        return result

    def _new_id(self, existing):
        for _ in range(20):
            value = uuid4().hex
            if value not in existing:
                return value
        raise AccessError('Unable to allocate an identifier', 503, 'temporarily_unavailable')

    def _create(self, state, owner_id, data, is_default=False):
        self._owner(owner_id)
        if (not isinstance(data, dict)
                or set(data) - {'name', 'enabled', 'display_overrides', 'content'}):
            raise ValueError('Invalid group fields')
        if len(state['groups']) >= GROUP_LIMIT:
            raise ValueError('Group limit reached (100)')
        enabled = data.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError('Enabled must be a boolean')
        group_id = self._new_id(state['groups'])
        now = _stamp(self.clock())
        row = dict(id=group_id, owner_id=owner_id, name=_name(data.get('name')),
                   enabled=enabled, display_overrides=self._settings(data.get('display_overrides', {}))[0],
                   content=self._content(data.get('content', {})), content_version=1,
                   created_at=now, updated_at=now, is_default=is_default)
        state['groups'][group_id] = row
        save_json(self.path, state)
        return self._public_group(row)

    def initialize_owner(self, owner_id, name='預設群組'):
        """Explicit, idempotent migration; ordinary reads never create a group."""
        with storage_lock:
            self._owner(owner_id)
            state = self._load()
            for row in state['groups'].values():
                if row.get('owner_id') == owner_id and row.get('is_default'):
                    return self._public_group(row)
            catalog = self.content_catalog()
            content = {key: list(catalog.get(key, [])) for key in CONTENT_FIELDS}
            content['schedule_ids'] = [row['id'] for row in catalog.get('schedules', [])]
            content = catalog.get('default_content', content)
            return self._create(state, owner_id, dict(name=name, content=content), is_default=True)

    def list_groups(self, owner_id):
        with storage_lock:
            self._owner(owner_id)
            return [self._public_group(row) for row in self._load()['groups'].values()
                    if row.get('owner_id') == owner_id]

    def get_group(self, owner_id, group_id):
        with storage_lock:
            return self._public_group(self._group(self._load(), owner_id, group_id))

    def create_group(self, owner_id, data):
        with storage_lock:
            return self._create(self._load(), owner_id, data)

    def update_group(self, owner_id, group_id, data):
        with storage_lock:
            state = self._load()
            row = self._group(state, owner_id, group_id)
            if (not isinstance(data, dict) or not data
                    or set(data) - {'name', 'enabled', 'display_overrides', 'content'}):
                raise ValueError('Invalid group fields')
            updated = deepcopy(row)
            if 'name' in data:
                updated['name'] = _name(data['name'])
            if 'enabled' in data:
                if type(data['enabled']) is not bool:
                    raise ValueError('Enabled must be a boolean')
                updated['enabled'] = data['enabled']
            if 'display_overrides' in data:
                updated['display_overrides'] = self._settings(data['display_overrides'])[0]
            if 'content' in data:
                # Content PATCH preserves other lists; explicit [] revokes that list.
                if not isinstance(data['content'], dict):
                    raise ValueError('Content selections must be an object')
                updated['content'] = self._content(dict(row['content'], **data['content']))
            if updated != row:
                if (any(updated[key] != row[key] for key in ('enabled', 'content'))
                        or self._settings(updated['display_overrides'])[1]
                        != self._settings(row['display_overrides'])[1]):
                    updated['content_version'] += 1
                updated['updated_at'] = _stamp(self.clock())
                state['groups'][group_id] = updated
                save_json(self.path, state)
            return self._public_group(updated)

    def delete_group(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            self._group(state, owner_id, group_id)
            if any(row.get('group_id') == group_id for row in state['devices'].values()):
                raise AccessError('Move group members before deleting the group', 409, 'group_has_members')
            del state['groups'][group_id]
            state['invites'].pop(group_id, None)
            save_json(self.path, state)

    def _digest(self, code):
        secret = self.secret() if callable(self.secret) else self.secret
        if isinstance(secret, str):
            secret = secret.encode()
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise AccessError('Invitation secret is unavailable', 503, 'access_not_ready')
        return hmac.new(secret, code.encode('ascii'), hashlib.sha256).hexdigest()

    def _invite_metadata(self, state, row):
        group = state['groups'].get(row['group_id'], {})
        remaining = max(0, min(row['capacity'] - row['used'], DEVICE_LIMIT - len(state['devices'])))
        status = ('closed' if row['closed'] else 'disabled' if not group.get('enabled')
                  else 'expired' if self.clock() >= _epoch(row['expires_at'])
                  else 'full' if remaining == 0 else 'active')
        return {**{key: row[key] for key in ('id', 'group_id', 'created_at', 'expires_at', 'capacity', 'used')},
                'remaining': remaining, 'status': status}

    def create_invite(self, owner_id, group_id, capacity=5):
        if type(capacity) is not int or not 1 <= capacity <= 100:
            raise ValueError('Capacity must be an integer from 1 to 100')
        with storage_lock:
            state = self._load()
            group = self._group(state, owner_id, group_id)
            if not group['enabled']:
                raise AccessError('Enable the group before creating an invitation', 409, 'group_disabled')
            if len(state['devices']) >= DEVICE_LIMIT:
                raise AccessError('Device limit reached (100)', 409, 'device_limit')
            for _ in range(20):
                code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))
                digest = self._digest(code)
                if not any(hmac.compare_digest(digest, row['code_digest']) for row in state['invites'].values()):
                    break
            else:
                raise AccessError('Unable to allocate an invitation', 503, 'temporarily_unavailable')
            now = self.clock()
            row = dict(id=self._new_id(set(state['groups']) | {row['id'] for row in state['invites'].values()}),
                       group_id=group_id, owner_id=owner_id, code_digest=digest,
                       created_at=_stamp(now), expires_at=_stamp(now + INVITE_SECONDS),
                       capacity=capacity, used=0, closed=False)
            state['invites'][group_id] = row
            save_json(self.path, state)
            return dict(self._invite_metadata(state, row), code=code)

    def get_invite(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            self._group(state, owner_id, group_id)
            row = state['invites'].get(group_id)
            return self._invite_metadata(state, row) if row else None

    def close_invite(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            self._group(state, owner_id, group_id)
            row = state['invites'].get(group_id)
            if row and not row['closed']:
                row['closed'] = True
                save_json(self.path, state)
            return self._invite_metadata(state, row) if row else None

    def _limit(self, source, purpose='invite'):
        """All attempts count; a fixed window stores at most 100 source keys."""
        now = self.clock()
        key = str(self.path.resolve()) + (':prepare' if purpose == 'prepare' else '')
        window = _RATE_WINDOWS.get(key)
        if window is None or now >= window['reset'] or now < window['start']:
            # Services normally share one state path. Bound test/multi-app paths too.
            if len(_RATE_WINDOWS) >= 100:
                oldest = min(_RATE_WINDOWS, key=lambda item: _RATE_WINDOWS[item]['start'])
                del _RATE_WINDOWS[oldest]
            window = _RATE_WINDOWS[key] = dict(start=now, reset=now + RATE_SECONDS, total=0, sources={})
        source = source if isinstance(source, str) and len(source) <= 200 else 'unknown'
        used = window['sources'].get(source, 0)
        if window['total'] >= GLOBAL_LIMIT or used >= SOURCE_LIMIT:
            raise AccessError('Too many invitation attempts', 429, 'rate_limited',
                              max(1, math.ceil(window['reset'] - now)))
        window['total'] += 1
        window['sources'][source] = used + 1

    def check_invite(self, code, source):
        """Read-only validation; join rechecks and consumes inside one transaction."""
        with storage_lock:
            self._limit(source)
            match = self._matching_invite(self._load(), code)
            return dict(invite_id=match['id'], group_id=match['group_id'], owner_id=match['owner_id'])

    def _matching_invite(self, state, code):
        normalized = code.upper() if isinstance(code, str) and code.isascii() else ''
        if len(normalized) != 6 or any(char not in CODE_ALPHABET for char in normalized):
            raise AccessError('Invalid or unavailable invitation', 400, 'invalid_invitation')
        digest = self._digest(normalized)
        match = None
        for row in state['invites'].values():
            if hmac.compare_digest(row['code_digest'], digest):
                match = row
        if match is None or self._invite_metadata(state, match)['status'] != 'active':
            raise AccessError('Invalid or unavailable invitation', 400, 'invalid_invitation')
        return match

    @staticmethod
    def _credential_digest(token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    @staticmethod
    def _identity(row):
        value = {key: row[key] for key in ('owner_id', 'group_id', 'credential_generation', 'assignment_revision')}
        value['device_id'] = row['id']
        value['identity_revision'] = revision(value)
        return value

    def _active_identity(self, state, row, owner_id):
        group = state['groups'].get(row['group_id'])
        if (row['owner_id'] != owner_id or not row['enabled'] or row['status'] != 'active'
                or row['rejoin_required'] or row['credential_digest'] is None
                or not group or not group['enabled'] or group['owner_id'] != owner_id):
            raise AccessError('Device authorization is no longer valid', 403, 'device_authorization_revoked')
        return self._identity(row)

    def _device_for_digest(self, state, digest):
        if digest is not None:
            return next((row for row in state['devices'].values()
                         if row['credential_digest'] is not None
                         and hmac.compare_digest(row['credential_digest'], digest)), None)
        return None

    def authenticate(self, token, owner_id):
        """Validate the current owner, credential and assignment before any response/304."""
        with storage_lock:
            self._owner(owner_id)
            state = self._load()
            row = self._device_for_digest(state, self._credential_digest(token))
            if row is None:
                raise AccessError('A device credential is required', 401, 'device_authentication_required')
            return self._active_identity(state, row, owner_id)

    def identity(self, token, owner_id):
        with storage_lock:
            self._owner(owner_id)
            state = self._load()
            digest = self._credential_digest(token)
            row = self._device_for_digest(state, digest)
            if row is not None:
                identity = self._active_identity(state, row, owner_id)
                group = state['groups'][identity['group_id']]
                return {'status': 'active', 'identity': identity,
                        'group': {'id': group['id'], 'name': group['name']}}
            if digest is not None:
                for attempt in state['attempts'].values():
                    if hmac.compare_digest(attempt['credential_digest'], digest):
                        if attempt['device_id'] is not None:
                            # A retained attempt cannot resurrect a cleared/revoked credential.
                            raise AccessError('Device authorization is no longer valid', 403,
                                              'device_authorization_revoked')
                        if attempt['owner_id'] == owner_id and _epoch(attempt['expires_at']) > self.clock():
                            return {'status': 'pending', 'attempt_id': attempt['id'],
                                    'expires_at': int(_epoch(attempt['expires_at']) * 1000)}
            raise AccessError('A device credential is required', 401, 'device_authentication_required')

    def _leave_device(self, state, token, owner_id):
        self._owner(owner_id)
        row = self._device_for_digest(state, self._credential_digest(token))
        if row is None:
            raise AccessError('A device credential is required', 401, 'device_authentication_required')
        if row['owner_id'] != owner_id:
            raise AccessError('Device authorization is no longer valid', 403, 'device_authorization_revoked')
        return row

    def authorize_leave(self, token, owner_id):
        """Require one's own credential before CSRF, including disabled groups."""
        with storage_lock:
            self._leave_device(self._load(), token, owner_id)

    def leave(self, token, owner_id):
        """Remove this device's authorization and observations together."""
        with storage_lock:
            state = self._load()
            row = self._leave_device(state, token, owner_id)
            self._remove_device(state, row['id'])

    def _owned_device(self, state, owner_id, device_id):
        self._owner(owner_id)
        _identifier(device_id)
        row = state['devices'].get(device_id)
        if row is None or row['owner_id'] != owner_id:
            raise AccessError('Device not found', 404, 'not_found')
        return row

    def authorize_management_device(self, owner_id, device_id):
        with storage_lock:
            self._owned_device(self._load(), owner_id, device_id)

    def _remove_device(self, state, device_id):
        # All callers hold storage_lock. Remove observations first: if the final
        # access write fails, the still-authorized device can report them again.
        DeviceService(self.path.with_name('devices.json')).remove(device_id)
        del state['devices'][device_id]
        # Also permit prepare with the stale cookie if the success reply is lost.
        state['attempts'] = {key: attempt for key, attempt in state['attempts'].items()
                             if attempt['device_id'] != device_id}
        save_json(self.path, state)

    def revoke(self, owner_id, device_id):
        with storage_lock:
            state = self._load()
            self._owned_device(state, owner_id, device_id)
            self._remove_device(state, device_id)

    def device_ids(self):
        """Internal snapshot for pruning observations; includes every owner."""
        with storage_lock:
            return set(self._load()['devices'])

    def list_devices(self, owner_id, include_legacy=False):
        with storage_lock:
            self._owner(owner_id)
            state = self._load()
            observed = {row['id']: row for row in DeviceService(self.path.with_name('devices.json')).list()}
            result = [dict(observed.get(row['id'], dict(DeviceService._public({'id': row['id']}), online=None)),
                           can_revoke=True, reported=row['id'] in observed)
                      for row in state['devices'].values() if row['owner_id'] == owner_id]
            if include_legacy:
                result.extend(dict(row, can_revoke=False, reported=True) for key, row in observed.items()
                              if key not in state['devices'])
            return result

    def prepare(self, owner_id, source, token=None):
        """Return attempt metadata and a token only when a new cookie is needed."""
        with storage_lock:
            self._owner(owner_id)
            self._limit(source, 'prepare')
            state = self._load()
            digest = self._credential_digest(token)
            device = self._device_for_digest(state, digest)
            if device is not None:
                self._active_identity(state, device, owner_id)
                raise AccessError('Device is already joined', 409, 'join_attempt_conflict')
            now = self.clock()
            state['attempts'] = {key: row for key, row in state['attempts'].items()
                                 if row['device_id'] is not None or _epoch(row['expires_at']) > now}
            for row in state['attempts'].values():
                if digest is not None and hmac.compare_digest(row['credential_digest'], digest):
                    if row['device_id'] is not None or row['owner_id'] != owner_id:
                        raise AccessError('Device authorization is no longer valid', 403,
                                          'device_authorization_revoked')
                    return {'attempt_id': row['id'], 'expires_at': int(_epoch(row['expires_at']) * 1000),
                            'token': None, 'created': False}
            pending = [row for row in state['attempts'].values() if row['device_id'] is None]
            if len(pending) >= PENDING_ATTEMPT_LIMIT:
                retry = max(1, math.ceil(min(_epoch(row['expires_at']) for row in pending) - now))
                raise AccessError('Too many pending attempts', 429, 'rate_limited', retry)
            for _ in range(20):
                new_token = secrets.token_urlsafe(32)
                new_digest = self._credential_digest(new_token)
                if (self._device_for_digest(state, new_digest) is None
                        and not any(row['credential_digest'] == new_digest for row in state['attempts'].values())):
                    break
            else:
                raise AccessError('Unable to allocate a credential', 503, 'temporarily_unavailable')
            attempt_id = self._new_id(state['attempts'])
            state['attempts'][attempt_id] = dict(id=attempt_id, owner_id=owner_id,
                credential_digest=new_digest, created_at=_stamp(now), expires_at=_stamp(now + ATTEMPT_SECONDS),
                device_id=None)
            save_json(self.path, state)
            return {'attempt_id': attempt_id, 'expires_at': int((now + ATTEMPT_SECONDS) * 1000),
                    'token': new_token, 'created': True}

    def join(self, owner_id, token, attempt_id, code, source):
        """Activate the same prepared credential and consume one seat in one write."""
        with storage_lock:
            self._owner(owner_id)
            state = self._load()
            digest = self._credential_digest(token)
            if digest is None:
                raise AccessError('A device credential is required', 401, 'device_authentication_required')
            attempt = state['attempts'].get(attempt_id) if isinstance(attempt_id, str) else None
            if (attempt is None or attempt['owner_id'] != owner_id
                    or not hmac.compare_digest(attempt['credential_digest'], digest)):
                raise AccessError('Join attempt no longer matches this browser', 409, 'join_attempt_conflict')
            if attempt['device_id'] is not None:
                row = state['devices'][attempt['device_id']]
                return {'identity': self._active_identity(state, row, owner_id), 'created': False}
            if _epoch(attempt['expires_at']) <= self.clock() or self._device_for_digest(state, digest) is not None:
                raise AccessError('Join attempt has expired or was replaced', 409, 'join_attempt_conflict')
            self._limit(source)
            invitation = self._matching_invite(state, code)
            if invitation['owner_id'] != owner_id:
                raise AccessError('Invalid or unavailable invitation', 400, 'invalid_invitation')
            device_id = self._new_id(state['devices'])
            row = dict(id=device_id, owner_id=owner_id, group_id=invitation['group_id'], enabled=True,
                       status='active', credential_digest=digest, credential_generation=1,
                       created_at=_stamp(self.clock()), assignment_revision=1, rejoin_required=False)
            state['devices'][device_id] = row
            attempt['device_id'] = device_id
            invitation['used'] += 1
            save_json(self.path, state)
            return {'identity': self._identity(row), 'created': True}

    def list_members(self, owner_id, group_id):
        with storage_lock:
            state = self._load()
            group = self._group(state, owner_id, group_id)
            return [{key: deepcopy(value) for key, value in row.items() if key != 'credential_digest'}
                    | {'device_id': row['id'], 'group_enabled': group['enabled']}
                    for row in state['devices'].values()
                    if row['owner_id'] == owner_id and row['group_id'] == group_id]
