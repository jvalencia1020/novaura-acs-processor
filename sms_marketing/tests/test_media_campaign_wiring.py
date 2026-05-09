"""PR2: media_campaign threaded through fallback and execute_action (package tests)."""
from unittest.mock import Mock, patch

from django.test import TestCase


class SMSMarketingMediaCampaignWiringTests(TestCase):
    """Attribution passed through processor fallback and execute_action → sender."""

    def test_opted_in_fallback_forwards_media_campaign_to_message_sender(self):
        from sms_marketing.services.processor import SMSMarketingProcessor

        processor = SMSMarketingProcessor()
        endpoint = Mock()
        endpoint.id = 10
        endpoint.value = '+15551234567'

        subscriber = Mock()
        subscriber.status = 'opted_in'
        subscriber.lead = None

        campaign = Mock()
        campaign.id = 7
        campaign.status = 'active'
        campaign.endpoint_id = endpoint.id
        campaign.account = None
        campaign.opted_in_fallback_template = None
        campaign.opted_in_fallback_message = 'Hi!'
        campaign.fallback_action_type = None
        campaign.fallback_action_config = None

        message = Mock()
        message.id = 123
        message.provider = 'twilio'
        message.provider_message_id = 'SMX'
        message.body_raw = 'hello'
        message.body_normalized = 'HELLO'
        message.webhook_query_params = {}
        message.error = None
        message.sms_campaign_id = campaign.id
        message.sms_campaign = campaign
        message.media_campaign_id = None
        message.save = Mock()

        outbound = Mock()
        outbound.id = 900

        resolved_media = Mock()

        with patch('sms_marketing.services.processor.SmsCampaignEvent.objects.create'):
            with patch(
                'sms_marketing.services.processor.resolve_crm_and_media_campaign',
                return_value=(None, resolved_media),
            ):
                with patch.object(processor.message_sender, 'send_message') as mock_send:
                    mock_send.return_value = (True, outbound)
                    ok = processor._handle_fallback(endpoint, subscriber, message)

        self.assertTrue(ok)
        self.assertEqual(mock_send.call_args.kwargs.get('media_campaign'), resolved_media)

    def test_execute_action_passes_media_campaign_to_send_message(self):
        from sms_marketing.services.actions import execute_action

        campaign = Mock()
        campaign.id = 1
        campaign.opt_in_mode = 'double'
        campaign.confirmation_message = 'Campaign confirm'
        campaign.endpoint = Mock()
        campaign.program = None
        campaign.follow_up_nurturing_campaign = None

        rule = Mock()
        rule.id = 10
        rule.action_type = 'OPT_IN'
        rule.initial_reply = None
        rule.confirmation_message = 'Rule confirm'
        rule.keyword = Mock()
        rule.keyword.keyword = 'JOIN'
        rule.action_config = None
        rule.short_link = None

        subscriber = Mock()
        subscriber.lead = None
        subscriber.lead_id = None
        subscriber.endpoint = campaign.endpoint
        subscriber.phone_number = '+15551234567'

        message = Mock()
        passed_media = Mock()

        with patch('sms_marketing.services.actions.transaction.atomic') as mock_atomic:
            mock_atomic.return_value.__enter__ = Mock(return_value=None)
            mock_atomic.return_value.__exit__ = Mock(return_value=False)
            with patch('sms_marketing.services.state.SmsSubscriberCampaignSubscription.objects.get_or_create') as mock_sub:
                mock_sub.return_value = (Mock(), True)
                with patch('sms_marketing.services.actions.SMSMarketingMessageSender') as mock_sender_cls:
                    mock_sender_cls.return_value.send_message.return_value = (True, Mock())
                    with patch('sms_marketing.services.actions.LeadMatchingService') as mock_lead_svc:
                        mock_lead_svc.return_value.get_lead_by_phone.return_value = None
                        result = execute_action(
                            campaign, rule, subscriber, message, {}, media_campaign=passed_media
                        )

        self.assertTrue(result.success)
        send_kw = mock_sender_cls.return_value.send_message.call_args.kwargs
        self.assertIs(send_kw.get('media_campaign'), passed_media)
