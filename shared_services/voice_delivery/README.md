# Modular Voice Delivery Architecture

This directory contains the modular voice delivery implementation that supports multiple voice platforms through a unified interface.

## Architecture Overview

The voice delivery system is built with the following components:

1. **BaseVoicePlatform** - Abstract base class for voice platforms
2. **Platform Implementations** - Concrete implementations for each platform (Bland AI, VAPI, etc.)
3. **VoicePlatformFactory** - Factory for creating platform instances
4. **VoiceDeliveryService** - High-level service for sending voice messages
5. **VoiceProcessor** - Communication processor for handling voice events

## Directory Structure

```
shared_services/
├── voice_platforms/
│   ├── __init__.py
│   ├── base_voice_platform.py      # Abstract base class
│   ├── bland_ai_platform.py        # Bland AI implementation
│   └── voice_platform_factory.py   # Platform factory
├── voice_delivery/
│   ├── __init__.py
│   ├── voice_delivery_service.py   # Main delivery service
│   └── README.md                   # This file
└── message_delivery/
    └── message_delivery_service.py # Updated to use voice delivery
```

## Components

### 1. BaseVoicePlatform

Abstract base class that defines the interface for all voice platforms:

```python
from shared_services.voice_platforms.base_voice_platform import BaseVoicePlatform

class CustomPlatform(BaseVoicePlatform):
    def _get_api_key(self) -> str:
        return "your_api_key"
    
    def send_call(self, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        # Implement platform-specific call sending
        pass
    
    def validate_payload(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        # Implement platform-specific validation
        pass
    
    def format_payload(self, voice_config, content: str, phone_number: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        # Implement platform-specific payload formatting
        pass
```

### 2. BlandAIPlatform

Concrete implementation for Bland AI:

- Handles Bland AI API authentication
- Formats payloads according to Bland AI API specification
- Validates payload requirements
- Manages API calls and error handling

### 3. VoicePlatformFactory

Factory for creating and managing voice platform instances:

```python
from shared_services.voice_platforms.voice_platform_factory import VoicePlatformFactory

# Get a platform instance
platform = VoicePlatformFactory.get_platform('bland_ai')

# Register a new platform
VoicePlatformFactory.register_platform('custom', CustomPlatform)

# Get supported platforms
platforms = VoicePlatformFactory.get_supported_platforms()
```

### 4. VoiceDeliveryService

High-level service for sending voice messages:

```python
from shared_services.voice_delivery.voice_delivery_service import VoiceDeliveryService

service = VoiceDeliveryService()

success, thread_message = service.send_voice_message(
    content="Hello, this is a test call",
    lead=lead_object,
    user=user_object,
    voice_config=voice_config,
    message_type='regular',
    metadata={'campaign_id': '123'}
)
```

### 5. VoiceProcessor

Communication processor for handling voice events from SQS:

```python
from communication_processor.services.voice_processor import VoiceProcessor

processor = VoiceProcessor(queue_url='https://sqs.region.amazonaws.com/account/voice-queue')
processor.process_messages(max_messages=10)
```

## Usage Examples

### Basic Voice Call

```python
from shared_services.voice_delivery.voice_delivery_service import VoiceDeliveryService
from external_models.models.channel_configs import VoiceConfig

# Get or create voice configuration
voice_config = VoiceConfig.objects.filter(platform='bland_ai').first()

# Create delivery service
voice_service = VoiceDeliveryService()

# Send voice call
success, thread_message = voice_service.send_voice_message(
    content="Hello, this is a test call from our AI assistant.",
    lead=lead,
    user=user,
    voice_config=voice_config,
    message_type='regular'
)

if success:
    print(f"Call initiated successfully. Thread message ID: {thread_message.id}")
else:
    print("Failed to initiate call")
```

### Using Message Delivery Service

