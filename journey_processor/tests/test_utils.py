# journey_processor/tests/test_utils.py

import logging
from django.utils import timezone

from external_models.models import (
    Journey, JourneyStep, JourneyStepConnection,
    JourneyEvent, LeadNurturingParticipant,
    Account, Campaign, Funnel, Lead,
    LeadNurturingCampaign, EmailConfig
)
from journey_processor.services.journey_processor import JourneyProcessor

logger = logging.getLogger(__name__)


def create_test_journey(account, user):
    """Create a test journey with some basic steps"""
    # Find or create a test campaign and funnel
    campaign = account.campaigns.first()
    if not campaign:
        logger.error("Cannot create test journey: no campaign available")
        return None
        
    funnel = campaign.funnels.first()
    if not funnel:
        logger.error("Cannot create test journey: no funnel available")
        return None

    # Create the journey
    journey = Journey.objects.create(
        account=account,
        name=f"Test Journey {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
        description="Automatically created test journey",
        funnel=funnel,
        campaign=campaign,
        created_by=user,
        is_active=True,
        start_date=timezone.now()
    )

    # Create email config for the nurturing campaign
    email_config = EmailConfig.objects.create(
        content="Test email content",
        subject="Test Subject",
        from_name="Test Sender",
        priority="normal",
        track_opens=True,
        track_clicks=True
    )

    # Create the nurturing campaign
    nurturing_campaign = LeadNurturingCampaign.objects.create(
        account=account,
        journey=journey,
        name=f"Test Nurturing Campaign {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
        description="Automatically created test nurturing campaign",
        campaign_type='journey',
        status='active',
        active=True,
        start_date=timezone.now(),
        created_by=user,
        email_config=email_config
    )

    # Create steps
    entry_step = JourneyStep.objects.create(
        journey=journey,
        name="Start",
        order=0,
        step_type="email",
        is_entry_point=True,
        is_active=True
    )

    delay_step = JourneyStep.objects.create(
        journey=journey,
        name="Wait 1 Day",
        order=1,
        step_type="delay",
        is_entry_point=False,
        is_active=True
    )

    condition_step = JourneyStep.objects.create(
        journey=journey,
        name="Check Status",
        order=2,
        step_type="condition",
        is_entry_point=False,
        is_active=True,
        config={
            "type": "field_condition",
            "field": "status",
            "operator": "eq",
            "value": "active"
        }
    )

    end_step = JourneyStep.objects.create(
        journey=journey,
        name="End",
        order=3,
        step_type="end",
        is_entry_point=False,
        is_active=True
    )

    # Create connections
    JourneyStepConnection.objects.create(
        from_step=entry_step,
        to_step=delay_step,
        trigger_type="immediate",
        is_active=True,
        priority=1
    )

    JourneyStepConnection.objects.create(
        from_step=delay_step,
        to_step=condition_step,
        trigger_type="delay",
        delay_duration=1,
        delay_unit="minutes",  # Use minutes for testing instead of days
        is_active=True,
        priority=1
    )

    JourneyStepConnection.objects.create(
        from_step=condition_step,
        to_step=end_step,
        trigger_type="immediate",
        condition_label="true",
        is_active=True,
        priority=1
    )

    return journey


def enroll_test_lead(journey, lead, user):
    """Enroll a test lead in a journey"""
    # Create the journey participant
    participant = LeadNurturingParticipant.objects.create(
        lead=lead,
        nurturing_campaign=journey.nurturing_campaigns.first(),
        status="active",
        created_by=user,
        last_updated_by=user
    )

    # Process the participant to start their journey
    processor = JourneyProcessor()
    processor.process_participant(participant)

    return participant


def trigger_test_event(lead_id, event_type, data=None):
    """Trigger a test event for a lead"""
    from journey_processor.utils.helpers import publish_journey_event

    event_data = data or {}
    event_data['lead_id'] = lead_id

    return publish_journey_event(event_type, event_data)