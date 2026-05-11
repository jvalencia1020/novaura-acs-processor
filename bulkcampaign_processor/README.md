# Bulk campaign processor

## Nurturing send caps (runtime)

Send caps are enforced in `BulkCampaignProcessor._send_message` via `bulkcampaign_processor.services.send_cap_service`.

### Settings (`acs_personalization.settings.base`)

| Setting | Default | Description |
|--------|---------|-------------|
| `SEND_CAPS_ENFORCEMENT_ENABLED` | `True` (env `True`/`False`) | Global kill switch; when `False`, all sends bypass cap claim. |
| `SEND_CAP_CLAIM_STALE_AFTER_SECONDS` | `300` | Reconciler marks stuck `metadata.send_cap_claim` rows as failed when older than this and `provider_message_id` is still null. |
| `SEND_CAP_REFUND_WHEN_NO_THREAD_MESSAGE` | `False` | When `True`, refund calendar bucket slots if the provider returns `(success=False, thread_message=None)`. Default prefers under-send vs over-send. |

### Rollout

1. Deploy with `SEND_CAPS_ENFORCEMENT_ENABLED=False` if you want a no-op first deploy; then enable in staging.
2. Validate deferrals (`deferral_reason` like `cap:hourly:42`) and bucket counts against CRM UI.
3. Enable in production; watch logs for `send_cap_claim_granted`, `send_cap_deferred`, `send_cap_refunded`, `send_cap_stale_reconciled`.
4. Schedule daily: `python manage.py cleanup_send_cap_buckets` (e.g. 03:00 UTC).

### Scope (v1)

Blast, drip, and reminder bulk messages only. Journey sends are not covered (separate path).
