from flask import Flask, render_template, jsonify, request, redirect, url_for, abort, send_from_directory, g, session, has_request_context
from datetime import datetime, timezone, timedelta
import requests
from icalendar import Calendar
import recurring_ical_events
import json
import os
import time
import hashlib
import re
from uuid import uuid4
from math import ceil
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from dotenv import load_dotenv
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from webclock.services.storage import load_json, save_json, revision, storage_lock
from webclock.services.holiday_service import HolidayService
from webclock.services.schedule_service import TAIPEI, next_event, read_schedules, calendar_target_matches
from webclock.services.display_service import browser_alarm_payload, parse_display_window
from webclock.services.calendar_display_service import (
    validate_display_targets, display_rule, display_bounds, display_item_id,
)
from webclock.services.device_service import DeviceService
from webclock.api.device import conditional
from webclock.api import register_api
from webclock.csrf import register_csrf
from webclock.services.auth_service import AuthService
from webclock.services.display_settings import DEFAULT_NIGHT, validate_settings, validate_time
from webclock.auth import register_auth
from webclock.access_control import register_access_control
from webclock.services.device_access_service import AccessError, DeviceAccessService, calendar_content_allows
from webclock.api.groups import groups_api
from webclock.api.managed_device import managed_device_api
from webclock.ingress import IngressPathMiddleware
from webclock.translations.clock_enrollment import DEVICE_ENROLLMENT_TRANSLATIONS
from webclock.translations.common import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, UI_TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')

ICAL_URL = os.getenv('ICAL_URL', "")
STATE_DIR = Path(os.getenv('WEBCLOCK_STATE_DIR', str(ROOT / 'webclock_state')))
NOTES_FILE = os.getenv('NOTES_FILE', str(STATE_DIR / 'manual_notes.json'))
SETTINGS_FILE = str(STATE_DIR / 'settings.json')
CACHE_DURATION = 300

app = Flask(__name__, root_path=str(ROOT))
app.wsgi_app = IngressPathMiddleware(app.wsgi_app)
_auth_services = {}


def auth_service():
    path = Path(SETTINGS_FILE).parent / 'auth.json'
    key = str(path.resolve())
    if key not in _auth_services:
        _auth_services[key] = AuthService(path)
    return _auth_services[key]


# Host initialization/reset takes effect after restart; every authenticated
# request also checks the server-side session record for immediate revocation.
app.secret_key = auth_service().session_secret()
register_access_control(app, auth_service)
register_csrf(app)
register_auth(app, auth_service)
holiday_service = HolidayService()
calendar_feed_cache = {}
MAX_CALENDAR_SOURCES = 20
MAX_CALENDAR_QUERY_DAYS = 366
MAX_CALENDAR_EVENTS = 10000
MAX_CALENDAR_QUERY_CACHE = 3


