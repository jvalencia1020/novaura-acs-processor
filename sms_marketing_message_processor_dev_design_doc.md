# SMS Marketing Message Processor Dev Design Doc (Backend)

> **Audience:** Django backend engineer  
> **Purpose:** Implement inbound SMS processing to evaluate keyword rules, manage subscriber opt-in/out state, and execute configured actions for `sms_marketing` campaigns.  
> **Current state:** `sms_marketing` configuration APIs exist (models/serializers/views).  
> **This phase:** inbound message processing + routing + state updates + logging + action dispatch.  
> **Optional:** outbound reply sending for confirmations/help (recommended, but can be stubbed).  

---

## 1) Goals

### Primary goals
1. **Ingest inbound SMS** (provider webhook) and persist as `SmsMessage` (direction=inbound).
2. **Resolve endpoint** (short code / phone number) to `communications.ContactEndpoint`.
3. **Route** inbound SMS to the appropriate `SmsKeywordCampaign` + `SmsKeywordRule` (or fallback).
4. **Enforce compliance keywords** (STOP/HELP) with highest priority.
5. **Update subscriber state** (`SmsSubscriber`) deterministically (opt-in/out).
6. **Emit audit logs** (`SmsCampaignEvent`) for every decision.
7. **Dispatch actions** (send template reply, start journey, create lead, route to agent) via async tasks.

### Non-goals (unless you choose to include)
- Full conversational inbox experience
- Complex throttling/frequency caps (can be added later)
- Cross-channel orchestration beyond invoking existing systems

---

## 2) High-Level Architecture

Inbound flow (recommended):
1. **Webhook endpoint** receives provider payload (Twilio).
2. **Idempotency guard** prevents duplicate processing (provider message id).
3. Create `SmsMessage` inbound record.
4. **Router** determines:
   - global command (STOP/HELP/etc), or
   - campaign + rule match, or
   - fallback behavior
5. **State machine** updates `SmsSubscriber` status.
6. Create `SmsCampaignEvent` describing decision.
7. **Action executor** enqueues tasks (and optionally sends immediate reply).

Recommended separation of concerns:
- `communication_processor` app: webhook endpoints, provider adapters, async execution plumbing
- `sms_marketing` app: routing + business rules + state transitions (pure functions/services)

---

## 3) Provider Integration (Twilio assumed)

### Webhook endpoints
**Implemented in:** `communication_processor` app

- `POST /api/communication_processor/webhooks/twilio/sms/marketing/` ✅ **IMPLEMENTED**
- `POST /webhooks/twilio/sms/status/` (optional; delivery receipts later)

**Implementation details:**
- Location: `communication_processor/views/sms_marketing_webhook.py`
- Shared utilities: `communication_processor/utils/twilio_helpers.py`
  - Reusable functions for SQS, validation, phone normalization
  - Can be used by other webhook endpoints (ACS, etc.)

**Webhook flow:**
1. Validates Twilio signature
2. Extracts and normalizes SMS data
3. Resolves ContactEndpoint
4. Creates `SmsMessage` (with idempotency check)
5. Pushes to SQS queue for async processing
6. Returns 200 OK immediately

**SQS Queue Configuration:**
- Queue URL: `settings.SQS_QUEUE_URLS['sms_marketing']` or fallback to `settings.SQS_QUEUE_URLS['sms']`
- Message attributes include: `EventType='sms.marketing.inbound'`, `Channel='sms'`, `MessageSid`, etc.

Inbound payload fields typically needed:
- `MessageSid` (idempotency key)
- `From` (sender phone)
- `To` (short code / long code)
- `Body`
- `NumMedia` (optional)
- `AccountSid` (optional)
- timestamp (server-side `received_at` is acceptable)

Security:
- Validate Twilio signature (implemented via `validate_twilio_request()`)
- Idempotency via `SmsMessage(provider, provider_message_id)` unique constraint

---

## 4) Data Model Usage

### Required models (already exist)
- `SmsMessage` (log) - **Now includes optional conversation links**
- `SmsSubscriber` (state per endpoint + phone)
- `SmsKeywordCampaign` (config; tied to CRM campaign + endpoint)
- `SmsKeywordRule` (keyword rules)
- `SmsCampaignEvent` (audit)

### Conversation Integration (Hybrid Approach)
`SmsMessage` model includes optional foreign keys to support agent replies and conversation threading:
- `conversation` → `communications.Conversation` (nullable)
  - Linked when `ROUTE_TO_AGENT` action is triggered
  - Enables agent replies and conversation threading
  - One conversation per subscriber per endpoint (reused for follow-ups)
- `conversation_message` → `communications.ConversationMessage` (nullable)
  - Linked when message is also stored in conversation thread
  - Provides bidirectional link between SMS marketing and conversation systems

**When to create/link conversations:**
- `ROUTE_TO_AGENT` action: Always create/link conversation
- Follow-up questions: Create conversation if doesn't exist
- Manual agent replies: Use existing conversation
- Simple keyword responses: No conversation needed

**Benefits:**
- `SmsMessage` remains primary audit trail for SMS marketing
- Conversations enable agent replies and threading
- Both systems can coexist and reference each other
- Flexible: conversations only created when needed

### Contact endpoint resolution
- `ContactEndpoint` in `communications` app is the source of truth for inbound identity.
- Resolve by matching:
  1. `ContactEndpoint.value == normalized_to_number` (E.164 format)
  2. `ContactEndpoint.channels` contains `channel='sms'` (via `ContactEndpointChannel` model)
  3. Optionally filter by `ContactEndpoint.platform` if provider account context is available
- The resolved endpoint links to:
  - `account` (CRM Account)
  - `funnel` (optional CRM Funnel)
  - Campaign mappings via `ContactEndpointCampaign` (many-to-many with `crm.Campaign`)

**Important for opt-in processing:**
- Endpoint resolution determines which `SmsKeywordCampaign` objects are eligible
- Campaigns are scoped to `(account, endpoint)` - ensure endpoint belongs to correct account
- If endpoint resolution fails, log error and optionally use fallback endpoint lookup by phone number only

If multiple environments/accounts share the same address:
- Use `ContactEndpoint.platform` and provider `AccountSid` to disambiguate
- Prefer endpoints with `is_primary=True` when multiple matches exist

---

## 5) Idempotency & Reliability

### Idempotency key
Use `(provider, provider_message_id)` unique constraint semantics (or a defensive lookup):
- If an inbound message with the same `MessageSid` already exists:
  - return 200 immediately
  - do not re-run routing/actions

