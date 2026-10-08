"""Native one-off calendar events; display windows never change event times."""
from datetime import date, datetime
from pathlib import Path
import re
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .calendar_display_service import display_bounds, validate_display_targets
from .storage import load_json, save_json, storage_lock

SOURCE_ID = 'webclock'
FIELDS = {'id', 'title', 'start', 'end', 'timezone', 'all_day', 'enabled',
          'display_window', 'owner_id', 'creator_client_id'}


def event_target(row):
    return dict(source_id=SOURCE_ID, uid=row['id'], scope='occurrence', recurrence_id='',
                title=row['title'], display_window=row['display_window'])


def validate_event(data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError('Invalid calendar event')
    row = dict(data)
    row.setdefault('id', uuid4().hex)
    row.setdefault('timezone', 'Asia/Taipei')
    row.setdefault('all_day', False)
    row.setdefault('enabled', True)
    row.setdefault('display_window', {'mode': 'day'})
    if not isinstance(row['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', row['id']):
        raise ValueError('Invalid event ID')
    if not isinstance(row.get('title'), str) or not 1 <= len(row['title'].strip()) <= 500:
        raise ValueError('Event title is required (maximum 500 characters)')
    row['title'] = row['title'].strip()
    for field in ('owner_id', 'creator_client_id'):
        if (not isinstance(row.get(field), str) or not 1 <= len(row[field]) <= 128
                or any(ord(char) < 32 for char in row[field])):
            raise ValueError('Invalid event ownership')
    if type(row['all_day']) is not bool or type(row['enabled']) is not bool:
        raise ValueError('Invalid event flags')
    if not isinstance(row['timezone'], str) or len(row['timezone']) > 128:
        raise ValueError('Invalid event timezone')
    try:
        zone = ZoneInfo(row['timezone'])
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError('Invalid event timezone') from error
    times = []
    for field in ('start', 'end'):
        value = row.get(field)
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError('Event start and end are required')
        if row['all_day']:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('All-day event dates must use YYYY-MM-DD')
            stamp = date.fromisoformat(value)
        else:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.utcoffset() is None:
                raise ValueError('Event times must include a timezone offset')
            try:
                stamp = stamp.astimezone(zone)
            except (OverflowError, OSError) as error:
                raise ValueError('Event date exceeds the supported range') from error
        if not 2 <= stamp.year < 9999:
            raise ValueError('Event date exceeds the supported range')
        row[field] = stamp.isoformat()
        times.append(stamp if row['all_day'] else stamp.timestamp())
    if times[1] <= times[0]:
        raise ValueError('Event end must be after start (all-day end is exclusive)')
    row['display_window'] = validate_display_targets([event_target(row)], {SOURCE_ID})[0]['display_window']
    try:
        bounds = display_bounds(project_event(row, datetime(2000, 1, 1, tzinfo=zone)), event_target(row), zone)
        if any(not 2 <= datetime.fromtimestamp(value / 1000, zone).year < 9999 for value in bounds):
            raise ValueError('Event display window exceeds the supported range')
    except (OverflowError, OSError) as error:
        raise ValueError('Event display window exceeds the supported range') from error
    return row


def _validated_rows(rows):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('Invalid stored calendar events')
    if any(not isinstance(row, dict) or not row.get('id') for row in rows):
        raise ValueError('Stored calendar event is missing an ID')
    result = [validate_event(row) for row in rows]
    if len({row['id'] for row in result}) != len(result):
        raise ValueError('Duplicate event IDs')
    return result


def read_events(directory):
    with storage_lock:
        return _validated_rows(load_json(Path(directory) / 'events.json', []))


def save_events(directory, rows):
    with storage_lock:
        read_events(directory)  # Never overwrite malformed stored data.
        save_json(Path(directory) / 'events.json', _validated_rows(rows))


def project_event(row, query_start):
    """Project only public calendar fields, retaining the event's own timezone."""
    zone = ZoneInfo(row['timezone'])
    if row['all_day']:
        start = datetime.combine(date.fromisoformat(row['start']), datetime.min.time(), zone)
        end = datetime.combine(date.fromisoformat(row['end']), datetime.min.time(), zone)
    else:
        start, end = (datetime.fromisoformat(row[field]) for field in ('start', 'end'))
    begins, finishes = start.astimezone(query_start.tzinfo), end.astimezone(query_start.tzinfo)
    return dict(source_id=SOURCE_ID, uid=row['id'], text=row['title'], recurring=False, recurrence_id='',
                time='' if row['all_day'] or begins.date() < query_start.date() else begins.strftime('%H:%M'),
                starts_at=int(start.timestamp() * 1000), ends_at=int(end.timestamp() * 1000),
                all_day=row['all_day'], start_date=begins.date().isoformat(), end_date=finishes.date().isoformat())


def query_events(rows, start, end):
    first, last = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    events = [project_event(row, start) for row in rows if row['enabled']]
    return sorted([event for event in events if event['starts_at'] < last and event['ends_at'] > first],
                  key=lambda event: (event['starts_at'], event['uid']))
