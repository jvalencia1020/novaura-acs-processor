# Link Tracking and Nurturing Attribution – Backend Changes Summary

This document outlines the model, API, and admin changes implemented for (1) **participant attribution** (follow-up messages back to originating SMS) and (2) **link tracking tied to nurturing campaigns and components**. It is intended for the backend engineer who maintains the **message processor** and **link processor** so they can integrate or rely on these fields where needed.

---

## Part 1: Participant Attribution (Follow-up → Originating SMS)

### Goal

When a lead is enrolled in a nurturing campaign via SMS (e.g. START_JOURNEY), we now store **which SmsMessage** and **which SmsSubscriber** triggered that enrollment. This allows attribution of follow-up nurturing messages back to the originating SMS and subscriber.

### Model Changes (ACS)

**Model:** `acs.LeadNurturingParticipant`

| Field | Type | Description |
|-------|------|-------------|
| `originating_sms_message` | FK → `sms_marketing.SmsMessage` (nullable) | The inbound SMS that triggered enrollment (e.g. the message that contained "START"). |
| `originating_subscriber` | FK → `sms_marketing.SmsSubscriber` (nullable) | The SMS subscriber who triggered enrollment. |

- Both fields are **optional** (null=True, blank=True). They are set when enrollment happens via the SMS flow (e.g. START_JOURNEY); they are **not** set by the participant create/update API or by other enrollment paths.
- **Related names:** `SmsMessage.nurturing_participants_enrolled`, `SmsSubscriber.nurturing_participations`.
- **Indexes:** Added on `originating_sms_message` and `originating_subscriber` for lookups.

**Migration:** `acs.0046_add_participant_originating_sms_attribution`

### API (ACS)

- **LeadNurturingParticipant** list/detail serializers expose `originating_sms_message` and `originating_subscriber` (IDs). Both are **read-only** in the API.

### Admin (ACS)

- **LeadNurturingParticipantAdmin:** `originating_sms_message` and `originating_subscriber` are in `autocomplete_fields` and `readonly_fields`. `originating_subscriber` is in `list_display`.

### Integration Notes for Message / Link Processor

- **Not yet implemented:** The code that creates a `LeadNurturingParticipant` when handling START_JOURNEY (e.g. in `sms_marketing.services.actions.handle_start_journey`) does **not** yet set `originating_sms_message` or `originating_subscriber`. When you add that, set both on the participant at creation time so that:
  - `participant.originating_sms_message` = the inbound `SmsMessage` that triggered the action.
  - `participant.originating_subscriber` = the `SmsSubscriber` for that conversation.
- Once set, the message processor can use these for attribution (e.g. tagging outbound nurturing messages with the originating SMS or subscriber for analytics).

---

## Part 2: Link Campaigns Scoped to Nurturing Campaigns

### Goal

Link campaigns can be associated with **lead nurturing campaigns** via a many-to-many mapping (same pattern as LinkCampaign ↔ crm.Campaign). This allows scoping “which links are available for this nurturing campaign” and reporting by nurturing campaign.

### Model Changes (link_tracking)

**New model:** `link_tracking.LinkCampaignNurturingCampaignMapping`

| Field | Type | Description |
|-------|------|-------------|
| `link_campaign` | FK → `LinkCampaign` | The link campaign. |
| `nurturing_campaign` | FK → `acs.LeadNurturingCampaign` | The nurturing campaign. |
| `start_date` | DateField (null=True) | When the mapping became effective. |
| `end_date` | DateField (null=True) | When the mapping ended (null = current). |
| `is_active` | BooleanField (default=True) | Whether the mapping is in use. |
| `created_at`, `created_by` | — | Audit. |

- **Unique:** `(link_campaign, nurturing_campaign)`.
- **Related names:** `LinkCampaign.nurturing_campaign_mappings`, `LeadNurturingCampaign.link_campaign_mappings`.
- **Table:** `link_tracking_link_campaign_nurturing_mappings`