**Implementation:**
- **Recommended:** Add unique constraint on `SmsMessage(provider, provider_message_id)` in database
- **Alternative:** Use `get_or_create` with defensive check:
  ```python
  message, created = SmsMessage.objects.get_or_create(
      provider='twilio',
      provider_message_id=message_sid,
      defaults={...}
  )
  if not created:
      return HttpResponse(status=200)  # Already processed
  ```
- **Important:** `provider_message_id` must be unique per provider (Twilio MessageSid is globally unique)

**Database Migration:**
```python
# Add unique constraint
class Migration:
    operations = [
        migrations.AlterUniqueTogether(
            name='smsmessage',
            unique_together={('provider', 'provider_message_id')},
        ),
    ]
```

### Async processing (recommended)
Webhook should be fast:
- Persist inbound `SmsMessage`
- Enqueue `process_inbound_sms_message(message_id)` task
- Return 200

Retry strategy:
- Celery retries for transient failures
- Dead-letter queue / failure status logged to `SmsCampaignEvent` and `SmsMessage.error`

---

## 6) Normalization Rules

### Phone numbers
- Normalize `From`/`To` to E.164 (use `phonenumbers` library if possible).
- Store normalized in `SmsMessage.from_number`, `SmsMessage.to_number`, `SmsSubscriber.phone_number`.

### Body normalization
Create two representations:
- `body_raw` (as received) - store in `SmsMessage.body_raw`
- `body_normalized` (trim, collapse whitespace) - store in `SmsMessage.body_normalized`
- `keyword_candidate` derived from normalized body:
  - Uppercase conversion
  - Remove leading/trailing whitespace
  - Collapse multiple spaces to single space
  - Remove punctuation (optional, but recommended for matching)
  - Example: " free!!! " → `FREE`
  - Example: "JOIN NOW" → `JOIN NOW` (preserve multi-word keywords)

**Keyword matching:**
- Keywords are stored in `marketing_tracking.Keyword` model
- Each `SmsKeywordRule` references a `Keyword` via foreign key
- Match against `keyword.keyword` field using `rule.match_type`:
  - `exact`: `keyword_candidate == keyword.keyword` (case-insensitive)
  - `starts_with`: `keyword_candidate.startswith(keyword.keyword)` (case-insensitive)
  - `contains`: `keyword.keyword in keyword_candidate` (case-insensitive)

---

## 7) Global Keyword Commands (Compliance First)

Before campaign routing, check for global commands (case-insensitive):
- STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT → OPT_OUT
- HELP, INFO → HELP

Rules:
- Global commands **always override** campaign keywords.
- OPT_OUT should set subscriber status to `OPTED_OUT` immediately.
- HELP should return program/help text if available (from `SmsProgram` or campaign/program defaults).

Log events:
- `SmsCampaignEvent(event_type=OPT_OUT/HELP)` with payload including matched command and raw body.

---

## 8) Subscriber State Machine

Subscriber key:
- `(endpoint, phone_number)` is canonical (unique constraint enforced).
- Use `SmsSubscriber.objects.get_or_create(endpoint=..., phone_number=normalized_from_number)`

**Subscriber status values:**
- `unknown` (default) - no opt-in/out recorded
- `pending_opt_in` - double opt-in: keyword received, awaiting confirmation
- `opted_in` - fully opted in (single opt-in) or confirmed (double opt-in)
- `opted_out` - explicitly opted out

**State transitions:**

1. **UNKNOWN → OPTED_IN** (single opt-in mode):
   - Triggered by keyword with `action_type='OPT_IN'` when `campaign.opt_in_mode='single'`
   - Set: `status='opted_in'`, `opt_in_at=now`, `opt_in_source='keyword'`, `opt_in_keyword=<matched_keyword>`
   - Update: `last_inbound_at=now`

2. **UNKNOWN → PENDING_OPT_IN** (double opt-in mode):
   - Triggered by keyword with `action_type='OPT_IN'` when `campaign.opt_in_mode='double'`
   - Set: `status='pending_opt_in'`, `opt_in_source='keyword'`, `opt_in_keyword=<matched_keyword>`
   - **Do NOT set `opt_in_at` yet** - only set when confirmed
   - Send confirmation message (e.g., "Reply YES to confirm opt-in")
   - Update: `last_inbound_at=now`

3. **PENDING_OPT_IN → OPTED_IN** (double opt-in confirmation):
   - User replies with confirmation keyword (typically "YES" or configured keyword)
   - Set: `status='opted_in'`, `opt_in_at=now`
   - Update: `last_inbound_at=now`
   - Send welcome message if configured

4. **UNKNOWN → OPTED_OUT** (STOP command):
   - Set: `status='opted_out'`, `opt_out_at=now`, `opt_out_source='keyword'`
   - Update: `last_inbound_at=now`

5. **OPTED_IN → OPTED_OUT** (STOP command):
   - Set: `status='opted_out'`, `opt_out_at=now`, `opt_out_source='keyword'`
   - Update: `last_inbound_at=now`

6. **OPTED_OUT → OPTED_IN** (re-opt-in):
   - **Policy decision required:** Default recommendation is **YES, allow re-opt-in**
   - Only if keyword has `action_type='OPT_IN'` and `rule.requires_not_opted_out=False` (or explicit override)
   - Set: `status='opted_in'`, `opt_in_at=now`, `opt_in_source='keyword'`, `opt_in_keyword=<matched_keyword>`
   - Clear: `opt_out_at=None`, `opt_out_source=None` (or preserve for audit)
   - Update: `last_inbound_at=now`

7. **PENDING_OPT_IN → OPTED_OUT** (user opts out during pending):
   - If user sends STOP while in pending state
   - Set: `status='opted_out'`, `opt_out_at=now`, `opt_out_source='keyword'`
   - Clear pending opt-in fields

**Maintain timestamps/sources:**
- On opt-in (final):
  - `status='opted_in'`, `opt_in_at=now`, `opt_in_source='keyword'`, `opt_in_keyword=<keyword>`
- On opt-out:
  - `status='opted_out'`, `opt_out_at=now`, `opt_out_source='keyword'`
- On pending opt-in:
  - `status='pending_opt_in'`, `opt_in_source='keyword'`, `opt_in_keyword=<keyword>`, `opt_in_at=None`

**Update activity:**
- Always set `last_inbound_at=now` when receiving inbound message
- Set `last_outbound_at=now` when sending outbound confirmations/help (if implemented)

**Lead linking:**
- `SmsSubscriber.lead` is optional and can be set during opt-in if:
  - Lead exists matching phone number (normalize and match)
  - Or lead is created via `CREATE_LEAD` action
  - Link lead to subscriber: `subscriber.lead = lead; subscriber.save()`

---

