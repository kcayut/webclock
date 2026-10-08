"""A failed calendar lookup differs from a successful lookup with no next alarm."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import Mock

from webclock.services.control_service import ControlService
from webclock.services.device_access_service import AccessError
from webclock.services.schedule_service import TAIPEI, validate_schedule


class ControlStatusTest(unittest.TestCase):
    def setUp(self):
        self.provider = Mock()
        self.service = ControlService('.', {}, None, None, self.provider, ['work'])
        self.schedule = validate_schedule(dict(name='Meeting', time='00:00',
            calendar_link=dict(mode='event', source_ids=['work'], offset_minutes=0)))

    def test_failed_or_invalid_calendar_is_not_reported_ready(self):
        for error in (OSError('offline'), ValueError('invalid feed'),
                      AccessError('Unavailable', 503, 'calendar_not_ready'),
                      RuntimeError('unavailable'), OverflowError('too many events')):
            with self.subTest(error=type(error).__name__):
                self.provider.side_effect = error
                result = self.service.result('schedules', self.schedule)
                self.assertIsNone(result['next_occurrence'])
                self.assertEqual(result['next_occurrence_status'], 'not_ready')
                self.assertIs(self.provider.call_args.kwargs['strict'], True)
        self.provider.side_effect = None
        self.provider.return_value = None
        self.assertEqual(self.service.result('schedules', self.schedule)['next_occurrence_status'], 'not_ready')

    def test_empty_success_and_valid_occurrence_remain_ready(self):
        self.provider.return_value = []
        result = self.service.result('schedules', self.schedule)
        self.assertEqual((result['next_occurrence'], result['next_occurrence_status']), (None, 'ready'))
        starts = datetime.now(TAIPEI).replace(microsecond=0) + timedelta(hours=1)
        self.provider.return_value = [dict(source_id='work', uid='meeting', all_day=False,
            starts_at=starts.timestamp() * 1000, ends_at=(starts + timedelta(hours=1)).timestamp() * 1000)]
        result = self.service.result('schedules', self.schedule)
        self.assertEqual((result['next_occurrence'], result['next_occurrence_status']), (starts.isoformat(), 'ready'))
        self.provider.reset_mock()
        result = self.service.result('schedules', dict(self.schedule, enabled=False))
        self.assertEqual((result['next_occurrence'], result['next_occurrence_status']), (None, 'ready'))
        self.provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
