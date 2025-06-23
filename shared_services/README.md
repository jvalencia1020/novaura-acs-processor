# Shared Services

This directory contains shared services that can be used across different channel processors in the communication processor app. These services promote code reuse and maintainability by providing common functionality that multiple processors can utilize.

## Services Overview

### 1. LeadMatchingService
**Purpose**: Handles lead matching across different communication channels.

**Key Methods**:
- `get_lead_from_event(event_data, fallback_identifier)`: Get lead from event data using enhanced fields
- `get_lead_by_phone(phone_number)`: Find lead by phone number
- `get_lead_by_email(email)`: Find lead by email address
- `get_lead_by_identifier(identifier)`: Find lead by any identifier
- `clean_phone_number(phone_number)`: Clean phone number for consistent formatting

**Usage Example**:
```python
from shared_services import LeadMatchingService

lead_service = LeadMatchingService()
lead = lead_service.get_lead_from_event(event_data, phone_number)
```

### 2. CampaignMatchingService
**Purpose**: Handles nurturing campaign matching across different communication channels.

**Key Methods**:
- `find_nurturing_campaign_from_event(event_data, lead)`: Find campaign from event data
- `get_campaign_by_name(campaign_name)`: Find campaign by name
- `find_campaign_by_lead(event_data, lead)`: Find campaign by lead and context
- `get_campaign_participant(lead, campaign)`: Get campaign participant
- `get_active_campaigns_for_lead(lead)`: Get all active campaigns for a lead

**Usage Example**:
```python
from shared_services import CampaignMatchingService

campaign_service = CampaignMatchingService()
campaign = campaign_service.find_nurturing_campaign_from_event(event_data, lead)
```

### 3. ConversationService
**Purpose**: Manages conversations, participants, and messages across different channels.

**Key Methods**:
- `get_or_create_conversation(event_data, channel)`: Get or create conversation
- `get_or_create_participant(conversation, identifier, identifier_type)`: Get or create participant
- `create_conversation_message(conversation, participant, event_data, channel)`: Create message
- `update_conversation_status(conversation, status)`: Update conversation status
- `get_conversation_by_sid(conversation_sid)`: Get conversation by SID

**Usage Example**:
```python
from shared_services import ConversationService

conversation_service = ConversationService()
conversation = conversation_service.get_or_create_conversation(event_data, 'sms')
```

### 4. KeywordProcessingService
**Purpose**: Handles reserved keywords (STOP, HELP, etc.) across different channels.

**Key Methods**:
- `check_reserved_keywords(message_body)`: Check for reserved keywords
- `handle_reserved_keyword(action, lead, campaign, contact_info, message_body, channel)`: Handle keyword action
- `get_keyword_help_text(channel)`: Get help text for keywords

**Usage Example**:
```python
from shared_services import KeywordProcessingService

keyword_service = KeywordProcessingService(message_sender)
action = keyword_service.check_reserved_keywords(message_body)
if action:
    keyword_service.handle_reserved_keyword(action, lead, campaign, phone, message_body, 'sms')
```

### 5. AIAgentService
**Purpose**: Handles AI agent functionality across different communication channels.

**Key Methods**:
- `handle_agent_response(event_data, lead, campaign, conversation_message, channel)`: Handle AI response
- `generate_agent_response(user_message, lead, campaign, prompt, context, channel)`: Generate AI response
- `validate_agent_config(agent_config)`: Validate agent configuration

**Usage Example**:
```python
from shared_services import AIAgentService

ai_service = AIAgentService(message_sender)
if event_data.get('agent_mode'):
    ai_service.handle_agent_response(event_data, lead, campaign, message, 'sms')
```

### 6. MessageDeliveryService (Existing)
**Purpose**: Handles message delivery operations across different channels.

### 7. MessageValidationService (Existing)
**Purpose**: Validates messages before they are sent.

### 8. TimeCalculationService (Existing)
**Purpose**: Handles time-related calculations and scheduling.

### 9. MessageGroupService (Existing)
**Purpose**: Manages message groups in bulk campaigns.

## Benefits of Using Shared Services

### 1. Code Reuse
- Common functionality is implemented once and reused across multiple processors
- Reduces code duplication and maintenance overhead

### 2. Consistency
- Ensures consistent behavior across different channel processors
- Standardized error handling and logging

### 3. Testability
- Services can be unit tested independently
- Easier to mock dependencies for testing

### 4. Maintainability
- Changes to common functionality only need to be made in one place
- Clear separation of concerns

### 5. Extensibility
- Easy to add new channel processors that use existing services
- Services can be extended without affecting existing processors

## Migration Guide

### From Original SMS Processor to Refactored Version

The original SMS processor had many functions that were specific to SMS but could be generalized. Here's how to migrate:

1. **Lead Matching**: Replace `_get_lead_from_event()` and `_get_lead_by_phone()` with `LeadMatchingService`
2. **Campaign Matching**: Replace `_find_nurturing_campaign_from_event()` with `CampaignMatchingService`
3. **Conversation Management**: Replace conversation creation methods with `ConversationService`
4. **Keyword Processing**: Replace keyword handling methods with `KeywordProcessingService`
5. **AI Agent**: Replace agent response methods with `AIAgentService`

### Example Migration

**Before (Original SMS Processor)**:
```python
def _get_lead_from_event(self, event_data, phone_number):
    # 50+ lines of lead matching logic
    pass

def _handle_opt_out(self, lead, campaign, from_number):
    # 30+ lines of opt-out logic
    pass
```

**After (Using Shared Services)**:
```python
def process_event(self, event_data):
    # Use shared services
    lead = self.lead_matching_service.get_lead_from_event(event_data, phone_number)
    
    if keyword_action:
        self.keyword_processing_service.handle_reserved_keyword(
            keyword_action, lead, campaign, from_number, message_body, 'sms'
        )
```

## Creating New Channel Processors

When creating new channel processors (e.g., Email, Chat, Voice), you can leverage these shared services:

```python
class EmailProcessor(BaseChannelProcessor):
    def __init__(self, queue_url, config=None):
        super().__init__('email', queue_url, config)
        self.message_sender = MessageSender()
        
        # Initialize shared services
        self.lead_matching_service = LeadMatchingService()
        self.campaign_matching_service = CampaignMatchingService()
        self.conversation_service = ConversationService()
        self.keyword_processing_service = KeywordProcessingService(self.message_sender)
        self.ai_agent_service = AIAgentService(self.message_sender)
    
    def process_event(self, event_data):
        # Use shared services for common functionality
        lead = self.lead_matching_service.get_lead_from_event(event_data, email)
        campaign = self.campaign_matching_service.find_nurturing_campaign_from_event(event_data, lead)
        conversation = self.conversation_service.get_or_create_conversation(event_data, 'email')
        
        # Add email-specific logic here
        # ...
```

## Best Practices

1. **Dependency Injection**: Pass dependencies (like MessageSender) to services that need them
2. **Error Handling**: Services handle their own errors and log appropriately
3. **Configuration**: Services should be configurable for different use cases
4. **Documentation**: Keep service methods well-documented with clear examples
5. **Testing**: Write comprehensive tests for each service
6. **Versioning**: Consider versioning for services that may change over time

## Future Enhancements

1. **Caching**: Add caching to frequently accessed data (leads, campaigns)
2. **Async Support**: Add async versions of services for better performance
3. **Metrics**: Add metrics collection to track service usage
4. **Configuration**: Add configuration management for service settings
5. **Plugins**: Allow for plugin-based extensions of services 