## 9) Campaign & Rule Matching Logic

### Eligible campaigns
A campaign is eligible if:
- `campaign.endpoint == resolved endpoint`
- `campaign.status == 'active'` (not 'draft', 'paused', or 'archived')

Order candidates by:
- `campaign.priority DESC`, then `campaign.id ASC` (stable tie-break)

**Query pattern:**
```python
eligible_campaigns = SmsKeywordCampaign.objects.filter(
    endpoint=resolved_endpoint,
    status='active'
).order_by('-priority', 'id')
```

### Eligible rules
Rule is eligible if:
- `rule.is_active == True`
- `rule.campaign` is in eligible campaigns list
- Keyword matching logic (see below)
- Subscriber status check:
  - If subscriber is `opted_out` and `rule.requires_not_opted_out == True`:
    - **Block rule** UNLESS `rule.action_type == 'OPT_IN'` (allow re-opt-in)
  - If subscriber is `pending_opt_in`:
    - Allow rules with confirmation keywords (e.g., "YES") to complete double opt-in
    - Block other rules until confirmation received

**Keyword matching:**
- Rules reference `marketing_tracking.Keyword` via `rule.keyword`
- Match `keyword_candidate` against `rule.keyword.keyword` using `rule.match_type`:
  - `exact`: `keyword_candidate.upper() == rule.keyword.keyword.upper()`
  - `starts_with`: `keyword_candidate.upper().startswith(rule.keyword.keyword.upper())`
  - `contains`: `rule.keyword.keyword.upper() in keyword_candidate.upper()`

**Matching priority (within same campaign):**
1. EXACT match (highest priority)
2. STARTS_WITH match
3. CONTAINS match (lowest priority, discouraged but supported)

**Tie-break (when multiple rules match same match_type):**
- `rule.priority DESC`, then `rule.id ASC`

**Cross-campaign matching:**
- Evaluate campaigns in priority order (campaign.priority DESC)
- Within each campaign, evaluate rules by match_type then rule.priority
- Return first match found (highest priority campaign + highest priority rule)

**Query pattern:**
```python
# For each eligible campaign (in priority order):
for campaign in eligible_campaigns:
    active_rules = campaign.rules.filter(is_active=True).order_by('-priority', 'id')
    
    # Try exact matches first
    for rule in active_rules.filter(match_type='exact'):
        if matches(rule, keyword_candidate):
            return (campaign, rule)
    
    # Then starts_with
    for rule in active_rules.filter(match_type='starts_with'):
        if matches(rule, keyword_candidate):
            return (campaign, rule)
    
    # Finally contains
    for rule in active_rules.filter(match_type='contains'):
        if matches(rule, keyword_candidate):
            return (campaign, rule)
```

Result:
- matched `(campaign, rule)` or no match.

### Fallback behavior
If no rule matches:
- Use `campaign.fallback_action_type/config` (if defined) OR
- Use endpoint/program default fallback (optional) OR
- No-op (log event) + optional generic help prompt

Important: fallback should be **deterministic** and logged.

---

## 10) Conflict Handling at Runtime

Conflicts should be prevented at activation time, but processor must be safe:
- If multiple campaigns/rules match due to misconfiguration:
  - pick highest priority deterministically
  - emit `SmsCampaignEvent(event_type=ERROR)` with payload including conflicts detected
  - optionally alert (Sentry/Slack)

---

## 11) Action Execution

### Action types (from `SmsKeywordRule.action_type`)
- `OPT_IN` - Opt-in subscriber (respects campaign opt_in_mode)
- `OPT_OUT` - Opt-out subscriber
- `HELP` - Send help information
- `SEND_TEMPLATE` - Send a configured template message
- `START_JOURNEY` - Enroll in nurturing journey
- `CREATE_LEAD` - Create or update lead in CRM
- `ROUTE_TO_AGENT` - Forward to ACS conversation engine
- `COMPOSITE` - Execute multiple actions in sequence/parallel (see Composite Actions below)

Processor responsibilities:
- Update subscriber state as required
- Create logs (`SmsCampaignEvent`)
- Enqueue downstream tasks (async)
- Link subscriber to lead if applicable

Recommended action execution pattern:
- `sms_marketing/services/actions.py`
  - `execute_action(route_result, inbound_message, subscriber) -> ExecutionResult`
- Each action should be implemented as a handler:
  - `handle_opt_in(campaign, rule, subscriber, message, action_config)`
  - `handle_opt_out(campaign, rule, subscriber, message, action_config)`
  - `handle_send_template(campaign, rule, subscriber, message, action_config)`
  - `handle_start_journey(campaign, rule, subscriber, message, action_config)`
  - `handle_create_lead(campaign, rule, subscriber, message, action_config)`
  - `handle_route_to_agent(campaign, rule, subscriber, message, action_config)`
  - `handle_composite(campaign, rule, subscriber, message, action_config)`

### Action execution details

#### OPT_IN action
**Behavior:**
1. Check `campaign.opt_in_mode`:
   - `'single'`: Set subscriber to `opted_in` immediately
   - `'double'`: Set subscriber to `pending_opt_in`, send confirmation request
   - `'none'`: Skip opt-in state change (log only)
2. Update subscriber:
   - `status='opted_in'` (single) or `'pending_opt_in'` (double)
   - `opt_in_at=now` (only if single opt-in or after confirmation)
   - `opt_in_source='keyword'`
   - `opt_in_keyword=<matched_keyword>` (from `rule.keyword.keyword`)
   - `last_inbound_at=now`
3. Link lead if phone matches existing lead (normalize and match)
4. Send confirmation message:
   - Single opt-in: Welcome message from `action_config.template_id` or campaign default
   - Double opt-in: "Reply YES to confirm" message
5. Log event: `SmsCampaignEvent(event_type='opt_in', ...)`
6. If campaign has `follow_up_nurturing_campaign`, enqueue enrollment task

**Action config structure:**
```json
{
  "template_id": 123,  // Optional: template for welcome message
  "welcome_message": "Thank you for opting in!",  // Optional: direct message text
  "link_lead": true,  // Optional: attempt to link to existing lead
  "create_lead_if_missing": false  // Optional: create lead if not found
}
```

#### OPT_OUT action
- Set subscriber `status='opted_out'`, `opt_out_at=now`, `opt_out_source='keyword'`
- Send opt-out confirmation ("You are unsubscribed.") if required by policy/provider
- Log event: `SmsCampaignEvent(event_type='opt_out', ...)`

#### HELP action
- Send help response from:
  1. `action_config.help_text` (rule-specific)
  2. `campaign.program.help_text` (if program exists)
  3. Default help message
