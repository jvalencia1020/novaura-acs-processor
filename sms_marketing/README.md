# SMS Marketing Message Processor

This module processes inbound SMS messages for SMS marketing campaigns, handling keyword matching, subscriber state management, and action execution.

## Architecture

### Services

- **`router.py`**: Routes inbound messages to campaigns and rules based on keyword matching
- **`state.py`**: Manages subscriber opt-in/opt-out state transitions
- **`actions.py`**: Executes actions (OPT_IN, SEND_TEMPLATE, START_JOURNEY, etc.)
- **`processor.py`**: Main processor that orchestrates the full message processing flow

### Processing Flow

1. **Message Reception**: Messages arrive via SQS queue (from webhook in separate repository)
2. **Subscriber Resolution**: Get or create `SmsSubscriber` for endpoint + phone number
3. **Keyword Routing**: Match message body to `SmsKeywordCampaign` and `SmsKeywordRule`
4. **State Management**: Update subscriber status (opt-in/opt-out)
5. **Action Execution**: Execute configured actions (send message, enroll in journey, etc.)
6. **Event Logging**: Create `SmsCampaignEvent` for audit trail

## Usage

### Running the Worker

```bash
python manage.py run_sms_marketing_worker
```

The worker will:
- Poll SQS queue configured in `SMS_MARKETING_QUEUE_URL`
- Filter messages by `EventType='sms.marketing.inbound'`
- Process messages asynchronously
- Handle S3 references if messages are stored in S3

### Configuration

Add to your `.env` file:

```bash
# SMS Marketing Queue
SMS_MARKETING_QUEUE_URL=https://sqs.region.amazonaws.com/account/sms-marketing-queue
SMS_MARKETING_DLQ_URL=https://sqs.region.amazonaws.com/account/sms-marketing-queue-dlq

# S3 Configuration (if messages stored in S3)
SMS_MARKETING_S3_BUCKET=your-bucket-name
SMS_MARKETING_S3_REGION=us-east-1

# Processing Settings
SMS_MARKETING_PROCESSING_ENABLED=True
SMS_MARKETING_MAX_RETRIES=3
SMS_MARKETING_VISIBILITY_TIMEOUT=300
```

## Features

### Global Compliance Keywords

The processor handles global compliance keywords with highest priority:
- **STOP keywords**: STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT → Opt-out subscriber
- **HELP keywords**: HELP, INFO → Send help information

### Keyword Matching

Keywords are matched using three match types (in priority order):
1. **Exact**: Exact case-insensitive match
2. **Starts With**: Message starts with keyword
3. **Contains**: Message contains keyword

### Opt-In Modes

- **Single Opt-in**: Immediate opt-in on keyword match
- **Double Opt-in**: Two-step process (keyword → confirmation)
- **No Opt-in**: Keyword triggers actions but doesn't change status

### Actions

Supported action types:
- `OPT_IN`: Opt-in subscriber (respects campaign opt_in_mode)
- `OPT_OUT`: Opt-out subscriber
- `HELP`: Send help information
- `SEND_TEMPLATE`: Send a configured template message
- `START_JOURNEY`: Enroll in nurturing journey
- `CREATE_LEAD`: Create or update lead in CRM
- `ROUTE_TO_AGENT`: Forward to ACS conversation engine
- `COMPOSITE`: Execute multiple actions in sequence/parallel

### Short links and template variables

When a keyword rule has a **short link** assigned (`SmsKeywordRule.short_link`), outbound message bodies can use the ACS template variable **`{{link.short_link}}`** (from the "link" category). It is replaced with the campaign short URL including a `?sms_msg_id=<message_id>` query parameter so each recipient gets a unique, trackable link. The link-runtime service forwards `sms_msg_id` onto the redirect URL and into click events for full user/responder journey tracking.

- Seed the link category and variable once: `python manage.py seed_link_template_variable` (from the `external_models` app).
- Use `{{link.short_link}}` in welcome messages, templates, or any body that is sent when the rule has a short link. Other variables (e.g. `{{lead.first_name}}`) are replaced in the same pass.

## Integration Points

### Lead Matching

The processor uses `LeadMatchingService` to match phone numbers to leads, trying multiple phone number formats:
- E.164 format (+12035835289)
- Digits only (12035835289)
- US format with/without country code

### Journey Enrollment

When `START_JOURNEY` action is executed:
- Creates `LeadNurturingParticipant` for the subscriber's lead
- Links to the nurturing campaign specified in action config or campaign's `follow_up_nurturing_campaign`

### Conversation Routing

When `ROUTE_TO_AGENT` action is executed:
- Creates or retrieves `Conversation` for subscriber
- Creates `ConversationMessage` for threading
- Links `SmsMessage` to conversation for bidirectional reference

## Error Handling

- Failed messages are moved to DLQ if configured
- Errors are logged to `SmsCampaignEvent` with `event_type='error'`
- Processing continues even if individual actions fail (unless `stop_on_error=True` in composite actions)

## Testing

To test the processor:

1. Create test `SmsMessage` in database
2. Run processor directly:
   ```python
   from sms_marketing.services.processor import SMSMarketingProcessor
   
   processor = SMSMarketingProcessor()
   processor.process_inbound_message({'sms_message_id': message_id})
   ```

3. Or send test message to SQS queue with proper format

## Message Format

Expected SQS message format:

```json
{
  "sms_message_id": 123,
  "message_sid": "SM...",
  "from_number": "+12035835289",
  "to_number": "+15551234567",
  "body": "JOIN",
  "body_normalized": "JOIN",
  "endpoint_id": 456
}
```

Or S3 reference:

```json
{
  "s3_bucket": "bucket-name",
  "s3_key": "path/to/message.json"
}
```

Message attributes should include:
- `EventType`: "sms.marketing.inbound"
- `Channel`: "sms"
- `MessageSid`: Twilio message SID

