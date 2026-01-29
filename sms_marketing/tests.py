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
            with patch.object(processor.action_executor.message_sender, 'send_message') as mock_send:
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
            with patch.object(processor.action_executor.message_sender, 'send_message') as mock_send:
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
            with patch.object(processor.action_executor.message_sender, 'send_message') as mock_send:
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
            with patch.object(processor.action_executor.message_sender, 'send_message') as mock_send:
                with patch.object(processor.action_executor, 'execute_action') as mock_exec:
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
    def test_opt_in_single_uses_rule_initial_reply_over_campaign_default(self):
        from sms_marketing.services.actions import SMSMarketingActionExecutor

        executor = SMSMarketingActionExecutor()

        campaign = Mock()
        campaign.id = 1
        campaign.opt_in_mode = 'single'
        campaign.welcome_message = 'Campaign welcome'

        rule = Mock()
        rule.id = 10
        rule.action_type = 'OPT_IN'
        rule.initial_reply = 'Rule initial reply'
        rule.confirmation_message = None
        rule.keyword = Mock()
        rule.keyword.keyword = 'JOIN'

        subscriber = Mock()
        subscriber.lead = None

        message = Mock()

        with patch('sms_marketing.services.state.SMSMarketingStateManager.handle_opt_in') as mock_handle_opt_in:
            mock_handle_opt_in.return_value = {'status': 'opted_in', 'confirmed': True}
            with patch.object(executor, '_link_or_create_lead') as mock_link:
                mock_link.return_value = None
                with patch.object(executor, '_send_message') as mock_send_message:
                    executor._handle_opt_in(campaign, rule, subscriber, message, action_config={})

        # Should send rule.initial_reply (not campaign.welcome_message)
        send_args = mock_send_message.call_args.args
        send_kwargs = mock_send_message.call_args.kwargs
        self.assertEqual(send_args[2], 'Rule initial reply')  # body
        self.assertEqual(send_kwargs.get('message_type'), 'welcome')
        self.assertEqual(send_kwargs.get('rule'), rule)

    def test_opt_in_double_uses_rule_confirmation_message_over_campaign_default(self):
        from sms_marketing.services.actions import SMSMarketingActionExecutor

        executor = SMSMarketingActionExecutor()

        campaign = Mock()
        campaign.id = 1
        campaign.opt_in_mode = 'double'
        campaign.confirmation_message = 'Campaign confirm'

        rule = Mock()
        rule.id = 10
        rule.action_type = 'OPT_IN'
        rule.initial_reply = None
        rule.confirmation_message = 'Rule confirm'
        rule.keyword = Mock()
        rule.keyword.keyword = 'JOIN'

        subscriber = Mock()
        subscriber.lead = None

        message = Mock()

        with patch('sms_marketing.services.state.SMSMarketingStateManager.handle_opt_in') as mock_handle_opt_in:
            mock_handle_opt_in.return_value = {'status': 'pending_opt_in', 'confirmed': False}
            with patch.object(executor, '_link_or_create_lead') as mock_link:
                mock_link.return_value = None
                with patch.object(executor, '_send_message') as mock_send_message:
                    executor._handle_opt_in(campaign, rule, subscriber, message, action_config={})

        send_args = mock_send_message.call_args.args
        send_kwargs = mock_send_message.call_args.kwargs
        self.assertEqual(send_args[2], 'Rule confirm')  # body
        self.assertEqual(send_kwargs.get('message_type'), 'confirmation')
        self.assertEqual(send_kwargs.get('rule'), rule)


class SMSMarketingPlainTextVariableReplacementTests(TestCase):
    def test_plain_text_messages_use_template_variable_replacement(self):
        from sms_marketing.services.actions import SMSMarketingActionExecutor

        executor = SMSMarketingActionExecutor()

        lead = Mock()
        lead.first_name = 'Ada'

        subscriber = Mock()
        subscriber.lead = lead
        subscriber.endpoint = Mock()
        subscriber.endpoint.value = '+15551234567'

        # Mock a TemplateVariable that provides {{lead.first_name}}
        var = Mock()
        var.get_placeholder.return_value = '{{lead.first_name}}'
        var.name = 'first_name'
        var.field_name = 'first_name'
        var.category = Mock()
        var.category.name = 'lead'

        qs = Mock()
        qs.select_related.return_value = [var]

        with patch('external_models.models.messages.TemplateVariable.objects.filter', return_value=qs):
            with patch.object(executor.message_sender, 'send_message') as mock_send:
                mock_send.return_value = (True, Mock())
                executor._send_message(
                    subscriber=subscriber,
                    campaign=None,
                    body='Hi {{lead.first_name}}',
                    rule=None,
                    message_type='regular',
                )

        send_kwargs = mock_send.call_args.kwargs
        self.assertEqual(send_kwargs['body'], 'Hi Ada')
