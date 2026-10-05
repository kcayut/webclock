"""Shared browser alarm projection; recurrence stays in schedule_service."""
from datetime import datetime, timedelta

from webclock.services.schedule_service import TAIPEI, next_occurrence, prefetch_calendar_sources


def browser_alarm_payload(schedules, holidays, now, calendar_events=None):
    now = now.astimezone(TAIPEI)
    minute = now.replace(second=0, microsecond=0)
    rows = [row for row in schedules if row['enabled'] and row['type'] == 'alarm']
    alarms, windows = [], {}

    def lookup(start, end, source_ids):
        key = (start, end, tuple(source_ids))
        if key not in windows:
            windows[key] = calendar_events(start=start, end=end, source_ids=source_ids) if calendar_events else []
        return windows[key]

    prefetch_calendar_sources(rows, now, lookup)
    for row in rows:
        cursor = minute
        # Keep distinct linked events within the current minute.
        while len(alarms) < 1000:
            event = next_occurrence(row, holidays, cursor, lookup)
            if not event:
                break
            stamp = datetime.fromisoformat(event['datetime'])
            alarms.append(dict(occurrence_id=event['occurrence_id'], id=event['id'],
                               name=event['name'], sound=event['browser_sound'],
                               volume=event['browser_volume'], starts_at=int(stamp.timestamp() * 1000)))
            if not row.get('calendar_link') or stamp > now:
                break
            cursor = stamp + timedelta(microseconds=1)
    alarms.sort(key=lambda event: (event['starts_at'], event['id']))
    return dict(enabled_count=len(rows), enabled_ids=sorted(row['id'] for row in rows),
                alarms=alarms, holiday_coverage=holidays.coverage,
                holiday_known=holidays.get_day_type(now.date())['known'])
