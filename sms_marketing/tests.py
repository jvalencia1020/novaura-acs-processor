"""
SMS marketing service tests.

Run with test settings so DATABASES and INSTALLED_APPS are correct:

    python manage.py test sms_marketing.tests --settings=acs_personalization.settings.test
"""
from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock


class SMSMarketingProcessorFallbackTests(TestCase):
    def _make_message(self):
        msg = Mock()
        msg.id = 123
        msg.provider = 'twilio'
        msg.provider_message_id = 'SM_TEST'
        msg.body_raw = 'hello'
        msg.body_normalized = 'HELLO'
        msg.webhook_query_params = {}
        msg.error = None
        msg.sms_campaign_id = None
        msg.sms_campaign = None
        msg.save = Mock()
        return msg

    def test_opted_in_no_keyword_match_uses_template(self):
        from sms_marketing.services.processor import SMSMarketingProcessor

        processor = SMSMarketingProcessor()
        endpoint = Mock()
        endpoint.id = 10
        endpoint.value = '+15551234567'

        subscriber = Mock()
        subscriber.status = 'opted_in'
        subscriber.lead = Mock()
        subscriber.lead.first_name = 'Ada'

        template = Mock()
        template.id = 99
        template.replace_variables = Mock(return_value='Hi Ada')

        campaign = Mock()
        campaign.id = 7
        campaign.status = 'active'
        campaign.endpoint_id = endpoint.id
        campaign.account = Mock()
        campaign.opted_in_fallback_template = template
        campaign.opted_in_fallback_message = 'ignored'
        campaign.fallback_action_type = None
        campaign.fallback_action_config = None

        message = self._make_message()
        message.sms_campaign_id = campaign.id
        message.sms_campaign = campaign

        outbound = Mock()
        outbound.id = 555

        with patch('sms_marketing.services.processor.SmsCampaignEvent.objects.create') as mock_event_create:
            with patch.object(processor.message_sender, 'send_message') as mock_send:
                mock_send.return_value = (True, outbound)

                ok = processor._handle_fallback(endpoint, subscriber, message)

        self.assertTrue(ok)
        template.replace_variables.assert_called_once()
        send_kwargs = mock_send.call_args.kwargs
        self.assertEqual(send_kwargs['campaign'], campaign)
        self.assertEqual(send_kwargs['body'], 'Hi Ada')
        self.assertEqual(send_kwargs['message_type'], 'opted_in_fallback')
        self.assertTrue(mock_event_create.called)
        payload = mock_event_create.call_args.kwargs['payload']
        self.assertTrue(payload.get('fallback'))
        self.assertEqual(payload.get('fallback_type'), 'opted_in_reply')
        self.assertTrue(payload.get('used_template'))
        self.assertEqual(payload.get('template_id'), 99)
        self.assertEqual(payload.get('sms_message_id'), 555)

    def test_opted_in_no_keyword_match_uses_plain_message(self):
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
        campaign.opted_in_fallback_message = 'Welcome back!'
        campaign.fallback_action_type = None
        campaign.fallback_action_config = None

        message = self._make_message()
        message.sms_campaign_id = campaign.id
        message.sms_campaign = campaign

        outbound = Mock()
        outbound.id = 556

        with patch('sms_marketing.services.processor.SmsCampaignEvent.objects.create') as mock_event_create:
            with patch.object(processor.message_sender, 'send_message') as mock_send:
                mock_send.return_value = (True, outbound)

                ok = processor._handle_fallback(endpoint, subscriber, message)

        self.assertTrue(ok)
        send_kwargs = mock_send.call_args.kwargs
        self.assertEqual(send_kwargs['body'], 'Welcome back!')
        self.assertEqual(send_kwargs['message_type'], 'opted_in_fallback')
        payload = mock_event_create.call_args.kwargs['payload']
        self.assertTrue(payload.get('fallback'))
        self.assertEqual(payload.get('fallback_type'), 'opted_in_reply')
        self.assertFalse(payload.get('used_template'))

    def test_not_opted_in_no_keyword_match_uses_plain_message_when_no_template(self):
        from sms_marketing.services.processor import SMSMarketingProcessor

        processor = SMSMarketingProcessor()
        endpoint = Mock()
        endpoint.id = 10
        endpoint.value = '+15551234567'
        endpoint.account = None

        subscriber = Mock()
        subscriber.status = 'unknown'
        subscriber.lead = None

        sms_settings = Mock()
        sms_settings.not_opted_in_default_reply_template = None
        sms_settings.not_opted_in_default_reply_message = 'Reply JOIN to opt in.'
        endpoint.sms_settings = sms_settings

        message = self._make_message()

        outbound = Mock()
        outbound.id = 558

        with patch('sms_marketing.services.processor.SmsCampaignEvent.objects.create') as mock_event_create:
            with patch.object(processor.message_sender, 'send_message') as mock_send:
                mock_send.return_value = (True, outbound)

                ok = processor._handle_fallback(endpoint, subscriber, message)

        self.assertTrue(ok)
        send_kwargs = mock_send.call_args.kwargs
        self.assertEqual(send_kwargs['campaign'], None)
        self.assertEqual(send_kwargs['body'], 'Reply JOIN to opt in.')
        self.assertEqual(send_kwargs['message_type'], 'not_opted_in_default_reply')
        payload = mock_event_create.call_args.kwargs['payload']
        self.assertTrue(payload.get('fallback'))
        self.assertEqual(payload.get('fallback_type'), 'endpoint_not_opted_in_reply')

    def test_not_opted_in_no_keyword_match_does_not_use_opted_in_fallback(self):
        from sms_marketing.services.processor import SMSMarketingProcessor

        processor = SMSMarketingProcessor()
        endpoint = Mock()
        endpoint.id = 10
        endpoint.value = '+15551234567'
        endpoint.account = None

        subscriber = Mock()
        subscriber.status = 'unknown'
        subscriber.lead = None

        message = self._make_message()
        message.sms_campaign_id = None
        message.sms_campaign = None

        sms_settings = Mock()
        sms_settings.not_opted_in_default_reply_template = Mock()
        sms_settings.not_opted_in_default_reply_template.channel = 'sms'
        sms_settings.not_opted_in_default_reply_template.id = 101
        sms_settings.not_opted_in_default_reply_template.replace_variables = Mock(return_value='Please opt in')
        sms_settings.not_opted_in_default_reply_message = 'ignored'
        endpoint.sms_settings = sms_settings

        outbound = Mock()
        outbound.id = 557

        with patch('sms_marketing.services.processor.SmsCampaignEvent.objects.create') as mock_event_create:
            with patch.object(processor.message_sender, 'send_message') as mock_send:
                with patch('sms_marketing.services.processor.execute_action') as mock_exec:
                    mock_send.return_value = (True, outbound)

                    ok = processor._handle_fallback(endpoint, subscriber, message)

        self.assertTrue(ok)
        mock_exec.assert_not_called()
        mock_send.assert_called_once()
        send_kwargs = mock_send.call_args.kwargs
        self.assertEqual(send_kwargs['campaign'], None)
        self.assertEqual(send_kwargs['body'], 'Please opt in')
        self.assertEqual(send_kwargs['message_type'], 'not_opted_in_default_reply')
        payload = mock_event_create.call_args.kwargs['payload']
        self.assertTrue(payload.get('fallback'))
        self.assertEqual(payload.get('fallback_type'), 'endpoint_not_opted_in_reply')
        self.assertEqual(payload.get('template_id'), 101)
        self.assertEqual(payload.get('sms_message_id'), 557)


