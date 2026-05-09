"""CampaignMatchingService prefers envelope media_campaign_id when matching participant."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class CampaignMatchingMediaAttributionTests(SimpleTestCase):
    def test_media_campaign_id_selects_nurturing_via_originating_subscription(self):
        from shared_services.campaign_matching_service import CampaignMatchingService

        lead = MagicMock()
        lead.id = 501
        nc = MagicMock()
        participant = MagicMock()
        participant.nurturing_campaign = nc

        qs = MagicMock()
        qs.select_related.return_value.first.return_value = participant

        svc = CampaignMatchingService()
        with patch('shared_services.campaign_matching_service.LeadNurturingParticipant.objects') as m:
            m.filter.return_value = qs
            out = svc.find_nurturing_campaign_from_event(
                {'media_campaign_id': 777},
                lead,
            )

        self.assertIs(out, nc)
        m.filter.assert_called_once()
        kwargs = m.filter.call_args.kwargs
        self.assertEqual(kwargs['lead'], lead)
        self.assertEqual(kwargs['status'], 'active')
        self.assertEqual(
            kwargs['originating_subscription__media_campaign_id'],
            777,
        )
