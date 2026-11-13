"""Pure display validation shared by the web app, groups and cold restore."""
from datetime import datetime

from webclock.translations.common import SUPPORTED_LANGUAGES


DEFAULT_NIGHT = {'enabled': False, 'start': '22:00', 'end': '07:00', 'brightness': 15, 'black': False}
SETTING_FIELDS = {'mode', 'brightness', 'timezone_offset', 'language', 'time_format', 'night',
                  'show_seconds', 'show_date', 'date_format', 'show_weekday',
                  'message_duration', 'message_transition'}


def validate_time(value):
    if not isinstance(value, str) or datetime.strptime(value, '%H:%M').strftime('%H:%M') != value:
        raise ValueError('Invalid time')
    return value


def validate_settings(data):
    if not isinstance(data, dict) or set(data) - SETTING_FIELDS:
        raise ValueError('Invalid settings object')
    result = dict(data)
    for key, low, high in (('brightness', 0, 100), ('timezone_offset', -12, 14)):
        if key in result:
            value = result[key]
            if type(value) not in (int, str):
                raise ValueError('Invalid ' + key)
            result[key] = int(value)
            if not low <= result[key] <= high:
                raise ValueError('Invalid ' + key)
    if 'mode' in result and result['mode'] not in ('normal', 'black'):
        raise ValueError('Invalid display mode')
    if 'language' in result and (not isinstance(result['language'], str) or result['language'] not in SUPPORTED_LANGUAGES):
        raise ValueError('Invalid language')
    if 'time_format' in result and result['time_format'] not in ('24h', '12h'):
        raise ValueError('Invalid time format')
    for key in ('show_seconds', 'show_date', 'show_weekday'):
        if key in result and type(result[key]) is not bool:
            raise ValueError('Invalid ' + key)
    if 'date_format' in result and result['date_format'] not in ('m/d', 'd/m', 'yyyy/m/d', 'yyyy-mm-dd'):
        raise ValueError('Invalid date format')
    if 'message_duration' in result and (type(result['message_duration']) is not int
                                       or not 1 <= result['message_duration'] <= 300):
        raise ValueError('Invalid message duration')
    if 'message_transition' in result and result['message_transition'] not in ('fade', 'left', 'up'):
        raise ValueError('Invalid message transition')
    if 'night' in result:
        night = result['night']
        if not isinstance(night, dict) or set(night) != set(DEFAULT_NIGHT):
            raise ValueError('Invalid night settings')
        if type(night['enabled']) is not bool or type(night['black']) is not bool:
            raise ValueError('Invalid night switch')
        if type(night['brightness']) is not int or not 0 <= night['brightness'] <= 100:
            raise ValueError('Invalid night brightness')
        for key in ('start', 'end'):
            validate_time(night[key])
        if night['start'] == night['end']:
            raise ValueError('Night times must differ')
    return result
