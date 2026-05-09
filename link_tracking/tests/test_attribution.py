"""Unit tests for link_tracking.services.attribution (mocked querysets)."""
import unittest
from unittest.mock import MagicMock, Mock

from link_tracking.services.attribution import (
    resolve_crm_and_media_campaign,
    resolve_media_campaign_for_link,
)


class LinkCampaignAttributionTests(unittest.TestCase):
    def _chain_first(self, row):
        m = MagicMock()
        m.filter.return_value = m
        m.annotate.return_value = m
        m.order_by.return_value = m
        m.first.return_value = row
        return m

    def test_resolve_link_campaign_none(self):
        self.assertEqual(resolve_crm_and_media_campaign(None), (None, None))

    def test_resolve_link_campaign_no_rows(self):
        lc = Mock()
        lc.crm_campaign_mappings = self._chain_first(None)
        self.assertEqual(resolve_crm_and_media_campaign(lc), (None, None))

    def test_resolve_prefers_open_ended_mapping(self):
        lc = Mock()
        open_row = Mock(crm_campaign_id=1, crm_campaign=Mock(id=1), media_campaign=Mock(id=10))
        lc.crm_campaign_mappings = self._chain_first(open_row)
        crm, media = resolve_crm_and_media_campaign(lc)
        self.assertEqual(crm, open_row.crm_campaign)
        self.assertEqual(media, open_row.media_campaign)


class ResolveMediaCampaignForLinkTests(unittest.TestCase):
    def test_link_override_wins(self):
        link = Mock()
        link.media_campaign_id = 99
        link.media_campaign = Mock(id=99)
        link.campaign = Mock(media_campaign_id=1, media_campaign=Mock(id=1))
        self.assertEqual(resolve_media_campaign_for_link(link).id, 99)

    def test_campaign_default_second(self):
        link = Mock()
        link.media_campaign_id = None
        link.media_campaign = None
        link.campaign = Mock()
        link.campaign.media_campaign_id = 42
        link.campaign.media_campaign = Mock(id=42)
        self.assertEqual(resolve_media_campaign_for_link(link).id, 42)

    def test_falls_back_to_mapping_media(self):
        link = Mock()
        link.media_campaign_id = None
        link.media_campaign = None
        link.campaign = Mock()
        link.campaign.media_campaign_id = None
        link.campaign.media_campaign = None
        row = Mock(crm_campaign=Mock(id=5), media_campaign=Mock(id=77))
        m = MagicMock()
        link.campaign.crm_campaign_mappings = m
        m.filter.return_value = m
        m.annotate.return_value = m
        m.order_by.return_value = m
        m.first.return_value = row
        self.assertEqual(resolve_media_campaign_for_link(link).id, 77)

    def test_all_none(self):
        link = Mock()
        link.media_campaign_id = None
        link.media_campaign = None
        link.campaign = Mock()
        link.campaign.media_campaign_id = None
        link.campaign.media_campaign = None
        m = MagicMock()
        link.campaign.crm_campaign_mappings = m
        m.filter.return_value = m
        m.annotate.return_value = m
        m.order_by.return_value = m
        m.first.return_value = None
        self.assertIsNone(resolve_media_campaign_for_link(link))
