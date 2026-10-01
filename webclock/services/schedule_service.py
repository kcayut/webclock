"""Server-owned schedules, persistence and deterministic occurrence calculation."""

import copy
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from pathlib import Path

from .holiday_service import parse_date
from .storage import load_json, save_json, storage_lock

TAIPEI = timezone(timedelta(hours=8), 'Asia/Taipei')
FIELDS = {'id', 'name', 'type', 'time', 'rule', 'enabled', 'skipped_occurrences',
          'browser_sound', 'skip_holidays', 'calendar_link'}
# Retain old prototype settings on disk, outside the management/API contract.
LEGACY_DEVICE_FIELDS = {'sound', 'volume', 'repeat', 'snooze_minutes'}


def validate_schedule(data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError('Invalid schedule object')
    result = dict(data)
    result.setdefault('id', uuid4().hex)
    result.setdefault('type', 'alarm')
    result.setdefault('rule', {})
    result.setdefault('enabled', True)
    result.setdefault('skipped_occurrences', [])
    result.setdefault('browser_sound', 'bell')
    result.setdefault('skip_holidays', False)
    if not isinstance(result['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', result['id']):
        raise ValueError('Invalid schedule id')
    if not isinstance(result.get('name'), str) or not 1 <= len(result['name'].strip()) <= 120:
        raise ValueError('Schedule name is required (maximum 120 characters)')
    result['name'] = result['name'].strip()
    if result['type'] not in ('alarm', 'reminder', 'announcement'):
        raise ValueError('Invalid schedule type')
    if not isinstance(result.get('time'), str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', result['time']):
        raise ValueError('Time must use HH:MM')
    if type(result['enabled']) is not bool:
        raise ValueError('Invalid enabled setting')
    if result['browser_sound'] not in ('bell', 'beep', 'digital', 'silent'):
        raise ValueError('Invalid browser sound')
    if type(result['skip_holidays']) is not bool:
        raise ValueError('Invalid holiday exclusion setting')
    link = result.get('calendar_link')
    if link is not None:
        if (result['type'] != 'alarm' or not isinstance(link, dict)
                or set(link) - {'mode', 'source_ids', 'offset_minutes', 'target'}
                or link.get('mode') not in ('event', 'day')):
            raise ValueError('Invalid calendar link')
        sources = link.get('source_ids')
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 50
                or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value)
                       for value in sources)):
            raise ValueError('Choose calendar source IDs')
        offset = link.get('offset_minutes', 0)
        if type(offset) is not int or not 0 <= offset <= 1440 or (link['mode'] == 'day' and offset):
            raise ValueError('Invalid calendar advance minutes')
        result['calendar_link'] = dict(mode=link['mode'], source_ids=sorted(set(sources)), offset_minutes=offset)
        if 'target' in link:
            target = link['target']
            if (not isinstance(target, dict)
                    or set(target) - {'source_id', 'uid', 'scope', 'recurrence_id', 'title'}
                    or target.get('source_id') not in sources
                    or not isinstance(target.get('uid'), str) or not 1 <= len(target['uid']) <= 1024
                    or not target['uid'].strip() or target.get('scope') not in ('occurrence', 'series')
                    or not isinstance(target.get('recurrence_id', ''), str)
                    or len(target.get('recurrence_id', '')) > 128
                    or ('title' in target and (not isinstance(target['title'], str) or len(target['title']) > 500))):
                raise ValueError('Invalid calendar target')
            result['calendar_link']['target'] = dict(target, recurrence_id=(
                target.get('recurrence_id', '') if target['scope'] == 'occurrence' else ''))
    rule = result['rule']
    if not isinstance(rule, dict) or len(rule) > 1 or set(rule) - {'weekdays', 'workday_only', 'holiday_only', 'dates'}:
        raise ValueError('Choose one schedule rule')
    if 'weekdays' in rule:
        values = rule['weekdays']
        if not isinstance(values, list) or not values or len(values) > 7 or any(type(n) is not int or not 1 <= n <= 7 for n in values):
            raise ValueError('Weekdays must use ISO Monday=1 through Sunday=7')
        rule = {'weekdays': sorted(set(values))}
    elif 'dates' in rule:
        values = rule['dates']
        if not isinstance(values, list) or not 1 <= len(values) <= 366:
            raise ValueError('Choose 1 to 366 dates')
        rule = {'dates': sorted({parse_date(value).isoformat() for value in values})}
    elif rule and next(iter(rule.values())) is not True:
        raise ValueError('Day rule must be true')
    if result['skip_holidays'] and rule.get('holiday_only'):
        raise ValueError('Holiday-only schedules cannot also skip holidays')
    result['rule'] = dict(rule)
    skipped = result['skipped_occurrences']
    if not isinstance(skipped, list) or len(skipped) > 3660:
        raise ValueError('Invalid skipped occurrences')
    canonical_skips = set()
    for value in skipped:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError('Invalid skipped occurrence')
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('Skipped occurrence needs a timezone')
        try:
            canonical_skips.add(stamp.astimezone(TAIPEI).isoformat())
        except OverflowError as error:
            raise ValueError('Skipped occurrence is outside the supported date range') from error
    result['skipped_occurrences'] = sorted(canonical_skips)
    return result