@app.after_request
def add_cors_headers(response):
    # Only the public display surface is cross-origin. Management HTML includes
    # CSRF tokens, including validation-error pages returned from form actions.
    if request.endpoint not in ('index', 'status', 'public_time', 'health', 'service_worker', 'static'):
        response.headers.setdefault('Cache-Control', 'no-store')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
    if request.endpoint in ('status', 'public_time', 'health'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def deployment_language():
    language = os.getenv('WEBCLOCK_LANGUAGE', DEFAULT_LANGUAGE)
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError('WEBCLOCK_LANGUAGE must be one of: ' + ', '.join(SUPPORTED_LANGUAGES))
    return language


DEFAULT_SETTINGS = {
    'mode': 'normal',
    'brightness': 100,
    'timezone_offset': 8,
    'language': deployment_language(),
    'time_format': '24h',
}
# ponytail: single-process file storage; use a database before adding writer processes.
settings_lock = RLock()


def load_display_settings():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            saved = validate_settings(json.load(f))
    except FileNotFoundError:
        saved = {}
    return dict(DEFAULT_SETTINGS, **saved)


def save_display_settings(settings):
    save_json(SETTINGS_FILE, settings)


def migrate_notes(legacy_path):
    # Docker's old single-file bind mount cannot be replaced atomically.
    # Copy it once into the already-persistent state directory; keep the original.
    if not os.path.exists(NOTES_FILE) and os.path.isfile(legacy_path):
        with open(legacy_path, encoding='utf-8') as f:
            content = f.read()
        data = json.loads(content) if content.strip() else []
        if not isinstance(data, list):
            raise ValueError('Invalid legacy reminders')
        save_json(NOTES_FILE, data)


migrate_notes(str(ROOT / 'manual_notes.json'))

display_settings = load_display_settings()


def get_local_now():
    offset = display_settings.get('timezone_offset', 8)
    tz = timezone(timedelta(hours=offset))
    return datetime.now(tz)


def load_notes():
    with settings_lock:
        try:
            with open(NOTES_FILE, encoding='utf-8') as f:
                content = f.read()
                data = json.loads(content) if content.strip() else []
        except FileNotFoundError:
            return []
        for note in data:
            note.setdefault('due_date', '')
        return sorted(data, key=lambda note: note['due_date'] or '9999')


def save_note(text, due_date, display_start='', display_end='', display_mode='range', weekdays=None):
    with settings_lock:
        notes = load_notes()
        new_id = 1 if not notes else max(n['id'] for n in notes) + 1
        notes.append({'id': new_id, 'text': text, 'due_date': due_date,
                      'display_start': display_start, 'display_end': display_end,
                      'display_mode': display_mode, 'weekdays': weekdays or [], 'enabled': True})
        save_json(NOTES_FILE, notes)


def delete_note(note_id):
    with settings_lock:
        notes = [n for n in load_notes() if n['id'] != int(note_id)]
        save_json(NOTES_FILE, notes)


def validate_note(note):
    if not isinstance(note, dict) or set(note) - {
        'id', 'text', 'due_date', 'display_start', 'display_end', 'display_mode', 'weekdays', 'enabled'
    }:
        raise ValueError('Invalid reminder')
    if not isinstance(note.get('text'), str) or not 1 <= len(note['text'].strip()) <= 1000:
        raise ValueError('Invalid text')
    start, end = parse_display_window(note)
    due = note.get('due_date', '')
    if not isinstance(due, str):
        raise ValueError('Invalid date')
    if due:
        fmt = '%Y-%m-%d %H:%M' if len(due) > 10 else '%Y-%m-%d'
        if datetime.strptime(due, fmt).strftime(fmt) != due:
            raise ValueError('Invalid date')
    days = note.get('weekdays', [])
    if not isinstance(days, list) or len(days) > 7 or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise ValueError('Invalid weekdays')
    if type(note.get('enabled', True)) is not bool:
        raise ValueError('Invalid enabled flag')
    return dict(note, text=note['text'].strip(), due_date=due, display_start=start, display_end=end,
                display_mode=note.get('display_mode', 'range'), weekdays=sorted(set(days)),
                enabled=note.get('enabled', True))


def note_from_form(existing=None):
    note = dict(existing or {})
    note.update(display_mode=request.form.get('display_mode', 'range'),
                display_start=request.form.get('display_start', ''),
                display_end=request.form.get('display_end', ''))
    if 'note_text' in request.form:
        date = request.form.get('note_date', '')
        clock_time = request.form.get('note_time', '')
        if clock_time and not date:
            raise ValueError('Time requires a date')
        note.update(text=request.form['note_text'], due_date=date + (' ' + clock_time if clock_time else ''))
    # Old clients editing only a window preserve an existing weekday selection.
    if 'weekdays_present' in request.form:
        note['weekdays'] = [int(day) for day in request.form.getlist('weekdays')]
    if note['display_mode'] != 'daily':
        note['weekdays'] = []
    return validate_note(note)


def note_visible(note, now):
    if not note.get('enabled', True):
        return False
    start, end = parse_display_window(note)
    if note.get('display_mode') == 'daily':
        clock_time = now.strftime('%H:%M')
        # An overnight window belongs to the day it starts, even after midnight.
        anchor = now - timedelta(days=1) if start and start > end and clock_time < end else now
        if note.get('weekdays') and anchor.weekday() not in note['weekdays']:
            return False
        return not start or (start <= clock_time < end if start < end else clock_time >= start or clock_time < end)
    if start:
        return start <= now.isoformat(timespec='minutes')[:16] < end
    return not note.get('due_date') or note['due_date'].startswith(now.strftime('%Y-%m-%d'))


def next_note_time(note, now):
    if not note.get('enabled', True):
        return None
    start, _ = parse_display_window(note)
    if note.get('display_mode') == 'daily':
        if not start:
            return None
        for offset in range(8):
            day = now + timedelta(days=offset)
            if note.get('weekdays') and day.weekday() not in note['weekdays']:
                continue
            candidate = datetime.strptime(day.strftime('%Y-%m-%d') + ' ' + start, '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
            if candidate > now:
                return candidate
    else:
        due = note.get('due_date', '')
        value = due if len(due) > 10 else start.replace('T', ' ')
        if value:
            candidate = datetime.strptime(value, '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
            if candidate > now and note_visible(note, candidate):
                return candidate
    return None


def normalize_calendar_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('Invalid calendar URL')
    value = value.strip()
    if not value:
        return ''
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid calendar URL')
    parts = urlsplit(value)
    if (parts.scheme not in ('http', 'https', 'webcal') or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.fragment or '\\' in value or parts.port == 0):
        raise ValueError('Invalid calendar URL')
    return urlunsplit(parts._replace(scheme='https' if parts.scheme == 'webcal' else parts.scheme))


def calendar_provider(url):
    host = urlsplit(url).hostname or ''
    if host == 'icloud.com' or host.endswith('.icloud.com'):
        return 'apple'
    if host == 'google.com' or host.endswith('.google.com'):
        return 'google'
    return 'ics'


def validate_calendar_sources(sources, create_ids=False):
    if not isinstance(sources, list) or len(sources) > MAX_CALENDAR_SOURCES:
        raise ValueError('Invalid calendar sources')
    result = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) - {'id', 'name', 'provider', 'url', 'display_enabled'}:
            raise ValueError('Invalid calendar source')
        source_id = source.get('id', '')
        if create_ids and source_id == '':
            source_id = uuid4().hex
        if (not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', source_id)
                or source_id == 'local' or source_id in seen):
            raise ValueError('Invalid calendar source ID')
        seen.add(source_id)
        name = source.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('Invalid calendar source name')
        provider = source.get('provider', 'ics')
        if provider not in ('apple', 'google', 'ics'):
            raise ValueError('Invalid calendar provider')
        enabled = source.get('display_enabled', True)
        if type(enabled) is not bool:
            raise ValueError('Invalid calendar display flag')
        url = normalize_calendar_url(source.get('url'))
        if not url:
            raise ValueError('Missing calendar URL')
        result.append(dict(id=source_id, name=name.strip(), provider=provider, url=url,
                           display_enabled=enabled))
    return result


def load_calendar_settings():
    # Missing state keeps the old .env subscription; a saved empty list disables it.
    data = load_json(Path(SETTINGS_FILE).parent / 'calendar.json', {'url': ICAL_URL})
    if not isinstance(data, dict):
        raise ValueError('Invalid calendar settings')
    if 'sources' not in data:
        url = normalize_calendar_url(data['url'])
        provider = calendar_provider(url)
        names = {'google': 'Google Calendar', 'apple': 'Apple Calendar', 'ics': 'Calendar'}
        sources = [dict(id='legacy', name=names[provider], provider=provider, url=url,
                        display_enabled=True)] if url else []
        return dict(sources=sources, local_display_enabled=True)
    enabled = data.get('local_display_enabled', True)
    if type(enabled) is not bool:
        raise ValueError('Invalid local display flag')
    sources = validate_calendar_sources(data['sources'])
    result = dict(sources=sources, local_display_enabled=enabled)
    targets = validate_display_targets(data.get('calendar_targets', []), {source['id'] for source in sources})
    if targets:
        result['calendar_targets'] = targets
    return result


def get_calendar_sources():
    # Private server-side catalogue. Only /api/calendar may expose its URLs.
    with settings_lock:
        return load_calendar_settings()['sources']


def get_calendar_url():
    sources = get_calendar_sources()
    return sources[0]['url'] if sources else ''


def calendar_settings_response(settings):
    # Keep the old single-URL management client compatible during upgrades.
    errors = []
    for source in settings['sources']:
        cached = calendar_feed_cache.get((str(Path(SETTINGS_FILE).parent), source['url']), {})
        if cached.get('error'):
            errors.append(dict(id=source['id'], error=cached['error']))
    return dict(settings, url=settings['sources'][0]['url'] if settings['sources'] else '', errors=errors)


def calendar_event(source_id, uid, text, start, end, all_day, query_start, recurring=False, recurrence_id=''):
    zone = query_start.tzinfo
    if all_day and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time(), tzinfo=zone)
        end = datetime.combine(end, datetime.min.time(), tzinfo=zone)
    start = start.replace(tzinfo=zone) if start.tzinfo is None else start.astimezone(zone)
    end = end.replace(tzinfo=zone) if end.tzinfo is None else end.astimezone(zone)
    return dict(source_id=source_id, uid=uid, text=text, recurring=recurring, recurrence_id=recurrence_id,
                time='' if all_day or start.date() < query_start.date() else start.strftime('%H:%M'),
                starts_at=int(start.timestamp() * 1000), ends_at=int(end.timestamp() * 1000),
                all_day=all_day, start_date=start.date().isoformat(), end_date=end.date().isoformat())


def calendar_event_overlaps(event, start, end):
    first, last = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    return event['starts_at'] < last and (event['ends_at'] > first or
            (event['ends_at'] == event['starts_at'] and event['starts_at'] >= first))


def local_calendar_events(start, end, zone=None):
    events = []
    zone = zone or get_local_now().tzinfo
    for note in load_notes():
        if not note.get('enabled', True):
            continue
        try:
            due = note.get('due_date', '')
            window_start, window_end = parse_display_window(note)
            windows = []
            if note.get('display_mode') == 'daily':
                if not window_start:
                    continue
                day = (start.astimezone(zone) - timedelta(days=1)).date()
                while day <= end.astimezone(zone).date():
                    begins = datetime.strptime(day.isoformat() + ' ' + window_start, '%Y-%m-%d %H:%M').replace(tzinfo=zone)
                    finishes = datetime.strptime(day.isoformat() + ' ' + window_end, '%Y-%m-%d %H:%M').replace(tzinfo=zone)
                    if finishes <= begins:
                        finishes += timedelta(days=1)
                    if note_visible(note, begins):
                        windows.append((begins, finishes, False))
                    day += timedelta(days=1)
            elif len(due) > 10:
                begins = datetime.strptime(due, '%Y-%m-%d %H:%M').replace(tzinfo=zone)
                if note_visible(note, begins):
                    windows.append((begins, begins, False))
            elif window_start:
                begins = datetime.fromisoformat(window_start).replace(tzinfo=zone)
                finishes = datetime.fromisoformat(window_end).replace(tzinfo=zone)
                windows.append((begins, finishes, False))
            elif due:
                begins = datetime.strptime(due, '%Y-%m-%d').replace(tzinfo=zone)
                windows.append((begins, begins + timedelta(days=1), True))
            # A reminder without a date or daily window is not a scheduled event.
            for begins, finishes, all_day in windows:
                recurring = note.get('display_mode') == 'daily'
                event = calendar_event('local', str(note['id']), note['text'], begins, finishes, all_day, start,
                                       recurring, begins.date().isoformat() if recurring else '')
                if calendar_event_overlaps(event, start, end):
                    events.append(event)
        except (ValueError, TypeError, KeyError):
            continue
    return events


def check_calendar_expansion(cal, start, end):
    # Conservative upper bound before the library allocates its occurrence list.
    # BY* filters can reduce this estimate; exceeding it is an explicit limit.
    budget = 0
    periods = {'YEARLY': 365 * 86400, 'MONTHLY': 28 * 86400, 'WEEKLY': 7 * 86400,
               'DAILY': 86400, 'HOURLY': 3600, 'MINUTELY': 60, 'SECONDLY': 1}
    for component in cal.walk('VEVENT'):
        rules = component.get('rrule', [])
        rules = rules if isinstance(rules, list) else [rules]
        budget += 1
        for rule in rules:
            frequency = str(rule['FREQ'][0]).upper()
            interval = max(1, int(rule.get('INTERVAL', [1])[0]))
            duration = component.get('duration')
            duration = duration.dt.total_seconds() if duration else 0
            if component.get('dtend') is not None:
                duration = (component['dtend'].dt - component['dtstart'].dt).total_seconds()
            span = (end - start).total_seconds() + max(0, duration)
            count = ceil(span / (periods[frequency] * interval)) + 2
            day_selectors = {'BYDAY', 'BYMONTHDAY', 'BYYEARDAY', 'BYWEEKNO'} & set(rule)
            if frequency == 'YEARLY':
                days = 366 if day_selectors else len(rule.get('BYMONTH', [1]))
                if 'BYYEARDAY' in rule:
                    days = min(days, len(rule['BYYEARDAY']))
                if 'BYMONTHDAY' in rule:
                    days = min(days, len(rule['BYMONTHDAY']) * len(rule.get('BYMONTH', range(12))))
                count *= days
            elif frequency == 'MONTHLY' and day_selectors:
                days = min(31, len(rule.get('BYMONTHDAY', range(31))))
                if 'BYDAY' in rule:
                    days = min(days, sum(1 if str(day)[:-2] else 5 for day in rule['BYDAY']))
                count *= days
            elif frequency == 'WEEKLY' and 'BYDAY' in rule:
                count *= min(7, len(rule['BYDAY']))
            if periods[frequency] >= 86400:
                count *= len(rule.get('BYHOUR', [1]))
            if periods[frequency] >= 3600:
                count *= len(rule.get('BYMINUTE', [1]))
            if periods[frequency] >= 60:
                count *= len(rule.get('BYSECOND', [1]))
            budget += min(count, int(rule.get('COUNT', [count])[0]))
        for dates in ('rdate', 'exdate'):
            values = component.get(dates, [])
            values = values if isinstance(values, list) else [values]
            budget += sum(len(value.dts) for value in values)
        if budget > MAX_CALENDAR_EVENTS:
            raise OverflowError('Calendar occurrence limit exceeded')


def fetch_calendar_source(url):
    key = (str(Path(SETTINGS_FILE).parent), url)
    cached = calendar_feed_cache.get(key)
    current_time = time.time()
    if cached is not None and current_time - cached['fetched_at'] < CACHE_DURATION:
        return cached
    # Failed refreshes replace the expired feed, so it cannot trigger stale alarms.
    cached = dict(fetched_at=current_time, calendar=None, queries={}, error=None)
    calendar_feed_cache[key] = cached
    try:
        response = requests.get(url, timeout=(2, 3))
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise OverflowError('Calendar feed size limit exceeded')
        cal = Calendar.from_ical(response.content)
        if len(cal.subcomponents) > MAX_CALENDAR_EVENTS:
            raise OverflowError('Calendar component limit exceeded')
        for component in cal.walk('VEVENT'):
            if (component.get('dtstart') is None and component.get('recurrence-id') is not None
                    and str(component.get('status', '')).upper() == 'CANCELLED'):
                component['DTSTART'] = component['RECURRENCE-ID']
        cal.subcomponents = [component for component in cal.subcomponents
                             if component.name != 'VEVENT' or component.get('dtstart') is not None]
        cached['recurring_uids'] = {str(component['uid']) for component in cal.walk('VEVENT')
                                   if component.get('uid') is not None
                                   and any(key in component for key in ('rrule', 'rdate', 'recurrence-id'))}
        cached['calendar'] = cal
    except Exception as error:
        # Request errors can contain the private subscription URL; never log it.
        cached['error'] = ('event_limit' if isinstance(error, OverflowError) else
                           'fetch_failed' if isinstance(error, requests.RequestException) else 'invalid_feed')
        app.logger.warning('Calendar sync failed (%s)', type(error).__name__)
    return cached


def get_calendar_events(start=None, end=None, source_ids=None, strict=False):
    # Serialize source edits and fetches so an in-flight removed feed cannot reappear.
    with settings_lock:
        return fetch_calendar_events(start, end, source_ids, strict=strict)


def fetch_calendar_events(start=None, end=None, source_ids=None, strict=False):
    if start is None:
        start = get_local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    if not isinstance(start, datetime) or start.utcoffset() is None:
        raise ValueError('Calendar query requires a timezone')
    if end is None:
        end = start + timedelta(days=1)
    if not isinstance(end, datetime) or end.utcoffset() is None:
        raise ValueError('Calendar query requires a timezone')
    end = end.astimezone(start.tzinfo)
    if end <= start or end - start > timedelta(days=MAX_CALENDAR_QUERY_DAYS):
        raise ValueError('Invalid calendar query range')
    if source_ids is not None and (not isinstance(source_ids, (list, tuple, set))
                                  or any(not isinstance(value, str) for value in source_ids)):
        raise ValueError('Invalid calendar source selection')
    try:
        sources = get_calendar_sources()
    except (OSError, ValueError, KeyError) as error:
        if strict:
            raise AccessError('Calendar catalog is unavailable; retry later', 503, 'calendar_not_ready') from error
        app.logger.warning('Could not read calendar settings')
        sources = []
    active_keys = {(str(Path(SETTINGS_FILE).parent), source['url']) for source in sources}
    for key in list(calendar_feed_cache):
        if key not in active_keys:
            del calendar_feed_cache[key]
    selected = set(source_ids) if source_ids is not None else {
        source['id'] for source in sources if source['display_enabled']}
    if strict and selected - {source['id'] for source in sources} - {'local'}:
        raise AccessError('Calendar source is unavailable; retry later', 503, 'calendar_not_ready')
    events = local_calendar_events(start, end) if 'local' in selected else []
    selected_urls = {source['url'] for source in sources if source['id'] in selected}
    pending = [url for url in selected_urls if time.time() - calendar_feed_cache.get(
        (str(Path(SETTINGS_FILE).parent), url), {}).get('fetched_at', 0) >= CACHE_DURATION]
    if len(pending) > 1:
        # One slow provider should not serialize every other calendar download.
        with ThreadPoolExecutor(max_workers=min(MAX_CALENDAR_SOURCES, len(pending))) as pool:
            list(pool.map(fetch_calendar_source, pending))
    for source in sources:
        if source['id'] not in selected:
            continue
        cached = fetch_calendar_source(source['url'])
        if cached['calendar'] is None:
            if strict:
                raise AccessError('Calendar catalog is unavailable; retry later', 503, 'calendar_not_ready')
            continue
        query_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        query_end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        if query_end < end:
            query_end += timedelta(days=1)
        query_key = (query_start.isoformat(), query_end.isoformat(), str(start.tzinfo), strict)
        if query_key in cached['queries'] and cached['queries'][query_key] is None:
            # Preserve the original failure kind without repeating expansion or logging.
            if strict:
                raise AccessError('Calendar catalog is unavailable; retry later', 503, 'calendar_not_ready')
            continue
        try:
            if query_key not in cached['queries']:
                if len(cached['queries']) >= MAX_CALENDAR_QUERY_CACHE:
                    cached['queries'].pop(next(iter(cached['queries'])))
                # Cache failures too; a frequent poll must not repeat expensive bad queries.
                cached['queries'][query_key] = None
                check_calendar_expansion(cached['calendar'], query_start, query_end)
                components = recurring_ical_events.of(cached['calendar'], skip_bad_series=not strict).between(query_start, query_end)
                if len(components) > MAX_CALENDAR_EVENTS:
                    raise OverflowError('Calendar occurrence limit exceeded')
                cached['queries'][query_key] = components
            for component in cached['queries'][query_key]:
                if component.get('dtstart') is None or str(component.get('status', '')).upper() == 'CANCELLED':
                    continue
                begins = component['dtstart'].dt
                all_day = not isinstance(begins, datetime)
                finishes = component.get('dtend')
                finishes = finishes.dt if finishes is not None else begins + (timedelta(days=1) if all_day else timedelta())
                uid = str(component.get('uid', '')) or hashlib.sha256(component.to_ical()).hexdigest()
                recurring = uid in cached['recurring_uids']
                recurrence_id = ''
                if recurring and component.get('recurrence-id') is not None:
                    # DTSTART can move; the original recurrence ID remains the occurrence's identity.
                    original = component['recurrence-id'].dt
                    if isinstance(original, datetime) and original.utcoffset() is not None:
                        original = original.astimezone(timezone.utc)
                    recurrence_id = original.isoformat()
                event = calendar_event(source['id'], uid, str(component.get('summary', '')),
                                       begins, finishes, all_day, start, recurring, recurrence_id)
                if calendar_event_overlaps(event, start, end):
                    events.append(event)
        except Exception as error:
            cached['queries'][query_key] = None
            cached['error'] = 'event_limit' if isinstance(error, OverflowError) else 'invalid_feed'
            if strict:
                raise AccessError('Calendar catalog is unavailable; retry later', 503, 'calendar_not_ready') from error
            app.logger.warning('Calendar events failed (%s)', type(error).__name__)
    return sorted(events, key=lambda event: (event['starts_at'], event['source_id'], event['uid']))


def template_context():
    language = display_settings.get('language', DEFAULT_SETTINGS['language'])
    if has_request_context():
        language = session.get('management_language', language)
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_SETTINGS['language']
    return {
        'app_base': request.script_root.rstrip('/') if has_request_context() else '',
        'display_only': has_request_context() and request.environ.get('webclock.surface') == 'display',
        'language': language,
        'time_format': display_settings.get('time_format', '24h'),
        'languages': SUPPORTED_LANGUAGES,
        'translations': {code: UI_TRANSLATIONS[code] for code in SUPPORTED_LANGUAGES},
    }


@app.route('/')
def index():
    context = template_context()
    # A management preference must never change the clock's initial language.
    context['language'] = display_settings.get('language', DEFAULT_SETTINGS['language'])
    context['deployment_mode'] = 'managed' if context['display_only'] else getattr(g, 'deployment_mode', 'recovery')
    context['device_enrollment_translations'] = DEVICE_ENROLLMENT_TRANSLATIONS
    if getattr(g, 'deployment_mode', 'self') != 'self':
        # Cacheable clock HTML never embeds private account display settings.
        context.update(language=DEFAULT_SETTINGS['language'], time_format='24h')
    keys = ('app_title', 'loading', 'notice_close', 'weekdays', 'page_error',
            'status_parse_failed', 'server_unavailable', 'server_timeout',
            'offline_ready', 'offline_unavailable', 'offline_failed', 'save', 'add', 'delete')
    context['translations'] = {
        language: {key: value for key, value in pack.items() if key in keys or key.startswith(('alarm_', 'connection_', 'local_reminder'))}
        for language, pack in context['translations'].items()
    }
    return render_template('index.html', **context)


@app.route('/admin')
def admin(error=None, editing_id=None):
    return render_template(
        'admin.html',
        notes=load_notes(),
        settings={'night': DEFAULT_NIGHT, **display_settings},
        error=error,
        editing_id=editing_id,
        **template_context()
    )


@app.route('/api/control', methods=['POST'])
def control():
    try:
        changes = validate_settings(request.get_json())
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid settings'}), 400
    with settings_lock:
        updated = dict(display_settings, **changes)
        try:
            save_display_settings(updated)
        except OSError:
            app.logger.exception('Could not save display settings')
            return jsonify({'error': 'Could not save settings'}), 500
        display_settings.update(updated)
        return jsonify({'status': 'ok', 'settings': display_settings})


@app.route('/api/calendar', methods=['GET', 'POST', 'PATCH'])
def calendar_settings():
    if request.headers.get('Origin', request.host_url.rstrip('/')) != request.host_url.rstrip('/'):
        abort(403)
    with settings_lock:
        try:
            current = load_calendar_settings()
        except (OSError, ValueError, KeyError):
            return jsonify(error='load_failed'), 500
        if request.method == 'GET':
            return jsonify(calendar_settings_response(current))
        data = request.get_json(silent=True)
        try:
            if not isinstance(data, dict):
                raise ValueError('Invalid calendar settings')
            if request.method == 'PATCH':
                if not data or set(data) - {'local_display_enabled', 'sources', 'calendar_targets'}:
                    raise ValueError('Invalid visibility settings')
                updated = current
                changes = data.get('sources', [])
                if not isinstance(changes, list) or len(changes) > MAX_CALENDAR_SOURCES:
                    raise ValueError('Invalid visibility sources')
                by_id = {source['id']: source for source in updated['sources']}
                seen = set()
                for change in changes:
                    if (not isinstance(change, dict) or set(change) != {'id', 'display_enabled'}
                            or not isinstance(change['id'], str) or change['id'] not in by_id
                            or change['id'] in seen or type(change['display_enabled']) is not bool):
                        raise ValueError('Invalid visibility source')
                    seen.add(change['id'])
                    by_id[change['id']]['display_enabled'] = change['display_enabled']
            elif set(data) == {'url'}:
                # A legacy client edits the first subscription without deleting later sources.
                updated = current
                url = normalize_calendar_url(data['url'])
                if url and updated['sources']:
                    updated['sources'][0]['url'] = url
                elif url:
                    updated['sources'] = [dict(id='legacy', name='Calendar', provider=calendar_provider(url),
                                               url=url, display_enabled=True)]
                elif updated['sources']:
                    updated['sources'].pop(0)
            else:
                if 'sources' not in data or set(data) - {'sources', 'local_display_enabled', 'url', 'errors', 'calendar_targets'}:
                    raise ValueError('Invalid calendar settings')
                updated = dict(sources=validate_calendar_sources(data['sources'], create_ids=True),
                               local_display_enabled=current['local_display_enabled'])
            source_ids = {source['id'] for source in updated['sources']}
            targets = data.get('calendar_targets', [target for target in current.get('calendar_targets', [])
                                                    if target['source_id'] in source_ids])
            targets = validate_display_targets(targets, source_ids)
            if targets:
                updated['calendar_targets'] = targets
            else:
                updated.pop('calendar_targets', None)
            if 'local_display_enabled' in data:
                if type(data['local_display_enabled']) is not bool:
                    raise ValueError('Invalid local display flag')
                updated['local_display_enabled'] = data['local_display_enabled']
        except (ValueError, TypeError):
            return jsonify(error='invalid_url' if isinstance(data, dict) and set(data) == {'url'} else 'invalid_settings'), 400
        try:
            save_json(Path(SETTINGS_FILE).parent / 'calendar.json', updated)
        except OSError:
            return jsonify(error='save_failed'), 500
        return jsonify(status='ok', **calendar_settings_response(updated))


@app.route('/add', methods=['POST'])
def add():
    try:
        note = note_from_form()
    except (ValueError, TypeError):
        return admin(error='window_error'), 400
    save_note(note['text'], note['due_date'], note['display_start'], note['display_end'],
              note['display_mode'], note['weekdays'])
    return redirect(url_for('admin', _anchor='calendar-title'))


@app.route('/schedule/<int:id>', methods=['POST'])
def schedule(id):
    with settings_lock:
        notes = load_notes()
        note = next((note for note in notes if note['id'] == id), None)
        if note is None:
            abort(404)
        try:
            updated = note_from_form(note)
        except (ValueError, TypeError):
            return admin(error='window_error', editing_id=id), 400
        note.update(updated)
        save_json(NOTES_FILE, notes)
    return redirect(url_for('admin', _anchor='calendar-title'))


@app.route('/toggle/<int:id>', methods=['POST'])
def toggle(id):
    with settings_lock:
        notes = load_notes()
        note = next((note for note in notes if note['id'] == id), None)
        if note is None:
            abort(404)
        note['enabled'] = not note.get('enabled', True)
        save_json(NOTES_FILE, notes)
    return redirect(url_for('admin', _anchor='calendar-title'))


@app.route('/api/backup', methods=['GET', 'POST'])
def backup():
    if request.headers.get('Origin', request.host_url.rstrip('/')) != request.host_url.rstrip('/'):
        abort(403)
    with settings_lock:
        if request.method == 'GET':
            response = jsonify(version=1, settings=display_settings, notes=load_notes())
            response.headers['Content-Disposition'] = 'attachment; filename="webclock-backup.json"'
            response.headers['Cache-Control'] = 'no-store'
            return response
        if request.content_length is None or request.content_length > 1024 * 1024:
            return jsonify(error='Backup too large'), 413
        try:
            data = request.get_json()
            if not isinstance(data, dict) or set(data) != {'version', 'settings', 'notes'} or type(data['version']) is not int or data['version'] != 1:
                raise ValueError('Unknown backup format')
            settings = dict(DEFAULT_SETTINGS, **validate_settings(data['settings']))
            if not {'mode', 'brightness', 'timezone_offset', 'language'} <= set(data['settings']):
                raise ValueError('Incomplete settings')
            if not isinstance(data['notes'], list) or len(data['notes']) > 1000:
                raise ValueError('Invalid notes')
            notes = [validate_note(note) for note in data['notes']]
            ids = [note.get('id') for note in notes]
            if any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Invalid reminder IDs')
        except (ValueError, TypeError, KeyError):
            return jsonify(error='Invalid backup'), 400
        previous_notes = load_notes()
        try:
            # Retain the previous data even if interrupted between the two file replacements.
            save_json(os.path.join(os.path.dirname(SETTINGS_FILE), 'before-import.json'),
                      dict(version=1, settings=display_settings, notes=previous_notes))
            save_json(NOTES_FILE, notes)
            try:
                save_display_settings(settings)
            except OSError:
                save_json(NOTES_FILE, previous_notes)
                raise
        except OSError:
            app.logger.exception('Backup restore failed; previous data retained in before-import.json')
            return jsonify(error='Could not restore backup'), 500
        display_settings.clear()
        display_settings.update(settings)
        return jsonify(status='ok')


@app.route('/sw.js')
def service_worker():
    response = send_from_directory(app.root_path, 'sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    delete_note(id)
    return redirect(url_for('admin', _anchor='calendar-title'))


def calendar_selected_occurrence(target, settings, zone, strict=False):
    """Locate an exact saved occurrence beyond the catalog horizon, then use the normal expander."""
    source = next((row for row in settings['sources'] if row['id'] == target['source_id']), None)
    if source is None:
        return []
    with settings_lock:
        cached = fetch_calendar_source(source['url'])
        if cached['calendar'] is None:
            if strict:
                raise AccessError('Calendar catalog is unavailable; retry later', 503, 'calendar_not_ready')
            return []
        recurrence_id = target.get('recurrence_id', '')
        anchor = None
        if recurrence_id:
            try:
                anchor = datetime.fromisoformat(recurrence_id)
            except ValueError:
                return []
        for component in cached['calendar'].walk('VEVENT'):
            if str(component.get('uid', '')) != target['uid']:
                continue
            original = component.get('recurrence-id')
            if original is not None:
                original = original.dt
                if isinstance(original, datetime) and original.utcoffset() is not None:
                    original = original.astimezone(timezone.utc)
                if original.isoformat() != recurrence_id:
                    continue
            elif recurrence_id or target['uid'] in cached['recurring_uids']:
                continue
            if str(component.get('status', '')).upper() == 'CANCELLED':
                return []
            begins = component.get('dtstart')
            if begins is not None:
                anchor = begins.dt
            break
        if anchor is None:
            return []
        if not isinstance(anchor, datetime):
            anchor = datetime.combine(anchor, datetime.min.time())
        anchor = anchor.replace(tzinfo=zone) if anchor.tzinfo is None else anchor.astimezone(zone)
        start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
        return [event for event in get_calendar_events(start=start, end=start + timedelta(days=1),
                source_ids=[target['source_id']], strict=strict) if calendar_target_matches(event, target)]


def calendar_display_events(now, settings, whole_sources=None, targets=None, exclusions=None):
    """Apply selection and display windows after fetching raw alarm-compatible events."""
    rules = settings.get('calendar_targets', [])
    if whole_sources is None and not rules:
        return get_calendar_events()  # Preserve legacy whole-source and multi-day display.
    whole = set(whole_sources if whole_sources is not None else
                [source['id'] for source in settings['sources'] if source['display_enabled']])
    selected = targets if targets is not None else rules
    sources = sorted(whole | {target['source_id'] for target in selected})
    if not sources:
        return []
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    events = get_calendar_events(start=start, end=end, source_ids=sources)
    base_keys = {(event.get('source_id'), event.get('uid'), event.get('recurrence_id', '')) for event in events}
    relevant = [rule for rule in rules if rule['source_id'] in sources]
    management_now = get_local_now()
    management_start = management_now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = max([1] + [ceil(rule['display_window'].get('before_minutes', 0) / 1440) + 1
                     if rule['display_window']['mode'] != 'absolute' else 1 for rule in relevant])
    if relevant and (days > 1 or management_start != start):
        events += get_calendar_events(start=management_start, end=management_start + timedelta(days=days),
                                      source_ids=sorted({rule['source_id'] for rule in relevant}))
    # Absolute windows need the actual selected occurrence even when it is years away.
    for rule in relevant:
        window = rule['display_window']
        if window['mode'] == 'absolute' and window['start'] <= management_now.isoformat(timespec='minutes')[:16] < window['end']:
            events += calendar_selected_occurrence(rule, settings, management_now.tzinfo)
    if (management_now - management_start < timedelta(minutes=1)
            and any(rule['display_window'].get('end') == 'event_end' for rule in relevant)):
        events += get_calendar_events(start=management_start - timedelta(minutes=1), end=management_start,
                                      source_ids=sorted({rule['source_id'] for rule in relevant}))
    unique, visible = {}, []
    grants = dict(calendar_source_ids=whole, calendar_targets=selected, calendar_exclusions=exclusions or [])
    for event in events:
        if not calendar_content_allows(grants, event):
            continue
        key = (event.get('source_id'), event.get('uid'), event.get('recurrence_id', ''))
        unique[key] = event
    for event in unique.values():
        rule = display_rule(event, relevant)
        if rule:
            first, last = display_bounds(event, rule, management_now.tzinfo)
            if not first <= int(now.timestamp() * 1000) < last:
                continue
        elif (event.get('source_id'), event.get('uid'), event.get('recurrence_id', '')) not in base_keys:
            continue
        event = dict(event)
        begins = datetime.fromtimestamp(event['starts_at'] / 1000, now.tzinfo)
        event['time'] = '' if event.get('all_day') or begins.date() < now.date() else begins.strftime('%H:%M')
        visible.append(event)
    return sorted(visible, key=lambda event: (event['starts_at'], event['source_id'], event['uid']))


@app.route('/api/calendar/display-items')
def calendar_display_items():
    """Management projection includes future selections, never subscription URLs."""
    try:
        settings = load_calendar_settings()
        now = get_local_now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=366)
        rules = settings.get('calendar_targets', [])
        whole = {source['id'] for source in settings['sources'] if source['display_enabled']}
        sources = sorted(whole | {target['source_id'] for target in rules})
        events = get_calendar_events(start=start, end=end, source_ids=sources, strict=True) if sources else []
        # Saved single occurrences remain editable outside the rolling year catalog.
        for rule in rules:
            if rule['scope'] == 'occurrence' and not any(calendar_target_matches(event, rule) for event in events):
                events += calendar_selected_occurrence(rule, settings, now.tzinfo, strict=True)
        names = {source['id']: source['name'] for source in settings['sources']}
        items, found = [], set()
        for event in events:
            rule = display_rule(event, rules)
            if event['source_id'] not in whole and rule is None:
                continue
            for index, candidate in enumerate(rules):
                if calendar_target_matches(event, candidate):
                    found.add(index)
            window = dict(rule['display_window']) if rule else {'mode': 'day'}
            target = dict(source_id=event['source_id'], uid=event['uid'], scope='occurrence',
                          recurrence_id=event.get('recurrence_id', ''), title=event['text'][:500], display_window=window)
            series = next((value for value in rules if value['scope'] == 'series' and calendar_target_matches(event, value)), None)
            series_target = (dict(source_id=event['source_id'], uid=event['uid'], scope='series', recurrence_id='',
                                  title=event['text'][:500], display_window=dict(series['display_window']) if series else {'mode': 'day'})
                             if event.get('recurring') else None)
            first, last = display_bounds(event, target, now.tzinfo)
            if rule is None:
                # Whole-source legacy events remain visible on every overlapping day.
                first_day = datetime.fromtimestamp(event['starts_at'] / 1000, now.tzinfo).replace(hour=0, minute=0, second=0, microsecond=0)
                last_day = datetime.fromtimestamp(max(event['starts_at'], event['ends_at'] - 1) / 1000, now.tzinfo).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                first, last = int(first_day.timestamp() * 1000), int(last_day.timestamp() * 1000)
            items.append(dict(id=display_item_id(target), target=target, series_target=series_target,
                              source_name=names[event['source_id']], text=event['text'],
                              starts_at=event['starts_at'], ends_at=event['ends_at'], all_day=event['all_day'],
                              recurring=event.get('recurring', False), selection_scope=rule['scope'] if rule else 'source',
                              window_start=first, window_end=last, visible=first <= int(now.timestamp() * 1000) < last,
                              status='ready'))
        def missing_item(rule):
            return dict(id=display_item_id(rule), target=rule, series_target=rule if rule['scope'] == 'series' else None,
                        source_name=names[rule['source_id']], text=rule.get('title') or rule['uid'],
                        starts_at=None, ends_at=None, all_day=False, recurring=rule['scope'] == 'series',
                        selection_scope=rule['scope'], window_start=None, window_end=None, visible=False, status='missing')
        for index, rule in enumerate(rules):
            if index not in found:
                items.append(missing_item(rule))
        expanded = items
        items = [item for item in expanded if item['status'] == 'missing'
                 or item['selection_scope'] != 'series' or item['target']['source_id'] in whole]
        stamp = int(now.timestamp() * 1000)
        for rule in rules:
            if rule['scope'] != 'series' or rule['source_id'] in whole:
                continue
            candidates = [item for item in expanded if item['status'] == 'ready' and item['selection_scope'] == 'series'
                          and calendar_target_matches(item['target'], rule)]
            if not candidates:
                if not any(item['id'] == display_item_id(rule) for item in items):
                    items.append(missing_item(rule))
                continue
            def order(item):
                current = item['starts_at'] <= stamp < max(item['ends_at'], item['starts_at'] + 60000)
                return (0 if current else 1 if item['starts_at'] >= stamp else 2, item['starts_at'])
            item = dict(min(candidates, key=order), id=display_item_id(rule), target=rule, series_target=rule,
                        selection_scope='series')
            first, last = display_bounds(item, rule, now.tzinfo)
            item.update(window_start=first, window_end=last, visible=first <= stamp < last)
            items.append(item)
        items.sort(key=lambda item: (item['starts_at'] is None, item['starts_at'] or 0, item['id']))
        selectors = []
        for item in items:
            for key in ('target', 'series_target'):
                if item[key] is not None:
                    selectors.append(dict(kind='calendar', target={field: value for field, value in item[key].items()
                                                                  if field != 'display_window'}))
        memberships = iter(group_service().item_assignments(group_owner(), selectors))
        for item in items:
            item['assignment'] = next(memberships)
            item['series_assignment'] = next(memberships) if item['series_target'] is not None else None
        response = jsonify(items=items, server_time=now.isoformat(), range_start=start.isoformat(), range_end=end.isoformat())
        response.headers['Cache-Control'] = 'no-store'
        return response
    except AccessError as error:
        return jsonify(error=str(error), code=error.code), error.status
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return jsonify(error='Calendar catalog is unavailable; retry later', code='calendar_not_ready'), 503


def display_snapshot(now, notes, schedules, calendar, calendar_lookup):
    events, upcoming = [], []
    for note in notes:
        try:
            if note_visible(note, now):
                due = note.get('due_date', '')
                events.append({'text': note['text'], 'time': due[11:] if len(due) > 10 else '',
                               '_sort': (due + ' 99:99' if len(due) == 10 else due) or '9999'})
            candidate = next_note_time(note, now)
            if candidate:
                upcoming.append({'text': note['text'], 'starts_at': int(candidate.timestamp() * 1000)})
        except (ValueError, TypeError):
            continue
    smart = next_event(schedules, holiday_service, now.astimezone(TAIPEI), calendar_lookup)
    if smart:
        upcoming.append({'text': smart['name'], 'starts_at': int(datetime.fromisoformat(smart['datetime']).timestamp() * 1000)})
    for event in calendar:
        if not event.get('all_day') and (event.get('starts_at') or 0) > int(now.timestamp() * 1000):
            upcoming.append({'text': event['text'], 'starts_at': event['starts_at']})
    events = [{'text': event['text'], 'time': event['time'],
               '_sort': datetime.fromtimestamp(event['starts_at'] / 1000, now.tzinfo).strftime(
                   '%Y-%m-%d 99:99' if event.get('all_day') else '%Y-%m-%d %H:%M')}
              for event in calendar] + events
    events.sort(key=lambda event: event['_sort'])
    for event in events:
        del event['_sort']
    return dict(events=events, next_event=min(upcoming, key=lambda event: event['starts_at'], default=None),
                is_holiday=holiday_service.is_holiday(now.date()))


@app.route('/api/status')
def status():
    if getattr(g, 'deployment_mode', 'self') != 'self':
        return jsonify(server_timestamp=int(time.time() * 1000), events=[], next_event=None)
    now = get_local_now()
    try:
        calendar_settings = load_calendar_settings()
        show_local = calendar_settings['local_display_enabled']
    except (OSError, ValueError, KeyError):
        show_local = True
        calendar_settings = {'sources': [], 'local_display_enabled': True}
    payload = display_snapshot(now, load_notes() if show_local else [],
                               read_schedules(Path(SETTINGS_FILE).parent), calendar_display_events(now, calendar_settings), get_calendar_events)
    # Calendar I/O may take time; send a fresh timestamp after projection.
    return jsonify(dict(payload, settings=display_settings, server_timestamp=int(get_local_now().timestamp() * 1000)))


@app.route('/api/time')
def public_time():
    return jsonify(server_timestamp=int(time.time() * 1000))


@app.route('/api/health')
def health():
    mode = getattr(g, 'deployment_mode', 'recovery')
    if mode == 'recovery':
        return jsonify(status='recovery_required'), 503
    return jsonify(status='ok', auth_schema=1, deployment_mode=mode,
                   device_schema=2, managed_device_schema=3,
                   managed_devices_ready=True)


@app.route('/api/management/language', methods=['POST'])
def management_language():
    data = request.get_json()
    if (not isinstance(data, dict) or set(data) != {'language'}
            or not isinstance(data['language'], str) or data['language'] not in SUPPORTED_LANGUAGES):
        return jsonify(error='invalid_language'), 400
    session['management_language'] = data['language']
    return jsonify(language=data['language'])


def group_service():
    identity = auth_service()
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        identity.ensure_initialized()
    return DeviceAccessService(
        Path(SETTINGS_FILE).parent / 'device-access.json',
        identity.invite_secret(), validate_settings,
        lambda: dict(display_settings, night=dict(DEFAULT_NIGHT, **display_settings.get('night', {}))),
        group_content_catalog)


def group_content_catalog():
    calendar = load_calendar_settings()
    notes = load_notes()
    schedules = read_schedules(Path(SETTINGS_FILE).parent)
    return {
        'calendar_source_ids': [source['id'] for source in calendar['sources']],
        'manual_note_ids': [note['id'] for note in notes],
        'schedules': schedules,
        'default_content': {
            'calendar_source_ids': [source['id'] for source in calendar['sources'] if source['display_enabled']],
            'manual_note_ids': [note['id'] for note in notes] if calendar['local_display_enabled'] else [],
            'schedule_ids': [row['id'] for row in schedules],
            **({'calendar_targets': [{key: value for key, value in target.items() if key != 'display_window'}
                                     for target in calendar['calendar_targets']]} if calendar.get('calendar_targets') else {}),
        },
    }


def group_owner():
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        auth_service().ensure_initialized()
    return getattr(g, 'owner_id', None) or auth_service().owner_id()


def group_ui_catalog():
    return dict(calendar_sources=[{'id': row['id'], 'name': row['name']} for row in get_calendar_sources()],
                manual_notes=[{'id': row['id'], 'text': row['text']} for row in load_notes()],
                schedules=[{'id': row['id'], 'name': row['name']} for row in read_schedules(Path(SETTINGS_FILE).parent)],
                defaults=dict(display_settings, night=dict(DEFAULT_NIGHT, **display_settings.get('night', {}))))


def device_service():
    return DeviceService(Path(SETTINGS_FILE).parent / 'devices.json')


def managed_content(identity):
    """Resolve references on the server; a deleted dependency grants no fallback."""
    with storage_lock:
        group = group_service().get_group(identity['owner_id'], identity['group_id'])
        content = group['content']
        all_notes = load_notes()
        notes = [row for row in all_notes if row['id'] in content['manual_note_ids']]
        calendar_settings = load_calendar_settings()
        source_rows = calendar_settings['sources']
        sources = {row['id'] for row in source_rows}
        schedules = [row for row in read_schedules(Path(SETTINGS_FILE).parent)
                     if row['id'] in content['schedule_ids']
                     and not set((row.get('calendar_link') or {}).get('source_ids', [])) - (sources | {'local'})]
        needed = set(content['calendar_source_ids']) | {
            target['source_id'] for target in content.get('calendar_targets', [])} | {
            source for row in schedules for source in (row.get('calendar_link') or {}).get('source_ids', [])}
        # This server-only digest detects deletion/replacement during calendar I/O.
        dependencies = [[row for row in source_rows if row['id'] in needed],
                        all_notes if 'local' in needed else []]
        rules = [target for target in calendar_settings.get('calendar_targets', []) if target['source_id'] in needed]
        # Management display rules/timezone can change while calendar I/O is running.
        if rules:
            dependencies += [rules, display_settings.get('timezone_offset', 8)]
        source_revision = revision(dependencies)
        return group, notes, schedules, source_revision


def managed_calendar_events(start, end, source_ids):
    # Linked local reminders keep the scheduler's Asia/Taipei semantics even if
    # a group's display timezone differs. Display selection is independent.
    external = [value for value in source_ids if value != 'local']
    events = get_calendar_events(start=start, end=end, source_ids=external) if external else []
    if 'local' in source_ids:
        events += local_calendar_events(start, end, zone=TAIPEI)
    return events


def managed_response(identity, group, notes, schedules, source_revision, payload):
    current_group, current_notes, current_schedules, current_sources = managed_content(identity)
    if (group['effective_settings'] != current_group['effective_settings']
            or group['content'] != current_group['content'] or notes != current_notes
            or schedules != current_schedules or source_revision != current_sources):
        raise AccessError('Display scope changed during request', 409, 'display_scope_changed')
    scope = identity['identity_revision']
    payload.update(schema_version=3, identity=identity,
                   config_revision=revision([scope, group['effective_settings']]),
                   schedule_revision=revision([scope, group['content'], notes, schedules, source_revision]),
                   holiday_revision=revision(holiday_service.export()))
    # Exclude only time and lease from ETag; visible events still change it.
    digest = revision(payload)
    stamp = int(time.time() * 1000)
    payload.update(server_timestamp=stamp, lease={'issued_at': stamp, 'expires_at': stamp + 300000})
    response = conditional(payload, digest)
    response.headers['X-WebClock-Server-Timestamp'] = str(stamp)
    response.headers['X-WebClock-Lease-Expires-At'] = str(stamp + 300000)
    response.headers['X-WebClock-Identity-Revision'] = scope
    response.headers['Vary'] = 'Cookie, Authorization'
    return response


def managed_display(identity):
    group, notes, schedules, source_revision = managed_content(identity)
    settings = group['effective_settings']
    now = datetime.now(timezone(timedelta(hours=settings['timezone_offset'])))
    calendar = calendar_display_events(now, load_calendar_settings(),
                                       group['content']['calendar_source_ids'],
                                       group['content'].get('calendar_targets', []),
                                       group['content'].get('calendar_exclusions', []))
    payload = display_snapshot(now, notes, schedules, calendar, managed_calendar_events)
    payload['settings'] = settings
    return managed_response(identity, group, notes, schedules, source_revision, payload)


def managed_alarms(identity):
    group, notes, schedules, source_revision = managed_content(identity)
    payload = browser_alarm_payload(schedules, holiday_service, datetime.now(TAIPEI), managed_calendar_events)
    return managed_response(identity, group, notes, schedules, source_revision, payload)


register_api(app, lambda: Path(SETTINGS_FILE).parent, holiday_service, template_context,
             calendar_events=lambda **query: get_calendar_events(**query),
             calendar_sources=lambda: get_calendar_sources(), device_access=group_service, owner_id=group_owner)
app.register_blueprint(groups_api(group_service, group_owner, group_ui_catalog, lambda: device_service().list()))
app.register_blueprint(managed_device_api(group_service, device_service, auth_service, managed_display, managed_alarms))


def main():
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    app.run(host=host, port=port)