- Log event: `SmsCampaignEvent(event_type='message_sent', ...)`

#### SEND_TEMPLATE action
- Extract `template_id` from `action_config.template_id`
- Load template (implementation depends on your template system)
- Render template with subscriber/lead context
- Queue outbound message via async task
- Log event: `SmsCampaignEvent(event_type='message_sent', ...)`

#### START_JOURNEY action
- Extract `nurturing_campaign_id` from `action_config.nurturing_campaign_id`
- Or use `campaign.follow_up_nurturing_campaign` if not specified
- Create `acs.LeadNurturingParticipant` (link to subscriber.lead if available)
- Enqueue first step in journey system
- Log event: `SmsCampaignEvent(event_type='nurturing_campaign_enrolled', nurturing_campaign=..., nurturing_participant=...)`

#### CREATE_LEAD action
- Extract lead data from `action_config.lead_data`
- Use subscriber phone number, endpoint account, campaign context
- Create or update `crm.Lead` via async task
- Link to subscriber: `subscriber.lead = created_lead; subscriber.save()`
- Log event: `SmsCampaignEvent(event_type='message_received', ...)`

#### ROUTE_TO_AGENT action
**Behavior:**
1. Get or create `Conversation` for subscriber:
   - Use deterministic conversation SID: `SM_MKT_{endpoint_id}_{phone_number}`
   - Link to subscriber's lead if available: `conversation.lead = subscriber.lead`
   - Set `conversation.channel = 'sms'`, `conversation.state = 'active'`
2. Create `ConversationMessage` for threading:
   - Link to conversation and create participant if needed
   - Store message body, direction='inbound', channel='sms'
   - Include reference to `SmsMessage` in `raw_data`
3. Link `SmsMessage` to conversation:
   - `message.conversation = conversation`
   - `message.conversation_message = conversation_message`
   - Save message
4. Route to ACS conversation engine (existing integration)
5. Log event: `SmsCampaignEvent(event_type='message_received', payload={'conversation_id': conversation.id, ...})`

**Action config structure:**
```json
{
  "create_conversation": true,  // Optional, defaults to true
  "conversation_friendly_name": "SMS Marketing - {subscriber.phone_number}",  // Optional
  "route_to_acs": true  // Optional, defaults to true
}
```

**Helper function pattern:**
```python
def get_or_create_sms_marketing_conversation(subscriber, endpoint, lead=None):
    """Get or create conversation for SMS marketing subscriber"""
    conversation_sid = f"SM_MKT_{endpoint.id}_{subscriber.phone_number}"
    
    conversation, created = Conversation.objects.get_or_create(
        twilio_sid=conversation_sid,
        defaults={
            'channel': 'sms',
            'state': 'active',
            'lead': lead,
            'messaging_service_sid': endpoint.value,  # Or endpoint identifier
        }
    )
    
    return conversation
```

#### COMPOSITE action
- Execute multiple actions from `action_config.actions` array
- Execution mode: `action_config.execution_mode` ('sequential' or 'parallel', default 'sequential')
- Stop on error: `action_config.stop_on_error` (default False)
- Timeout: `action_config.execution_timeout` (optional, seconds)
- Each sub-action has `type` and `config` fields
- Log events for each sub-action execution
- Return aggregated result

**Composite action config structure:**
```json
{
  "actions": [
    {"type": "OPT_IN", "config": {}},
    {"type": "CREATE_LEAD", "config": {"crm_campaign_id": 123}},
    {"type": "SEND_TEMPLATE", "config": {"template_id": 456}}
  ],
  "execution_mode": "sequential",
  "stop_on_error": false,
  "execution_timeout": 30
}
```

---

## 12) Outbound Reply Sending (Optional but Recommended)

Short code programs typically need immediate replies for:
- OPT_IN confirmation
- HELP
- STOP confirmation
- Simple template replies

Implementation options:
- Reuse existing `communications` / `communication_processor` send pipeline:
  - create an outbound `SmsMessage` with direction=outbound, status=queued
  - enqueue `send_sms_message(message_id)`
- Or integrate directly with Twilio in a thin adapter.

Do not block webhook on send; always async.

---

## 13) Logging & Observability

### Required logs per inbound message
1. `SmsMessage` inbound row created (always)
2. `SmsCampaignEvent` created for the primary decision (see event types below)
3. If an outbound message is queued/sent:
   - `SmsMessage` outbound row + status transitions (queued→sent→delivered/failed)

### Event types (from `SmsCampaignEvent.EVENT_TYPE_CHOICES`)
- `keyword_matched` - Keyword matched a rule
- `rule_triggered` - Rule action was executed
- `opt_in` - Subscriber opted in (single or confirmed double opt-in)
- `opt_out` - Subscriber opted out
- `nurturing_campaign_enrolled` - Subscriber enrolled in nurturing campaign
- `message_sent` - Outbound message was sent
- `message_received` - Inbound message was received (logged separately from keyword_matched)
- `error` - Error occurred during processing

### Event payload structure

**Base payload (all events):**
```json
{
  "provider": "twilio",
  "provider_message_id": "SM...",
  "normalized_body": "JOIN",
  "keyword_candidate": "JOIN",
  "subscriber_status_before": "unknown",
  "subscriber_status_after": "opted_in"
}
```

**keyword_matched event:**
```json
{
  ...base_payload,
  "selected_campaign_id": 123,
  "selected_campaign_name": "Summer Campaign",
  "selected_rule_id": 456,
  "matched_keyword": "JOIN",
  "match_type": "exact",
  "action_type": "OPT_IN"
}
```

**opt_in event:**
```json
{
  ...base_payload,
  "campaign_id": 123,
  "rule_id": 456,
  "opt_in_mode": "single",
  "opt_in_keyword": "JOIN",
  "opt_in_source": "keyword",
  "confirmed": true,  // false for double opt-in pending
  "lead_linked": true,
  "lead_id": 789  // if lead was linked/created
}
```

**opt_out event:**
```json
{
  ...base_payload,
  "opt_out_source": "keyword",
  "opt_out_keyword": "STOP",
  "was_opted_in": true  // previous status
}
```

**nurturing_campaign_enrolled event:**
```json
{
  ...base_payload,
  "campaign_id": 123,
  "rule_id": 456,
  "nurturing_campaign_id": 789,
  "nurturing_participant_id": 101,
  "lead_id": 102  // if lead was linked
}
```

**error event:**
```json
{
  ...base_payload,
  "error_type": "endpoint_not_found" | "subscriber_opted_out" | "processing_error",
  "error_message": "Detailed error message",
  "traceback": "..."  // optional, for debugging
}
```