class SMSMarketingOptInReplyTests(TestCase):
    def test_opt_in_single_returns_success_and_welcome_message_uses_rule_initial_reply(self):
        from sms_marketing.services.actions import execute_action, get_welcome_message_for_opt_in

        campaign = Mock()
        campaign.id = 1
        campaign.opt_in_mode = 'single'
        campaign.welcome_message = 'Campaign welcome'
        campaign.endpoint = Mock()
        campaign.program = None
        campaign.follow_up_nurturing_campaign = None  # so _enroll returns None (getattr(Mock, 'x', None) returns Mock)

        rule = Mock()
        rule.id = 10
        rule.action_type = 'OPT_IN'
        rule.initial_reply = 'Rule initial reply'
        rule.confirmation_message = None
        rule.keyword = Mock()
        rule.keyword.keyword = 'JOIN'
        rule.action_config = None

        subscriber = Mock()
        subscriber.lead = None
        subscriber.lead_id = None
        subscriber.endpoint = campaign.endpoint
        subscriber.phone_number = '+15551234567'

        message = Mock()

        with patch('sms_marketing.services.actions.transaction.atomic') as mock_atomic:
            mock_atomic.return_value.__enter__ = Mock(return_value=None)
            mock_atomic.return_value.__exit__ = Mock(return_value=False)
            with patch('sms_marketing.services.state.SmsSubscriberCampaignSubscription.objects.get_or_create') as mock_sub:
                mock_sub.return_value = (Mock(), True)
                with patch('sms_marketing.services.actions.SMSMarketingMessageSender') as mock_sender_cls:
                    mock_sender_cls.return_value.send_message.return_value = (True, Mock())
                    with patch('sms_marketing.services.actions.LeadMatchingService') as mock_lead_svc:
                        mock_lead_svc.return_value.get_lead_by_phone.return_value = None
                        result = execute_action(campaign, rule, subscriber, message, {})

        self.assertTrue(result.success)
        # Welcome message resolution should prefer rule.initial_reply over campaign.welcome_message when config is empty
        welcome = get_welcome_message_for_opt_in(campaign, rule, {})
        self.assertEqual(welcome, 'Rule initial reply')

    def test_opt_in_double_returns_success(self):
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

        subscriber = Mock()
        subscriber.lead = None
        subscriber.lead_id = None
        subscriber.endpoint = campaign.endpoint
        subscriber.phone_number = '+15551234567'

        message = Mock()

        with patch('sms_marketing.services.actions.transaction.atomic') as mock_atomic:
            mock_atomic.return_value.__enter__ = Mock(return_value=None)
            mock_atomic.return_value.__exit__ = Mock(return_value=False)
            with patch('sms_marketing.services.state.SmsSubscriberCampaignSubscription.objects.get_or_create') as mock_sub:
                mock_sub.return_value = (Mock(), True)
                with patch('sms_marketing.services.actions.SMSMarketingMessageSender') as mock_sender_cls:
                    mock_sender_cls.return_value.send_message.return_value = (True, Mock())
                    with patch('sms_marketing.services.actions.LeadMatchingService') as mock_lead_svc:
                        mock_lead_svc.return_value.get_lead_by_phone.return_value = None
                        result = execute_action(campaign, rule, subscriber, message, {})

        self.assertTrue(result.success)


class SMSMarketingGetWelcomeMessageTests(TestCase):
    def test_get_welcome_message_for_opt_in_prefers_rule_then_config_then_campaign(self):
        from sms_marketing.services.actions import get_welcome_message_for_opt_in

        campaign = Mock()
        campaign.welcome_message = 'Campaign welcome'

        rule = Mock()
        rule.initial_reply = 'Rule initial reply'

        # Rule initial_reply (actual rule model field) takes precedence
        self.assertEqual(
            get_welcome_message_for_opt_in(campaign, rule, {'welcome_message': 'Config welcome'}),
            'Rule initial reply',
        )
        self.assertEqual(
            get_welcome_message_for_opt_in(campaign, rule, {}),
            'Rule initial reply',
        )
        rule.initial_reply = None
        self.assertEqual(
            get_welcome_message_for_opt_in(campaign, rule, {'welcome_message': 'Config welcome'}),
            'Config welcome',
        )
        self.assertEqual(
            get_welcome_message_for_opt_in(campaign, rule, {}),
            'Campaign welcome',
        )
        campaign.welcome_message = None
        self.assertIsNone(get_welcome_message_for_opt_in(campaign, rule, {}))
