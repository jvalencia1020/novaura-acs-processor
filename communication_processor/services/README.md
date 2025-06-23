# Communication Processor Services Guide

This directory contains the core services for processing communication events across different channels (SMS, Email, Voice, etc.) in your communication processor app. The services are designed to handle SQS events, process them according to channel-specific logic, and create communication events for tracking and analytics.

## Architecture Overview

The services follow a layered architecture with:

1. **BaseChannelProcessor** - Abstract base class defining the interface
2. **Channel-specific Processors** - Concrete implementations for each channel
3. **ProcessorFactory** - Factory pattern for creating processor instances
4. **Shared Services** - Reusable functionality across processors

## Services Directory Structure

```
communication_processor/services/
├── __init__.py                 # Package initialization
├── base_processor.py          # Abstract base class for all processors
├── processor_factory.py       # Factory for creating processor instances
├── sms_processor.py           # SMS channel processor (refactored with shared services)
└── email_processor.py         # Email channel processor
```

## Core Services

### 1. BaseChannelProcessor (`base_processor.py`)

**Purpose**: Abstract base class that defines the interface and common functionality for all channel processors.

**Key Features**:
- SQS message handling (receive, process, delete)
- Common conversation and thread management
- Campaign matching logic
- Batch processing capabilities
- Error handling and logging

**Abstract Methods**:
- `process_event(event_data)` - Process a single communication event
- `validate_event(event_data)` - Validate event data for the channel

**Key Methods**:
```python
# SQS Operations
receive_messages(max_messages=10, wait_time=20)
delete_message(receipt_handle)
process_messages(max_messages=10)

# Conversation Management
get_or_create_conversation(external_id, **kwargs)
get_or_create_thread(lead_id, channel, **kwargs)

# Campaign Matching
_find_nurturing_campaign(event_data, lead)
```

**Usage Example**:
```python
from communication_processor.services.base_processor import BaseChannelProcessor

class CustomProcessor(BaseChannelProcessor):
    def __init__(self, queue_url, config=None):
        super().__init__('custom', queue_url, config)
    
    def validate_event(self, event_data):
        # Implement validation logic
        return True
    
    def process_event(self, event_data):
        # Implement processing logic
        return CommunicationEvent.objects.create(...)
```

### 2. SMSProcessor (`sms_processor.py`)

**Purpose**: Processes SMS communication events from Twilio, using shared services for better code reuse.

**Key Features**:
- Twilio webhook processing
- Lead matching using shared services
- Campaign matching using shared services
- Conversation management using shared services
- Keyword processing (STOP, HELP, etc.) using shared services
- AI agent integration using shared services
- Enhanced SQS message support

**Dependencies**:
- `shared_services.LeadMatchingService`
- `shared_services.CampaignMatchingService`
- `shared_services.ConversationService`
- `shared_services.KeywordProcessingService`
- `shared_services.AIAgentService`

**Key Methods**:
```python
# Event Processing
validate_event(event_data)
process_event(event_data)

# Business Logic
_process_incoming_message(event_data, lead, campaign, message)
_process_regular_message(event_data, lead, campaign, message)
_process_campaign_response(event_data, lead, campaign, message)

# Event Type Detection
_determine_event_type(event_data)
_extract_event_data(event_data)
```

**Usage Example**:
```python
from communication_processor.services.sms_processor import SMSProcessor

# Create SMS processor
sms_processor = SMSProcessor(
    queue_url='https://sqs.region.amazonaws.com/account/sms-queue',
    config={'agent_mode': True}
)

# Process messages
stats = sms_processor.process_messages(max_messages=10)
print(f"Processed: {stats['processed']}, Failed: {stats['failed']}")
```

### 3. EmailProcessor (`email_processor.py`)

**Purpose**: Processes email communication events from email service providers.

**Key Features**:
- Email event processing (delivered, bounced, opened, clicked)
- Email address validation
- Conversation and participant management
- Campaign association
- Event type determination

**Key Methods**:
```python
# Event Processing
validate_event(event_data)
process_event(event_data)

# Email Validation
_is_valid_email(email)

# Event Type Detection
_determine_event_type(event_data)

# Lead and Conversation Management
_get_lead_by_email(email)
_get_or_create_conversation(event_data)
_get_or_create_participant(conversation, email)
_create_conversation_message(conversation, participant, event_data)
```

**Usage Example**:
```python
from communication_processor.services.email_processor import EmailProcessor

# Create email processor
email_processor = EmailProcessor(
    queue_url='https://sqs.region.amazonaws.com/account/email-queue'
)

# Process email events
stats = email_processor.process_messages(max_messages=10)
```

### 4. ProcessorFactory (`processor_factory.py`)

**Purpose**: Factory class for creating and managing channel-specific processors.

**Key Features**:
- Dynamic processor creation
- Configuration management
- Processor registry
- Validation support

**Key Methods**:
```python
# Processor Creation
get_processor(channel_type, queue_url=None, config=None)
get_all_processors()

# Registry Management
register_processor(channel_type, processor_class)
get_supported_channels()

# Configuration
validate_processor_config(channel_type, config)
```

**Usage Example**:
```python
from communication_processor.services.processor_factory import ProcessorFactory

# Get a specific processor
sms_processor = ProcessorFactory.get_processor('sms')

# Get all active processors
all_processors = ProcessorFactory.get_all_processors()

# Register a new processor
ProcessorFactory.register_processor('voice', VoiceProcessor)

# Get supported channels
channels = ProcessorFactory.get_supported_channels()
```

## Integration with Shared Services

The SMS processor has been refactored to use shared services from the `shared_services` package:

### LeadMatchingService
- Handles lead lookup by phone, email, or ID
- Phone number cleaning and formatting
- Enhanced event data parsing