**fallback_triggered event:**
```json
{
  ...base_payload,
  "campaign_id": 123,  // campaign that triggered fallback
  "fallback_action_type": "SEND_TEMPLATE",
  "fallback_action_config": {...},
  "reason": "no_keyword_match"
}
```

---

## 14) Implementation Modules

### ✅ Implemented in `communication_processor/` (This Repository)

#### Webhook Endpoint
- **`views/sms_marketing_webhook.py`** ✅ **IMPLEMENTED**
  - `twilio_sms_marketing_webhook()` - lightweight webhook endpoint
  - URL: `/api/communication_processor/webhooks/twilio/sms/marketing/`
  - Flow:
    1. Validates Twilio signature
    2. Extracts and normalizes SMS data
    3. Resolves ContactEndpoint
    4. Creates `SmsMessage` (with idempotency check)
    5. Pushes to SQS queue with message attributes
    6. Returns 200 OK immediately
  - Error handling: Returns 200 even on errors to prevent Twilio retries
  - Idempotency: Uses `SmsMessage(provider, provider_message_id)` unique constraint

#### Shared Utilities
- **`utils/twilio_helpers.py`** ✅ **IMPLEMENTED**
  - **Reusable across all webhook endpoints** (ACS, SMS marketing, etc.)
  - Functions:
    - `validate_twilio_request(request)` - Twilio signature validation
    - `extract_sms_data(event_data)` - Extract and structure SMS data from Twilio payload
    - `normalize_phone_number(phone_number)` - Returns tuple: `(normalized_e164, list_of_formats)`
      - Primary: E.164 format (e.g., "+12035835289")
      - Formats: List of all possible formats for matching
    - `normalize_message_body(body)` - Trim, collapse whitespace
    - `send_to_sqs(queue_url, message_body, message_attributes)` - Send message to SQS queue
    - `get_sqs_client()` / `get_sqs_client_instance()` - SQS client management (singleton)
    - `get_sms_marketing_queue_url()` - Get queue URL from settings

**Note:** ACS webhook (`acs/views/twilio_webhooks.py`) has been refactored to use these shared utilities.

### SQS Message Format (Sent by Webhook)

The webhook sends messages to SQS with the following structure:

**Message Body (JSON):**
```json
{
  "message_sid": "SM1234567890abcdef",
  "sms_message_sid": "SM1234567890abcdef",
  "sms_sid": "SM1234567890abcdef",
  "account_sid": "AC1234567890abcdef",
  "messaging_service_sid": "MG1234567890abcdef",
  "from_number": "+12035835289",
  "to_number": "+15551234567",
  "body": "JOIN",
  "body_normalized": "JOIN",
  "event_type": "sms.message",
  "status": "received",
  "num_segments": 1,
  "num_media": 0,
  "media_url": null,
  "endpoint_id": 123,
  "endpoint_value": "+15551234567",
  "account_id": 456,
  "funnel_id": null,
  "direction": "inbound",
  "channel": "sms",
  "webhook_received_at": "2024-01-15T10:30:05Z",
  "sms_message_id": 789,
  "raw_data": {
    "MessageSid": "SM1234567890abcdef",
    "From": "+12035835289",
    "To": "+15551234567",
    "Body": "JOIN",
    ...
  }
}
```

**Message Attributes (for SQS filtering):**
- `EventType`: "sms.marketing.inbound" (use this to filter messages)
- `Channel`: "sms"
- `MessageSid`: Twilio message SID (for idempotency)
- `Direction`: "inbound"
- `AccountId`: Account ID (if available, as string)
- `SmsMessageId`: Database ID of SmsMessage record (as string)

**Processor Implementation Notes:**
- Filter SQS messages by `EventType='sms.marketing.inbound'` attribute
- Use `sms_message_id` from message body to load `SmsMessage` from database
- If `sms_message_id` is missing, processor can create `SmsMessage` from payload (fallback)
- All phone numbers are already normalized to E.164 format
- `body_normalized` is ready for keyword matching (trimmed, whitespace collapsed)

### To be implemented in SMS processor (separate repository)

**SQS Consumer:**
- Consume messages from SQS queue (`settings.SQS_QUEUE_URLS['sms_marketing']`)
- Filter by `EventType='sms.marketing.inbound'` message attribute
- Process each message asynchronously

**Processing Task:**
- `process_inbound_sms_message(sqs_message_body)` or `process_inbound_sms_message(sms_message_id)`
  - Load `SmsMessage` by ID from message body
  - Get or create `SmsSubscriber`
  - Extract keyword candidate from `body_normalized`
  - Check global compliance keywords (STOP/HELP)
  - Route to campaign/rule
  - Update subscriber state
  - Execute actions
  - Create `SmsCampaignEvent` logs

**Required Services:**
- Keyword routing logic
- Subscriber state machine
- Action execution handlers
- Event logging

### To be implemented in `sms_marketing/services/` (this repository)

**Service modules (can be imported by processor):**
- `router.py`
  - `route_inbound(endpoint, from_number, body_normalized, subscriber) -> RouteResult`
  - Campaign/rule matching logic
- `state.py`
  - Subscriber state transitions helpers
  - `update_subscriber_status()`, `handle_opt_in()`, `handle_opt_out()`
- `actions.py`
  - Action dispatcher + handlers
  - `execute_action(campaign, rule, subscriber, message, action_config) -> ExecutionResult`
  - Individual handlers: `handle_opt_in()`, `handle_send_template()`, etc.
- `normalization.py` (optional - can reuse from `communication_processor.utils`)
  - Keyword candidate extraction
  - Additional normalization helpers if needed

---

## 15) Suggested Pseudocode (End-to-End)

### Webhook (fast) ✅ IMPLEMENTED
**Location:** `communication_processor/views/sms_marketing_webhook.py`

