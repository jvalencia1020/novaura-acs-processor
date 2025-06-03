import logging
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from twilio.rest import Client
import pytz
from datetime import timedelta

from external_models.models.nurturing_campaigns import (
    LeadNurturingCampaign,
    LeadNurturingParticipant,
    BulkCampaignMessage,
)

from external_models.models.drip_campaigns import (
    DripCampaignMessageStep,
    DripCampaignProgress,
    DripCampaignSchedule
)

from external_models.models.reminder_campaigns import (
    ReminderCampaignProgress,
    ReminderCampaignSchedule,
    ReminderTime
)

from external_models.models.blast_campaigns import (
    BlastCampaignProgress,
    BlastCampaignSchedule
)

from external_models.models.communications import (
    Conversation,
    Participant,
    ConversationMessage,
    ConversationThread,
    ThreadMessage
)

from django.conf import settings
import time

logger = logging.getLogger(__name__)

class BulkCampaignProcessor:
    """
    Service class for processing bulk nurturing campaigns
    Handles drip campaigns, reminder campaigns, and blast campaigns
    """

    def __init__(self):
        self.campaign_processors = {
            'drip': self._process_drip_campaign,
            'reminder': self._process_reminder_campaign,
            'blast': self._process_blast_campaign
        }

    def process_campaign(self, campaign):
        """
        Process a bulk nurturing campaign based on its type

        Args:
            campaign: LeadNurturingCampaign instance

        Returns:
            int: Number of messages scheduled/sent
        """
        if not campaign.is_active_or_scheduled():
            logger.warning(f"Skipping inactive campaign {campaign.id} - Status: {campaign.status}")
            return 0

        processor = self.campaign_processors.get(campaign.campaign_type)
        if not processor:
            logger.error(f"No processor found for campaign type: {campaign.campaign_type}")
            return 0

        try:
            result = processor(campaign)
            return result
        except Exception as e:
            logger.exception(f"Error processing campaign {campaign.id}: {str(e)}")
            return 0

    def process_due_messages(self):
        """
        Process all messages that are due to be sent
        This should be run periodically by a scheduled task

        Returns:
            int: Number of messages processed
        """
        # Find all pending messages that are due
        due_messages = BulkCampaignMessage.objects.filter(
            status__in=['pending', 'scheduled'],
            scheduled_for__lte=timezone.now()
        ).select_related(
            'campaign',
            'participant',
            'participant__lead'
        )

        processed_count = 0

        for message in due_messages:
            try:
                if self._send_message(message):
                    processed_count += 1
            except Exception as e:
                logger.exception(f"Error processing message {message.id}: {e}")

        return processed_count

    def _process_drip_campaign(self, campaign):
        """Process a drip campaign"""
        if not campaign.drip_schedule:
            logger.error(f"Drip campaign {campaign.id} has no schedule")
            return 0

        schedule = campaign.drip_schedule
        now = timezone.now()

        # Find active participants that need messages
        participants = LeadNurturingParticipant.objects.filter(
            nurturing_campaign=campaign,
            status='active'
        ).select_related('lead')

        scheduled_count = 0

        for participant in participants:
            try:
                # Get or create progress
                progress = participant.drip_campaign_progress.first()
                
                # If no progress exists, we should start with the first step
                if not progress:
                    first_step = schedule.message_steps.order_by('order').first()
                    if not first_step:
                        logger.error(f"No message steps found for drip schedule {schedule.id}")
                        continue
                    
                    progress = DripCampaignProgress.objects.create(
                        participant=participant,
                        current_step=first_step,
                        next_scheduled_interval=now
                    )
                
                # If no current step, we're done with the sequence
                if not progress.current_step:
                    continue
                
                # Check if it's time for next message
                should_send = self._should_send_drip_message(participant, schedule)
                
                if not should_send:
                    continue

                # Schedule next message
                if self._schedule_drip_message(participant, schedule):
                    scheduled_count += 1

            except Exception as e:
                logger.exception(f"Error processing participant {participant.id}: {str(e)}")
                continue

        return scheduled_count

    def _process_reminder_campaign(self, campaign):
        """Process a reminder campaign"""
        if not campaign.reminder_schedule:
            logger.error(f"Reminder campaign {campaign.id} has no schedule")
            return 0

        schedule = campaign.reminder_schedule
        now = timezone.now()

        # Find active participants that need reminders and have scheduled reachouts
        participants = LeadNurturingParticipant.objects.filter(
            nurturing_campaign=campaign,
            status='active',
            lead__scheduled_reachouts__status='open'  # Only include leads with open scheduled reachouts
        ).select_related('lead').distinct()

        scheduled_count = 0

        for participant in participants:
            # Get the scheduled reachout for this lead
            scheduled_reachout = participant.lead.scheduled_reachouts.filter(
                status='open'
            ).order_by('scheduled_date').first()

            if not scheduled_reachout:
                continue

            # Find next reminder time
            next_reminder = self._get_next_reminder_time(participant, schedule)
            if not next_reminder:
                continue

            # Schedule reminder
            if self._schedule_reminder_message(participant, next_reminder, scheduled_reachout):
                scheduled_count += 1

        return scheduled_count

    def _process_blast_campaign(self, campaign):
        """Process a blast campaign"""
        if not campaign.blast_schedule:
            logger.error(f"Blast campaign {campaign.id} has no schedule")
            return 0

        schedule = campaign.blast_schedule
        now = timezone.now()

        # Check if it's time to send the blast
        if schedule.send_time > now:
            return 0

        # Check if campaign is active
        if not campaign.is_active_or_scheduled():
            return 0

        # Find active participants that haven't received the blast
        participants = LeadNurturingParticipant.objects.filter(
            nurturing_campaign=campaign,
            status='active'
        ).exclude(
            bulk_messages__campaign=campaign
        ).select_related('lead')

        scheduled_count = 0

        for participant in participants:
            try:
                # Check if we should send based on business hours
                if schedule.business_hours_only:
                    current_time = now.time()
                    if current_time < schedule.start_time:
                        continue

                # Schedule blast message
                if self._schedule_blast_message(participant, schedule):
                    scheduled_count += 1

            except Exception as e:
                logger.exception(f"Error processing participant {participant.id}: {e}")
                continue

        return scheduled_count

    def _should_send_drip_message(self, participant, schedule):
        """Check if it's time to send the next message for a participant"""
        progress = participant.drip_campaign_progress.first()
        if not progress:
            logger.error(f"No progress found for participant {participant.id}")
            return False

        if not progress.current_step:
            return False

        now = timezone.now()

        # Check if we're past the scheduled time
        if now < progress.next_scheduled_interval:
            return False

        # Check business hours if enabled
        if schedule.business_hours_only:
            current_hour = now.hour
            if current_hour < schedule.start_time or current_hour >= schedule.end_time:
                return False

        # Check weekend restrictions if enabled
        if schedule.exclude_weekends:
            if now.weekday() >= 5:  # 5 is Saturday, 6 is Sunday
                return False

        return True

    def _get_next_reminder_time(self, participant, schedule):
        """Get the next reminder time for a participant"""
        # Get all reminder times ordered appropriately
        reminder_times = schedule.reminder_times.all().order_by(
            'days_before', 'days_before_relative', 'hours_before', 'minutes_before'
        )

        # Get the scheduled reachout for this lead
        scheduled_reachout = participant.lead.scheduled_reachouts.filter(
            status='open'
        ).order_by('scheduled_date').first()

        if not scheduled_reachout:
            logger.warning(f"No scheduled reachout found for participant {participant.id}")
            return None

        if schedule.use_relative_schedule:
            # For relative scheduling, we need the scheduled reachout date
            appointment_time = scheduled_reachout.scheduled_date
            if not appointment_time:
                logger.warning(f"No scheduled date found for participant {participant.id}")
                return None

            # Get all sent reminders for this participant
            sent_reminders = participant.reminder_campaign_progress.all()
            
            # For relative scheduling, we need to check if we've already sent reminders
            # with the same relative timing
            for reminder in reminder_times:
                # Calculate total minutes before appointment
                total_minutes = reminder.get_total_minutes_before()
                
                # Check if we've already sent a reminder at this relative time
                already_sent = False
                for sent_reminder in sent_reminders:
                    # Calculate the time difference between the sent reminder and appointment
                    if sent_reminder.sent_at:
                        time_diff = appointment_time - sent_reminder.sent_at
                        sent_minutes = time_diff.total_seconds() / 60
                        if abs(sent_minutes - total_minutes) < 1:  # Allow 1 minute tolerance
                            already_sent = True
                            break
                
                if not already_sent:
                    return reminder

        else:
            # For absolute scheduling
            sent_days = set(
                participant.reminder_campaign_progress.values_list('days_before', flat=True)
            )

            for reminder in reminder_times:
                if reminder.days_before not in sent_days:
                    return reminder

        return None

    def _schedule_drip_message(self, participant, schedule):
        """Schedule a drip campaign message"""
        try:
            with transaction.atomic():
                # Get or create progress
                progress = participant.drip_campaign_progress.first()
                if not progress:
                    # Start with the first step
                    first_step = schedule.message_steps.order_by('order').first()
                    if not first_step:
                        logger.error(f"No message steps found for drip schedule {schedule.id}")
                        return False
                    
                    progress = DripCampaignProgress.objects.create(
                        participant=participant,
                        current_step=first_step,
                        next_scheduled_interval=timezone.now()
                    )
                
                # Get the current step
                current_step = progress.current_step
                if not current_step:
                    logger.debug(f"Participant {participant.id} has no current step")
                    return False
                
                # Calculate next send time
                now = timezone.now()
                next_time = now + current_step.get_delay_timedelta()
                
                # Apply business hours restrictions
                if schedule.business_hours_only:
                    if next_time.time() < schedule.start_time:
                        next_time = timezone.make_aware(
                            timezone.datetime.combine(next_time.date(), schedule.start_time)
                        )
                    elif next_time.time() > schedule.end_time:
                        next_time = timezone.make_aware(
                            timezone.datetime.combine(next_time.date() + timedelta(days=1), schedule.start_time)
                        )
                
                # Apply weekend restrictions
                if schedule.exclude_weekends:
                    while next_time.weekday() >= 5:
                        next_time += timedelta(days=1)
                
                # Update progress with next interval
                progress.next_scheduled_interval = next_time
                progress.save()
                
                # Validate message step has content
                if not current_step.template and not current_step.content:
                    logger.error(f"Message step {current_step.id} has no content or template")
                    return False

                # Create message
                try:
                    message = BulkCampaignMessage.objects.create(
                        campaign=participant.nurturing_campaign,
                        participant=participant,
                        status='scheduled',
                        scheduled_for=next_time,
                        drip_message_step=current_step,
                        step_order=current_step.order
                    )
                except Exception as e:
                    logger.error(f"Failed to create message for participant {participant.id}: {str(e)}")
                    return False
                
                # Update participant progress
                try:
                    participant.update_campaign_progress(
                        scheduled_time=next_time
                    )
                except Exception as e:
                    logger.error(f"Failed to update participant progress for {participant.id}: {str(e)}")
                    return False
                
                return True
                
        except Exception as e:
            logger.exception(f"Error scheduling drip message for participant {participant.id}: {str(e)}")
            return False

    def _schedule_reminder_message(self, participant, reminder, scheduled_reachout):
        """Schedule a reminder campaign message"""
        try:
            with transaction.atomic():
                # Calculate send time based on reminder settings and scheduled reachout date
                send_time = self._calculate_reminder_time(reminder, participant, scheduled_reachout.scheduled_date)

                if not send_time:
                    logger.debug(f"No valid send time calculated for participant {participant.id}")
                    return False

                # Create message
                message = BulkCampaignMessage.objects.create(
                    campaign=participant.nurturing_campaign,
                    participant=participant,
                    status='scheduled',
                    scheduled_for=send_time
                )

                # Create progress record
                if reminder.schedule.use_relative_schedule:
                    # For relative scheduling, store all the relative timing fields
                    ReminderCampaignProgress.objects.create(
                        participant=participant,
                        days_before_relative=reminder.days_before_relative,
                        hours_before=reminder.hours_before,
                        minutes_before=reminder.minutes_before,
                        sent_at=send_time,
                        reminder_time=reminder
                    )
                else:
                    # For absolute scheduling
                    ReminderCampaignProgress.objects.create(
                        participant=participant,
                        days_before=reminder.days_before,
                        time=reminder.time,
                        sent_at=send_time,
                        reminder_time=reminder
                    )

                # Update participant progress
                participant.update_campaign_progress(
                    scheduled_time=message.scheduled_for
                )

                return True
        except Exception as e:
            logger.exception(f"Error scheduling reminder message: {e}")
            return False

    def _schedule_blast_message(self, participant, schedule):
        """Schedule a blast campaign message"""
        try:
            with transaction.atomic():
                send_time = schedule.send_time

                # Check if we should send based on business hours
                if schedule.business_hours_only:
                    current_time = send_time.time()
                    if current_time < schedule.start_time:
                        # Move to start time today
                        send_time = timezone.make_aware(
                            timezone.datetime.combine(send_time.date(), schedule.start_time)
                        )
                    elif current_time > schedule.end_time:
                        # Move to start time next day
                        send_time = timezone.make_aware(
                            timezone.datetime.combine(send_time.date() + timedelta(days=1), schedule.start_time)
                        )

                # Create message
                message = BulkCampaignMessage.objects.create(
                    campaign=participant.nurturing_campaign,
                    participant=participant,
                    status='scheduled',
                    scheduled_for=send_time
                )

                # Create or update blast progress
                progress, created = BlastCampaignProgress.objects.get_or_create(
                    participant=participant,
                    defaults={
                        'message_sent': False,
                        'sent_at': None
                    }
                )

                # Update participant progress
                participant.update_campaign_progress(
                    scheduled_time=message.scheduled_for
                )

                logger.info(f"Scheduled blast message for participant {participant.id} at {send_time}")
                return True

        except Exception as e:
            logger.exception(f"Error scheduling blast message for participant {participant.id}: {e}")
            return False

    def _send_message(self, message):
        """Send a scheduled message"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant

            # Check if message can be sent
            if not campaign.can_send_message(participant):
                logger.debug(f"Cannot send message {message.id} - campaign or participant not active")
                return False

            # Send message based on channel
            if campaign.channel == 'email':
                success = self._send_email(message)
            elif campaign.channel == 'sms':
                success = self._send_sms(message)
            elif campaign.channel == 'voice':
                success = self._send_voice(message)
            elif campaign.channel == 'chat':
                success = self._send_chat(message)
            else:
                logger.error(f"Unsupported channel: {campaign.channel}")
                return False

            if success:
                # Update message status
                message.update_status('sent')
                
                # Update participant progress
                participant.update_campaign_progress(message_sent=True)

                # For drip campaigns, update the current step if this was the last message in the sequence
                if campaign.campaign_type == 'drip' and message.drip_message_step:
                    progress = participant.drip_campaign_progress.first()
                    if progress and progress.current_step == message.drip_message_step:
                        # Find next step
                        next_step = campaign.drip_schedule.message_steps.filter(
                            order__gt=message.drip_message_step.order
                        ).order_by('order').first()
                        
                        if next_step:
                            progress.current_step = next_step
                        else:
                            progress.current_step = None
                        progress.save()

                return True

            return False

        except Exception as e:
            logger.exception(f"Error sending message {message.id}: {e}")
            message.update_status('failed', {'error': str(e)})
            return False

    def _get_next_send_time(self, schedule):
        """Calculate the next time a message should be sent based on schedule"""
        now = timezone.now()
        
        # If outside business hours, move to next business day
        if schedule.business_hours_only:
            if now.time() >= schedule.end_time:
                # Move to next day
                next_day = now + timezone.timedelta(days=1)
                if schedule.exclude_weekends and next_day.weekday() >= 5:
                    # Skip weekend
                    next_day += timezone.timedelta(days=2)
                return timezone.make_aware(timezone.datetime.combine(next_day.date(), schedule.start_time))
            elif now.time() < schedule.start_time:
                # Move to start time today
                return timezone.make_aware(timezone.datetime.combine(now.date(), schedule.start_time))

        return now

    def _calculate_reminder_time(self, reminder, participant=None, scheduled_reachout_date=None):
        """Calculate the send time for a reminder"""
        now = timezone.now()

        if reminder.schedule.use_relative_schedule:
            if not scheduled_reachout_date:
                logger.warning("No scheduled reachout date provided for relative scheduling")
                return None

            total_minutes = reminder.get_total_minutes_before()
            
            # Calculate time before scheduled reachout
            send_time = scheduled_reachout_date - timezone.timedelta(minutes=total_minutes)
            
            # If the calculated time is in the past, return None
            if send_time <= now:
                logger.debug(f"Calculated send time {send_time} is in the past")
                return None
                
            return send_time
        else:
            # Absolute scheduling
            if reminder.days_before is not None:
                if not scheduled_reachout_date:
                    logger.warning("No scheduled reachout date provided for absolute scheduling")
                    return None

                send_date = scheduled_reachout_date.date() - timezone.timedelta(days=reminder.days_before)
                if reminder.time:
                    return timezone.make_aware(timezone.datetime.combine(send_date, reminder.time))
                return timezone.make_aware(timezone.datetime.combine(send_date, time(9, 0)))  # Default to 9 AM

        return None

    def _send_email(self, message):
        """Send an email message using the configured email service"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Prepare context for variable replacement
            context = {
                'lead': {
                    'first_name': lead.first_name,
                    'last_name': lead.last_name,
                    'email': lead.email,
                    'phone_number': lead.phone_number,
                    'company': lead.company_name if hasattr(lead, 'company_name') else None,
                    'title': lead.title if hasattr(lead, 'title') else None,
                },
                'campaign': {
                    'name': campaign.name,
                    'type': campaign.campaign_type,
                    'channel': campaign.channel,
                }
            }

            # Get message content using the appropriate source
            processed_content = message.get_message_content()
            processed_subject = campaign.subject.replace_variables(context) if hasattr(campaign, 'subject') else None

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='email',
                status='open',
                subject=processed_subject,
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=processed_content,
                channel='email',
                lead=lead,
                user=campaign.created_by
            )

            # TODO: Implement actual email sending using your email service
            # This could be SendGrid, Mailgun, etc.
            # For now, we'll just mark it as sent
            message.update_status('sent')
            thread_message.read_status = True
            thread_message.save()

            return True

        except Exception as e:
            logger.error(f"Error sending email message: {str(e)}")
            return False

    def _send_sms(self, message):
        """Send an SMS message using Twilio's direct messaging API"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Prepare context for variable replacement
            context = {
                'lead': {
                    'first_name': lead.first_name,
                    'last_name': lead.last_name,
                    'email': lead.email,
                    'phone_number': lead.phone_number,
                    'company': lead.company_name if hasattr(lead, 'company_name') else None,
                    'title': lead.title if hasattr(lead, 'title') else None,
                },
                'campaign': {
                    'name': campaign.name,
                    'type': campaign.campaign_type,
                    'channel': campaign.channel,
                }
            }

            # Get message content using the appropriate source
            processed_content = message.get_message_content()

            # Get the service phone number
            service_phone = None
            if message.campaign.config and message.campaign.config.get('from_number'):
                service_phone = message.campaign.config['from_number']
            elif message.campaign.crm_campaign and message.campaign.crm_campaign.campaign_from_number:
                service_phone = message.campaign.crm_campaign.campaign_from_number

            if not service_phone:
                raise ValueError("No service phone number found in campaign configuration")

            # Format phone numbers
            formatted_to = self._format_phone_number(lead.phone_number)
            formatted_from = self._format_phone_number(service_phone)

            if not formatted_to or not formatted_from:
                raise ValueError("Invalid phone number format")

            # Initialize Twilio client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

            # Send message directly
            twilio_message = client.messages.create(
                body=processed_content,
                from_=formatted_from,
                to=formatted_to
            )

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='sms',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=processed_content,
                channel='sms',
                lead=lead,
                user=campaign.created_by
            )

            return True

        except Exception as e:
            logger.error(f"Error sending SMS message: {str(e)}")
            return False

    def _send_voice(self, message):
        """Send a voice message using Bland AI"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Prepare context for variable replacement
            context = {
                'lead': {
                    'first_name': lead.first_name,
                    'last_name': lead.last_name,
                    'email': lead.email,
                    'phone_number': lead.phone_number,
                    'company': lead.company_name if hasattr(lead, 'company_name') else None,
                    'title': lead.title if hasattr(lead, 'title') else None,
                },
                'campaign': {
                    'name': campaign.name,
                    'type': campaign.campaign_type,
                    'channel': campaign.channel,
                }
            }

            # Get message content using the appropriate source
            processed_content = message.get_message_content()

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='voice',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=processed_content,
                channel='voice',
                lead=lead,
                user=campaign.created_by
            )

            # TODO: Implement actual voice call using Bland AI
            # This would involve:
            # 1. Creating a Bland AI call
            # 2. Linking it to the thread
            # 3. Initiating the call
            # For now, we'll just mark it as sent
            message.update_status('sent')
            thread_message.read_status = True
            thread_message.save()

            return True

        except Exception as e:
            logger.error(f"Error sending voice message: {str(e)}")
            return False

    def _send_chat(self, message):
        """Send a chat message using the configured chat service"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Prepare context for variable replacement
            context = {
                'lead': {
                    'first_name': lead.first_name,
                    'last_name': lead.last_name,
                    'email': lead.email,
                    'phone_number': lead.phone_number,
                    'company': lead.company_name if hasattr(lead, 'company_name') else None,
                    'title': lead.title if hasattr(lead, 'title') else None,
                },
                'campaign': {
                    'name': campaign.name,
                    'type': campaign.campaign_type,
                    'channel': campaign.channel,
                }
            }

            # Get message content using the appropriate source
            processed_content = message.get_message_content()

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='chat',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=processed_content,
                channel='chat',
                lead=lead,
                user=campaign.created_by
            )

            # TODO: Implement actual chat message sending using your chat service
            # This could be Intercom, Drift, etc.
            # For now, we'll just mark it as sent
            message.update_status('sent')
            thread_message.read_status = True
            thread_message.save()

            return True

        except Exception as e:
            logger.error(f"Error sending chat message: {str(e)}")
            return False

    def _add_identity_participant(self, conversation_obj, identity, projected_address=None):
        """
        Add an identity-based participant to the conversation.
        
        Args:
            conversation_obj: The conversation object
            identity: The identity to use for the participant (e.g., 'acs-system')
            projected_address: The phone number to project for this identity (e.g., Twilio number)
            
        Returns:
            tuple: (participant_obj, created) where created is a boolean indicating if the participant was newly created
        """
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # First check if the participant exists in our database
        existing = Participant.objects.filter(
            conversation=conversation_obj,
            user=None,  # If you don't link a user in your DB for 'system'
            phone_number=None,
        ).first()

        if existing:
            logger.debug(f"Found existing participant in database with SID: {existing.participant_sid}")
            return existing, False

        # Check if the participant exists in Twilio
        logger.debug(f"Checking for existing participant with identity='{identity}' in Twilio")
        existing_participants = client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .participants \
            .list()

        # Look for a participant with matching identity
        for participant in existing_participants:
            if participant.identity == identity:
                logger.debug(f"Found existing participant in Twilio with SID: {participant.sid}")
                # Create or update our database record
                participant_obj, _ = Participant.objects.get_or_create(
                    participant_sid=participant.sid,
                    defaults={
                        'conversation': conversation_obj,
                        'phone_number': None,
                        'user': None
                    }
                )
                return participant_obj, False

        # If we get here, we need to create a new participant
        logger.debug(f"Adding new identity participant with identity='{identity}'")
        participant_params = {'identity': identity}
        
        # Add projected address if provided
        if projected_address:
            logger.debug(f"Using projected address: {projected_address}")
            participant_params['messaging_binding_projected_address'] = projected_address

        participant = client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .participants \
            .create(**participant_params)

        participant_obj = Participant.objects.create(
            participant_sid=participant.sid,
            conversation=conversation_obj,
            phone_number=None,
            user=None  # or link to a special "system" user if desired
        )
        return participant_obj, True

    def _format_phone_number(self, phone_number):
        """
        Format phone number to E.164 format required by Twilio
        Args:
            phone_number (str): Raw phone number in any format (e.g., XXX-XXX-XXXX, (XXX) XXX-XXXX, etc.)
        Returns:
            str: Phone number in E.164 format
        """
        if not phone_number:
            logger.debug("No phone number provided to format")
            return None
            
        # Remove any non-digit characters (including hyphens, parentheses, spaces)
        digits = ''.join(filter(str.isdigit, phone_number))
        
        # Handle XXX-XXX-XXXX format (10 digits)
        if len(digits) == 10:
            formatted = f"+1{digits}"
            return formatted
            
        # If number starts with 1 and is 11 digits, it's already a US number
        if len(digits) == 11 and digits.startswith('1'):
            formatted = f"+{digits}"
            return formatted
            
        # If number already has country code (starts with +), just ensure it's clean
        if phone_number.startswith('+'):
            formatted = f"+{digits}"
            return formatted
            
        # If we can't determine the format, return None
        logger.warning(f"Could not determine format for phone number: {phone_number}")
        return None 