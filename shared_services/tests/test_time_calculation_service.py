"""Tests for TimeCalculationService scheduling helpers."""

from datetime import datetime, time
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from shared_services.time_calculation_service import TimeCalculationService


class GetNextValidTimeTests(SimpleTestCase):
    def setUp(self):
        self.svc = TimeCalculationService()

    def test_drip_like_weekend_only_no_business_hours(self):
        """exclude_weekends still applies when business_hours_only is False."""
        # 2026-04-18 is a Saturday (weekday 5)
        saturday = timezone.make_aware(datetime(2026, 4, 18, 12, 0, 0))
        schedule = SimpleNamespace(
            business_hours_only=False,
            exclude_weekends=True,
        )
        result = self.svc.get_next_valid_time(saturday, schedule)
        self.assertEqual(result.weekday(), 0, 'should roll to Monday')
        self.assertEqual(result.date(), datetime(2026, 4, 20).date())

    def test_drip_like_legacy_business_hours_window(self):
        """Drip-style schedule uses calculate_next_business_time when start/end exist."""
        # Same calendar day 18:00, window 09:00–17:00 → next business morning
        current = timezone.make_aware(datetime(2026, 4, 15, 18, 0, 0))  # Wednesday
        schedule = SimpleNamespace(
            business_hours_only=True,
            start_time=time(9, 0),
            end_time=time(17, 0),
            exclude_weekends=False,
        )
        result = self.svc.get_next_valid_time(current, schedule)
        self.assertEqual(result.date(), datetime(2026, 4, 16).date())
        self.assertEqual(result.time(), time(9, 0))

    def test_blast_like_business_hours_without_crm_or_legacy_window(self):
        """Blast schedules lack start/end; no exception; time unchanged; warning logged."""
        send_time = timezone.make_aware(datetime(2026, 4, 17, 18, 17, 0))
        nurturing = SimpleNamespace(id=252, pk=252, crm_campaign=None)
        schedule = SimpleNamespace(
            pk=42,
            id=42,
            campaign=nurturing,
            business_hours_only=True,
        )
        with self.assertLogs(
            'shared_services.time_calculation_service', level='WARNING'
        ) as cm:
            result = self.svc.get_next_valid_time(send_time, schedule)

        self.assertEqual(result, send_time)
        self.assertTrue(
            any('business_hours_only is True' in m for m in cm.output),
            cm.output,
        )
        self.assertTrue(any('schedule_id=42' in m for m in cm.output), cm.output)
        self.assertTrue(
            any('nurturing_campaign_id=252' in m for m in cm.output), cm.output
        )