**Actual Implementation:**
```python
@csrf_exempt
@require_http_methods(["POST"])
def twilio_sms_marketing_webhook(request):
    # 1. Validate Twilio signature (using shared utility)
    if not validate_twilio_request(request):
        return HttpResponse(status=403)
    
    # 2. Extract SMS data (using shared utility)
    event_data = request.POST.dict()
    sms_data = extract_sms_data(event_data)
    
    # 3. Normalize phone numbers (using shared utility)
    normalized_from, _ = normalize_phone_number(sms_data['from_number'])
    normalized_to, _ = normalize_phone_number(sms_data['to_number'])
    
    # 4. Resolve endpoint
    endpoint = ContactEndpoint.objects.filter(
        value=normalized_to,
        channels__channel='sms'
    ).first()
    
    if not endpoint:
        return HttpResponse(status=200)  # Return 200 to prevent retries
    
    # 5. Normalize message body (using shared utility)
    body_normalized = normalize_message_body(sms_data['body'])
    
    # 6. Idempotency check - get or create SmsMessage
    message, created = SmsMessage.objects.get_or_create(
        provider='twilio',
        provider_message_id=sms_data['message_sid'],
        defaults={
            'endpoint': endpoint,
            'direction': 'inbound',
            'status': 'received',
            'from_number': normalized_from,
            'to_number': normalized_to,
            'body_raw': sms_data['body'],
            'body_normalized': body_normalized,
            'received_at': timezone.now(),
        }
    )
    
    if not created:
        return HttpResponse(status=200)  # Already processed
    
    # 7. Prepare SQS message with endpoint context
    sqs_data = {
        # ... (see SQS Message Format section above)
    }
    
    # 8. Push to SQS (using shared utility)
    send_to_sqs(
        queue_url=get_sms_marketing_queue_url(),
        message_body=sqs_data,
        message_attributes={...}
    )
    
    # 9. Return 200 immediately
    return HttpResponse(status=200)
```

**Key Implementation Details:**
- Uses shared utilities from `communication_processor.utils.twilio_helpers`
- Idempotency via database unique constraint on `(provider, provider_message_id)`
- Returns 200 even on errors to prevent Twilio retries
- Includes `sms_message_id` in SQS payload for processor to load message

### Task processor (To be implemented in SMS processor repository)
**Note:** This runs in a separate Django project/service that consumes from SQS.

```python
# In your SMS processor service
def process_sqs_message(sqs_message):
    """
    Process message from SQS queue.
    Can be triggered by:
    - Lambda function
    - Celery task
    - Background worker
    """
    message_body = json.loads(sqs_message['Body'])
    sms_message_id = message_body.get('sms_message_id')
    
    if sms_message_id:
        # Load from database
        process_inbound_sms_message(sms_message_id)
    else:
        # Process from SQS payload directly
        process_inbound_sms_from_payload(message_body)

@shared_task  # or @celery_app.task
def process_inbound_sms_message(message_id):
    try:
        # 1. Load message + endpoint
        message = SmsMessage.objects.get(id=message_id)
        endpoint = message.endpoint
        
        # 2. Get or create subscriber
        subscriber, created = SmsSubscriber.objects.get_or_create(
            endpoint=endpoint,
            phone_number=message.from_number,
            defaults={'status': 'unknown'}
        )
        
        # Update last_inbound_at
        subscriber.last_inbound_at = timezone.now()
        subscriber.save(update_fields=['last_inbound_at'])
        
        # 3. Normalize body + extract keyword candidate
        keyword_candidate = extract_keyword_candidate(message.body_normalized)
        
        # 4. Check global compliance keywords (STOP/HELP) - highest priority
        if is_global_stop_keyword(keyword_candidate):
            handle_global_opt_out(subscriber, message)
            return
        
        if is_global_help_keyword(keyword_candidate):
            handle_global_help(subscriber, message, endpoint)
            return
        
        # 5. Route to campaign/rule
        route_result = route_inbound_message(endpoint, keyword_candidate, subscriber)
        
        if not route_result:
            # No match - handle fallback
            handle_fallback(endpoint, subscriber, message)
            return
        
        campaign = route_result.campaign
        rule = route_result.rule
        
        # 6. Check subscriber status restrictions
        if subscriber.status == 'opted_out' and rule.requires_not_opted_out:
            if rule.action_type != 'OPT_IN':
                # Blocked - subscriber opted out
                log_event(endpoint, campaign, rule, subscriber, message, 
                         event_type='error', 
                         payload={'reason': 'subscriber_opted_out'})
                return
        
        # 7. Handle double opt-in confirmation
        if subscriber.status == 'pending_opt_in':
            if is_confirmation_keyword(keyword_candidate, campaign):
                # Complete double opt-in
                subscriber.status = 'opted_in'
                subscriber.opt_in_at = timezone.now()
                subscriber.save()
                log_event(endpoint, campaign, rule, subscriber, message, 
                         event_type='opt_in',
                         payload={'confirmed': True})
                # Send welcome message
                send_welcome_message(campaign, subscriber, message)
                return
            else:
                # Still pending - ignore non-confirmation keywords
                log_event(endpoint, campaign, rule, subscriber, message,
                         event_type='error',
                         payload={'reason': 'awaiting_confirmation'})
                return
        
        # 8. Update message with campaign/rule/subscriber links
        message.campaign = campaign
        message.rule = rule
        message.subscriber = subscriber
        message.save()
        
        # 9. Execute action
        execution_result = execute_action(
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            action_config=rule.action_config or {}
        )
        
        # 10. Log event
        log_event(
            endpoint=endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type=execution_result.event_type,
            payload=execution_result.payload
        )
        
    except Exception as e:
        logger.exception(f"Error processing message {message_id}: {e}")
        # Log error event
        if 'message' in locals():
            log_event(
                endpoint=message.endpoint,
                campaign=None,
                rule=None,
                subscriber=None,
                message=message,
                event_type='error',
                payload={'error': str(e)}
            )
        raise
```

### Helper functions
```python
def route_inbound_message(endpoint, keyword_candidate, subscriber):
    """Route message to campaign and rule"""
    # Get eligible campaigns
    campaigns = SmsKeywordCampaign.objects.filter(
        endpoint=endpoint,
        status='active'
    ).order_by('-priority', 'id')
    
    for campaign in campaigns:
        # Get active rules for this campaign
        rules = campaign.rules.filter(is_active=True).order_by('-priority', 'id')
        
        # Check subscriber status restrictions
        if subscriber.status == 'opted_out':
            rules = rules.filter(
                Q(requires_not_opted_out=False) | Q(action_type='OPT_IN')
        )
        
        # Try exact matches first
        for rule in rules.filter(match_type='exact'):
            if matches_keyword(rule, keyword_candidate, 'exact'):
                return RouteResult(campaign=campaign, rule=rule)
        
        # Then starts_with
        for rule in rules.filter(match_type='starts_with'):
            if matches_keyword(rule, keyword_candidate, 'starts_with'):
                return RouteResult(campaign=campaign, rule=rule)
        
        # Finally contains
        for rule in rules.filter(match_type='contains'):
            if matches_keyword(rule, keyword_candidate, 'contains'):
                return RouteResult(campaign=campaign, rule=rule)
    
    return None

def matches_keyword(rule, keyword_candidate, match_type):
    """Check if keyword matches rule"""
    keyword_text = rule.keyword.keyword.upper()
    candidate = keyword_candidate.upper()
    
    if match_type == 'exact':
        return candidate == keyword_text
    elif match_type == 'starts_with':
        return candidate.startswith(keyword_text)
    elif match_type == 'contains':
        return keyword_text in candidate
    return False
```