def read_schedules(directory):
    """Expose only server fields while accepting the previous prototype's records."""
    with storage_lock:
        rows = load_json(Path(directory) / 'schedules.json', [])
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('Invalid stored schedules')
        if any(not isinstance(row, dict) or not row.get('id') for row in rows):
            raise ValueError('Stored schedule is missing an ID')
        validated = [validate_schedule({key: value for key, value in row.items()
                                        if key not in LEGACY_DEVICE_FIELDS}) for row in rows]
        if len({row['id'] for row in validated}) != len(validated):
            raise ValueError('Duplicate schedule IDs')
        return validated


def save_schedules(directory, rows):
    """Keep existing device settings inert; editing server data must not erase them."""
    with storage_lock:
        read_schedules(directory)  # Never overwrite malformed stored data.
        path = Path(directory) / 'schedules.json'
        legacy = {row['id']: {key: value for key, value in row.items() if key in LEGACY_DEVICE_FIELDS}
                  for row in load_json(path, [])}
        validated = [validate_schedule(row) for row in rows]
        if len(validated) > 1000 or len({row['id'] for row in validated}) != len(validated):
            raise ValueError('Duplicate schedule ID or schedule limit reached')
        save_json(path, [dict(legacy.get(row['id'], {}), **row) for row in validated])


def matches_date(schedule, holidays, value):
    day = parse_date(value)
    if schedule.get('skip_holidays') and holidays.is_workday(day) is not True:
        return False
    rule = schedule['rule']
    if 'weekdays' in rule:
        return day.isoweekday() in rule['weekdays']
    if 'dates' in rule:
        return day.isoformat() in rule['dates']
    if rule.get('workday_only'):
        return holidays.is_workday(day) is True
    if rule.get('holiday_only'):
        return holidays.is_holiday(day) is True
    return True


