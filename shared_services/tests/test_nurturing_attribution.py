"""Unit tests for shared_services.nurturing_attribution."""
from unittest.mock import Mock

from django.test import SimpleTestCase

from shared_services.nurturing_attribution import (
    resolve_media_campaign_for_enrollment,
    resolve_media_campaign_for_participant,
)


def _mc(crm_id):
    m = Mock()
    m.crm_campaign_id = crm_id
    return m


class ResolveMediaCampaignForEnrollmentTests(SimpleTestCase):
    def test_returns_none_when_nurturing_campaign_is_none(self):
        self.assertIsNone(
            resolve_media_campaign_for_enrollment(None, override=_mc(1)),
        )

    def test_override_wins_when_crm_consistent(self):
        nc = Mock(crm_campaign_id=10)
        override = _mc(10)
        sub = Mock(media_campaign=_mc(10))
        self.assertIs(
            resolve_media_campaign_for_enrollment(
                nc, originating_subscription=sub, override=override,
            ),
            override,
        )

    def test_skips_override_when_crm_mismatch_uses_subscription(self):
        nc = Mock(crm_campaign_id=10)
        override = _mc(99)
        sub_mc = _mc(10)
        sub = Mock(media_campaign=sub_mc)
        self.assertIs(
            resolve_media_campaign_for_enrollment(
                nc, originating_subscription=sub, override=override,
            ),
            sub_mc,
        )

    def test_subscription_skipped_when_mismatch_uses_campaign_default(self):
        nc = Mock(crm_campaign_id=10)
        nc.media_campaign = _mc(10)
        sub = Mock(media_campaign=_mc(99))
        self.assertIs(
            resolve_media_campaign_for_enrollment(nc, originating_subscription=sub),
            nc.media_campaign,
        )

    def test_campaign_default_when_no_subscription(self):
        nc = Mock(crm_campaign_id=5)
        nc.media_campaign = _mc(5)
        self.assertIs(
            resolve_media_campaign_for_enrollment(nc),
            nc.media_campaign,
        )

    def test_returns_none_when_all_candidates_mismatch(self):
        nc = Mock(crm_campaign_id=10)
        nc.media_campaign = _mc(20)
        sub = Mock(media_campaign=_mc(30))
        self.assertIsNone(
            resolve_media_campaign_for_enrollment(nc, originating_subscription=sub),
        )

    def test_when_nurturing_has_no_crm_any_media_accepted(self):
        nc = Mock(crm_campaign_id=None)
        nc.media_campaign = None
        lone = _mc(999)
        self.assertIs(
            resolve_media_campaign_for_enrollment(nc, override=lone),
            lone,
        )


class ResolveMediaCampaignForParticipantTests(SimpleTestCase):
    def test_returns_none_when_participant_is_none(self):
        self.assertIsNone(resolve_media_campaign_for_participant(None))

    def test_participant_snapshot_wins(self):
        snap = _mc(10)
        p = Mock(media_campaign_id=1, media_campaign=snap)
        p.nurturing_campaign = Mock(crm_campaign_id=10)
        p.originating_subscription = Mock(media_campaign=_mc(10))
        self.assertIs(resolve_media_campaign_for_participant(p), snap)

    def test_subscription_when_snapshot_null_and_crm_consistent(self):
        sub_mc = _mc(7)
        p = Mock(media_campaign_id=None, media_campaign=None)
        p.nurturing_campaign = Mock(crm_campaign_id=7)
        p.originating_subscription = Mock(media_campaign=sub_mc)
        self.assertIs(resolve_media_campaign_for_participant(p), sub_mc)

    def test_skips_subscription_when_crm_mismatch_uses_campaign_default(self):
        nc_mc = _mc(10)
        nc = Mock(crm_campaign_id=10)
        nc.media_campaign = nc_mc
        p = Mock(media_campaign_id=None, media_campaign=None)
        p.nurturing_campaign = nc
        p.originating_subscription = Mock(media_campaign=_mc(99))
        self.assertIs(resolve_media_campaign_for_participant(p), nc_mc)

    def test_campaign_default_when_no_subscription(self):
        nc_mc = _mc(3)
        nc = Mock(crm_campaign_id=3)
        nc.media_campaign = nc_mc
        p = Mock(media_campaign_id=None, media_campaign=None)
        p.nurturing_campaign = nc
        p.originating_subscription = None
        self.assertIs(resolve_media_campaign_for_participant(p), nc_mc)

    def test_returns_none_when_nothing_resolves(self):
        nc = Mock(crm_campaign_id=1)
        nc.media_campaign = _mc(2)
        p = Mock(media_campaign_id=None, media_campaign=None)
        p.nurturing_campaign = nc
        p.originating_subscription = None
        self.assertIsNone(resolve_media_campaign_for_participant(p))
