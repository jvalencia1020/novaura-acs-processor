# Communication Processor

A Django app for processing SQS events from communication channels (SMS, Email, etc.) and integrating with nurturing campaigns.

## Features

### Core Functionality
- **SQS Event Processing**: Consume and process events from AWS SQS queues
- **Multi-Channel Support**: SMS (Twilio), Email, and extensible for other channels
- **Database Persistence**: Track all communication events and processing status
- **Admin Interface**: Monitor and manage communication events and channel processors
- **Error Handling**: Comprehensive error handling with retry logic and dead letter queues

### SMS Processing Features
- **Reserved Keywords**: Handle opt-out, help, info, and confirmation requests
- **Lead Matching**: Automatically match phone numbers to leads in your CRM
- **Campaign Integration**: Link communication events to nurturing campaigns
- **Conversation Management**: Create and manage Twilio conversations and participants
- **Message Responses**: Send automated responses for reserved keywords

### Reserved Keywords
The SMS processor supports the following reserved keywords:

| Keyword | Action | Description |
|---------|--------|-------------|
| `STOP` | Opt-out | Unsubscribe from current campaign |
| `STOPALL` | Opt-out all | Unsubscribe from all campaigns |
| `START` | Opt-in | Re-subscribe to current campaign |
| `HELP` | Help | Send help information |
| `INFO` | Info | Send campaign information |
| `YES` | Confirm | Handle positive confirmation |
| `NO` | Decline | Handle negative confirmation |
| `UNSUBSCRIBE` | Opt-out | Alternative opt-out keyword |
| `CANCEL` | Opt-out | Alternative opt-out keyword |

## Architecture

### Models

#### CommunicationEvent
Tracks all communication events processed by the system:
- Event type and channel
- External IDs and raw data
- Lead and campaign associations
- Processing status and timestamps

#### ChannelProcessor
Configuration for different communication channels:
- Channel type and queue settings
- Processor class and configuration
- Status and monitoring

#### SQSMessage
Tracks SQS message processing:
- Message ID and receipt handle
- Processing status and attempts
- Error information and retry logic

### Services

#### BaseChannelProcessor
Abstract base class for all channel processors:
- Common validation and processing logic
- Error handling and logging
- Database operations

#### SMSProcessor
Handles SMS events from Twilio:
- Reserved keyword processing
- Lead matching and campaign integration
- Conversation and participant management
- Automated response sending

#### EmailProcessor
Handles email events:
- Email parsing and validation
- Lead matching by email address
- Campaign integration

#### ProcessorFactory
Creates appropriate processor instances based on channel type.

### Utilities

#### MessageSender
Handles sending response messages:
- SMS sending via Twilio
- Extensible for other platforms
- Predefined message templates

## Setup

### Installation

1. Add to INSTALLED_APPS:
```python
INSTALLED_APPS = [
    ...
    'communication_processor',
    ...
]
```

2. Run migrations:
```bash
python manage.py migrate
```

3. Configure SQS queues in settings:
```python
SQS_QUEUES = {
    'sms': {
        'url': 'https://sqs.region.amazonaws.com/account/sms-queue',
        'region': 'us-east-1',
    },
    'email': {
        'url': 'https://sqs.region.amazonaws.com/account/email-queue',
        'region': 'us-east-1',
    },
}
```

4. Configure Twilio settings (for SMS):
```python
TWILIO_ACCOUNT_SID = 'your_account_sid'
TWILIO_AUTH_TOKEN = 'your_auth_token'
TWILIO_PHONE_NUMBER = '+1234567890'
```

### Management Commands

#### Setup Channel Processors
```bash
python manage.py setup_channel_processors
```

#### Run Communication Processor
```bash
python manage.py run_communication_processor --channel sms
```

#### Test SMS Processor
```bash
python manage.py test_sms_processor --keyword STOP --phone +1234567890
```

## Usage

### Processing SMS Events

The SMS processor handles various types of events:

1. **Inbound Messages**: Process user responses and reserved keywords
2. **Delivery Status**: Track message delivery and failure
3. **Read Receipts**: Monitor message engagement

### Reserved Keyword Processing

When a user sends a reserved keyword:

1. **Keyword Detection**: Processor checks message body against reserved keywords
2. **Action Execution**: Appropriate action is taken (opt-out, help, etc.)
3. **Database Update**: Lead and campaign status are updated
4. **Response Sending**: Confirmation message is sent to user

### Campaign Integration

Communication events are automatically linked to nurturing campaigns:

1. **Lead Matching**: Find lead by phone number or email
2. **Campaign Detection**: Identify active campaigns for the lead
3. **Event Creation**: Create communication event with campaign association
4. **Journey Integration**: For journey campaigns, create journey events

### Example Event Processing

```python
from communication_processor.services.sms_processor import SMSProcessor

# Initialize processor
processor = SMSProcessor('sms-queue-url')

# Sample Twilio webhook data
event_data = {
    'MessageSid': 'SM1234567890abcdef',
    'AccountSid': 'AC1234567890abcdef',
    'From': '+1234567890',
    'To': '+1987654321',
    'Body': 'STOP',
    'Direction': 'inbound',
    'MessageStatus': 'received',
}

# Process the event
communication_event = processor.process_event(event_data)
```

## Testing

### Unit Tests
```bash
python manage.py test communication_processor.tests.test_sms_processor
```

### Integration Tests
```bash
python manage.py test communication_processor.tests.test_sms_processor.SMSProcessorIntegrationTestCase
```

### Manual Testing
```bash
# Test with STOP keyword
python manage.py test_sms_processor --keyword STOP

# Test with HELP keyword
python manage.py test_sms_processor --keyword HELP

# Test with regular message
python manage.py test_sms_processor
```

## Monitoring

### Admin Interface
- View all communication events
- Monitor processing status
- Check channel processor configurations
- Filter events by campaign, lead, or status

### Logging
The processor logs all activities:
- Event processing status
- Reserved keyword actions
- Lead matching results
- Campaign integration
- Error conditions

### Metrics
Track key metrics:
- Events processed per channel
- Reserved keyword usage
- Opt-out rates
- Campaign engagement
- Processing errors

## Configuration

### Environment Variables
```bash
# SQS Configuration
SQS_QUEUE_URL_SMS=https://sqs.region.amazonaws.com/account/sms-queue
SQS_QUEUE_URL_EMAIL=https://sqs.region.amazonaws.com/account/email-queue
AWS_REGION=us-east-1

# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890
```

### Settings
```python
# Communication Processor Settings
COMMUNICATION_PROCESSOR = {
    'max_retries': 3,
    'visibility_timeout': 30,
    'batch_size': 10,
    'polling_interval': 5,
}
```

## Troubleshooting

### Common Issues

1. **Lead Not Found**: Ensure leads have correct phone numbers in the database
2. **Campaign Not Linked**: Check that leads are participants in active campaigns
3. **Message Sending Failed**: Verify Twilio credentials and phone number configuration
4. **SQS Connection Issues**: Check AWS credentials and queue permissions

### Debug Mode
Enable debug logging:
```python
LOGGING = {
    'loggers': {
        'communication_processor': {
            'level': 'DEBUG',
            'handlers': ['console'],
        },
    },
}
```

## Contributing

1. Follow Django coding standards
2. Add tests for new functionality
3. Update documentation
4. Use meaningful commit messages

## License

This project is licensed under the MIT License. 