---

## 16) Testing Plan

### Unit tests (services)
- normalization functions
- global keyword detection
- campaign/rule matching priority
- subscriber state transitions

### Integration tests
- webhook endpoint accepts payload and creates `SmsMessage`
- idempotency prevents duplicates
- `process_inbound_sms_message` creates `SmsCampaignEvent`
- OPT_OUT blocks further actions and logs correctly

---

## 17) Acceptance Criteria

### Webhook (✅ Implemented)
1. ✅ Inbound webhook persists `SmsMessage` and pushes to SQS queue.
2. ✅ Idempotency works using provider message id (database unique constraint).
3. ✅ Webhook returns 200 immediately (does not block on processing).
4. ✅ SQS message includes all necessary context (endpoint, account, message ID).

### Processor (To be implemented)
1. Processor consumes messages from SQS queue (`EventType='sms.marketing.inbound'`).
2. Processor resolves endpoint, subscriber, and matches correct rule deterministically.
3. STOP/HELP override is implemented (highest priority).
4. Subscriber state updates (opt-in/out) happen correctly with timestamps and sources.
5. Events are logged in `SmsCampaignEvent` for every inbound message.
6. Actions are dispatched asynchronously (even if downstream handlers are stubs).
7. Conversation links are created when `ROUTE_TO_AGENT` action is triggered.
8. Double opt-in flow works correctly (pending → confirmed).

---

## 18) Keyword Opt-In Processing Details

### Double Opt-In Flow

**Campaign Configuration:**
- `SmsKeywordCampaign.opt_in_mode` determines behavior:
  - `'single'`: Immediate opt-in on keyword match
  - `'double'`: Two-step process (keyword → confirmation)
  - `'none'`: No automatic opt-in state change

**Double Opt-In Process:**
1. User texts opt-in keyword (e.g., "JOIN")
2. System sets subscriber to `pending_opt_in` status
3. System sends confirmation request: "Reply YES to confirm opt-in"
4. User replies with confirmation keyword (typically "YES")
5. System sets subscriber to `opted_in` and sets `opt_in_at` timestamp
6. System sends welcome message

**Confirmation Keyword Matching:**
- Default confirmation keywords: "YES", "Y", "CONFIRM", "OK"
- Can be configured in `action_config.confirmation_keywords` array
- Match using same logic as regular keywords (exact/starts_with/contains)
- When subscriber is `pending_opt_in`, only confirmation keywords trigger state change

**Important Notes:**
- During `pending_opt_in` state, other keywords are ignored (except STOP/HELP)
- If user sends STOP during pending, transition to `opted_out`
- Confirmation timeout: Consider adding `pending_opt_in_expires_at` field if needed
- Double opt-in confirmation should link to original campaign that triggered it

### Lead Linking During Opt-In

**Automatic Lead Matching:**
- When processing opt-in, attempt to link subscriber to existing lead:
  1. Normalize subscriber phone number to multiple formats
  2. Search `crm.Lead` by phone number (check all phone fields)
  3. If match found: `subscriber.lead = matched_lead; subscriber.save()`
  4. If no match and `action_config.create_lead_if_missing=True`:
     - Create new lead with phone number
     - Link to campaign's account
     - Link subscriber to new lead

**Lead Creation via CREATE_LEAD Action:**
- Extract lead data from `action_config.lead_data`:
  ```json
  {
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "crm_campaign_id": 123,
    "source": "sms_keyword"
  }
  ```
- Use subscriber phone number as primary phone
- Link to `campaign.account`
- Link to `campaign.crm_campaigns` (primary or all)
- Create lead via async task to avoid blocking
- After creation: `subscriber.lead = created_lead; subscriber.save()`

### Campaign Opt-In Mode Considerations

**Single Opt-In (`opt_in_mode='single'`):**
- Immediate opt-in on keyword match
- Set `opt_in_at` immediately
- Send welcome message immediately
- Simpler flow, less compliance protection

**Double Opt-In (`opt_in_mode='double'`):**
- Two-step confirmation required
- Better compliance (TCPA, GDPR)
- Higher abandonment rate
- Requires confirmation keyword matching logic

**No Opt-In (`opt_in_mode='none'`):**
- Keyword triggers actions but doesn't change opt-in status
- Useful for informational keywords
- Subscriber remains in current state (unknown/opted_in/opted_out)

### Keyword Matching Specifics

**Keyword Model Structure:**
- Keywords stored in `marketing_tracking.Keyword`
- Each keyword has: `keyword` (text), `endpoint`, `account`, `status`
- `SmsKeywordRule` references `Keyword` via foreign key
- Keyword must belong to same endpoint as campaign

**Matching Algorithm:**
1. Normalize incoming message body to `keyword_candidate`
2. For each eligible campaign (priority order):
   - For each active rule (priority order):
     - Get `rule.keyword.keyword`
     - Apply `rule.match_type`:
       - `exact`: Case-insensitive exact match
       - `starts_with`: Case-insensitive prefix match
       - `contains`: Case-insensitive substring match
     - If match found, return (campaign, rule)
3. If no match, check fallback

**Multi-word Keywords:**
- Preserve spaces in normalization: "JOIN NOW" → "JOIN NOW"
- Match against full keyword text
- Example: Keyword "JOIN NOW" matches "JOIN NOW" (exact) or "JOIN NOW PLEASE" (starts_with)

### ContactEndpoint Resolution Details

**Resolution Steps:**
1. Normalize `To` number to E.164 format
2. Query: `ContactEndpoint.objects.filter(value=normalized_to)`
3. Filter by SMS channel: `.filter(channels__channel='sms')`
4. If multiple matches:
   - Prefer `is_primary=True`
   - Prefer matching `platform` if provider context available
   - Use first match (deterministic)
5. Validate endpoint has `account` (required for campaign lookup)

**Endpoint Context:**
- Endpoint provides: `account`, `funnel` (optional), campaign mappings
- Campaigns are scoped to `(account, endpoint)`
- Ensure endpoint belongs to correct account for security

---

## 19) Open Decisions (Defaults Engineer Should Confirm)

- **Allow re-opt-in after opt-out via keyword?** (recommended: **yes**, explicit)
  - Default: Allow if `rule.action_type='OPT_IN'` and `rule.requires_not_opted_out=False`
- **Are campaigns endpoint-scoped only, or tenant/account-scoped too?**
  - Current model: Campaigns are `(account, endpoint)` scoped
  - Confirmed: Endpoint resolution determines eligible campaigns
