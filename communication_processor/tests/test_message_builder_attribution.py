"""SQS envelope optional crm_campaign_id / media_campaign_id fields."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from communication_processor.utils.message_builder import SQSMessageBuilder, build_agent_message


class SQSMessageBuilderAttributionTests(SimpleTestCase):
    _twilio = {
        'MessageSid': 'SM123',
        'From': '+15550001111',
        'To': '+15550002222',
        'Body': 'hi',
        'Direction': 'inbound',
        'MessageStatus': 'received',
    }

    def test_build_sms_message_adds_crm_and_media_ids(self):
        crm = SimpleNamespace(id=42)
        media = SimpleNamespace(id=9001)
        msg = SQSMessageBuilder.build_sms_message(
            self._twilio,
            crm_campaign=crm,
            media_campaign=media,
        )
        self.assertEqual(msg['crm_campaign_id'], 42)
        self.assertEqual(msg['media_campaign_id'], 9001)

    def test_build_delivery_status_forwards_attribution(self):
        crm = SimpleNamespace(id=7)
        media = SimpleNamespace(id=8)
        msg = SQSMessageBuilder.build_delivery_status_message(
            {**self._twilio, 'MessageStatus': 'delivered'},
            crm_campaign=crm,
            media_campaign=media,
        )
        self.assertEqual(msg['event_type'], 'sms.delivery_status')
        self.assertEqual(msg['crm_campaign_id'], 7)
        self.assertEqual(msg['media_campaign_id'], 8)

    def test_build_opt_out_forwards_attribution(self):
        crm = SimpleNamespace(id=1)
        media = SimpleNamespace(id=2)
        msg = SQSMessageBuilder.build_opt_out_message(
            '+15550003333',
            crm_campaign=crm,
            media_campaign=media,
        )
        self.assertEqual(msg['event_type'], 'sms.opt_out')
        self.assertEqual(msg['crm_campaign_id'], 1)
        self.assertEqual(msg['media_campaign_id'], 2)

    def test_build_agent_message_wrapper_forwards_attribution(self):
        crm = SimpleNamespace(id=99)
        media = SimpleNamespace(id=100)
        msg = build_agent_message(
            self._twilio,
            crm_campaign=crm,
            media_campaign=media,
        )
        self.assertTrue(msg.get('agent_mode'))
        self.assertEqual(msg['crm_campaign_id'], 99)
        self.assertEqual(msg['media_campaign_id'], 100)
