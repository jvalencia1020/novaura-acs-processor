# Communication Processor

A Django app for processing SQS events from various communication channels (SMS, Email, Voice, Chat, etc.).

## Overview

The Communication Processor app provides a scalable, extensible system for processing communication events from different channels via AWS SQS queues. It supports multiple communication platforms and provides a unified interface for handling events across all channels.

## Features

- **Multi-channel Support**: Process events from SMS, Email, Voice, Chat, and social media platforms
- **SQS Integration**: Built-in AWS SQS message processing with retry logic
- **Extensible Architecture**: Easy to add new communication channels
- **Event Tracking**: Comprehensive tracking of all communication events
- **Admin Interface**: Django admin interface for monitoring and configuration
- **Management Commands**: CLI tools for setup and operation
- **Error Handling**: Robust error handling and retry mechanisms

## Architecture

### Core Components

1. **BaseChannelProcessor**: Abstract base class for all channel processors
2. **Channel-Specific Processors**: Implementations for SMS, Email, etc.
3. **ProcessorFactory**: Factory class for creating and managing processors
4. **Models**: Database models for tracking events and configurations
5. **Management Commands**: CLI tools for operation and setup

### Data Flow

1. SQS messages are received from communication platform queues
2. Messages are validated and processed by channel-specific processors
3. Communication events are created and linked to CRM entities
4. Events trigger signals for additional processing (notifications, analytics, etc.)

## Models

### SQSMessage
Tracks SQS messages that have been processed by the communication processor.

### CommunicationEvent
Represents a communication event that was processed from an SQS message.

### ChannelProcessor
Configuration for different communication channel processors.

## Setup

### 1. Add to INSTALLED_APPS

Add `communication_processor` to your Django settings:

```python
INSTALLED_APPS = [
    # ... other apps
    'communication_processor',
]
```

### 2. Run Migrations

```bash
python manage.py makemigrations communication_processor
python manage.py migrate
```

### 3. Configure Channel Processors

Set up channel configurations using the management command:

```bash
# Set up SMS processor
python manage.py setup_channel_processors --channel sms --queue-url https://sqs.region.amazonaws.com/account/sms-queue

# Set up Email processor
python manage.py setup_channel_processors --channel email --queue-url https://sqs.region.amazonaws.com/account/email-queue

# List all configurations
python manage.py setup_channel_processors --list
```

### 4. Environment Variables

Add the following environment variables to your settings:

```bash
# SQS Queue URLs (optional - can be set via management command)
SMS_QUEUE_URL=https://sqs.region.amazonaws.com/account/sms-queue
EMAIL_QUEUE_URL=https://sqs.region.amazonaws.com/account/email-queue

# AWS Configuration
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
```

## Usage

### Running the Processor

Start the communication processor:

```bash
# Process all active channels
python manage.py run_communication_processor

# Process specific channel
python manage.py run_communication_processor --channel sms

# Process with custom settings
python manage.py run_communication_processor --batch-size 20 --interval 60

# Dry run (for testing)
python manage.py run_communication_processor --dry-run
```

### Management Commands

#### setup_channel_processors
Configure channel processors:

```bash
# Set up a channel
python manage.py setup_channel_processors --channel sms --queue-url <queue-url>

# List configurations
python manage.py setup_channel_processors --list

# Enable/disable channels
python manage.py setup_channel_processors --enable sms
python manage.py setup_channel_processors --disable email

# Delete configuration
python manage.py setup_channel_processors --delete sms
```

#### run_communication_processor
Run the communication processor:

```bash
# Basic usage
python manage.py run_communication_processor

# Process specific channel
python manage.py run_communication_processor --channel sms

# Custom settings
python manage.py run_communication_processor --batch-size 10 --interval 30 --max-cycles 100

# Dry run
python manage.py run_communication_processor --dry-run
```

## Adding New Channels

### 1. Create Processor Class

Create a new processor class inheriting from `BaseChannelProcessor`:

```python
# communication_processor/services/whatsapp_processor.py
from communication_processor.services.base_processor import BaseChannelProcessor

class WhatsAppProcessor(BaseChannelProcessor):
    def __init__(self, queue_url: str, config: Dict[str, Any] = None):
        super().__init__('whatsapp', queue_url, config)
    
    def validate_event(self, event_data: Dict[str, Any]) -> bool:
        # Implement validation logic
        pass
    
    def process_event(self, event_data: Dict[str, Any]) -> CommunicationEvent:
        # Implement processing logic
        pass
```

### 2. Register Processor

Register the processor in the factory:

```python
# In your app's ready() method or management command
from communication_processor.services.processor_factory import ProcessorFactory
from communication_processor.services.whatsapp_processor import WhatsAppProcessor

ProcessorFactory.register_processor('whatsapp', WhatsAppProcessor)
```

### 3. Configure Channel

Set up the channel configuration:

```bash
python manage.py setup_channel_processors --channel whatsapp --queue-url <queue-url>
```

## Admin Interface

The app provides a comprehensive Django admin interface for:

- **SQS Messages**: View and monitor SQS message processing
- **Communication Events**: Browse and search communication events
- **Channel Processors**: Configure and manage channel processors

Access the admin interface at `/admin/` after setting up a superuser.

## Monitoring and Logging

### Logging

The app uses Django's logging system. Configure logging in your settings:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'communication_processor': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}
```

### Metrics

Track processing metrics through the admin interface or by querying the models:

```python
from communication_processor.models import CommunicationEvent, SQSMessage

# Get processing statistics
total_events = CommunicationEvent.objects.count()
failed_messages = SQSMessage.objects.filter(status='failed').count()
```

## Error Handling

The app includes comprehensive error handling:

- **Retry Logic**: Failed messages are retried up to a configurable limit
- **Error Tracking**: All errors are logged and tracked in the database
- **Graceful Degradation**: Individual channel failures don't affect other channels

## Testing

### Unit Tests

Run the test suite:

```bash
python manage.py test communication_processor
```

### Integration Tests

Test with real SQS queues:

```bash
# Dry run to test configuration
python manage.py run_communication_processor --dry-run

# Test specific channel
python manage.py run_communication_processor --channel sms --max-cycles 1
```

## Deployment

### Docker

The app is designed to work with Docker containers. Include in your Dockerfile:

```dockerfile
# Run migrations
RUN python manage.py migrate

# Start the processor
CMD ["python", "manage.py", "run_communication_processor"]
```

### AWS ECS

Deploy as an ECS service with appropriate IAM roles for SQS access.

### Environment Variables

Set required environment variables in your deployment environment:

```bash
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
DATABASE_URL=your_database_url
```

## Contributing

1. Follow the existing code structure
2. Add tests for new features
3. Update documentation
4. Ensure all tests pass

## License

This app is part of the Novaura ACS Processor project. 