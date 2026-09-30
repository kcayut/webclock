"""Run with: python -m unittest discover -s tests -p test_schedules.py"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from webclock.services.holiday_service import HolidayService
from webclock.services.schedule_service import TAIPEI, next_event, next_occurrence, validate_schedule


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holidays = HolidayService()

    def schedule(self, **changes):
        return validate_schedule({'id': 'wake', 'name': '上班起床', 'time': '07:30', **changes})

    def next(self, schedule, stamp):
        return next_occurrence(schedule, self.holidays, datetime.fromisoformat(stamp))

    def test_holidays_makeup_and_coverage(self):
        for day in ('2023-09-23', '2024-02-17', '2025-02-08'):
            self.assertTrue(self.holidays.is_workday(day))
            self.assertTrue(self.holidays.get_day_type(day)['makeup_workday'])
        for day in ('2026-09-25', '2026-09-26', '2026-09-28', '2027-12-31'):
            self.assertTrue(self.holidays.is_holiday(day))
        self.assertTrue(self.holidays.is_workday('2026-09-23'))
        self.assertIsNone(self.holidays.is_holiday('2028-01-03'))
        self.assertEqual(self.holidays.get_day_type('2028-01-03')['type'], 'unknown')

    def test_calendar_export_is_complete_and_cannot_mutate_server(self):
        snapshot = self.holidays.export()
        self.assertEqual(snapshot['timezone'], 'Asia/Taipei')
        self.assertEqual(snapshot['coverage'], {'start': '2023-01-01', 'end': '2027-12-31'})
        self.assertEqual(len(snapshot['days']), 1826)
        del snapshot['days']['2026-09-23']
        self.assertTrue(self.holidays.is_workday('2026-09-23'))

    def test_rules_and_midnight(self):
        now = '2026-09-24T08:00:00+08:00'
        work = self.schedule(rule={'workday_only': True})
        self.assertEqual(self.next(work, now)['datetime'], '2026-09-29T07:30:00+08:00')
        holiday = self.schedule(rule={'holiday_only': True})
        self.assertEqual(self.next(holiday, now)['datetime'], '2026-09-25T07:30:00+08:00')
        weekly = self.schedule(rule={'weekdays': [1, 3, 5]})
        self.assertEqual(self.next(weekly, now)['datetime'], '2026-09-25T07:30:00+08:00')
        dated = self.schedule(rule={'dates': ['2030-10-03']})
        self.assertEqual(self.next(dated, now)['datetime'], '2030-10-03T07:30:00+08:00')
        midnight = self.schedule(time='00:00')
        self.assertEqual(self.next(midnight, '2026-09-23T23:59:59+08:00')['datetime'], '2026-09-24T00:00:00+08:00')
        self.assertIsNone(self.next(work, '2028-01-03T00:00:00+08:00'))

    def test_skip_multiple_occurrences_without_disabling(self):
        schedule = self.schedule(rule={'workday_only': True})
        now = '2026-09-23T07:00:00+08:00'
        first = self.next(schedule, now)
        schedule['skipped_occurrences'].append(first['datetime'])
        second = self.next(schedule, now)
        schedule['skipped_occurrences'].append(second['datetime'])
        third = self.next(schedule, now)
        self.assertEqual(first['occurrence_id'], 'wake@2026-09-23T07:30:00+08:00')
        self.assertEqual(second['datetime'], '2026-09-24T07:30:00+08:00')
        self.assertEqual(third['datetime'], '2026-09-29T07:30:00+08:00')
        self.assertTrue(schedule['enabled'])

    def test_exact_time_timezone_disable_and_once_exhaustion(self):
        now = datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc)
        event = next_event([self.schedule()], self.holidays, now)
        self.assertEqual(event['datetime'], '2026-09-23T07:30:00+08:00')
        self.assertEqual(next_event([self.schedule()], self.holidays, now + timedelta(seconds=1))['datetime'], '2026-09-24T07:30:00+08:00')
        self.assertIsNone(next_event([self.schedule(enabled=False)], self.holidays, now))
        self.assertIsNone(next_event([self.schedule(rule={'dates': ['2026-09-22']})], self.holidays, now))
        with self.assertRaises(ValueError):
            next_event([self.schedule()], self.holidays, now.replace(tzinfo=None))

    def test_browser_sound_and_holiday_exclusion(self):
        self.assertEqual(self.schedule()['browser_sound'], 'bell')
        self.assertFalse(self.schedule()['skip_holidays'])
        for sound in ('bell', 'beep', 'digital', 'silent'):
            self.assertEqual(self.schedule(browser_sound=sound)['browser_sound'], sound)
        daily = self.schedule(skip_holidays=True)
        self.assertEqual(self.next(daily, '2026-09-24T08:00:00+08:00')['datetime'], '2026-09-29T07:30:00+08:00')
        weekly = self.schedule(rule={'weekdays': [5]}, skip_holidays=True)
        self.assertEqual(self.next(weekly, '2026-09-24T08:00:00+08:00')['datetime'], '2026-10-02T07:30:00+08:00')
        dated = self.schedule(rule={'dates': ['2026-09-25', '2026-09-26', '2026-09-29']}, skip_holidays=True)
        self.assertEqual(self.next(dated, '2026-09-24T08:00:00+08:00')['datetime'], '2026-09-29T07:30:00+08:00')
        makeup = self.schedule(rule={'weekdays': [6]}, skip_holidays=True)
        self.assertEqual(self.next(makeup, '2025-02-07T08:00:00+08:00')['datetime'], '2025-02-08T07:30:00+08:00')
        self.assertIsNone(self.next(daily, '2028-01-03T00:00:00+08:00'))
        unknown = self.schedule(rule={'dates': ['2030-10-03']}, skip_holidays=True)
        self.assertIsNone(self.next(unknown, '2026-09-24T08:00:00+08:00'))
        self.assertEqual(self.next(self.schedule(), '2028-01-03T00:00:00+08:00')['datetime'], '2028-01-03T07:30:00+08:00')

    def calendar_event(self, start, end=None, source='local', all_day=False, uid='meeting'):
        first = datetime.fromisoformat(start)
        last = datetime.fromisoformat(end) if end else first
        return dict(source_id=source, uid=uid, starts_at=first.timestamp() * 1000,
                    ends_at=last.timestamp() * 1000, all_day=all_day)

    def linked(self, mode='event', sources=None, offset=0, **changes):
        return self.schedule(calendar_link=dict(mode=mode, source_ids=sources or ['local'], offset_minutes=offset), **changes)

    def test_calendar_event_advance_seconds_skip_and_source_filter(self):
        now = datetime.fromisoformat('2026-09-30T07:00:00+08:00')
        first = self.calendar_event('2026-09-30T08:10:45+08:00')
        second = self.calendar_event('2026-10-01T08:10:45+08:00')  # Same recurring UID, different occurrence.
        provider = Mock(return_value=[self.calendar_event('2026-09-30T07:30:00+08:00', source='unselected'),
                                      self.calendar_event('2026-09-30T00:00:00+08:00', all_day=True), first, first, second])
        schedule = self.linked(offset=10)
        event = next_event([schedule], self.holidays, now, provider)
        self.assertEqual(event['datetime'], '2026-09-30T08:00:45+08:00')
        self.assertEqual(event['occurrence_id'], 'wake@2026-09-30T08:00:45+08:00')
        schedule['skipped_occurrences'] = [event['datetime']]
        schedule = validate_schedule(schedule)
        self.assertEqual(next_occurrence(schedule, self.holidays, now, provider)['datetime'], '2026-10-01T08:00:45+08:00')
        self.assertEqual(provider.call_args.kwargs['source_ids'], ['local'])
        self.assertEqual(provider.call_args.kwargs['start'].isoformat(), '2026-09-30T00:10:00+08:00')
        self.assertEqual(provider.call_args.kwargs['end'] - provider.call_args.kwargs['start'], timedelta(days=366))

    def test_calendar_advance_filters_actual_taiwan_ring_day(self):
        # Friday's event rings Thursday night; weekday and holiday filters apply to Thursday.
        provider = Mock(return_value=[self.calendar_event('2026-09-25T00:15:20+08:00')])
        now = datetime.fromisoformat('2026-09-24T23:00:00+08:00')
        schedule = self.linked(offset=30, rule={'weekdays': [4]}, skip_holidays=True)
        self.assertEqual(next_occurrence(schedule, self.holidays, now, provider)['datetime'], '2026-09-24T23:45:20+08:00')
        schedule['rule'] = {'weekdays': [5]}
        self.assertIsNone(next_occurrence(schedule, self.holidays, now, provider))

    def test_calendar_day_overlap_all_day_end_exclusive_and_sparse_dates(self):
        provider = Mock(return_value=[
            self.calendar_event('2026-09-30T23:00:00+08:00', '2026-10-02T00:00:00+08:00'),
            self.calendar_event('2026-10-20T00:00:00+08:00', '2026-10-21T00:00:00+08:00', all_day=True),
        ])
        schedule = self.linked(mode='day')
        now = datetime.fromisoformat('2026-09-30T08:00:00+08:00')
        self.assertEqual(next_occurrence(schedule, self.holidays, now, provider)['datetime'], '2026-10-01T07:30:00+08:00')
        now = datetime.fromisoformat('2026-10-01T08:00:00+08:00')
        self.assertEqual(next_occurrence(schedule, self.holidays, now, provider)['datetime'], '2026-10-20T07:30:00+08:00')
        # A zero-duration event at midnight belongs to that day.
        provider.return_value = [self.calendar_event('2026-10-02T00:00:00+08:00')]
        self.assertEqual(next_occurrence(schedule, self.holidays, now, provider)['datetime'], '2026-10-02T07:30:00+08:00')

    def test_calendar_links_do_not_fall_back_when_unavailable(self):
        now = datetime.fromisoformat('2026-09-30T07:00:00+08:00')
        for mode in ('event', 'day'):
            schedule = self.linked(mode=mode)
            for provider in (None, Mock(return_value=[]), Mock(side_effect=OSError('unavailable'))):
                self.assertIsNone(next_occurrence(schedule, self.holidays, now, provider))
        unknown = self.linked(mode='day', skip_holidays=True)
        provider = Mock(return_value=[self.calendar_event('2028-01-03T08:00:00+08:00')])
        self.assertIsNone(next_occurrence(unknown, self.holidays, datetime.fromisoformat('2028-01-03T07:00:00+08:00'), provider))
        disabled = self.linked(enabled=False)
        next_occurrence(disabled, self.holidays, now, provider)
        self.assertEqual(provider.call_count, 1, 'Disabled schedules must not fetch calendars')
        failed = Mock(side_effect=OSError('unavailable'))
        self.assertEqual(next_event([self.schedule(), self.linked()], self.holidays, now, failed)['datetime'],
                         '2026-09-30T07:30:00+08:00', 'Failed prefetch must preserve ordinary alarms')

    def test_calendar_link_schema_preserves_old_rows_and_rejects_urls(self):
        self.assertNotIn('calendar_link', self.schedule())
        self.assertIsNone(self.schedule(calendar_link=None)['calendar_link'])
        linked = self.linked(sources=['work', 'local', 'work'])
        self.assertEqual(linked['calendar_link']['source_ids'], ['local', 'work'])
        invalid = [[], {}, {'mode': 'other', 'source_ids': ['local']},
                   {'mode': 'day', 'source_ids': ['local'], 'offset_minutes': 1},
                   {'mode': 'event', 'source_ids': ['https://private.example/secret']},
                   {'mode': 'event', 'source_ids': []}, {'mode': 'event', 'source_ids': 'local'},
                   {'mode': 'event', 'source_ids': [False]}, {'mode': 'event', 'source_ids': ['local'], 'url': 'secret'},
                   *[{'mode': 'event', 'source_ids': ['local'], 'offset_minutes': value} for value in (-1, 1441, True, '5')]]
        for link in invalid:
            with self.subTest(link=link), self.assertRaises(ValueError):
                self.schedule(calendar_link=link)
        with self.assertRaises(ValueError):
            self.linked(type='reminder')
        event_skips = ['2026-09-30T07:30:45.123000+08:00']
        linked['skipped_occurrences'] = event_skips
        self.assertEqual(validate_schedule(dict(linked, calendar_link=None))['skipped_occurrences'], event_skips)
        self.assertEqual(self.linked(mode='day', skipped_occurrences=event_skips)['skipped_occurrences'], event_skips)

    def test_validation_rejects_ambiguous_or_unsafe_values(self):
        invalid = [dict(time='24:00'), dict(time='7:30'), dict(volume=70), dict(repeat='once'),
                   dict(rule={'weekdays': [0]}), dict(rule={'weekdays': [True]}),
                   dict(rule={'workday_only': True, 'holiday_only': True}),
                   dict(rule={'workday_only': False}), dict(rule={'dates': ['2026-02-30']}),
                   dict(sound='../alarm.wav'), dict(sound='-alarm.wav'), dict(sound='_alarm.wav'),
                   dict(browser_sound='file.wav'), dict(browser_sound=None), dict(browser_sound=[]),
                   dict(skip_holidays='false'), dict(skip_holidays=1),
                   dict(skip_holidays=True, rule={'holiday_only': True}),
                   dict(enabled='false'), dict(snooze_minutes=5),
                   dict(skipped_occurrences=['2026-09-23T07:30:00']),
                   dict(skipped_occurrences=['0001-01-01T00:00:00+14:00']),
                   dict(skipped_occurrences=['9999-12-31T23:59:00-12:00']), dict(unknown=True)]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.schedule(**change)
        self.assertEqual(self.schedule(rule={'weekdays': [5, 1, 1]})['rule'], {'weekdays': [1, 5]})
        self.assertEqual(self.schedule(skipped_occurrences=['2026-09-22T23:30:00Z'])['skipped_occurrences'], ['2026-09-23T07:30:00+08:00'])


if __name__ == '__main__':
    unittest.main()