- **What is the canonical SMS template model for `SEND_TEMPLATE` actions?**
  - Need to identify template system/model
  - Action config expects `template_id` - confirm model/table
- **Which journey/ACS hooks exist today (what tasks/services to call)?**
  - `START_JOURNEY` action needs: `acs.LeadNurturingCampaign` and `acs.LeadNurturingParticipant` creation
  - `ROUTE_TO_AGENT` action needs: ACS conversation engine integration
  - Confirm existing task/service names
- **Double opt-in confirmation keywords:**
  - Default: ["YES", "Y", "CONFIRM", "OK"]
  - Should be configurable per campaign or global?
- **Pending opt-in expiration:**
  - Should `pending_opt_in` status expire after X days?
  - If yes, what happens to expired pending opt-ins?
- **Lead matching strategy:**
  - How many phone number formats to try?
  - Should matching be fuzzy or exact only?
  - Create lead automatically or require explicit CREATE_LEAD action?

---

## 20) Integration Points for Processor Team

### Database Models (This Repository) ✅ Ready
All models are in `sms_marketing` app and ready for use:
- **`SmsMessage`** - Message log (includes conversation links)
  - Fields: `id`, `endpoint`, `provider`, `provider_message_id`, `direction`, `status`, `from_number`, `to_number`, `body_raw`, `body_normalized`, `campaign`, `rule`, `subscriber`, `conversation`, `conversation_message`, `error`, timestamps
  - Unique constraint: `(provider, provider_message_id)` for idempotency
- **`SmsSubscriber`** - Subscriber state management
  - Fields: `id`, `endpoint`, `phone_number`, `lead`, `status`, `opt_in_*`, `opt_out_*`, `last_inbound_at`, `last_outbound_at`, `metadata`
  - Unique constraint: `(endpoint, phone_number)`
- **`SmsKeywordCampaign`** - Campaign configuration
  - Fields: `id`, `account`, `endpoint`, `name`, `status`, `priority`, `opt_in_mode`, `fallback_action_type`, `fallback_action_config`
- **`SmsKeywordRule`** - Keyword rules
  - Fields: `id`, `campaign`, `keyword` (FK to `marketing_tracking.Keyword`), `match_type`, `priority`, `requires_not_opted_out`, `action_type`, `action_config`, `is_active`
- **`SmsCampaignEvent`** - Event logging
  - Fields: `id`, `endpoint`, `campaign`, `rule`, `subscriber`, `message`, `nurturing_campaign`, `nurturing_participant`, `event_type`, `payload`, `created_at`

### API Endpoints Available
- **SMS Marketing APIs:** `/api/sms_marketing/`
  - Campaigns, rules, subscribers, messages, events (CRUD operations)
- **Communication Processor Webhook:** `/api/communication_processor/webhooks/twilio/sms/marketing/`
  - Webhook endpoint (✅ already implemented)
  - Accepts POST requests from Twilio
  - Validates signature, persists message, pushes to SQS

### Shared Utilities Available
**Location:** `communication_processor.utils.twilio_helpers`

**Functions available:**
```python
# Phone normalization (returns tuple: (e164, formats))
normalized_e164, formats = normalize_phone_number("+1-203-583-5289")
# Returns: ("+12035835289", ["+12035835289", "203-583-5289", "2035835289", ...])

# Message body normalization
normalized = normalize_message_body("  JOIN   NOW  ")
# Returns: "JOIN NOW"

# SQS sending
send_to_sqs(queue_url, message_body, message_attributes)
```

**Note:** If processor is in separate repository, you may need to:
- Copy utility functions (recommended for independence), OR
- Install this repository as a package dependency, OR
- Re-implement normalization logic (documented in this spec)

### SQS Queue Configuration
**Settings required in webhook service:**
```python
SQS_QUEUE_URLS = {
    'sms_marketing': 'https://sqs.region.amazonaws.com/account/sms-marketing-queue',
    # or fallback to:
    'sms': 'https://sqs.region.amazonaws.com/account/sms-queue'
}

AWS_TWILIO_SQS_REGION = 'us-east-1'  # or your region
TWILIO_AUTH_TOKEN = 'your_twilio_auth_token'  # for signature validation
```

**Processor service needs:**
- SQS queue URL (same as above)
- AWS credentials/region for consuming from SQS
- Database connection to shared database (for model access)

### Message Processing Flow
1. **Webhook** (this repo) → Validates Twilio → Creates `SmsMessage` → Pushes to SQS → Returns 200
2. **SQS Consumer** (processor repo) → Polls queue → Filters by `EventType='sms.marketing.inbound'`
3. **Processor** (processor repo) → Loads `SmsMessage` by ID → Processes → Updates models
4. **Models** (this repo) → All updates persist to shared database

### Conversation Integration
When implementing `ROUTE_TO_AGENT` action:
- Link `SmsMessage.conversation` to `communications.Conversation`
- Link `SmsMessage.conversation_message` to `communications.ConversationMessage`
- See Section 11 (ROUTE_TO_AGENT action) for implementation details
- Helper function pattern provided in Section 11

### Database Access
**Processor needs access to:**
- `sms_marketing` app models (SmsMessage, SmsSubscriber, SmsKeywordCampaign, SmsKeywordRule, SmsCampaignEvent)
- `communications` app models (ContactEndpoint, Conversation, ConversationMessage, Participant)
- `crm` app models (Account, Campaign, Lead)
- `acs` app models (LeadNurturingCampaign, LeadNurturingParticipant)
- `marketing_tracking` app models (Keyword)

**Recommended approach:**
- Share database connection (same database, different Django project)
- Or use Django ORM with models imported from this repository
- Or use REST API calls (slower, not recommended for high volume)

### Testing Considerations
- **Webhook testing:** Can be tested independently (creates `SmsMessage`, pushes to SQS)
- **Processor testing:** Can be tested with:
  - Mock SQS messages (use actual message format from webhook)
  - Direct database `SmsMessage` records (bypass SQS)
  - Unit tests for routing/matching logic
- **Idempotency:** Test duplicate `provider_message_id` handling
- **State transitions:** Test all subscriber status changes
- **Integration:** Test end-to-end flow (webhook → SQS → processor → database updates)

### Error Handling
- **Webhook errors:** Returns 200 to prevent Twilio retries, logs errors
- **Processor errors:** Should log to `SmsCampaignEvent` with `event_type='error'`
- **SQS failures:** Webhook continues (message persisted in DB, can be reprocessed)
- **Database failures:** Processor should retry with exponential backoff
- **Dead letter queue:** Consider implementing for failed messages after max retries
