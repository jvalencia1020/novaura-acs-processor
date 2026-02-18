# SMS / Nurturing Processor Engineer Instructions

This document gives the processor engineer a clear outline for implementing:

1. **Lead creation and subscription.lead** when SMS leads come through (inbound flow).
2. **originating_subscription_id** on LeadNurturingParticipant and how it gets set.
3. **Using originating subscription for the link** when `use_opt_in_rule_link` is true on blast (and drip/reminder) campaigns.

---

## 1. Context: What the backend does vs what the processor does

| Responsibility | Backend (this repo) | Processor (your repo) |
|----------------|---------------------|------------------------|
| Receive Twilio webhook | ✅ Creates `SmsMessage`, pushes to SQS | — |
| Consume SQS | — | ✅ |
| Get or create `SmsSubscriber` | — | ✅ By `endpoint_id` + `from_number` (E.164) |
| Keyword routing (campaign + rule) | — | ✅ |
| Call action handler | — | ✅ Calls `execute_action(campaign, rule, subscriber, message, config)` |
| Lead create/update (dedup, phone normalize) | ✅ Inside `handle_create_lead` | — |
| Set `subscriber.lead` and `subscription.lead` | ✅ Inside action handlers | — |
| Create/update `SmsSubscriberCampaignSubscription` | ✅ Inside `handle_opt_in` / `handle_start_journey` / `handle_create_lead` | — |
| Set `LeadNurturingParticipant.originating_subscription` | ✅ When creating participant (START_JOURNEY or assign_leads with lead_assignments) | — |
| Send blast/drip/reminder messages | — | ✅ When sending, resolve link from schedule/step and optionally from `participant.originating_subscription.opt_in_rule.short_link` |

---

## 2. Inbound SMS flow: order of operations

Implement the consumer so it follows this order:

1. **Receive SQS message** (payload from webhook: `sms_message_id`, `from_number`, `endpoint_id`, `body_normalized`, `account_id`, `sms_campaign_id`, `nurturing_campaign_id`, etc.).

2. **Load `SmsMessage`** (e.g. by `sms_message_id` from payload). Use the backend API or direct DB access depending on your architecture.

3. **Get or create `SmsSubscriber`**:
   - Lookup key: `endpoint_id` (from payload) + `from_number` (E.164 from payload).
   - `SmsSubscriber` has unique `(endpoint, phone_number)`.
   - On create, defaults: e.g. `status='unknown'`. Do **not** set `lead` here; lead is set later by action handlers when CREATE_LEAD or link-lead API runs.

4. **Optional: link message to subscriber**  
   Update `SmsMessage.subscriber_id = subscriber.id` if your backend supports it (so the message is tied to the subscriber).

5. **Extract keyword** from `body_normalized` (or equivalent) and **route to campaign + rule** (e.g. keyword "START" → campaign X, rule OPT_IN; "JOIN" → campaign Y, rule CREATE_LEAD or COMPOSITE with CREATE_LEAD + START_JOURNEY).

6. **Call the backend action executor** with the matched campaign, rule, subscriber, and message. The backend will:
   - For **OPT_IN**: get_or_create `SmsSubscriberCampaignSubscription`, set status/opt_in_rule/opt_in_message, and backfill `subscription.lead = subscriber.lead` if subscriber already has a lead.
   - For **CREATE_LEAD**: find or create lead (with phone normalization and dedup by campaign + phone/email), set `subscriber.lead` and `subscription.lead` for that campaign.
   - For **START_JOURNEY**: get_or_create `SmsSubscriberCampaignSubscription`, get_or_create `LeadNurturingParticipant` with **`originating_subscription`** set to that subscription (so the participant is tied to the opt-in rule for link resolution later).

You do **not** need to create leads or set `subscription.lead` in the processor; the backend does it inside these handlers.

---

## 3. Lead creation (CREATE_LEAD) – backend behavior

When the processor calls the backend with action type **CREATE_LEAD**:

- The backend (`handle_create_lead` in `sms_marketing/services/actions.py`):
  - Resolves the **CRM campaign** from the SMS campaign (primary or first active linked).
  - Looks up an **existing lead** by campaign + normalized phone (and email if in config). Phone is normalized to **XXX-XXX-XXXX** (e.g. `203-583-5289`) so E.164 from SMS matches DB.
  - If found: updates that lead with non-null values and links it to the subscriber.
  - If not found: creates a new lead (campaign required) and links it to the subscriber.
  - Sets **`subscriber.lead`** and updates **`SmsSubscriberCampaignSubscription`** for that (subscriber, campaign) with **`lead`**.

Processor requirements:

- Ensure the **SMS campaign** has a **linked CRM campaign** (primary or active) when using CREATE_LEAD; otherwise the backend returns an error.
- Pass **subscriber** and **message** (and campaign/rule/config) to the backend; no need to pass lead explicitly—the backend creates/updates and attaches it.

---

## 4. Originating subscription: what it is and who sets it

- **`LeadNurturingParticipant.originating_subscription`** is a FK to **`SmsSubscriberCampaignSubscription`** (the per–(subscriber, SMS campaign) opt-in record that has `opt_in_rule`, `opt_in_message`, and `lead`).
- It identifies **which** keyword/rule (and thus which short link) to use for this participant when the campaign uses **use_opt_in_rule_link** (drip, reminder, or blast).

**Who sets it:**

