import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.db import transaction

from communication_processor.services.sms_processor import SMSProcessor
from communication_processor.models import CommunicationEvent
from external_models.models.communications import Conversation, ConversationMessage, Participant
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant


class SMSProcessorTestCase(TestCase):
    """Test cases for SMS processor functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.processor = SMSProcessor('test-queue-url')
        
        # Create test lead
        self.lead = Lead.objects.create(
            first_name='Test',
            last_name='User',
            email='test@example.com',
            phone_number='+1234567890'
        )
        
        # Create test campaign
        self.campaign = LeadNurturingCampaign.objects.create(
            name='Test Campaign',
            campaign_type='drip',
            status='active'
        )
        
        # Create test participant
        self.participant = LeadNurturingParticipant.objects.create(
            lead=self.lead,
            nurturing_campaign=self.campaign,
            status='active'
        )
        
        # Sample event data
        self.sample_event = {
            'MessageSid': 'SM1234567890abcdef',
            'AccountSid': 'AC1234567890abcdef',
            'From': '+1234567890',
            'To': '+1987654321',
            'Body': 'Hello, this is a test message',
            'Direction': 'inbound',
            'MessageStatus': 'received',
            'NumSegments': 1,
            'NumMedia': 0,
            'MessagingServiceSid': 'MG1234567890abcdef',
            'ConversationSid': 'CH1234567890abcdef',
        }
    
    def test_validate_event_valid(self):
        """Test event validation with valid data."""
        is_valid = self.processor.validate_event(self.sample_event)
        self.assertTrue(is_valid)
    
    def test_validate_event_missing_required_fields(self):
        """Test event validation with missing required fields."""
        invalid_event = {'MessageSid': 'SM1234567890abcdef'}  # Missing AccountSid
        is_valid = self.processor.validate_event(invalid_event)
        self.assertFalse(is_valid)
    
    def test_validate_event_invalid_message_sid(self):
        """Test event validation with invalid MessageSid format."""
        invalid_event = self.sample_event.copy()
        invalid_event['MessageSid'] = 'INVALID123'
        is_valid = self.processor.validate_event(invalid_event)
        self.assertFalse(is_valid)
    
    def test_determine_event_type_inbound(self):
        """Test event type determination for inbound messages."""
        event_type = self.processor._determine_event_type(self.sample_event)
        self.assertEqual(event_type, 'message_received')
    
    def test_determine_event_type_outbound(self):
        """Test event type determination for outbound messages."""
        outbound_event = self.sample_event.copy()
        outbound_event['Direction'] = 'outbound-api'
        event_type = self.processor._determine_event_type(outbound_event)
        self.assertEqual(event_type, 'message_sent')
    
    def test_determine_event_type_delivered(self):
        """Test event type determination for delivery status."""
        delivered_event = self.sample_event.copy()
        delivered_event['MessageStatus'] = 'delivered'
        event_type = self.processor._determine_event_type(delivered_event)
        self.assertEqual(event_type, 'delivery_status')
    
    def test_check_reserved_keywords_stop(self):
        """Test reserved keyword detection for STOP."""
        action = self.processor._check_reserved_keywords('STOP')
        self.assertEqual(action, 'opt_out')
    
    def test_check_reserved_keywords_help(self):
        """Test reserved keyword detection for HELP."""
        action = self.processor._check_reserved_keywords('HELP')
        self.assertEqual(action, 'help')
    
    def test_check_reserved_keywords_no_match(self):
        """Test reserved keyword detection with no match."""
        action = self.processor._check_reserved_keywords('RANDOM')
        self.assertIsNone(action)
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_help_message')
    def test_handle_help_request(self, mock_send_help):
        """Test help request handling."""
        mock_send_help.return_value = True
        
        self.processor._handle_help_request(
            self.lead, self.campaign, '+1234567890'
        )
        
        mock_send_help.assert_called_once_with('+1234567890')
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_info_message')
    def test_handle_info_request(self, mock_send_info):
        """Test info request handling."""
        mock_send_info.return_value = True
        
        self.processor._handle_info_request(
            self.lead, self.campaign, '+1234567890'
        )
        
        mock_send_info.assert_called_once_with('+1234567890', 'Test Campaign')
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_opt_out_confirmation')
    def test_handle_opt_out(self, mock_send_opt_out):
        """Test opt-out handling."""
        mock_send_opt_out.return_value = True
        
        self.processor._handle_opt_out(
            self.lead, self.campaign, '+1234567890'
        )
        
        # Check that participant was opted out
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.status, 'opted_out')
        
        # Check that confirmation message was sent
        mock_send_opt_out.assert_called_once_with('+1234567890', 'Test Campaign')
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_opt_in_confirmation')
    def test_handle_opt_in(self, mock_send_opt_in):
        """Test opt-in handling."""
        # First opt out the participant
        self.participant.opt_out()
        self.assertEqual(self.participant.status, 'opted_out')
        
        mock_send_opt_in.return_value = True
        
        self.processor._handle_opt_in(
            self.lead, self.campaign, '+1234567890'
        )
        
        # Check that participant was opted back in
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.status, 'active')
        
        # Check that confirmation message was sent
        mock_send_opt_in.assert_called_once_with('+1234567890', 'Test Campaign')
    
    def test_clean_phone_number(self):
        """Test phone number cleaning."""
        # Test with various formats
        test_cases = [
            ('1234567890', '+1234567890'),
            ('+1234567890', '+1234567890'),
            ('(123) 456-7890', '+1234567890'),
            ('123-456-7890', '+1234567890'),
            ('123.456.7890', '+1234567890'),
        ]
        
        for input_phone, expected in test_cases:
            cleaned = self.processor._clean_phone_number(input_phone)
            self.assertEqual(cleaned, expected)
    
    @patch('communication_processor.services.sms_processor.SMSProcessor._get_lead_by_phone')
    def test_process_event_creates_communication_event(self, mock_get_lead):
        """Test that processing an event creates a communication event."""
        mock_get_lead.return_value = self.lead
        
        with patch.object(self.processor, '_find_nurturing_campaign') as mock_find_campaign:
            mock_find_campaign.return_value = self.campaign
            
            communication_event = self.processor.process_event(self.sample_event)
            
            self.assertIsInstance(communication_event, CommunicationEvent)
            self.assertEqual(communication_event.event_type, 'message_received')
            self.assertEqual(communication_event.channel_type, 'sms')
            self.assertEqual(communication_event.external_id, 'SM1234567890abcdef')
            self.assertEqual(communication_event.lead, self.lead)
            self.assertEqual(communication_event.nurturing_campaign, self.campaign)
    
    def test_process_regular_message_updates_lead_engagement(self):
        """Test that regular messages update lead engagement."""
        with patch.object(self.processor, '_process_campaign_response') as mock_campaign_response:
            self.processor._process_regular_message(
                self.sample_event, self.lead, self.campaign, None
            )
            
            # Check that lead's last_contact_date was updated
            self.lead.refresh_from_db()
            self.assertIsNotNone(self.lead.last_contact_date)
            
            # Check that campaign response was processed
            mock_campaign_response.assert_called_once()
    
    @patch('external_models.models.journeys.JourneyEvent.objects.create')
    def test_process_journey_response(self, mock_create_journey_event):
        """Test journey response processing."""
        with patch('external_models.models.journeys.EventType.objects.get') as mock_get_event_type:
            mock_event_type = Mock()
            mock_get_event_type.return_value = mock_event_type
            
            self.processor._process_journey_response(
                self.sample_event, self.participant, None
            )
            
            # Check that journey event was created
            mock_create_journey_event.assert_called_once()
            call_args = mock_create_journey_event.call_args
            self.assertEqual(call_args[1]['participant'], self.participant)
            self.assertEqual(call_args[1]['event_type'], mock_event_type)
    
    def test_process_bulk_campaign_response(self):
        """Test bulk campaign response processing."""
        with patch.object(self.participant, 'update_campaign_progress') as mock_update_progress:
            self.processor._process_bulk_campaign_response(
                self.sample_event, self.participant, None
            )
            
            # Check that campaign progress was updated
            mock_update_progress.assert_called_once()
            
            # Check that participant's last_event_at was updated
            self.participant.refresh_from_db()
            self.assertIsNotNone(self.participant.last_event_at)


class SMSProcessorIntegrationTestCase(TestCase):
    """Integration tests for SMS processor with database operations."""
    
    def setUp(self):
        """Set up test data."""
        self.processor = SMSProcessor('test-queue-url')
        
        # Create test lead
        self.lead = Lead.objects.create(
            first_name='Integration',
            last_name='Test',
            email='integration@example.com',
            phone_number='+1234567890'
        )
        
        # Create test campaign
        self.campaign = LeadNurturingCampaign.objects.create(
            name='Integration Test Campaign',
            campaign_type='journey',
            status='active'
        )
        
        # Sample event data
        self.sample_event = {
            'MessageSid': 'SM1234567890abcdef',
            'AccountSid': 'AC1234567890abcdef',
            'From': '+1234567890',
            'To': '+1987654321',
            'Body': 'STOP',
            'Direction': 'inbound',
            'MessageStatus': 'received',
            'NumSegments': 1,
            'NumMedia': 0,
            'MessagingServiceSid': 'MG1234567890abcdef',
            'ConversationSid': 'CH1234567890abcdef',
        }
    
    @patch('communication_processor.services.sms_processor.SMSProcessor._get_lead_by_phone')
    @patch('communication_processor.services.sms_processor.SMSProcessor._find_nurturing_campaign')
    @patch('communication_processor.utils.message_sender.MessageSender.send_opt_out_confirmation')
    def test_full_opt_out_flow(self, mock_send_opt_out, mock_find_campaign, mock_get_lead):
        """Test the complete opt-out flow."""
        # Setup mocks
        mock_get_lead.return_value = self.lead
        mock_find_campaign.return_value = self.campaign
        mock_send_opt_out.return_value = True
        
        # Create participant
        participant = LeadNurturingParticipant.objects.create(
            lead=self.lead,
            nurturing_campaign=self.campaign,
            status='active'
        )
        
        # Process the event
        communication_event = self.processor.process_event(self.sample_event)
        
        # Verify communication event was created
        self.assertIsInstance(communication_event, CommunicationEvent)
        self.assertEqual(communication_event.event_type, 'message_received')
        self.assertEqual(communication_event.lead, self.lead)
        self.assertEqual(communication_event.nurturing_campaign, self.campaign)
        
        # Verify participant was opted out
        participant.refresh_from_db()
        self.assertEqual(participant.status, 'opted_out')
        
        # Verify confirmation message was sent
        mock_send_opt_out.assert_called_once_with('+1234567890', 'Integration Test Campaign') 