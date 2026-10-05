"""Display-only calendar selectors and windows; alarm event times stay untouched."""
from datetime import datetime, timedelta
import hashlib
import json

from .schedule_service import calendar_target_matches, validate_calendar_target
from .display_service import parse_display_window


def target_key(target):
    return (target['source_id'], target['uid'], target['scope'], target.get('recurrence_id', ''))


def validate_display_targets(values, sources):
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError('Invalid calendar display targets')
    result = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('Invalid calendar display target')
        target = validate_calendar_target({key: item for key, item in value.items() if key != 'display_window'}, sources)
        window = value.get('display_window', {'mode': 'day'})
        if not isinstance(window, dict):
            raise ValueError('Invalid calendar display window')
        mode = window.get('mode')
        if mode == 'day' and set(window) == {'mode'}:
            pass
        elif mode == 'relative' and set(window) == {'mode', 'before_minutes', 'end'}:
            if (type(window['before_minutes']) is not int or not 0 <= window['before_minutes'] <= 525600
                    or window['end'] not in ('event_end', 'day_end')):
                raise ValueError('Invalid relative display window')
        elif mode == 'absolute' and set(window) == {'mode', 'start', 'end'} and target['scope'] == 'occurrence':
            if not isinstance(window['start'], str) or not isinstance(window['end'], str) or not window['start'] or not window['end']:
                raise ValueError('Invalid absolute display window')
            parse_display_window(dict(display_start=window['start'], display_end=window['end']))
        else:
            raise ValueError('Invalid calendar display window')
        target['display_window'] = dict(window)
        result[target_key(target)] = target
    return [result[key] for key in sorted(result)]


def display_rule(event, targets):
    matches = [target for target in targets if calendar_target_matches(event, target)]
    return next((target for target in matches if target['scope'] == 'occurrence'), matches[0] if matches else None)


def display_bounds(event, rule, zone):
    """Return absolute half-open bounds, interpreted in the management display zone."""
    window = rule.get('display_window', {'mode': 'day'})
    start = datetime.fromtimestamp(event['starts_at'] / 1000, zone)
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if window['mode'] == 'day':
        first, last = midnight, midnight + timedelta(days=1)
    elif window['mode'] == 'absolute':
        first = datetime.fromisoformat(window['start']).replace(tzinfo=zone)
        last = datetime.fromisoformat(window['end']).replace(tzinfo=zone)
    else:
        first = start - timedelta(minutes=window['before_minutes'])
        event_end = datetime.fromtimestamp(event['ends_at'] / 1000, zone)
        last = ((event_end if event_end > start else start + timedelta(minutes=1))
                if window['end'] == 'event_end' else midnight + timedelta(days=1))
    return int(first.timestamp() * 1000), int(last.timestamp() * 1000)


def display_item_id(target):
    identity = target_key(target)
    return 'calendar-' + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