def next_calendar_occurrence(schedule, holidays, now, calendar_events):
    """Resolve selected calendar sources on the server; never fall back to daily."""
    if not callable(calendar_events):
        return None
    link = schedule['calendar_link']
    target = link.get('target')
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    advance = timedelta(minutes=link['offset_minutes'])
    try:
        end = start + timedelta(days=366)
        shift = advance if link['mode'] == 'event' else timedelta()
        events = calendar_events(start=start + shift, end=end + shift, source_ids=link['source_ids'])
    except (OSError, ValueError, OverflowError):
        return None
    if not isinstance(events, list):
        return None
    candidates = set()
    hour, minute = map(int, schedule['time'].split(':'))
    for item in events:
        if not isinstance(item, dict) or item.get('source_id') not in link['source_ids']:
            continue
        if target and (item['source_id'] != target['source_id'] or item.get('uid') != target['uid']
                       or (target['scope'] == 'occurrence'
                           and item.get('recurrence_id', '') != target['recurrence_id'])):
            continue
        first, last = item.get('starts_at'), item.get('ends_at', item.get('starts_at'))
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (first, last)):
            continue
        try:
            event_start = datetime.fromtimestamp(first / 1000, TAIPEI)
            event_end = datetime.fromtimestamp(last / 1000, TAIPEI)
            if event_end < event_start:
                continue
            if link['mode'] == 'event':
                # A date-only event has no specified ringing time.
                if item.get('all_day') is True:
                    continue
                candidate = event_start - advance
                if start <= candidate < end:
                    candidates.add(candidate)
            else:
                first_day = max(start.date(), event_start.date())
                last_day = min((end - timedelta(days=1)).date(),
                               (event_end - timedelta(microseconds=1)).date()
                               if event_end > event_start else event_start.date())
                for offset in range((last_day - first_day).days + 1):
                    candidates.add(datetime.combine(first_day + timedelta(days=offset), time(hour, minute), TAIPEI))
        except (OSError, ValueError, OverflowError):
            continue
    skipped = set(schedule['skipped_occurrences'])
    for stamp in sorted(candidates):
        if stamp < now or stamp.isoformat() in skipped or not matches_date(schedule, holidays, stamp.date()):
            continue
        result = copy.deepcopy(schedule)
        result['datetime'] = stamp.isoformat()
        result['occurrence_id'] = schedule['id'] + '@' + result['datetime']
        return result
    return None


def next_occurrence(schedule, holidays, now, calendar_events=None):
    """Earliest unskipped occurrence at or after an aware timestamp, in Taiwan."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Current time must include a timezone')
    if not schedule['enabled']:
        return None
    now = now.astimezone(TAIPEI)
    if schedule.get('calendar_link'):
        return next_calendar_occurrence(schedule, holidays, now, calendar_events)
    rule = schedule['rule']
    skipped = set(schedule['skipped_occurrences'])
    if 'dates' in rule:
        candidates = (parse_date(value) for value in sorted(rule['dates']))
    else:
        start = now.date()
        if schedule.get('skip_holidays') or rule.get('workday_only') or rule.get('holiday_only'):
            start = max(start, parse_date(holidays.coverage['start']))
            end = parse_date(holidays.coverage['end'])
        else:
            # Every non-calendar rule occurs at least weekly, even with skips.
            end = date.fromordinal(min(date.max.toordinal(), start.toordinal() + 7 * (len(skipped) + 1)))
        candidates = (start + timedelta(days=n) for n in range((end - start).days + 1))
    hour, minute = map(int, schedule['time'].split(':'))
    for day in candidates:
        stamp = datetime.combine(day, time(hour, minute), TAIPEI)
        if stamp < now or stamp.isoformat() in skipped or not matches_date(schedule, holidays, day):
            continue
        event = copy.deepcopy(schedule)
        event['datetime'] = stamp.isoformat()
        event['occurrence_id'] = schedule['id'] + '@' + event['datetime']
        return event
    return None


def prefetch_calendar_sources(schedules, now, calendar_events):
    """Warm feeds together so separate linked alarms do not download serially."""
    sources = sorted({source for row in schedules if row['enabled'] and row.get('calendar_link')
                      for source in row['calendar_link']['source_ids']})
    if not sources or not callable(calendar_events):
        return
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return  # next_occurrence retains the public timestamp validation.
    try:
        start = now.astimezone(TAIPEI).replace(hour=0, minute=0, second=0, microsecond=0)
        calendar_events(start=start, end=start + timedelta(days=1), source_ids=sources)
    except (OSError, ValueError, OverflowError):
        pass  # A failed linked source must not suppress ordinary alarms.


def next_event(schedules, holidays, now, calendar_events=None):
    schedules = list(schedules)
    prefetch_calendar_sources(schedules, now, calendar_events)
    events = (next_occurrence(schedule, holidays, now, calendar_events) for schedule in schedules)
    return min((event for event in events if event),
               key=lambda event: (event['datetime'], event['id']), default=None)
