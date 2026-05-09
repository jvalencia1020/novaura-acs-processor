"""Dynamo runtime record includes attribution IDs from resolvers."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from link_tracking.services.runtime_publisher import build_runtime_record


class BuildRuntimeRecordAttributionTests(SimpleTestCase):
    def _minimal_link(self):
        domain = SimpleNamespace(domain_name='short.example')
        campaign = MagicMock()
        campaign.utm_template = None
        link = MagicMock()
        link.id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        link.domain = domain
        link.slug_canonical = 'ABC123'
        link.fallback_url = ''
        link.append_query_params = False
        link.dynamic_param_allowlist = []
        link.utm_overrides = {}
        link.campaign = campaign
        link.expires_at = None
        link.max_clicks = None
        link.routing_rules = None
        link.signature_required = False
        link.signature_secret_ref = None
        link.campaign_identifier = ''
        link.keyword = ''
        link.channel = 'sms'
        link.destination_url = 'https://dest.example/page'
        link.runtime_version = 1
        link.updated_at = None
        link.created_at = None
        link.slug_type = 'system'
        return link

    @patch('link_tracking.services.runtime_publisher._resolve_utm_params', return_value={})
    @patch('link_tracking.services.runtime_publisher.resolve_crm_and_media_campaign')
    @patch('link_tracking.services.runtime_publisher.resolve_media_campaign_for_link')
    def test_adds_string_ids_when_resolvers_return_objects(
        self, mock_resolve_media, mock_resolve_crm, _mock_utm
    ):
        mock_resolve_media.return_value = SimpleNamespace(id='m1')
        mock_resolve_crm.return_value = (SimpleNamespace(id='c1'), None)
        link = self._minimal_link()
        rec = build_runtime_record(link)
        self.assertEqual(rec['media_campaign_id'], 'm1')
        self.assertEqual(rec['crm_campaign_id'], 'c1')

    @patch('link_tracking.services.runtime_publisher._resolve_utm_params', return_value={})
    @patch('link_tracking.services.runtime_publisher.resolve_crm_and_media_campaign')
    @patch('link_tracking.services.runtime_publisher.resolve_media_campaign_for_link')
    def test_omits_ids_when_resolvers_return_none(self, mock_resolve_media, mock_resolve_crm, _mock_utm):
        mock_resolve_media.return_value = None
        mock_resolve_crm.return_value = (None, None)
        link = self._minimal_link()
        rec = build_runtime_record(link)
        self.assertNotIn('media_campaign_id', rec)
        self.assertNotIn('crm_campaign_id', rec)