- **Backend** sets it in two cases:
  1. **START_JOURNEY** (inbound SMS): When the backend creates or updates the participant, it uses the **subscription** it just get_or_created for (subscriber + campaign) and sets **`participant.originating_subscription = subscription`**. The processor does not set this; the backend does when you call the START_JOURNEY action.
  2. **assign_leads with lead_assignments** (UI): When the frontend calls `POST .../assign_leads/` with **`lead_assignments`** (each item can have `lead_id` and optional `originating_subscription_id`), the backend creates participants and sets **`participant.originating_subscription_id`** from the payload. The processor does not need to set this for UI-assigned leads.

Processor requirements:

- Do **not** set `originating_subscription_id` in the processor for SMS-enrolled participants; the backend sets it when handling START_JOURNEY.
- When **sending** blast (or drip/reminder) messages, **read** `participant.originating_subscription` to resolve the short link when `use_opt_in_rule_link` is true (see below).

---

## 5. Using the originating subscription for the link (blast, drip, reminder)

When the processor sends a **blast**, **drip step**, or **reminder** message, it often needs to plug a **short link** into the message content.

- **Blast:** `BlastCampaignSchedule` has:
  - **`short_link`** (FK to `link_tracking.Link`): optional fixed link.
  - **`use_opt_in_rule_link`** (boolean): if **true**, the processor must use the link from the **opt-in rule** tied to the participant’s **originating subscription**, instead of the fixed `short_link`.

**Resolution logic (implement this in the processor):**

1. Load the schedule (blast) or step (drip/reminder) and check **`use_opt_in_rule_link`**.
2. If **false**: use the schedule/step **`short_link`** (if set) for the link in the message.
3. If **true**:
   - Load **`participant.originating_subscription`** (FK to `SmsSubscriberCampaignSubscription`).
   - If null: fall back to schedule/step **`short_link`** (or no link if not set).
   - If set: from that subscription, take **`opt_in_rule`** (FK to `SmsKeywordRule`). From the rule, take **`short_link`** (FK to `link_tracking.Link`). Use that link’s URL (e.g. `link.get_full_url()`) in the message.
   - If `originating_subscription.opt_in_rule` or `opt_in_rule.short_link` is null: fall back to schedule/step **`short_link`**.

Same pattern applies to **drip** and **reminder** components that have **`use_opt_in_rule_link`** (and optional **`short_link`**).

**Data path summary:**

- `LeadNurturingParticipant.originating_subscription` → `SmsSubscriberCampaignSubscription`
- `SmsSubscriberCampaignSubscription.opt_in_rule` → `SmsKeywordRule`
- `SmsKeywordRule.short_link` → `link_tracking.Link`  
Use that link’s full URL when **use_opt_in_rule_link** is true.

---

## 6. API reference (for assign_leads and eligible subscriptions)

These are used by the **frontend** (lead selection page), not by the processor for inbound SMS. The processor only needs to **read** participants and their **originating_subscription** when sending blast/drip/reminder.

- **Assign leads with per-lead subscription:**  
  `POST /api/acs/nurturing-campaigns/{id}/assign_leads/`  
  Body: `{ "lead_assignments": [ { "lead_id": 1, "originating_subscription_id": 101 }, ... ], "status": "active" }`.  
  Backend creates participants and sets **originating_subscription_id** from the payload.

- **Eligible subscriptions for UI:**  
  `GET /api/acs/nurturing-campaigns/{id}/eligible-originating-subscriptions/?lead_ids=1,2,3`  
  Returns which **SmsSubscriberCampaignSubscription** IDs can be used per lead (opted-in, linked to nurturing campaign, and belonging to that lead).  
  Frontend uses this to show dropdowns; processor does not call this.

See **docs/LEAD_SELECTION_ORIGINATING_SUBSCRIPTION_API.md** for full request/response shapes and validation rules.

---

## 7. Checklist for the processor engineer

- [ ] **Inbound SMS:** Consume SQS, load `SmsMessage`, get_or_create **SmsSubscriber** by `endpoint_id` + `from_number` (E.164).
- [ ] **Inbound SMS:** After keyword routing, call backend **execute_action(campaign, rule, subscriber, message, config)**. Do not create leads or set subscription.lead in the processor.
- [ ] **CREATE_LEAD:** Rely on backend to create/update lead (with dedup and phone normalization) and set subscriber.lead and subscription.lead.
- [ ] **START_JOURNEY:** Rely on backend to create participant and set **participant.originating_subscription** to the subscription for that (subscriber, campaign).
- [ ] **Blast (and drip/reminder):** When building the outbound message and a short link is needed:
  - [ ] Read **use_opt_in_rule_link** from the blast schedule (or drip step / reminder message).
  - [ ] If true: resolve link from **participant.originating_subscription → opt_in_rule → short_link**; if any is null, fall back to schedule/step **short_link**.
  - [ ] If false: use schedule/step **short_link** only.
- [ ] **assign_leads / eligible-originating-subscriptions:** No processor changes; used by frontend. Processor only reads **participant.originating_subscription** when sending messages.

---

## 8. Summary

- **Lead creation** and **subscription.lead** are handled entirely in the **backend** when the processor calls **execute_action** (OPT_IN, CREATE_LEAD, START_JOURNEY).
- **originating_subscription** on the participant is set by the **backend** (on START_JOURNEY or on assign_leads with lead_assignments). The processor only **uses** it when sending blast/drip/reminder and **use_opt_in_rule_link** is true.
- **Link resolution for blast (and drip/reminder):** if **use_opt_in_rule_link** is true, use **participant.originating_subscription.opt_in_rule.short_link**; otherwise use the schedule/step **short_link**.