```python
from shared_services.message_delivery.message_delivery_service import MessageDeliveryService

message_service = MessageDeliveryService()

# Send voice message through the unified interface
success, thread_message = message_service.send_message(
    channel='voice',
    content="Hello, this is a test call",
    lead=lead,
    user=user
)
```

### Processing Voice Events

```python
from communication_processor.services.processor_factory import ProcessorFactory

# Get voice processor
voice_processor = ProcessorFactory.get_processor('voice')

# Process voice events from SQS
stats = voice_processor.process_messages(max_messages=10)
print(f"Processed: {stats['processed']}, Failed: {stats['failed']}")
```

## Configuration

### Django Settings

Add the Bland AI API key to your Django settings:

```python
# settings.py
BLAND_AI_API_KEY = 'your_bland_ai_api_key_here'
```

### Voice Configuration

Create voice configurations through the VoiceConfig model:

```python
from external_models.models.channel_configs import VoiceConfig

# Create Bland AI configuration
voice_config = VoiceConfig.objects.create(
    platform='bland_ai',
    content="Default call content",
    voice_id="maya",
    language="en",
    max_duration=5,
    record_call=True,
    platform_config={
        'temperature': 0.7,
        'model': 'gpt-4',
        'wait_for_greeting': True,
        'block_interruptions': False
    },
    webhook_config={
        'url': 'https://your-webhook-url.com/webhook',
        'events': ['call', 'latency', 'webhook']
    }
)
```

## Adding New Platforms

To add support for a new voice platform (e.g., VAPI):

1. **Create Platform Implementation**:

```python
# shared_services/voice_platforms/vapi_platform.py
from .base_voice_platform import BaseVoicePlatform

class VAPIPlatform(BaseVoicePlatform):
    def _get_api_key(self) -> str:
        return getattr(settings, 'VAPI_API_KEY', None)
    
    def send_call(self, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        # Implement VAPI-specific call sending
        pass
    
    def validate_payload(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        # Implement VAPI-specific validation
        pass
    
    def format_payload(self, voice_config, content: str, phone_number: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        # Implement VAPI-specific payload formatting
        pass
```

2. **Register Platform**:

```python
# In voice_platform_factory.py
from .vapi_platform import VAPIPlatform

PLATFORMS = {
    'bland_ai': BlandAIPlatform,
    'vapi': VAPIPlatform,
}
```

3. **Add Platform-Specific Call Records**:

```python
# In voice_delivery_service.py
def _create_call_record(self, platform: str, response: Dict[str, Any], ...):
    if platform == 'vapi':
        vapi_call = VAPICall.objects.create(
            call_id=response['call_id'],
            # ... other fields
        )
```

## Error Handling

The system includes comprehensive error handling:

- **API Errors**: Network failures, authentication errors, rate limiting
- **Validation Errors**: Invalid payloads, missing required fields
- **Configuration Errors**: Missing API keys, invalid configurations
- **Database Errors**: Failed record creation, constraint violations

All errors are logged with appropriate context and handled gracefully.

## Testing

Run the test script to verify the implementation:

```bash
python test_voice_delivery.py
```

This will test:
- Platform factory functionality
- Voice configuration creation
- Payload formatting
- Service initialization

## Benefits

1. **Modularity**: Each platform is isolated and can be developed independently
2. **Extensibility**: Easy to add new platforms without changing existing code
3. **Testability**: Each component can be tested in isolation
4. **Maintainability**: Platform-specific code is contained and organized
5. **Reusability**: Services can be used across different parts of the application
6. **Configuration**: Flexible configuration system for different use cases
7. **Error Handling**: Comprehensive error handling and logging

## Future Enhancements

- **Call Status Tracking**: Real-time call status updates via webhooks
- **Analytics**: Call analytics and reporting
- **Retry Logic**: Automatic retry for failed calls
- **Rate Limiting**: Platform-specific rate limiting
- **Cost Tracking**: Call cost tracking and billing integration
- **Multi-Platform Support**: Support for VAPI, ElevenLabs, Twilio Voice, etc. 