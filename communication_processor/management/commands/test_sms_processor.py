from django.core.management.base import BaseCommand
from django.utils import timezone
from communication_processor.services.sms_processor import SMSProcessor
from communication_processor.models import CommunicationEvent


class Command(BaseCommand):
    help = 'Test the SMS processor with sample data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keyword',
            type=str,
            help='Test a specific reserved keyword (STOP, HELP, INFO, etc.)'
        )
        parser.add_argument(
            '--phone',
            type=str,
            default='+1234567890',
            help='Phone number to use for testing'
        )
        parser.add_argument(
            '--lead-id',
            type=int,
            help='Lead ID to include in the message'
        )
        parser.add_argument(
            '--campaign-id',
            type=int,
            help='Nurturing campaign ID to include in the message'
        )
        parser.add_argument(
            '--participant-id',
            type=int,
            help='Campaign participant ID to include in the message'
        )
        parser.add_argument(
            '--enhanced',
            action='store_true',
            help='Use enhanced message structure with additional context'
        )
        parser.add_argument(
            '--agent-mode',
            action='store_true',
            help='Enable AI agent mode for testing'
        )
        parser.add_argument(
            '--agent-prompt',
            type=str,
            help='Custom prompt for the AI agent'
        )

    def handle(self, *args, **options):
        # Initialize processor
        processor = SMSProcessor('test-queue-url')
        
        # Base event data
        base_event = {
            'message_sid': 'SM1234567890abcdef',
            'sms_message_sid': 'SM1234567890abcdef',
            'sms_sid': 'SM1234567890abcdef',
            'account_sid': 'AC1234567890abcdef',
            'messaging_service_sid': 'MG1234567890abcdef',
            'from_number': options['phone'],
            'to_number': '+1987654321',
            'body': options['keyword'] if options['keyword'] else 'Hello, this is a test message',
            'event_type': 'sms.status',
            'status': 'received',
            'num_segments': 1,
            'num_media': 0,
            'media_url': None,
            'conversation_id': 132,
            'participant_id': 18,
            'direction': 'inbound',
            'channel': 'sms',
        }
        
        # Add enhanced fields if requested
        if options['enhanced']:
            enhanced_fields = {
                'lead_id': options['lead_id'],
                'nurturing_campaign_id': options['campaign_id'],
                'campaign_participant_id': options['participant_id'],
                'lead_phone_number': options['phone'],
                'lead_email': 'test@example.com',
                'lead_first_name': 'Test',
                'lead_last_name': 'User',
                'message_context': {
                    'campaign_name': 'Test Campaign',
                    'campaign_type': 'drip',
                    'step_number': 1,
                    'journey_step_id': 456,
                    'triggered_by': 'scheduled',
                    'original_message_id': 'SM1234567890abcdef',
                    'scheduled_send_time': timezone.now().isoformat(),
                    'message_template_id': 'test_step_1'
                },
                'metadata': {
                    'source_campaign': 'test_2024',
                    'utm_source': 'sms_campaign',
                    'utm_medium': 'sms',
                    'utm_campaign': 'test_series',
                    'utm_content': 'step_1',
                    'utm_term': 'test',
                    'referrer': 'website_form',
                    'landing_page': 'https://example.com/test'
                },
                'processing_hints': {
                    'expected_keywords': ['YES', 'NO', 'STOP', 'HELP', 'INFO'],
                    'auto_response_enabled': True,
                    'require_lead_match': True,
                    'campaign_priority': 'high',
                    'retry_on_failure': True,
                    'max_retries': 3,
                    'timeout_seconds': 30
                },
                'timestamps': {
                    'webhook_received': timezone.now().isoformat(),
                    'message_sent': timezone.now().isoformat(),
                    'message_delivered': timezone.now().isoformat()
                }
            }
            
            # Only add fields that are not None
            for key, value in enhanced_fields.items():
                if value is not None:
                    base_event[key] = value
        
        # Add agent mode if requested
        if options['agent_mode']:
            base_event['agent_mode'] = True
            base_event['agent_config'] = {
                'enabled': True,
                'model': 'gpt-4',
                'temperature': 0.7,
                'max_tokens': 150,
                'prompt': options['agent_prompt'] or "You are a helpful AI assistant for our company. Respond naturally and helpfully to customer inquiries.",
                'context': {
                    'campaign_name': 'Test Campaign',
                    'campaign_type': 'drip',
                    'step_number': 1,
                    'conversation_history': [],
                    'campaign_goals': [
                        'Provide helpful information',
                        'Answer customer questions',
                        'Guide customers through the process'
                    ],
                    'response_style': 'friendly and professional',
                    'include_opt_out_info': True
                },
                'fallback_response': "Thanks for your message! I'm here to help. Please let me know if you have any questions."
            }
        
        self.stdout.write(f"Testing SMS processor with event: {base_event}")
        
        # Validate event
        is_valid = processor.validate_event(base_event)
        self.stdout.write(f"Event validation: {'✅ PASS' if is_valid else '❌ FAIL'}")
        
        if not is_valid:
            self.stdout.write(self.style.ERROR("Event validation failed. Exiting."))
            return
        
        # Process event
        try:
            communication_event = processor.process_event(base_event)
            self.stdout.write(
                self.style.SUCCESS(f"✅ Successfully processed event: {communication_event}")
            )
            
            # Display event details
            self.stdout.write(f"Event Type: {communication_event.event_type}")
            self.stdout.write(f"Channel Type: {communication_event.channel_type}")
            self.stdout.write(f"External ID: {communication_event.external_id}")
            self.stdout.write(f"Lead: {communication_event.lead}")
            self.stdout.write(f"Nurturing Campaign: {communication_event.nurturing_campaign}")
            self.stdout.write(f"Created At: {communication_event.created_at}")
            
            # Display enhanced data if available
            if options['enhanced']:
                event_data = communication_event.event_data
                if 'message_context' in event_data:
                    self.stdout.write(f"Campaign Context: {event_data['message_context']}")
                if 'metadata' in event_data:
                    self.stdout.write(f"Metadata: {event_data['metadata']}")
                if 'processing_hints' in event_data:
                    self.stdout.write(f"Processing Hints: {event_data['processing_hints']}")
            
            # Display agent mode data if available
            if options['agent_mode']:
                event_data = communication_event.event_data
                if 'agent_mode' in event_data:
                    self.stdout.write(f"Agent Mode: {event_data['agent_mode']}")
                if 'agent_config' in event_data:
                    agent_config = event_data['agent_config']
                    self.stdout.write(f"Agent Model: {agent_config.get('model', 'Not specified')}")
                    self.stdout.write(f"Agent Prompt: {agent_config.get('prompt', 'Not specified')[:50]}...")
                
                # Check if agent response event was created
                agent_events = CommunicationEvent.objects.filter(
                    event_type='agent_response',
                    lead=communication_event.lead
                ).order_by('-created_at')
                
                if agent_events.exists():
                    latest_agent_event = agent_events.first()
                    self.stdout.write(f"Agent Response Event: {latest_agent_event}")
                    self.stdout.write(f"Agent Response: {latest_agent_event.event_data.get('body', 'Not found')}")
                else:
                    self.stdout.write("No agent response event found")
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error processing event: {e}")
            )
            import traceback
            self.stdout.write(traceback.format_exc()) 