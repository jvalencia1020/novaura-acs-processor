"""Unit tests for sms_marketing.services.attribution and lead_attribution."""
import unittest
from unittest.mock import MagicMock, Mock

from sms_marketing.services.attribution import resolve_crm_and_media_campaign
from sms_marketing.services.lead_attribution import maybe_fill_lead_media_campaign


class SmsCampaignAttributionTests(unittest.TestCase):
    def _chain_first(self, row):
        m = MagicMock()
        m.filter.return_value = m
        m.annotate.return_value = m
        m.order_by.return_value = m
        m.first.return_value = row
        return m

    def test_none_campaign(self):
        self.assertEqual(resolve_crm_and_media_campaign(None), (None, None))

    def test_no_active_rows(self):
        sc = Mock()
        sc.crm_campaign_relations = self._chain_first(None)
        self.assertEqual(resolve_crm_and_media_campaign(sc), (None, None))

    def test_returns_first_ordered_row(self):
        sc = Mock()
        row = Mock(crm_campaign=Mock(id=3), media_campaign=Mock(id=8))
        sc.crm_campaign_relations = self._chain_first(row)
        crm, media = resolve_crm_and_media_campaign(sc)
        self.assertEqual(crm.id, 3)
        self.assertEqual(media.id, 8)

    def test_filter_is_active_true(self):
        sc = Mock()
        rels = MagicMock()
        sc.crm_campaign_relations = rels
        rels.filter.return_value = rels
        rels.annotate.return_value = rels
        rels.order_by.return_value = rels
        rels.first.return_value = Mock(crm_campaign=Mock(), media_campaign=None)
        resolve_crm_and_media_campaign(sc)
        rels.filter.assert_called_once()
        self.assertEqual(rels.filter.call_args[1], {'is_active': True})


class MaybeFillLeadMediaCampaignTests(unittest.TestCase):
    def test_noop_when_lead_none(self):
        self.assertFalse(maybe_fill_lead_media_campaign(None, Mock(), Mock()))

    def test_noop_when_media_none(self):
        lead = Mock(media_campaign_id=None)
        self.assertFalse(maybe_fill_lead_media_campaign(lead, Mock(id=1), None))

    def test_noop_when_lead_already_has_media(self):
        lead = Mock(media_campaign_id=5)
        self.assertFalse(maybe_fill_lead_media_campaign(lead, Mock(id=1), Mock(crm_campaign_id=1)))

    def test_noop_crm_mismatch(self):
        lead = Mock(media_campaign_id=None)
        media = Mock(crm_campaign_id=2)
        crm = Mock(id=1)
        self.assertFalse(maybe_fill_lead_media_campaign(lead, crm, media))
        lead.save.assert_not_called()

    def test_fills_when_null_and_crm_matches(self):
        lead = Mock(media_campaign_id=None)
        media = Mock(crm_campaign_id=7)
        crm = Mock(id=7)
        self.assertTrue(maybe_fill_lead_media_campaign(lead, crm, media))
        self.assertIs(lead.media_campaign, media)
        lead.save.assert_called_once_with(update_fields=['media_campaign'])
