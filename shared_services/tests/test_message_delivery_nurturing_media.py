"""MessageDeliveryService passes nurturing participant media into email log_context."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from external_models.models.channel_configs import EmailConfig
from shared_services.message_delivery.message_delivery_service import MessageDeliveryService


class MessageDeliveryNurturingMediaTests(SimpleTestCase):
    def test_email_send_merges_nurturing_participant_media_campaign_id(self):
        ec = EmailConfig(
            email_content_mode=EmailConfig.MODE_INLINE,
            content='hello',
        )
        ec.from_endpoint_id = 99

        lead = MagicMock()
        lead.email = 'a@b.com'

        media = MagicMock()
        media.id = 42

        svc = MessageDeliveryService()
        with patch.object(MessageDeliveryService, '_send_email', return_value=(True, MagicMock())) as m_send:
            svc.send_message(
                channel='email',
                content='<p>x</p>',
                lead=lead,
                user=MagicMock(),
                channel_config=ec,
                log_context={'bulk_campaign_message_id': 7},
                media_campaign=media,
            )

        m_send.assert_called_once()
        call_kw = m_send.call_args.kwargs
        log_ctx = call_kw['log_context']
        self.assertEqual(log_ctx['bulk_campaign_message_id'], 7)
        self.assertEqual(log_ctx['nurturing_participant_media_campaign_id'], 42)
        self.assertEqual(log_ctx['contact_endpoint_id'], 99)
