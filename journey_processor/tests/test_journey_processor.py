# journey_processor/tests/test_journey_processor.py

import pytest
from django.utils import timezone

from external_models.models.external_references import (
    Account, Lead, Campaign, Funnel
)

from external_models.models.accounts import (
    User
)
from journey_processor.tests.test_utils import (
    create_test_journey,
    enroll_test_lead,
    trigger_test_event
)
from journey_processor.services.journey_processor import JourneyProcessor


@pytest.mark.django_db
class TestJourneyProcessor:
    """Test cases for the JourneyProcessor service"""

    def test_create_and_enroll_lead(self, default_lead_status):
        """Test creating a journey and enrolling a lead"""
        # Create test data
        account = Account.objects.create(name="Test Account")
        user = User.objects.create(username="testuser")
        campaign = Campaign.objects.create(
            account=account,
            name="Test Campaign"
        )
        funnel = Funnel.objects.create(
            campaign=campaign,
            name="Test Funnel",
            created_by=user,
            direction='inbound'
        )
        lead = Lead.objects.create(
            campaign=campaign,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            status=default_lead_status
        )

        # Create journey
        journey = create_test_journey(account, user)
        assert journey is not None
        assert journey.steps.count() == 4  # Entry, delay, condition, end

        # Enroll lead
        participant = enroll_test_lead(journey, lead, user)
        assert participant is not None
        assert participant.status == "active"
        assert participant.current_journey_step is not None

    def test_process_timed_connections(self, default_lead_status):
        """Test processing of timed connections"""
        # Create test data
        account = Account.objects.create(name="Test Account")
        user = User.objects.create(username="testuser")
        campaign = Campaign.objects.create(
            account=account,
            name="Test Campaign"
        )
        funnel = Funnel.objects.create(
            campaign=campaign,
            name="Test Funnel",
            created_by=user,
            direction='inbound'
        )
        lead = Lead.objects.create(
            campaign=campaign,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            status=default_lead_status
        )

        # Create journey and enroll lead
        journey = create_test_journey(account, user)
        participant = enroll_test_lead(journey, lead, user)

        # Process timed connections
        processor = JourneyProcessor()
        processed_count = processor.process_timed_connections()
        assert processed_count == 0  # No connections should be processed yet

    def test_process_event(self, default_lead_status):
        """Test processing of events"""
        # Create test data
        account = Account.objects.create(name="Test Account")
        user = User.objects.create(username="testuser")
        campaign = Campaign.objects.create(
            account=account,
            name="Test Campaign"
        )
        funnel = Funnel.objects.create(
            campaign=campaign,
            name="Test Funnel",
            created_by=user,
            direction='inbound'
        )
        lead = Lead.objects.create(
            campaign=campaign,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            status=default_lead_status
        )

        # Create journey and enroll lead
        journey = create_test_journey(account, user)
        participant = enroll_test_lead(journey, lead, user)

        # Trigger test event
        event_data = {
            'lead_id': lead.id,
            'test_data': 'test_value'
        }
        result = trigger_test_event(lead.id, 'test_event', event_data)
        assert result is not None 