**Migration:** `link_tracking.0008_add_link_campaign_nurturing_campaign_mapping` (depends on `acs.0046`).

### API (link_tracking)

- **LinkCampaign detail (and list where detail is used):**
  - **Read:** `nurturing_campaign_ids` (list of nurturing campaign IDs), `nurturing_campaign_mappings` (list of mapping objects with nurturing_campaign, name, start_date, end_date, is_active, etc.).
- **LinkCampaign create:** Request body can include optional `nurturing_campaign_ids` (list of integers). Creating a link campaign with that list creates the corresponding `LinkCampaignNurturingCampaignMapping` rows.

### Admin (link_tracking)

- **LinkCampaign:** New inline **LinkCampaignNurturingCampaignMappingInline**; staff can add/edit nurturing campaign mappings from the LinkCampaign change page.

### Integration Notes for Message / Link Processor

- To “list links (or link campaigns) available for a given nurturing campaign,” filter by active mappings, e.g. link campaigns that have a `LinkCampaignNurturingCampaignMapping` with `nurturing_campaign_id=<id>` and `is_active=True`. The API does not yet expose a dedicated query param for this; it can be added later or derived from the detail payload (`nurturing_campaign_ids` / `nurturing_campaign_mappings`).

---

## Part 3: Short Link on Nurturing Components (Drip, Reminder, Journey)

### Goal

Optional **short link** (FK to `link_tracking.Link`) is attached to the specific **step** or **message** that sends content (drip step, reminder message, journey step). The messaging processor can read this when building the outbound message and insert the resolved short URL (e.g. redirect URL with SMS message ID and click ID appended by your existing logic).

### Model Changes (ACS)

| Model | Field | Related name on Link |
|-------|-------|----------------------|
| `acs.DripCampaignMessageStep` | `short_link` (FK → `link_tracking.Link`, nullable) | `link.drip_message_steps` |
| `acs.ReminderMessage` | `short_link` (FK → `link_tracking.Link`, nullable) | `link.reminder_messages` |
| `acs.JourneyStep` | `short_link` (FK → `link_tracking.Link`, nullable) | `link.journey_steps` |

- All are optional (null=True, blank=True). No validation requires a link.
- **Migration:** `acs.0047_add_short_link_to_nurturing_components` (depends on `acs.0046` and `link_tracking.0008`).

### API (ACS)

- **DripCampaignMessageStep:** Serializer fields `short_link` (ID), `short_link_url` (read-only, full short URL when set).
- **ReminderMessage:** Same: `short_link`, `short_link_url`.
- **JourneyStep:** Same: `short_link`, `short_link_url`.
- All are read/write (client can set which link is used for that step/message).

### Admin (ACS)

- **DripCampaignMessageStepAdmin:** `short_link` in `list_display` and `autocomplete_fields`.
- **ReminderMessageAdmin:** Same.
- **JourneyStepAdmin:** Same; `short_link` also in the Configuration fieldset.

### Integration Notes for Message / Link Processor

- When the **message processor** builds an outbound SMS (or email) for:
  - a **drip** step: read `DripCampaignMessageStep.short_link` (or the step’s channel config’s step) and, if set, resolve that `Link` to the redirect URL and insert it into the body (your processor already appends SMS message ID and click ID to the URL).
  - a **reminder** message: read `ReminderMessage.short_link` and use it the same way.
  - a **journey** step (email/SMS/voice/chat): read `JourneyStep.short_link` and use it the same way.
- The **link processor** (redirect service) does not need changes for these FKs; it already resolves the short URL and appends UTM/params. The only requirement is that the message processor passes the correct short URL (from the step’s or message’s `short_link`) into the message body and, if desired, appends any attribution params (e.g. `sms_message_id`, `click_id`) per your existing convention.

---

## Part 4: SMS Campaign on SmsSubscriber

### Goal