### CampaignMatchingService
- Campaign lookup by ID, name, or participant
- Smart campaign selection when multiple active
- Campaign participant management

### ConversationService
- Conversation creation and management
- Participant handling
- Message creation

### KeywordProcessingService
- Reserved keyword detection (STOP, HELP, etc.)
- Keyword action handling (opt-out, opt-in, etc.)
- Channel-specific help text

### AIAgentService
- AI agent response generation
- Agent configuration validation
- Agent event creation

## Configuration

### Channel Processor Configuration

Each channel processor can be configured through the database:

```python
from communication_processor.models import ChannelProcessor

# Create channel configuration
ChannelProcessor.objects.create(
    channel_type='sms',
    queue_url='https://sqs.region.amazonaws.com/account/sms-queue',
    is_active=True,
    config={
        'agent_mode': True,
        'agent_config': {
            'prompt': 'You are a helpful customer service agent...',
            'context': {'step_number': 1}
        }
    }
)
```

### SQS Queue Configuration

Each processor connects to an SQS queue for event processing:

```python
# Queue URL format
queue_url = 'https://sqs.{region}.amazonaws.com/{account-id}/{queue-name}'

# Example
queue_url = 'https://sqs.us-east-1.amazonaws.com/123456789012/sms-events'
```

## Event Processing Flow

### 1. Message Reception
```python
# Receive messages from SQS
messages = processor.receive_messages(max_messages=10, wait_time=20)
```

### 2. Event Validation
```python
# Validate event data
if processor.validate_event(event_data):
    # Process the event
    communication_event = processor.process_event(event_data)
```

### 3. Event Processing
```python
# Channel-specific processing
# - Lead matching
# - Campaign association
# - Conversation management
# - Business logic execution
# - AI agent integration (if enabled)
```

### 4. Message Cleanup
```python
# Delete processed message from SQS
processor.delete_message(receipt_handle)
```

## Error Handling

### SQS Message Errors
- Failed messages are marked with error status
- Error messages are logged and stored
- Messages remain in queue for retry (if configured)

### Processing Errors
- Individual message failures don't stop batch processing
- Errors are logged with full context
- Communication events are created even for failed processing

### Validation Errors
- Invalid events are marked as failed
- Error details are stored in SQS message record
- Processing continues with next message

## Monitoring and Logging

### Logging Levels
- **INFO**: Successful processing, statistics
- **WARNING**: Validation failures, missing data
- **ERROR**: Processing failures, SQS errors
- **DEBUG**: Detailed processing steps

### Key Metrics
- Messages processed per batch
- Processing success/failure rates
- Processing time per message
- Queue depth and latency

### Example Log Output
```
INFO: Received 5 messages from sms queue
INFO: Successfully processed sms event: SM1234567890abcdef
INFO: Processed: 4, Failed: 1, Deleted: 4
WARNING: SMS event missing required field: MessageSid
ERROR: Error processing sms message: Invalid phone number format
```

## Testing

### Unit Testing
```python
from django.test import TestCase
from communication_processor.services.sms_processor import SMSProcessor

class SMSProcessorTestCase(TestCase):
    def setUp(self):
        self.processor = SMSProcessor('test-queue-url')
    
    def test_validate_event(self):
        event_data = {
            'MessageSid': 'SM1234567890abcdef',
            'AccountSid': 'AC1234567890abcdef'
        }
        self.assertTrue(self.processor.validate_event(event_data))
    
    def test_process_event(self):
        # Test event processing
        pass
```

### Integration Testing
```python
# Test with real SQS messages
processor = SMSProcessor(queue_url)
stats = processor.process_messages(max_messages=1)
assert stats['processed'] >= 0
```

## Best Practices

### 1. Error Handling
- Always validate event data before processing
- Handle SQS errors gracefully
- Log errors with sufficient context
- Don't let single message failures stop batch processing

### 2. Performance
- Use batch processing for efficiency
- Implement appropriate timeouts
- Monitor queue depth and processing times
- Consider async processing for high-volume scenarios

### 3. Monitoring
- Log processing statistics
- Monitor error rates and types
- Track processing latency
- Set up alerts for processing failures

### 4. Configuration
- Use database configuration for flexibility
- Validate configuration on startup
- Support environment-specific settings
- Document configuration options

### 5. Testing
- Unit test all processor methods
- Test with various event data formats
- Mock external dependencies
- Test error scenarios

## Future Enhancements

### 1. Additional Channels
- Voice processor for call events
- Chat processor for messaging platforms
- WhatsApp processor for WhatsApp Business API
- Social media processors

### 2. Performance Improvements
- Async processing support
- Message batching optimization
- Caching for frequently accessed data
- Database connection pooling

### 3. Advanced Features
- Real-time processing with WebSockets
- Event streaming with Kinesis
- Machine learning integration
- Advanced analytics and reporting

### 4. Monitoring and Observability
- Distributed tracing
- Metrics collection and dashboards
- Health checks and readiness probes
- Automated alerting

## Troubleshooting

### Common Issues

1. **SQS Connection Errors**
   - Check AWS credentials and permissions
   - Verify queue URL format
   - Ensure queue exists and is accessible

2. **Processing Failures**
   - Check event data format
   - Verify required fields are present
   - Review error logs for specific issues

3. **Performance Issues**
   - Monitor queue depth
   - Check processing times
   - Consider increasing batch sizes
   - Review database query performance

4. **Configuration Issues**
   - Validate processor configuration
   - Check database connection
   - Verify shared service dependencies

### Debug Mode
Enable debug logging for detailed processing information:

```python
import logging
logging.getLogger('communication_processor.services').setLevel(logging.DEBUG)
```

This guide provides a comprehensive overview of the communication processor services. For specific implementation details, refer to the individual service files and their docstrings. 