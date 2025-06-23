from django.core.management.base import BaseCommand
from django.utils import timezone
from communication_processor.utils.message_builder import SQSMessageBuilder, build_inbound_sms_message, build_campaign_response_message, build_agent_message
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant

import os


class Command(BaseCommand):
    help = 'Build enhanced SQS messages for testing and demonstration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            type=str,
            choices=['basic', 'enhanced', 'campaign', 'opt-out', 'delivery-status', 'agent'],
            default='basic',
            help='Type of message to build'
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
            '--phone',
            type=str,
            default='+1234567890',
            help='Phone number to use'
        )
        parser.add_argument(
            '--keyword',
            type=str,
            default='STOP',
            help='Keyword for opt-out messages'
        )
        parser.add_argument(
            '--output',
            type=str,
            choices=['dict', 'json'],
            default='dict',
            help='Output format'
        )
        parser.add_argument(
            '--agent-mode',
            action='store_true',
            help='Enable AI agent mode for message processing'
        )
        parser.add_argument(
            '--agent-prompt',
            type=str,
            help='Custom prompt for the AI agent'
        )
        parser.add_argument(
            '--agent-model',
            type=str,
            default='gpt-4',
            help='AI model to use for agent responses'
        )

    def handle(self, *args, **options):
        # Sample Twilio data
        twilio_data = {
            'MessageSid': 'SMc9d0fb007afd53a7c1aad1bd86f23f60',
            'SmsMessageSid': 'SMc9d0fb007afd53a7c1aad1bd86f23f60',
            'SmsSid': 'SMc9d0fb007afd53a7c1aad1bd86f23f60',
            'AccountSid': os.getenv('TWILIO_SID'),
            'MessagingServiceSid': 'MGfa5a3f72d04342db7f5ec0da1e766174',
            'From': options['phone'],
            'To': '+18883034619',
            'Body': 'Hello, I need help with your services',
            'Direction': 'inbound',
            'MessageStatus': 'received',
            'NumSegments': 1,
            'NumMedia': 0,
            'MediaUrl': None,
        }
        
        # Get lead and campaign if IDs provided
        lead = None
        nurturing_campaign = None
        campaign_participant = None
        
        if options['lead_id']:
            try:
                lead = Lead.objects.get(id=options['lead_id'])
                self.stdout.write(f"Found lead: {lead.first_name} {lead.last_name} ({lead.email})")
            except Lead.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Lead with ID {options['lead_id']} not found"))
        
        if options['campaign_id']:
            try:
                nurturing_campaign = LeadNurturingCampaign.objects.get(id=options['campaign_id'])
                self.stdout.write(f"Found campaign: {nurturing_campaign.name} ({nurturing_campaign.campaign_type})")
                
                # Find campaign participant if lead is provided
                if lead:
                    campaign_participant = LeadNurturingParticipant.objects.filter(
                        lead=lead,
                        nurturing_campaign=nurturing_campaign,
                        status='active'
                    ).first()
                    if campaign_participant:
                        self.stdout.write(f"Found campaign participant: ID {campaign_participant.id}")
            except LeadNurturingCampaign.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Campaign with ID {options['campaign_id']} not found"))
        
        # Build message based on type
        message = None
        
        if options['type'] == 'basic':
            message = SQSMessageBuilder.build_sms_message(twilio_data)
            
        elif options['type'] == 'enhanced':
            message = SQSMessageBuilder.build_sms_message(
                twilio_data, lead, nurturing_campaign, campaign_participant
            )
            
        elif options['type'] == 'campaign':
            if not lead or not nurturing_campaign:
                self.stdout.write(self.style.ERROR("Campaign messages require both --lead-id and --campaign-id"))
                return
            
            if not campaign_participant:
                self.stdout.write(self.style.WARNING("No active campaign participant found"))
                return
            
            message = build_campaign_response_message(
                twilio_data, lead, nurturing_campaign, campaign_participant, step_number=1
            )
            
        elif options['type'] == 'opt-out':
            message = SQSMessageBuilder.build_opt_out_message(
                options['phone'], lead, nurturing_campaign, campaign_participant, options['keyword']
            )
            
        elif options['type'] == 'delivery-status':
            # Modify Twilio data for delivery status
            delivery_data = twilio_data.copy()
            delivery_data['MessageStatus'] = 'delivered'
            delivery_data['DateCreated'] = timezone.now().isoformat()
            delivery_data['DateUpdated'] = timezone.now().isoformat()
            
            message = SQSMessageBuilder.build_delivery_status_message(
                delivery_data, lead, nurturing_campaign, campaign_participant
            )
            
        elif options['type'] == 'agent':
            # Build agent message
            agent_prompt = options['agent_prompt'] or "You are a helpful customer service AI assistant. Respond naturally and helpfully to customer inquiries."
            
            message = build_agent_message(
                twilio_data, lead, nurturing_campaign, campaign_participant,
                agent_prompt=agent_prompt
            )
        
        # Add agent mode to any message type if requested
        if options['agent_mode'] and options['type'] != 'agent':
            message['agent_mode'] = True
            message['agent_config'] = {
                'enabled': True,
                'model': options['agent_model'],
                'temperature': 0.7,
                'max_tokens': 150,
                'prompt': options['agent_prompt'] or "You are a helpful AI assistant. Respond naturally and helpfully to customer inquiries.",
                'context': {
                    'campaign_name': nurturing_campaign.name if nurturing_campaign else 'General',
                    'campaign_type': nurturing_campaign.campaign_type if nurturing_campaign else 'general',
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
        
        # Output the message
        if options['output'] == 'json':
            output = SQSMessageBuilder.to_json(message)
            self.stdout.write("Generated SQS Message (JSON):")
            self.stdout.write(output)
        else:
            self.stdout.write("Generated SQS Message (Dictionary):")
            self.stdout.write(str(message))
        
        # Show key fields
        self.stdout.write("\n" + "="*50)
        self.stdout.write("KEY FIELDS:")
        self.stdout.write(f"Event Type: {message.get('event_type')}")
        self.stdout.write(f"From: {message.get('from_number')}")
        self.stdout.write(f"Body: {message.get('body')}")
        self.stdout.write(f"Lead ID: {message.get('lead_id', 'Not provided')}")
        self.stdout.write(f"Campaign ID: {message.get('nurturing_campaign_id', 'Not provided')}")
        self.stdout.write(f"Participant ID: {message.get('campaign_participant_id', 'Not provided')}")
        self.stdout.write(f"Agent Mode: {message.get('agent_mode', False)}")
        
        if 'message_context' in message:
            context = message['message_context']
            self.stdout.write(f"Campaign Name: {context.get('campaign_name', 'Not provided')}")
            self.stdout.write(f"Step Number: {context.get('step_number', 'Not provided')}")
        
        if 'processing_hints' in message:
            hints = message['processing_hints']
            self.stdout.write(f"Expected Keywords: {hints.get('expected_keywords', [])}")
            self.stdout.write(f"Auto Response: {hints.get('auto_response_enabled', False)}")
        
        if 'agent_config' in message:
            agent_config = message['agent_config']
            self.stdout.write(f"Agent Model: {agent_config.get('model', 'Not specified')}")
            self.stdout.write(f"Agent Enabled: {agent_config.get('enabled', False)}")
            self.stdout.write(f"Agent Prompt: {agent_config.get('prompt', 'Not specified')[:50]}...")
        
        self.stdout.write("="*50)
        
        # Usage instructions
        self.stdout.write("\nUSAGE INSTRUCTIONS:")
        self.stdout.write("1. Copy the message to your SQS queue")
        self.stdout.write("2. The communication processor will automatically handle it")
        self.stdout.write("3. Check the admin interface for processing results")
        
        if options['type'] == 'opt-out':
            self.stdout.write("\nOPT-OUT PROCESSING:")
            self.stdout.write("- User will be opted out from the campaign")
            self.stdout.write("- Confirmation message will be sent")
            self.stdout.write("- Lead status will be updated")
        
        elif options['type'] == 'campaign':
            self.stdout.write("\nCAMPAIGN RESPONSE PROCESSING:")
            self.stdout.write("- Response will be logged in campaign participant")
            self.stdout.write("- Journey events will be created (if journey campaign)")
            self.stdout.write("- Campaign progress will be updated")
        
        elif options['type'] == 'agent' or options['agent_mode']:
            self.stdout.write("\nAI AGENT PROCESSING:")
            self.stdout.write("- AI agent will generate a response")
            self.stdout.write("- Response will be sent back to the user")
            self.stdout.write("- Agent response event will be created")
            self.stdout.write("- Conversation history will be updated") 