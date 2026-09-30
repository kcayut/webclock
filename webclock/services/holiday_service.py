"""Offline Taiwan government work calendar shared by the UI and schedulers."""

import copy
import json
from datetime import date, timedelta
from pathlib import Path


def parse_date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('Date must use YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('Date must use YYYY-MM-DD')
    return parsed


class HolidayService:
    def __init__(self):
        path = Path(__file__).resolve().parents[1] / 'data' / 'taiwan_calendar.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        self.coverage = raw['coverage']
        self.source = raw['source']
        self.days = {}
        start, end = (parse_date(self.coverage[key]) for key in ('start', 'end'))
        makeup = set(raw['makeup_workdays'])
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            key = day.isoformat()
            holiday = key not in makeup and (key in raw['holidays'] or day.weekday() >= 5)
            self.days[key] = {
                'type': 'holiday' if holiday else 'workday',
                'name': raw['holidays'].get(key, '補班日' if key in makeup else ''),
                'makeup_workday': key in makeup,
            }

    def get_day_type(self, value):
        key = parse_date(value).isoformat()
        item = self.days.get(key)
        return {
            'date': key,
            'type': item['type'] if item else 'unknown',
            'holiday': item['type'] == 'holiday' if item else None,
            'name': item.get('name', '') if item else '',
            'makeup_workday': item.get('makeup_workday', False) if item else False,
            'known': item is not None,
        }

    def is_holiday(self, value):
        return self.get_day_type(value)['holiday']

    def is_workday(self, value):
        holiday = self.is_holiday(value)
        return not holiday if holiday is not None else None

    def export(self):
        return copy.deepcopy({
            'schema_version': 1,
            'timezone': 'Asia/Taipei',
            'coverage': self.coverage,
            'source': self.source,
            'days': self.days,
        })