Each **SmsSubscriber** can be associated with an **SMS marketing campaign** (`SmsKeywordCampaign`). This enables campaign-scoped subscriber lists, reporting (e.g. subscriber counts per campaign), and API filtering without joining through endpoint.

### Model Changes (sms_marketing)

**Model:** `sms_marketing.SmsSubscriber`

| Field | Type | Description |
|-------|------|-------------|
| `sms_campaign` | FK → `SmsKeywordCampaign` (nullable) | The SMS marketing campaign this subscriber is associated with (e.g. the campaign they opted into). |

- **Optional** (null=True, blank=True). Unique is still `(endpoint, phone_number)`; the FK does not change uniqueness.
- **Related name:** `SmsKeywordCampaign.subscribers`.
- **Index:** Added on `sms_campaign` for list/filter by campaign.

**Migration:** `sms_marketing.0019_smssubscriber_campaign`

### API (sms_marketing)

- **SmsSubscriber** list/detail: `sms_campaign` (ID), `sms_campaign_name` (read-only). Filter by `?sms_campaign=<id>`.

### Admin (sms_marketing)

- **SmsSubscriberAdmin:** `sms_campaign` in `list_display`, `list_filter`, and `autocomplete_fields`.

### Integration Notes for Message Processor

- **When creating the SMS subscriber:** Please set **`sms_campaign`** (the SMS marketing campaign ID) whenever you create or resolve an `SmsSubscriber`. Use the campaign that is in context for the inbound message (e.g. the campaign whose keyword/rule matched, or the campaign that owns the endpoint). Example: when creating the subscriber in the webhook or in opt-in/action handlers, set `subscriber.sms_campaign = campaign` (or `subscriber.sms_campaign_id = campaign.id`) before saving. This keeps campaign-scoped queries and reporting accurate and avoids the need to infer campaign from endpoint only.
- Existing subscriber rows will have `sms_campaign=None` until the processor is updated or data is backfilled.

---

## Summary Table

| Area | What was added | Where |
|------|----------------|-------|
| Participant attribution | `originating_sms_message`, `originating_subscriber` on `LeadNurturingParticipant` | acs (model, migration 0046, serializer, admin) |
| Nurturing scope for link campaigns | `LinkCampaignNurturingCampaignMapping` | link_tracking (model, migration 0008, serializers, admin) |
| LinkCampaign API | `nurturing_campaign_ids`, `nurturing_campaign_mappings`; create accepts `nurturing_campaign_ids` | link_tracking API |
| Step/message links | `short_link` on DripCampaignMessageStep, ReminderMessage, JourneyStep | acs (models, migration 0047, serializers, admin) |
| SMS campaign on subscriber | `sms_campaign` on `SmsSubscriber`; filter by campaign, `sms_campaign_name` in API | sms_marketing (model, migration 0019, serializer, admin, viewset) |

---

## Migrations Order

When applying migrations, use:

1. `python manage.py migrate acs`  
   - Ensures `acs.0046` (participant attribution) is applied.
2. `python manage.py migrate link_tracking`  
   - Applies `link_tracking.0008` (nurturing mapping; depends on acs.0046).
3. `python manage.py migrate acs`  
   - Applies `acs.0047` (short_link on drip/reminder/journey; depends on link_tracking.0008).
4. `python manage.py migrate sms_marketing`  
   - Applies `sms_marketing.0019` (sms_campaign on SmsSubscriber).

Or run `python manage.py migrate` once; Django will apply them in dependency order.

---

## Out of Scope (Not Implemented)

- **handle_start_journey** in `sms_marketing.services.actions` does **not** yet set `originating_sms_message` or `originating_subscriber` on the created participant; that is left for a follow-up.
- **BulkCampaignMessage** and **SmsMessage** do **not** have a `short_link` FK in this change; the message processor does not need to persist which link was in which sent message unless you add that later.
- No new query params on the link (or link campaign) list API for “filter by nurturing campaign”; can be added later if needed.
