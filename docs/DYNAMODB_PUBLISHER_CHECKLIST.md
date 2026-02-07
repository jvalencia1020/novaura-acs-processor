# DynamoDB Publisher Checklist for Link Runtime

When your systems publish link records to the DynamoDB table used by the link runtime service, use the **correct attribute types**. The runtime expects native DynamoDB types when it reads items.

## Issues in CSV-style / string payloads

If you're posting data that originated from or looks like the sample below, fix the following.

### 1. **`active` must be Boolean (BOOL), not string**

- **Wrong:** `"active": "false"` or `"active": "true"` (string).
- **Right:** `"active": false` or `"active": true` (boolean).

**Why:** The runtime does `if not runtime_record.get("active", False)`. If `active` is the string `"false"`, that value is truthy in Python, so the link is treated as **active** instead of inactive.

---

### 2. **`append_query_params` must be Boolean (BOOL), not string**

- **Wrong:** `"append_query_params": "true"` (string).
- **Right:** `"append_query_params": true` (boolean).

**Why:** Same as above; string `"false"` would be truthy and params would still be appended when you might not want them.

---

### 3. **`dynamic_param_allowlist` must be a List (L), not a string**

- **Wrong:** A single string containing DynamoDB-style JSON, e.g.  
  `"[{\"S\":\"click_id\"},{\"S\":\"geo\"},{\"S\":\"click_ts\"},{\"S\":\"sms_msg_id\"}]"`
- **Right:** DynamoDB **List (L)** of strings:  
  `["click_id", "geo", "click_ts", "sms_msg_id"]`

**Why:** The runtime does `isinstance(allowlist, list)` and then `for param_name in allowlist`. If this is a string, the loop iterates over **characters**, so allowlisted request params (e.g. `sms_msg_id`) are not applied correctly. Only a real list works.

---

### 4. **`resolved_query_params` must be a Map (M), not a string**

- **Wrong:** `"resolved_query_params": "{}"` (string) or a stringified JSON object.
- **Right:** DynamoDB **Map (M)** — e.g. `{}` for empty, or `{"utm_source": "sms", "utm_campaign": "help"}` for UTM.

**Why:** The runtime does `isinstance(resolved, dict)`. If it's a string, no resolved params are merged onto the redirect URL. Use a real Map (empty or with key/value pairs).

---

## Correct types summary

| Attribute | DynamoDB type | Example (conceptual) |
|-----------|----------------|----------------------|
| PK | String (S) | `DOMAIN#textvictorylegal.com` |
| SK | String (S) | `SLUG#NEC` |
| active | Boolean (BOOL) | `true` or `false` |
| append_query_params | Boolean (BOOL) | `true` or `false` |
| destination_url | String (S) | `https://govictory23.com` |
| fallback_url | String (S) | `https://textvictorylegal.com/disabled` |
| dynamic_param_allowlist | List (L) of String | `["click_id", "geo", "click_ts", "sms_msg_id"]` |
| resolved_query_params | Map (M) | `{}` or `{"utm_source": "sms"}` |
| link_id, campaign_id, channel, etc. | String (S) | As needed |
| published_at_epoch, updated_at_epoch, runtime_version, max_clicks | Number (N) | Integer |

---

## Example: one record (pseudo-JSON for readability)

What the runtime expects when it reads the item (DynamoDB will use its own type names in the API):

```json
{
  "PK": "DOMAIN#textvictorylegal.com",
  "SK": "SLUG#NEC",
  "active": false,
  "append_query_params": true,
  "destination_url": "https://govictory23.com",
  "fallback_url": "https://textvictorylegal.com/disabled",
  "dynamic_param_allowlist": ["click_id", "geo", "click_ts", "sms_msg_id"],
  "resolved_query_params": {},
  "link_id": "c8f68543-36ae-4420-becd-b1b7af4fea5b",
  "campaign_id": "vln_nec_ctv",
  "channel": "sms",
  "max_clicks": 100000,
  "published_at_epoch": 1770413656,
  "runtime_version": 1,
  "updated_at_epoch": 1770351895
}
```

---

## Checklist for your publishing pipeline

- [x] `active` is written as **boolean** (not `"true"` / `"false"` string).
- [x] `append_query_params` is written as **boolean**.
- [x] `dynamic_param_allowlist` is written as a **List (L)** of strings, not a single string or stringified JSON.
- [x] `resolved_query_params` is written as a **Map (M)** (empty `{}` or key/value pairs), not a string.
- [x] PK format: `DOMAIN#<domain>` (e.g. `DOMAIN#textvictorylegal.com`).
- [x] SK format: `SLUG#<slug>` (e.g. `SLUG#NEC`); runtime normalizes slug to uppercase on request.

**ACS processor:** The publisher in `link_tracking.services.runtime_publisher` (used when sending SMS/email/journey messages with short links) implements this checklist. It normalizes `dynamic_param_allowlist` and `resolved_query_params` from model data so that even string or malformed values are emitted as the correct DynamoDB types.

After these fixes, the link runtime will read the records with the correct types and process redirects and query params as intended.
