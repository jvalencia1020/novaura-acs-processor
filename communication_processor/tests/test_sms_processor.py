import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.db import transaction

from communication_processor.services.sms_processor import SMSProcessor
from communication_processor.models import CommunicationEvent


class SMSProcessorTestCase(TestCase):
    """Test cases for SMS processor functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.processor = SMSProcessor('test-queue-url')
        
        # Create mock objects instead of real database objects
        self.lead = Mock()
        self.lead.first_name = 'Test'
        self.lead.last_name = 'User'
        self.lead.email = 'test@example.com'
        self.lead.phone_number = '+1234567890'
        self.lead.id = 1
        
        self.nurturing_campaign = Mock()
        self.nurturing_campaign.name = 'Test Campaign'
        self.nurturing_campaign.campaign_type = 'drip'
        self.nurturing_campaign.status = 'active'
        self.nurturing_campaign.id = 1
        
        self.participant = Mock()
        self.participant.lead = self.lead
        self.participant.nurturing_campaign = self.nurturing_campaign
        self.participant.status = 'active'
        self.participant.id = 1
        self.participant.refresh_from_db = Mock()
        self.participant.opt_out = Mock()
        
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
        with patch.object(self.processor.keyword_processing_service, 'check_reserved_keywords') as mock_check:
            mock_check.return_value = 'opt_out'
            action = self.processor.keyword_processing_service.check_reserved_keywords('STOP')
            self.assertEqual(action, 'opt_out')
    
    def test_check_reserved_keywords_help(self):
        """Test reserved keyword detection for HELP."""
        with patch.object(self.processor.keyword_processing_service, 'check_reserved_keywords') as mock_check:
            mock_check.return_value = 'help'
            action = self.processor.keyword_processing_service.check_reserved_keywords('HELP')
            self.assertEqual(action, 'help')
    
    def test_check_reserved_keywords_no_match(self):
        """Test reserved keyword detection with no match."""
        with patch.object(self.processor.keyword_processing_service, 'check_reserved_keywords') as mock_check:
            mock_check.return_value = None
            action = self.processor.keyword_processing_service.check_reserved_keywords('RANDOM')
            self.assertIsNone(action)
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_help_message')
    def test_handle_help_request(self, mock_send_help):
        """Test help request handling."""
        mock_send_help.return_value = True
        
        with patch.object(self.processor.keyword_processing_service, 'handle_reserved_keyword') as mock_handle:
            self.processor.keyword_processing_service.handle_reserved_keyword(
                'help', self.lead, self.nurturing_campaign, '+1234567890', 'HELP', 'sms'
            )
            
            mock_handle.assert_called_once_with(
                'help', self.lead, self.nurturing_campaign, '+1234567890', 'HELP', 'sms'
            )
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_info_message')
    def test_handle_info_request(self, mock_send_info):
        """Test info request handling."""
        mock_send_info.return_value = True
        
        with patch.object(self.processor.keyword_processing_service, 'handle_reserved_keyword') as mock_handle:
            self.processor.keyword_processing_service.handle_reserved_keyword(
                'info', self.lead, self.nurturing_campaign, '+1234567890', 'INFO', 'sms'
            )
            
            mock_handle.assert_called_once_with(
                'info', self.lead, self.nurturing_campaign, '+1234567890', 'INFO', 'sms'
            )
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_opt_out_confirmation')
    def test_handle_opt_out(self, mock_send_opt_out):
        """Test opt-out handling."""
        mock_send_opt_out.return_value = True
        
        with patch.object(self.processor.keyword_processing_service, 'handle_reserved_keyword') as mock_handle:
            self.processor.keyword_processing_service.handle_reserved_keyword(
                'opt_out', self.lead, self.nurturing_campaign, '+1234567890', 'STOP', 'sms'
            )
            
            mock_handle.assert_called_once_with(
                'opt_out', self.lead, self.nurturing_campaign, '+1234567890', 'STOP', 'sms'
            )
    
    @patch('communication_processor.utils.message_sender.MessageSender.send_opt_in_confirmation')
    def test_handle_opt_in(self, mock_send_opt_in):
        """Test opt-in handling."""
        mock_send_opt_in.return_value = True
        
        with patch.object(self.processor.keyword_processing_service, 'handle_reserved_keyword') as mock_handle:
            self.processor.keyword_processing_service.handle_reserved_keyword(
                'opt_in', self.lead, self.nurturing_campaign, '+1234567890', 'START', 'sms'
            )
            
            mock_handle.assert_called_once_with(
                'opt_in', self.lead, self.nurturing_campaign, '+1234567890', 'START', 'sms'
            )
    
    def test_clean_phone_number(self):
        """Test phone number cleaning through shared service."""
        with patch.object(self.processor.lead_matching_service, 'clean_phone_number') as mock_clean:
            mock_clean.return_value = '+1234567890'
            
            # Test with various formats
            test_cases = [
                ('1234567890', '+1234567890'),
                ('+1234567890', '+1234567890'),
                ('(123) 456-7890', '+1234567890'),
                ('123-456-7890', '+1234567890'),
                ('123.456.7890', '+1234567890'),
            ]
            
            for input_phone, expected in test_cases:
                cleaned = self.processor.lead_matching_service.clean_phone_number(input_phone)
                self.assertEqual(cleaned, expected)
    
    def test_process_event_creates_communication_event(self):
        """Test that processing an event creates a communication event."""
        with patch.object(self.processor, 'lead_matching_service') as mock_lead_service:
            mock_lead_service.get_lead_from_event.return_value = self.lead
            
            with patch.object(self.processor, 'campaign_matching_service') as mock_campaign_service:
                mock_campaign_service.find_nurturing_campaign_from_event.return_value = self.nurturing_campaign
                
                with patch.object(self.processor, 'conversation_service') as mock_conversation_service:
                    mock_conversation = Mock()
                    mock_conversation_service.get_or_create_conversation.return_value = mock_conversation
                    
                    mock_participant = Mock()
                    mock_conversation_service.get_or_create_participant.return_value = mock_participant
                    
                    mock_message = Mock()
                    mock_conversation_service.create_conversation_message.return_value = mock_message
                    
                    with patch('communication_processor.models.CommunicationEvent.objects.create') as mock_create:
                        mock_communication_event = Mock()
                        mock_communication_event.event_type = 'message_received'
                        mock_communication_event.channel_type = 'sms'
                        mock_communication_event.external_id = 'SM1234567890abcdef'
                        mock_communication_event.lead = self.lead
                        mock_communication_event.nurturing_campaign = self.nurturing_campaign
                        mock_create.return_value = mock_communication_event
                        
                        communication_event = self.processor.process_event(self.sample_event)
                        
                        # Verify the create method was called with correct parameters
                        mock_create.assert_called_once()
                        call_args = mock_create.call_args[1]  # Get keyword arguments
                        self.assertEqual(call_args['event_type'], 'message_received')
                        self.assertEqual(call_args['channel_type'], 'sms')
                        self.assertEqual(call_args['external_id'], 'SM1234567890abcdef')
                        self.assertEqual(call_args['lead'], self.lead)
                        self.assertEqual(call_args['nurturing_campaign'], self.nurturing_campaign)
                        
                        # Verify the returned object
                        self.assertEqual(communication_event.event_type, 'message_received')
                        self.assertEqual(communication_event.channel_type, 'sms')
                        self.assertEqual(communication_event.external_id, 'SM1234567890abcdef')
                        self.assertEqual(communication_event.lead, self.lead)
                        self.assertEqual(communication_event.nurturing_campaign, self.nurturing_campaign)
    
    def test_process_regular_message_updates_lead_engagement(self):
        """Test that regular messages update lead engagement."""
        with patch.object(self.processor, '_process_campaign_response') as mock_campaign_response:
            self.processor._process_regular_message(
                self.sample_event, self.lead, self.nurturing_campaign, None
            )
            
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


class SMSProcessorIntegrationTestCase(TestCase):
    """Integration tests for SMS processor with database operations."""
    
    def setUp(self):
        """Set up test data."""
        self.processor = SMSProcessor('test-queue-url')
        
        # Create mock objects
        self.lead = Mock()
        self.lead.first_name = 'Integration'
        self.lead.last_name = 'Test'
        self.lead.email = 'integration@example.com'
        self.lead.phone_number = '+1234567890'
        self.lead.id = 1
        
        self.nurturing_campaign = Mock()
        self.nurturing_campaign.name = 'Integration Test Campaign'
        self.nurturing_campaign.campaign_type = 'journey'
        self.nurturing_campaign.status = 'active'
        self.nurturing_campaign.id = 1
        
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
    
    def test_full_opt_out_flow(self):
        """Test the complete opt-out flow."""
        with patch.object(self.processor, 'lead_matching_service') as mock_lead_service:
            mock_lead_service.get_lead_from_event.return_value = self.lead
            
            with patch.object(self.processor, 'campaign_matching_service') as mock_campaign_service:
                mock_campaign_service.find_nurturing_campaign_from_event.return_value = self.nurturing_campaign
                
                with patch.object(self.processor, 'conversation_service') as mock_conversation_service:
                    mock_conversation = Mock()
                    mock_conversation_service.get_or_create_conversation.return_value = mock_conversation
                    
                    mock_participant = Mock()
                    mock_conversation_service.get_or_create_participant.return_value = mock_participant
                    
                    mock_message = Mock()
                    mock_conversation_service.create_conversation_message.return_value = mock_message
                    
                    with patch('communication_processor.models.CommunicationEvent.objects.create') as mock_create:
                        mock_communication_event = Mock()
                        mock_communication_event.event_type = 'message_received'
                        mock_communication_event.channel_type = 'sms'
                        mock_communication_event.external_id = 'SM1234567890abcdef'
                        mock_communication_event.lead = self.lead
                        mock_communication_event.nurturing_campaign = self.nurturing_campaign
                        mock_create.return_value = mock_communication_event
                        
                        # Process the event
                        communication_event = self.processor.process_event(self.sample_event)
                        
                        # Verify communication event was created
                        mock_create.assert_called_once()
                        call_args = mock_create.call_args[1]  # Get keyword arguments
                        self.assertEqual(call_args['event_type'], 'message_received')
                        self.assertEqual(call_args['channel_type'], 'sms')
                        self.assertEqual(call_args['external_id'], 'SM1234567890abcdef')
                        self.assertEqual(call_args['lead'], self.lead)
                        self.assertEqual(call_args['nurturing_campaign'], self.nurturing_campaign)
                        
                        # Verify the returned object
                        self.assertEqual(communication_event.event_type, 'message_received')
                        self.assertEqual(communication_event.lead, self.lead)
                        self.assertEqual(communication_event.nurturing_campaign, self.nurturing_campaign) 