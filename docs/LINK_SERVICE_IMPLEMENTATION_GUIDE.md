Implementation Spec: Runtime Redirect Service & Terraform Infrastructure
Document Version: 1.3
Last Updated: February 5, 2026
Status: Foundation-Complete, Aligned with Django link_tracking Control Plane; SMS message ID tracking (forward-from-request) specified for runtime

Table of Contents

Overview
Architecture
Control Plane (Django link_tracking)
Runtime Record Schema (DynamoDB)
SMS message ID tracking – runtime implementation checklist
Runtime Service Implementation
Terraform Infrastructure
DynamoDB Schema
Deployment
Monitoring & Observability
Testing
Runbooks


Overview
Purpose
The Runtime Redirect Service is the hot path for all short link redirects. It must be:

Fast: p99 latency < 150ms
Reliable: 99.95%+ uptime
Secure: Bot detection, signature validation, rate limiting
Scalable: Handle traffic spikes without degradation
Observable: Rich metrics and logging

Non-Goals (Runtime Service Only)

The runtime service itself is NOT a control plane (no CRUD operations), NOT connected to the Django DB (reads only from DynamoDB), and NOT responsible for analytics aggregation (just emits events). The control plane—CRUD, publishing to DynamoDB, and outbox—lives in the existing Django app `link_tracking` (see Control Plane section below).

Key Principles

Stateless: No local state, horizontally scalable
Fast Path: Minimize latency at all costs
Fail Safe: Degrade gracefully, never return 500s
Event-Driven: Async event emission, non-blocking


Architecture
High-Level Flow
┌─────────────────────────────────────────────────────────────┐
│                         User Request                         │
│                  GET go.novaura.io/a9K2                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      CloudFront (CDN)                        │
│  - SSL Termination                                           │
│  - DDoS Protection (AWS Shield)                              │
│  - WAF Rules (Rate Limiting, Bot Detection)                  │
│  - Edge Caching (30-60s TTL)                                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Application Load Balancer (ALB)                 │
│  - Health Checks                                             │
│  - Target Group Routing                                      │
│  - Sticky Sessions (disabled)                                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    ECS Fargate Service                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Runtime Container (FastAPI)                          │  │
│  │  1. Parse domain + slug from request                  │  │
│  │  2. Fetch from DynamoDB (PK/SK lookup)                │  │
│  │  3. Apply policy checks (active, expiry, etc.)        │  │
│  │  4. Resolve destination URL (routing engine)          │  │
│  │  5. Emit click event to Firehose (async)              │  │
│  │  6. Return 302 redirect                               │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                                   │
         │ DynamoDB Read                     │ Emit Event
         ▼                                   ▼
┌──────────────────┐              ┌──────────────────────┐
│   DynamoDB       │              │  Kinesis Firehose    │
│  (Runtime Store) │              │  (Event Stream)      │
│                  │              │         ↓            │
│  PK: DOMAIN#...  │              │    S3 Bucket         │
│  SK: SLUG#...    │              │         ↓            │
└──────────────────┘              │    Snowflake         │
                                  └──────────────────────┘
Technology Stack

Language: Python 3.11
Framework: FastAPI
ASGI Server: Uvicorn with Gunicorn
AWS Services:

ECS Fargate (compute)
DynamoDB (runtime data store)
CloudFront (CDN)
ALB (load balancer)
Kinesis Firehose (event streaming)
CloudWatch (monitoring)
Secrets Manager (secrets)


Infrastructure: Terraform


Control Plane (Django link_tracking)
The control plane is implemented in the Django app `link_tracking`. It owns link/domain/campaign CRUD, UTM resolution, and publishing to the DynamoDB runtime store. The runtime service only reads from DynamoDB.

Models (source of truth for runtime data)

- **Domain** – Short-link domain (e.g. go.novaura.io). Fields: domain_name, purpose, active, status, health_score, warming fields, optional FK to marketing_tracking.URLDomain. Links on a domain only redirect when both the link and the domain are active.
- **LinkCampaign** – Campaign scoped to an account. Fields: account (FK to crm.Account), campaign_id (optional, nullable; when set, unique per account), name, description, utm_template (JSON with template variables), active, start_date, end_date. CRM campaigns are associated via many-to-many: LinkCampaignCrmCampaignMapping (see below). Create API allows omitting campaign_id.
- **LinkCampaignCrmCampaignMapping** – Maps one LinkCampaign to one or more crm.Campaign(s) for attribution. Fields: link_campaign, crm_campaign, start_date, end_date, is_active. Same link campaign can be used in multiple CRM campaigns over time. A **dedicated nested API** supports full CRUD: `GET/POST /api/link_tracking/campaigns/{link_campaign_uuid}/crm-mappings/` and `GET/PATCH/DELETE .../crm-mappings/{mapping_id}/` so clients can assign and manage mappings (including dates and is_active) without going through campaign create/update.
- **GlobalUTMPolicy** – Singleton with default_utm_params (organization-wide UTM defaults).
- **Link** – Short link. Key fields: domain, campaign (LinkCampaign), slug_canonical (unique per domain), campaign_identifier (denormalized from campaign.campaign_id; may be empty if campaign.campaign_id is null), keyword (optional CharField for UTM/attribution, e.g. HELP, LAW), channel (SMS/Email/QR/etc.), destination_url, fallback_url, append_query_params, utm_overrides, **dynamic_param_allowlist** (e.g. ["click_id","geo","click_ts","**sms_msg_id**"]; control plane validates allowed params: click_id, ab_variant, geo, click_ts, sms_msg_id), active, expires_at, max_clicks, signature_required, signature_secret_ref (AWS Secrets Manager ref), routing_rules (JSON), runtime_version. Slug can be system-generated or vanity (slug_original stored for vanity). **SMS integration:** sms_marketing.SmsKeywordRule has an optional FK `short_link` to Link. The SMS processor (novaura-acs-processor) uses create-before-send: it creates SmsMessage (pending), builds the short URL as `get_full_url() + ?sms_msg_id=<SmsMessage.id>`, injects it into the ACS template variable **{{link.short_link}}** (category "link", variable "short_link"; seeded via `python manage.py seed_link_template_variable`), then sends and updates the message. The **runtime service must forward** any param in dynamic_param_allowlist that appears on the **incoming request** (e.g. sms_msg_id) onto the final redirect URL and include it in the click event so that journey/analytics can join clicks to the original SMS message.
- **PublishOutbox** – Outbox pattern for reliable publish. idempotency_key = "{link_id}:{updated_at_timestamp}", status (pending/processing/complete/failed), retry_count, error_message, completed_at.
- **LinkVersion** – Audit trail for link changes (destination_url, utm_overrides, routing_rules, active, version, changed_by, change_reason).

Control plane API (link_tracking)

- **Base path:** `/api/link_tracking/`. Resources: domains, campaigns, links, utm-policy, publish-outbox, privacy-requests.
- **Link campaigns:** Create with optional `campaign_id` (nullable); list/detail include `crm_campaign_ids` and `crm_campaign_mappings`. Assignments are managed via the nested **crm-mappings** endpoint (see below).
- **Link campaign ↔ CRM campaign mappings (dedicated endpoint):** `GET/POST /api/link_tracking/campaigns/{link_campaign_uuid}/crm-mappings/` and `GET/PATCH/DELETE .../crm-mappings/{mapping_id}/`. Create body: `crm_campaign` (required), optional `start_date`, `end_date`, `is_active`. Update supports dates and `is_active`. This allows the frontend to assign link campaigns to CRM campaigns and manage date ranges and active state without embedding mapping data in campaign create/update.
- **Links:** Create/update support optional `keyword` (string). Bulk create uses `keywords` (list of strings), one link per keyword. List/detail expose link fields; preview endpoint returns resolved UTM and final URL.

For frontend-oriented API usage (link create/edit, bulk create, crm-mappings, SMS rule short_link), see **LINK_TRACKING_FRONTEND_FEATURES.md**.

Publishing to DynamoDB

- **LinkPublisher** (link_tracking.services.publisher):
  - `build_runtime_record(link)` – Builds the DynamoDB item: resolves UTM via UTMResolver (global + campaign utm_template + link utm_overrides, with template variables slug, campaign_id, keyword, channel, short_code, domain, slug_type, created_date), then builds record with PK/SK, link_id, destination_url, fallback_url (= link.fallback_url or `https://{domain.domain_name}/disabled`), active = link.active and link.domain.active, expires_at_epoch, max_clicks, append_query_params, resolved_query_params, dynamic_param_allowlist, signature_required, signature_key_id (from link.signature_secret_ref when signature_required), routing_rules, campaign_id, keyword, channel, runtime_version, published_at_epoch, updated_at_epoch. Keys with value None are omitted.
  - `create_publish_outbox(link)` – Creates PublishOutbox with idempotency_key, status PENDING.
  - `publish_link(link, outbox=None)` – Puts item with ConditionExpression so that write only succeeds if item does not exist or has older runtime_version (optimistic concurrency).
  - `unpublish_link(link)` – Sets active = false for the item.
  - `bulk_republish_campaign(campaign_id)` – Republishes all active links for that campaign_identifier (creates outbox + publish_link per link).
- **UTMResolver** (link_tracking.services.utm_resolver) – Resolves GlobalUTMPolicy + LinkCampaign.utm_template + Link.utm_overrides with Template substitution; result is stored as resolved_query_params in the runtime record (resolved at publish time, not at redirect time).

Settings (Django)

- `LINK_RUNTIME_TABLE_NAME` – DynamoDB table name (default: `link-runtime-prod`).
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` – Used by LinkPublisher and management commands.

Management commands

- `setup_dynamodb` – Creates DynamoDB table with PK (S), SK (S), campaign_id (S), GSI `campaign-index` (campaign_id hash, SK range), BillingMode PAY_PER_REQUEST. Table name from settings.LINK_RUNTIME_TABLE_NAME.
- `republish_campaign` – Accepts campaign_id; enqueues republish_campaign_task (Celery) to bulk republish all active links for that campaign_identifier. Used for campaigns that have campaign_id set.

Celery tasks (link_tracking.tasks.publisher_tasks)

- `publish_link_task(link_id)` – Creates outbox, calls publish_link, retries on failure.
- `republish_campaign_task(campaign_id)` – Calls LinkPublisher.bulk_republish_campaign(campaign_id).
- `cleanup_old_outbox_entries` – Deletes completed outbox older than 7 days, failed older than 30 days.
- `retry_pending_outbox` – Re-queues publish_link_task for outbox entries stuck in PENDING for > 5 minutes.


Runtime Record Schema (DynamoDB)
Each item in the runtime table is produced by LinkPublisher.build_runtime_record(link). The runtime service reads these items by PK/SK (domain/slug). Attributes present in the record (nulls omitted by publisher):

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | S | `DOMAIN#{domain_name}` (e.g. DOMAIN#go.novaura.io) |
| SK | S | `SLUG#{slug_canonical}` (e.g. SLUG#ABC123) |
| link_id | S | UUID of the Link |
| destination_url | S | Final destination URL (may include query params) |
| fallback_url | S | Redirect when disabled/expired; default `https://{domain}/disabled` if blank |
| active | BOOL | True only when both link.active and link.domain.active |
| expires_at_epoch | N | Unix timestamp; optional |
| max_clicks | N | Optional circuit breaker |
| append_query_params | BOOL | If false, destination_url used as-is (passthrough) |
| resolved_query_params | M | Resolved UTM/static params (from GlobalUTMPolicy + campaign utm_template + link utm_overrides) |
| dynamic_param_allowlist | L | e.g. ["click_id","geo","click_ts","sms_msg_id"]; default ["click_id"]. May include **sms_msg_id** for "forward from request" behavior: when present on the incoming request, its value is forwarded onto the final redirect URL and included in the click event. |
| signature_required | BOOL | If true, runtime validates HMAC query params |
| signature_key_id | S | AWS Secrets Manager secret ref (when signature_required) |
| routing_rules | M | A/B, geo, time-based rules; optional |
| campaign_id | S | Campaign identifier (denormalized from link.campaign.campaign_id; may be omitted if null) |
| keyword | S | Optional keyword string (link.keyword) for UTM/attribution; omitted if blank |
| channel | S | sms, email, qr, etc. |
| runtime_version | N | Incremented on each publish; used for conditional put |
| published_at_epoch | N | Unix timestamp when record was published |
| updated_at_epoch | N | Unix timestamp of link.updated_at |

The table uses GSI `campaign-index` (campaign_id, SK) for campaign-scoped operations (e.g. bulk republish by campaign). Runtime redirect path uses only GetItem by PK/SK.

**SMS message ID tracking – runtime implementation checklist**

When the control plane includes **sms_msg_id** in a link’s `dynamic_param_allowlist`, the SMS flow sends URLs like `https://go.example.com/ABC?sms_msg_id=<uuid>`. The runtime service must:

1. **Pass incoming query params into the redirect flow** – When handling `GET /{slug}?...`, collect the request’s query params (e.g. `dict(request.query_params)` or equivalent) and pass them to both the URL builder and the event emitter.
2. **Forward allowlisted request params onto the redirect URL** – In `URLBuilder.build_redirect_url`, accept an optional `request_query_params` (or similar). For each param name in `runtime_record['dynamic_param_allowlist']` that is a **forward-from-request** param (e.g. **sms_msg_id**), if that param is present in `request_query_params`, add it to `final_params` so it appears on the 302 redirect URL. This allows the destination page and analytics to attribute the click to the specific SMS message.
3. **Include sms_msg_id (and other forwarded params) in the click event** – When emitting the click event to Firehose, include a field **sms_msg_id** (string, optional) when the param is present on the request. Downstream (e.g. Snowflake, journey pipeline) can then join clicks to `SmsMessage` by ID for full user/responder journey tracking.
4. **Optional: Glue/Firehose schema** – If the click event schema is fixed (e.g. Glue table), add a column **sms_msg_id** (string, optional) so analytics can query on it.

No DynamoDB schema change is required; the existing `dynamic_param_allowlist` list in each runtime record is sufficient. The control plane already publishes links with `sms_msg_id` in the allowlist when used for SMS.


Runtime Service Implementation
Project Structure
link-runtime-service/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app
│   ├── config.py                  # Configuration
│   ├── models/
│   │   ├── __init__.py
│   │   ├── runtime_record.py      # DynamoDB record model
│   │   └── click_event.py         # Click event model
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dynamodb_service.py    # DynamoDB client
│   │   ├── url_builder.py         # URL construction
│   │   ├── routing_engine.py      # Routing logic
│   │   ├── signature_validator.py # HMAC validation
│   │   └── event_emitter.py       # Firehose events
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── logging.py             # Request logging
│   │   ├── metrics.py             # CloudWatch metrics
│   │   └── error_handler.py       # Error handling
│   └── utils/
│       ├── __init__.py
│       ├── cache.py               # In-memory caching
│       └── bot_detector.py        # Bot detection
├── tests/
│   ├── __init__.py
│   ├── test_redirect.py
│   ├── test_url_builder.py
│   └── test_routing.py
├── terraform/                      # Infrastructure as Code
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── dynamodb.tf
│   ├── ecs.tf
│   ├── cloudfront.tf
│   ├── firehose.tf
│   └── monitoring.tf
├── Dockerfile
├── requirements.txt
├── .env.example
├── docker-compose.yml             # Local development
└── README.md
Core Application
app/main.py:
pythonfrom fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging
import time
from typing import Optional

from app.config import settings
from app.services.dynamodb_service import DynamoDBService
from app.services.url_builder import URLBuilder
from app.services.routing_engine import RoutingEngine
from app.services.event_emitter import EventEmitter
from app.services.signature_validator import SignatureValidator
from app.middleware.logging import LoggingMiddleware
from app.middleware.metrics import MetricsMiddleware
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.utils.bot_detector import BotDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Link Runtime Service",
    description="High-performance redirect service for short links",
    version="1.0.0",
    docs_url=None,  # Disable docs in production
    redoc_url=None,
)

# Add middleware
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)

# CORS (if needed for development)
if settings.ENVIRONMENT == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Initialize services
dynamodb_service = DynamoDBService()
url_builder = URLBuilder()
routing_engine = RoutingEngine()
event_emitter = EventEmitter()
signature_validator = SignatureValidator()
bot_detector = BotDetector()


@app.get("/health")
async def health_check():
    """Health check endpoint for ALB"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": time.time()
    }


@app.get("/{slug}")
async def redirect(slug: str, request: Request):
    """
    Main redirect endpoint
    
    Flow:
    1. Parse domain from Host header
    2. Fetch runtime record from DynamoDB
    3. Apply policy checks
    4. Resolve destination URL
    5. Emit click event (async)
    6. Return 302 redirect
    """
    start_time = time.time()
    
    # Extract domain from Host header
    domain = request.headers.get("host", "").split(":")[0]
    
    # Normalize slug (uppercase)
    slug_canonical = slug.upper()
    
    logger.info(f"Redirect request: {domain}/{slug_canonical}")
    
    try:
        # 1. Fetch runtime record from DynamoDB
        runtime_record = await dynamodb_service.get_link(domain, slug_canonical)
        
        if not runtime_record:
            logger.warning(f"Link not found: {domain}/{slug_canonical}")
            # Fallback: control plane may publish fallback_url per link; unknown slug uses default
            return RedirectResponse(
                url=settings.DEFAULT_FALLBACK_URL,
                status_code=302
            )
        
        # 2. Policy checks
        policy_check = _check_policy(runtime_record, request)
        
        if not policy_check["allowed"]:
            logger.info(f"Policy check failed: {policy_check['reason']}")
            # Control plane sends fallback_url per link (or https://{domain}/disabled); else use default
            fallback_url = runtime_record.get("fallback_url", settings.DEFAULT_FALLBACK_URL)
            return RedirectResponse(url=fallback_url, status_code=302)
        
        # 3. Signature validation (if required)
        if runtime_record.get("signature_required", False):
            signature = request.query_params.get("sig")
            timestamp = request.query_params.get("ts")
            
            is_valid = signature_validator.validate(
                runtime_record,
                slug_canonical,
                signature,
                timestamp
            )
            
            if not is_valid:
                logger.warning(f"Invalid signature for {domain}/{slug_canonical}")
                return RedirectResponse(
                    url=runtime_record.get("fallback_url", settings.DEFAULT_FALLBACK_URL),
                    status_code=302
                )
        
        # 4. Generate click session ID
        import uuid
        click_session_id = str(uuid.uuid4())
        
        # 5. Build context for routing
        context = {
            "geo_country": request.headers.get("CloudFront-Viewer-Country", ""),
            "user_agent": request.headers.get("User-Agent", ""),
            "referer": request.headers.get("Referer", ""),
            "ip_address": request.headers.get("X-Forwarded-For", "").split(",")[0],
        }
        # Incoming query params (e.g. sms_msg_id) – forward allowlisted ones onto redirect URL and into click event
        request_query_params = dict(request.query_params) if request.query_params else {}

        # 6. Resolve destination URL (routing engine)
        destination_url = routing_engine.resolve_destination(
            runtime_record,
            click_session_id,
            context
        )

        # 7. Build final URL with query params (pass request_query_params so sms_msg_id etc. are forwarded)
        final_url = url_builder.build_redirect_url(
            runtime_record,
            click_session_id,
            context,
            request_query_params=request_query_params,
        )

        # 8. Bot detection
        is_bot = bot_detector.is_bot(context["user_agent"], context["ip_address"])

        # 9. Emit click event (async, non-blocking); include request_query_params so sms_msg_id is in payload
        latency_ms = int((time.time() - start_time) * 1000)

        event_emitter.emit_click_event(
            runtime_record=runtime_record,
            click_session_id=click_session_id,
            context=context,
            final_url=final_url,
            is_bot=is_bot,
            latency_ms=latency_ms,
            request_query_params=request_query_params,
        )
        
        # 10. Return redirect
        logger.info(f"Redirecting {domain}/{slug_canonical} -> {final_url} ({latency_ms}ms)")
        
        return RedirectResponse(url=final_url, status_code=302)
    
    except Exception as e:
        logger.error(f"Error processing redirect: {e}", exc_info=True)
        
        # Fail safe - redirect to default fallback
        return RedirectResponse(
            url=settings.DEFAULT_FALLBACK_URL,
            status_code=302
        )


def _check_policy(runtime_record: dict, request: Request) -> dict:
    """
    Check if link is allowed to redirect
    
    Returns:
        dict with "allowed" (bool) and "reason" (str)
    """
    # Check active flag
    if not runtime_record.get("active", False):
        return {"allowed": False, "reason": "link_inactive"}
    
    # Check expiry
    expires_at_epoch = runtime_record.get("expires_at_epoch")
    if expires_at_epoch and time.time() > expires_at_epoch:
        return {"allowed": False, "reason": "link_expired"}
    
    # Check max clicks (if implemented)
    max_clicks = runtime_record.get("max_clicks")
    if max_clicks:
        # This would require a counter in DynamoDB or Redis
        # For now, skip this check in runtime (handle in analytics)
        pass
    
    return {"allowed": True, "reason": "ok"}


@app.get("/robots.txt")
async def robots():
    """Robots.txt to prevent indexing"""
    return Response(
        content="User-agent: *\nDisallow: /",
        media_type="text/plain"
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )

Configuration
app/config.py:
pythonfrom pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Environment
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    
    # AWS
    AWS_REGION: str = "us-east-1"
    # Must match Django settings.LINK_RUNTIME_TABLE_NAME (control plane publishes to this table)
    DYNAMODB_TABLE_NAME: str = "link-runtime-prod"
    
    # Firehose
    FIREHOSE_STREAM_NAME: str = "link-click-events"
    
    # Secrets Manager
    SECRETS_MANAGER_SECRET_NAME: Optional[str] = None
    
    # Fallback URL
    DEFAULT_FALLBACK_URL: str = "https://novaura.io/link-disabled"
    
    # Caching
    CACHE_TTL_SECONDS: int = 300  # 5 minutes
    CACHE_MAX_SIZE: int = 10000   # 10k entries
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_IP: int = 100  # per minute
    
    # Metrics
    CLOUDWATCH_NAMESPACE: str = "LinkRuntime"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

DynamoDB Service
app/services/dynamodb_service.py:
pythonimport boto3
from typing import Optional, Dict
import logging
from functools import lru_cache
import hashlib
import time

from app.config import settings
from app.utils.cache import TTLCache

logger = logging.getLogger(__name__)


class DynamoDBService:
    """Service for fetching runtime records from DynamoDB"""
    
    def __init__(self):
        self.dynamodb = boto3.resource(
            'dynamodb',
            region_name=settings.AWS_REGION
        )
        self.table = self.dynamodb.Table(settings.DYNAMODB_TABLE_NAME)
        
        # In-memory cache for runtime records
        self.cache = TTLCache(
            max_size=settings.CACHE_MAX_SIZE,
            ttl=settings.CACHE_TTL_SECONDS
        )
        
        logger.info(f"Initialized DynamoDB service: {settings.DYNAMODB_TABLE_NAME}")
    
    async def get_link(self, domain: str, slug: str) -> Optional[Dict]:
        """
        Fetch runtime record from DynamoDB
        
        Uses in-memory cache to reduce DynamoDB reads
        
        Args:
            domain: Domain name (e.g., go.novaura.io)
            slug: Canonical slug (e.g., ABC123)
        
        Returns:
            Runtime record dict or None if not found
        """
        # Generate cache key
        cache_key = f"{domain}:{slug}"
        
        # Check cache first
        cached_record = self.cache.get(cache_key)
        if cached_record is not None:
            logger.debug(f"Cache hit: {cache_key}")
            return cached_record
        
        # Fetch from DynamoDB
        try:
            pk = f"DOMAIN#{domain}"
            sk = f"SLUG#{slug}"
            
            logger.debug(f"DynamoDB query: PK={pk}, SK={sk}")
            
            response = self.table.get_item(
                Key={
                    'PK': pk,
                    'SK': sk
                }
            )
            
            if 'Item' not in response:
                logger.info(f"Link not found in DynamoDB: {domain}/{slug}")
                # Cache negative result briefly (10 seconds)
                self.cache.set(cache_key, None, ttl=10)
                return None
            
            item = response['Item']
            
            # Cache the result
            self.cache.set(cache_key, item)
            
            logger.info(f"Fetched from DynamoDB: {domain}/{slug}")
            
            return item
        
        except Exception as e:
            logger.error(f"DynamoDB error: {e}", exc_info=True)
            # On error, return None (fail safe)
            return None
    
    def invalidate_cache(self, domain: str, slug: str):
        """Invalidate cache for a specific link"""
        cache_key = f"{domain}:{slug}"
        self.cache.delete(cache_key)
        logger.info(f"Cache invalidated: {cache_key}")

URL Builder
app/services/url_builder.py:
pythonfrom urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class URLBuilder:
    """Build final redirect URL with query params"""
    
    def build_redirect_url(
        self,
        runtime_record: Dict,
        click_session_id: str,
        context: Dict,
        request_query_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Build final redirect URL with merged query params.

        Precedence:
        1. Existing params in destination_url (base)
        2. Resolved static params (UTM from runtime record)
        3. Dynamic params (click_id, geo, click_ts) and forward-from-request params (e.g. sms_msg_id) – highest precedence

        Forward-from-request: for each param name in dynamic_param_allowlist that is present in
        request_query_params (e.g. sms_msg_id), add it to final_params so it appears on the redirect URL.

        Args:
            runtime_record: Runtime record from DynamoDB
            click_session_id: Generated click session ID
            context: Request context (geo, user_agent, etc.)
            request_query_params: Incoming request query params (e.g. from request.query_params); used to forward sms_msg_id etc.

        Returns:
            Final redirect URL with all params
        """
        destination_url = runtime_record.get('destination_url', '')
        request_query_params = request_query_params or {}

        # Passthrough mode - return as-is
        if not runtime_record.get('append_query_params', True):
            return destination_url

        # Parse destination URL
        parsed = urlparse(destination_url)

        # Extract existing query params
        existing_params = {}
        if parsed.query:
            existing_params = {
                k: v[0] if isinstance(v, list) and len(v) == 1 else v
                for k, v in parse_qs(parsed.query).items()
            }

        # Start with existing params
        final_params = existing_params.copy()

        # Merge resolved static params (UTM)
        resolved_params = runtime_record.get('resolved_query_params', {})
        final_params.update(resolved_params)

        # Add dynamic params based on allowlist
        dynamic_allowlist = runtime_record.get('dynamic_param_allowlist', ['click_id'])

        if 'click_id' in dynamic_allowlist:
            final_params['click_id'] = click_session_id

        if 'geo' in dynamic_allowlist and context.get('geo_country'):
            final_params['geo'] = context['geo_country']

        if 'click_ts' in dynamic_allowlist:
            import time
            final_params['click_ts'] = str(int(time.time()))

        # Forward allowlisted params from incoming request (e.g. sms_msg_id for SMS journey tracking)
        for param_name in dynamic_allowlist:
            if param_name in request_query_params and param_name not in ('click_id', 'geo', 'click_ts'):
                final_params[param_name] = request_query_params[param_name]

        # Rebuild URL with merged params
        new_query = urlencode(final_params, doseq=True)
        final_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        
        logger.debug(f"Built URL: {destination_url} -> {final_url}")
        
        return final_url

Routing Engine
app/services/routing_engine.py:
pythonfrom typing import Dict, Optional
import logging
import hashlib

logger = logging.getLogger(__name__)


class RoutingEngine:
    """Resolve destination URL based on routing rules"""
    
    def resolve_destination(
        self,
        runtime_record: Dict,
        click_session_id: str,
        context: Dict
    ) -> str:
        """
        Resolve destination URL based on routing rules
        
        Supports:
        - A/B testing
        - Geo-based routing
        - Time-based routing
        - Default (passthrough)
        
        Args:
            runtime_record: Runtime record from DynamoDB
            click_session_id: Click session ID
            context: Request context
        
        Returns:
            Resolved destination URL
        """
        routing_rules = runtime_record.get('routing_rules', {})
        
        if not routing_rules:
            # No routing - return default destination
            return runtime_record.get('destination_url', '')
        
        routing_type = routing_rules.get('type')
        
        if routing_type == 'ab_test':
            return self._resolve_ab_test(routing_rules, click_session_id)
        
        elif routing_type == 'geo':
            return self._resolve_geo(routing_rules, context)
        
        elif routing_type == 'time':
            return self._resolve_time(routing_rules)
        
        else:
            logger.warning(f"Unknown routing type: {routing_type}")
            return runtime_record.get('destination_url', '')
    
    def _resolve_ab_test(self, routing_rules: Dict, click_session_id: str) -> str:
        """
        A/B test routing using deterministic hash
        
        Example routing_rules:
        {
            "type": "ab_test",
            "variant_a": "https://page-a.com",
            "variant_b": "https://page-b.com",
            "split": 0.5
        }
        """
        variant_a = routing_rules.get('variant_a', '')
        variant_b = routing_rules.get('variant_b', '')
        split = routing_rules.get('split', 0.5)
        
        # Deterministic hash of session ID
        hash_value = int(hashlib.md5(click_session_id.encode()).hexdigest(), 16)
        
        # Distribute based on split
        if (hash_value % 100) < (split * 100):
            logger.debug(f"A/B test: variant_a")
            return variant_a
        else:
            logger.debug(f"A/B test: variant_b")
            return variant_b
    
    def _resolve_geo(self, routing_rules: Dict, context: Dict) -> str:
        """
        Geo-based routing
        
        Example routing_rules:
        {
            "type": "geo",
            "us": "https://us.example.com",
            "eu": "https://eu.example.com",
            "default": "https://example.com"
        }
        """
        geo_country = context.get('geo_country', '').upper()
        
        # Map country to region (simplified)
        geo_region = self._map_country_to_region(geo_country)
        
        # Lookup destination by region
        destination = routing_rules.get(
            geo_region.lower(),
            routing_rules.get('default', '')
        )
        
        logger.debug(f"Geo routing: {geo_country} -> {geo_region} -> {destination}")
        
        return destination
    
    def _map_country_to_region(self, country_code: str) -> str:
        """Map country code to region"""
        eu_countries = ['GB', 'FR', 'DE', 'IT', 'ES', 'NL', 'BE', 'SE', 'PL']
        
        if country_code == 'US':
            return 'US'
        elif country_code in eu_countries:
            return 'EU'
        else:
            return 'OTHER'
    
    def _resolve_time(self, routing_rules: Dict) -> str:
        """
        Time-based routing
        
        Example routing_rules:
        {
            "type": "time",
            "business_hours": "https://sales.example.com",
            "after_hours": "https://form.example.com",
            "timezone": "America/New_York"
        }
        """
        from datetime import datetime
        import pytz
        
        timezone_str = routing_rules.get('timezone', 'UTC')
        tz = pytz.timezone(timezone_str)
        
        current_time = datetime.now(tz)
        hour = current_time.hour
        
        # Business hours: 9am - 5pm
        if 9 <= hour < 17:
            destination = routing_rules.get('business_hours', '')
        else:
            destination = routing_rules.get('after_hours', '')
        
        logger.debug(f"Time routing: hour={hour} -> {destination}")
        
        return destination

Event Emitter
app/services/event_emitter.py:
pythonimport boto3
import json
import logging
import time
import hashlib
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor
import uuid

from app.config import settings

logger = logging.getLogger(__name__)


class EventEmitter:
    """Emit click events to Kinesis Firehose (async)"""
    
    def __init__(self):
        self.firehose = boto3.client(
            'firehose',
            region_name=settings.AWS_REGION
        )
        
        # Thread pool for async event emission
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        logger.info(f"Initialized EventEmitter: {settings.FIREHOSE_STREAM_NAME}")
    
    def emit_click_event(
        self,
        runtime_record: Dict,
        click_session_id: str,
        context: Dict,
        final_url: str,
        is_bot: bool,
        latency_ms: int,
        request_query_params: Optional[Dict[str, str]] = None,
    ):
        """
        Emit click event to Firehose (non-blocking).

        request_query_params: Incoming request query params; used to include sms_msg_id etc. in event for journey tracking.
        """
        self.executor.submit(
            self._emit_event_sync,
            runtime_record,
            click_session_id,
            context,
            final_url,
            is_bot,
            latency_ms,
            request_query_params or {},
        )

    def _emit_event_sync(
        self,
        runtime_record: Dict,
        click_session_id: str,
        context: Dict,
        final_url: str,
        is_bot: bool,
        latency_ms: int,
        request_query_params: Dict[str, str],
    ):
        """Synchronous event emission (runs in thread pool)"""
        try:
            event = self._build_click_event(
                runtime_record,
                click_session_id,
                context,
                final_url,
                is_bot,
                latency_ms,
                request_query_params,
            )
            
            # Send to Firehose
            response = self.firehose.put_record(
                DeliveryStreamName=settings.FIREHOSE_STREAM_NAME,
                Record={
                    'Data': json.dumps(event) + '\n'  # Newline-delimited JSON
                }
            )
            
            logger.debug(f"Event emitted: {click_session_id} -> {response['RecordId']}")
        
        except Exception as e:
            logger.error(f"Failed to emit event: {e}", exc_info=True)
            # Don't raise - event emission failure should not affect redirect
    
    def _build_click_event(
        self,
        runtime_record: Dict,
        click_session_id: str,
        context: Dict,
        final_url: str,
        is_bot: bool,
        latency_ms: int,
        request_query_params: Dict[str, str],
    ) -> Dict:
        """Build click event structure. Include sms_msg_id when present for SMS journey tracking."""
        ip_hash = hashlib.sha256(
            context.get('ip_address', '').encode()
        ).hexdigest()
        final_url_hash = hashlib.sha256(final_url.encode()).hexdigest()

        event = {
            'event_id': str(uuid.uuid4()),
            'event_type': 'click',
            'timestamp': time.time(),
            'link_id': runtime_record.get('link_id', ''),
            'domain': runtime_record.get('PK', '').replace('DOMAIN#', ''),
            'slug': runtime_record.get('SK', '').replace('SLUG#', ''),
            'campaign_id': runtime_record.get('campaign_id', ''),
            'keyword': runtime_record.get('keyword', ''),
            'channel': runtime_record.get('channel', ''),
            'click_session_id': click_session_id,
            'user_agent': context.get('user_agent', ''),
            'referer': context.get('referer', ''),
            'ip_hash': ip_hash,
            'geo_country': context.get('geo_country', ''),
            'final_url_hash': final_url_hash,
            'routing_reason': runtime_record.get('routing_rules', {}).get('type', 'default'),
            'is_bot': is_bot,
            'fraud_score': 0.0,
            'redirect_latency_ms': latency_ms,
        }
        # Forward-from-request: include sms_msg_id when present so analytics can join to SmsMessage
        if request_query_params.get('sms_msg_id'):
            event['sms_msg_id'] = request_query_params['sms_msg_id']
        return event

Bot Detector
app/utils/bot_detector.py:
pythonimport re
import logging
from typing import List

logger = logging.getLogger(__name__)


class BotDetector:
    """Detect bots and crawlers from user agent"""
    
    # Known bot patterns
    BOT_PATTERNS = [
        r'bot',
        r'crawler',
        r'spider',
        r'scraper',
        r'curl',
        r'wget',
        r'python-requests',
        r'http',
        r'java',
        r'php',
        r'ruby',
        r'go-http-client',
        r'okhttp',
        r'apache-httpclient',
    ]
    
    # Known good bots (search engines)
    GOOD_BOTS = [
        'googlebot',
        'bingbot',
        'slurp',  # Yahoo
        'duckduckbot',
        'baiduspider',
        'yandexbot',
        'facebookexternalhit',
        'twitterbot',
        'linkedinbot',
    ]
    
    # IP ranges known for bots (simplified)
    BOT_IP_PREFIXES = [
        '66.249.',  # Google
        '157.55.',  # Microsoft
    ]
    
    def __init__(self):
        # Compile regex patterns
        self.bot_regex = re.compile('|'.join(self.BOT_PATTERNS), re.IGNORECASE)
        self.good_bot_regex = re.compile('|'.join(self.GOOD_BOTS), re.IGNORECASE)
    
    def is_bot(self, user_agent: str, ip_address: str) -> bool:
        """
        Detect if request is from a bot
        
        Args:
            user_agent: User-Agent header
            ip_address: Client IP address
        
        Returns:
            True if bot detected, False otherwise
        """
        if not user_agent:
            # No user agent = likely bot
            return True
        
        # Check good bots first (search engines)
        if self.good_bot_regex.search(user_agent):
            logger.debug(f"Good bot detected: {user_agent}")
            return False  # Don't flag as bot for analytics
        
        # Check bad bot patterns
        if self.bot_regex.search(user_agent):
            logger.debug(f"Bot detected: {user_agent}")
            return True
        
        # Check IP ranges
        for prefix in self.BOT_IP_PREFIXES:
            if ip_address.startswith(prefix):
                logger.debug(f"Bot IP detected: {ip_address}")
                return True
        
        return False

Caching Utility
app/utils/cache.py:
pythonimport time
from typing import Any, Optional, Dict
from collections import OrderedDict
import threading


class TTLCache:
    """Thread-safe TTL cache with LRU eviction"""
    
    def __init__(self, max_size: int = 10000, ttl: int = 300):
        """
        Args:
            max_size: Maximum number of entries
            ttl: Time-to-live in seconds
        """
        self.max_size = max_size
        self.ttl = ttl
        self.cache: OrderedDict = OrderedDict()
        self.lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self.lock:
            if key not in self.cache:
                return None
            
            entry = self.cache[key]
            
            # Check if expired
            if time.time() > entry['expires_at']:
                del self.cache[key]
                return None
            
            # Move to end (LRU)
            self.cache.move_to_end(key)
            
            return entry['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache"""
        with self.lock:
            # Use custom TTL or default
            expires_at = time.time() + (ttl or self.ttl)
            
            # Add to cache
            self.cache[key] = {
                'value': value,
                'expires_at': expires_at
            }
            
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            
            # Evict if over max size
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)  # Remove oldest
    
    def delete(self, key: str):
        """Delete key from cache"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
    
    def clear(self):
        """Clear entire cache"""
        with self.lock:
            self.cache.clear()

Middleware
app/middleware/metrics.py:
pythonimport time
import boto3
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Send metrics to CloudWatch"""
    
    def __init__(self, app):
        super().__init__(app)
        
        if settings.ENVIRONMENT == "production":
            self.cloudwatch = boto3.client(
                'cloudwatch',
                region_name=settings.AWS_REGION
            )
        else:
            self.cloudwatch = None
    
    async def dispatch(self, request: Request, call_next):
        # Start timer
        start_time = time.time()
        
        # Process request
        response: Response = await call_next(request)
        
        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000
        
        # Send metrics to CloudWatch (async)
        if self.cloudwatch:
            try:
                self.cloudwatch.put_metric_data(
                    Namespace=settings.CLOUDWATCH_NAMESPACE,
                    MetricData=[
                        {
                            'MetricName': 'RequestLatency',
                            'Value': latency_ms,
                            'Unit': 'Milliseconds',
                            'Dimensions': [
                                {
                                    'Name': 'Path',
                                    'Value': request.url.path
                                },
                                {
                                    'Name': 'StatusCode',
                                    'Value': str(response.status_code)
                                }
                            ]
                        },
                        {
                            'MetricName': 'RequestCount',
                            'Value': 1,
                            'Unit': 'Count',
                            'Dimensions': [
                                {
                                    'Name': 'StatusCode',
                                    'Value': str(response.status_code)
                                }
                            ]
                        }
                    ]
                )
            except Exception as e:
                logger.error(f"Failed to send metrics: {e}")
        
        return response

Dockerfile
Dockerfile:
dockerfileFROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run application with Gunicorn
CMD ["gunicorn", "app.main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
requirements.txt:
txtfastapi==0.109.0
uvicorn[standard]==0.27.0
gunicorn==21.2.0
boto3==1.34.0
pydantic-settings==2.1.0
python-multipart==0.0.6
pytz==2024.1

Terraform Infrastructure
Main Configuration
terraform/main.tf:
hclterraform {
  required_version = ">= 1.5"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  backend "s3" {
    bucket         = "novaura-terraform-state"
    key            = "link-runtime/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "LinkTracking"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

Variables
terraform/variables.tf:
hclvariable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "link-runtime"
}

variable "vpc_id" {
  description = "VPC ID for ECS deployment"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for ALB"
  type        = list(string)
}

variable "domain_name" {
  description = "Primary domain for CloudFront"
  type        = string
  default     = "go.novaura.io"
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for CloudFront"
  type        = string
}

variable "ecs_task_cpu" {
  description = "ECS task CPU units"
  type        = string
  default     = "512"  # 0.5 vCPU
}

variable "ecs_task_memory" {
  description = "ECS task memory (MB)"
  type        = string
  default     = "1024"  # 1 GB
}

variable "ecs_desired_count" {
  description = "Desired number of ECS tasks"
  type        = number
  default     = 2
}

variable "ecs_min_capacity" {
  description = "Minimum ECS task count for auto-scaling"
  type        = number
  default     = 2
}

variable "ecs_max_capacity" {
  description = "Maximum ECS task count for auto-scaling"
  type        = number
  default     = 20
}

variable "default_fallback_url" {
  description = "Default fallback URL for disabled links"
  type        = string
  default     = "https://novaura.io/link-disabled"
}

DynamoDB
The same table is written by the Django control plane (LinkPublisher, settings.LINK_RUNTIME_TABLE_NAME) and read by the runtime service (DYNAMODB_TABLE_NAME). Ensure both use the same table name (e.g. link-runtime-prod or link-runtime-${environment}). The Django management command `setup_dynamodb` creates a table with the same key schema and GSI; Terraform can manage the table instead for production. TTL is optional: the control plane does not currently set a `ttl` attribute on items.

terraform/dynamodb.tf:
hclresource "aws_dynamodb_table" "link_runtime" {
  name           = "link-runtime-${var.environment}"
  billing_mode   = "PAY_PER_REQUEST"  # On-demand pricing
  hash_key       = "PK"
  range_key      = "SK"
  
  attribute {
    name = "PK"
    type = "S"
  }
  
  attribute {
    name = "SK"
    type = "S"
  }
  
  attribute {
    name = "campaign_id"
    type = "S"
  }
  
  # Global Secondary Index for campaign queries (used by control plane for bulk republish)
  global_secondary_index {
    name            = "campaign-index"
    hash_key        = "campaign_id"
    range_key       = "SK"
    projection_type = "ALL"
  }
  
  # Point-in-time recovery
  point_in_time_recovery {
    enabled = true
  }
  
  # Server-side encryption
  server_side_encryption {
    enabled = true
  }
  
  # TTL for automatic cleanup (optional; control plane does not set ttl on items currently)
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
  
  tags = {
    Name = "link-runtime-${var.environment}"
  }
}

# CloudWatch Alarms for DynamoDB
resource "aws_cloudwatch_metric_alarm" "dynamodb_read_throttle" {
  alarm_name          = "${var.project_name}-dynamodb-read-throttle"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "UserErrors"
  namespace           = "AWS/DynamoDB"
  period              = "60"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "DynamoDB read throttle detected"
  
  dimensions = {
    TableName = aws_dynamodb_table.link_runtime.name
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

ECS Cluster & Service
terraform/ecs.tf:
hcl# ECS Cluster
resource "aws_ecs_cluster" "runtime" {
  name = "${var.project_name}-cluster"
  
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ECR Repository
resource "aws_ecr_repository" "runtime" {
  name                 = "${var.project_name}"
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  encryption_configuration {
    encryption_type = "AES256"
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "runtime" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 7
}

# ECS Task Definition
resource "aws_ecs_task_definition" "runtime" {
  family                   = var.project_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "runtime-service"
      image     = "${aws_ecr_repository.runtime.repository_url}:latest"
      essential = true
      
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      
      environment = [
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "DYNAMODB_TABLE_NAME"
          value = aws_dynamodb_table.link_runtime.name
        },
        {
          name  = "FIREHOSE_STREAM_NAME"
          value = aws_kinesis_firehose_delivery_stream.click_events.name
        },
        {
          name  = "DEFAULT_FALLBACK_URL"
          value = var.default_fallback_url
        },
        {
          name  = "CLOUDWATCH_NAMESPACE"
          value = "LinkRuntime"
        }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.runtime.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "runtime"
        }
      }
      
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])
}

# Application Load Balancer
resource "aws_lb" "runtime" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
  
  enable_deletion_protection = true
  enable_http2               = true
  
  access_logs {
    bucket  = aws_s3_bucket.alb_logs.id
    enabled = true
  }
}

# ALB Target Group
resource "aws_lb_target_group" "runtime" {
  name        = "${var.project_name}-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  
  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  
  deregistration_delay = 30
}

# ALB Listener (HTTP - redirects to HTTPS)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.runtime.arn
  port              = "80"
  protocol          = "HTTP"
  
  default_action {
    type = "redirect"
    
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# ALB Listener (HTTPS)
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.runtime.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"
  certificate_arn   = var.acm_certificate_arn
  
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.runtime.arn
  }
}

# ECS Service
resource "aws_ecs_service" "runtime" {
  name            = "${var.project_name}-service"
  cluster         = aws_ecs_cluster.runtime.id
  task_definition = aws_ecs_task_definition.runtime.arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }
  
  load_balancer {
    target_group_arn = aws_lb_target_group.runtime.arn
    container_name   = "runtime-service"
    container_port   = 8000
  }
  
  deployment_configuration {
    maximum_percent         = 200
    minimum_healthy_percent = 100
  }
  
  depends_on = [aws_lb_listener.https]
}

# Auto Scaling
resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.ecs_max_capacity
  min_capacity       = var.ecs_min_capacity
  resource_id        = "service/${aws_ecs_cluster.runtime.name}/${aws_ecs_service.runtime.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Auto Scaling Policy - CPU
resource "aws_appautoscaling_policy" "ecs_cpu" {
  name               = "${var.project_name}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace
  
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70.0
  }
}

# Auto Scaling Policy - ALB Request Count
resource "aws_appautoscaling_policy" "ecs_requests" {
  name               = "${var.project_name}-request-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace
  
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.runtime.arn_suffix}/${aws_lb_target_group.runtime.arn_suffix}"
    }
    target_value = 1000.0  # 1000 requests per target
  }
}

# Security Group - ALB
resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-alb-"
  vpc_id      = var.vpc_id
  
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from internet"
  }
  
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from internet"
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  lifecycle {
    create_before_destroy = true
  }
}

# Security Group - ECS Tasks
resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${var.project_name}-ecs-tasks-"
  vpc_id      = var.vpc_id
  
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "From ALB"
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }
  
  lifecycle {
    create_before_destroy = true
  }
}

# S3 Bucket for ALB Logs
resource "aws_s3_bucket" "alb_logs" {
  bucket = "${var.project_name}-alb-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  
  rule {
    id     = "delete-old-logs"
    status = "Enabled"
    
    expiration {
      days = 30
    }
  }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

Implementation Spec: Runtime Redirect Service & Terraform Infrastructure (Continued)

CloudFront Configuration
terraform/cloudfront.tf:
hcl# CloudFront Distribution
resource "aws_cloudfront_distribution" "runtime" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "Link Runtime Service - ${var.environment}"
  default_root_object = ""
  price_class         = "PriceClass_100"  # US, Canada, Europe
  
  # Primary domain
  aliases = [var.domain_name]
  
  # Origin - ALB
  origin {
    domain_name = aws_lb.runtime.dns_name
    origin_id   = "alb-origin"
    
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 30
      origin_keepalive_timeout = 5
    }
    
    # Custom headers to identify CloudFront traffic
    custom_header {
      name  = "X-CloudFront-Secret"
      value = random_password.cloudfront_secret.result
    }
  }
  
  # Default cache behavior
  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "alb-origin"
    
    forwarded_values {
      query_string = true
      headers      = ["Host"]
      
      cookies {
        forward = "none"
      }
    }
    
    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 60    # 1 minute cache
    max_ttl                = 300   # 5 minutes max
    compress               = true
    
    # Lambda@Edge functions (optional)
    # lambda_function_association {
    #   event_type   = "viewer-request"
    #   lambda_arn   = aws_lambda_function.edge_auth.qualified_arn
    #   include_body = false
    # }
  }
  
  # Restrictions
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  
  # SSL Certificate
  viewer_certificate {
    acm_certificate_arn      = var.acm_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
  
  # Logging
  logging_config {
    include_cookies = false
    bucket          = aws_s3_bucket.cloudfront_logs.bucket_domain_name
    prefix          = "cloudfront/"
  }
  
  # Custom error responses
  custom_error_response {
    error_code            = 404
    response_code         = 302
    response_page_path    = "/"
    error_caching_min_ttl = 10
  }
  
  custom_error_response {
    error_code            = 500
    response_code         = 302
    response_page_path    = "/"
    error_caching_min_ttl = 0
  }
  
  custom_error_response {
    error_code            = 502
    response_code         = 302
    response_page_path    = "/"
    error_caching_min_ttl = 0
  }
  
  custom_error_response {
    error_code            = 503
    response_code         = 302
    response_page_path    = "/"
    error_caching_min_ttl = 0
  }
  
  custom_error_response {
    error_code            = 504
    response_code         = 302
    response_page_path    = "/"
    error_caching_min_ttl = 0
  }
  
  tags = {
    Name = "${var.project_name}-cloudfront"
  }
}

# Random secret for CloudFront -> ALB authentication
resource "random_password" "cloudfront_secret" {
  length  = 32
  special = true
}

# Store secret in Secrets Manager
resource "aws_secretsmanager_secret" "cloudfront_secret" {
  name = "${var.project_name}-cloudfront-secret"
}

resource "aws_secretsmanager_secret_version" "cloudfront_secret" {
  secret_id     = aws_secretsmanager_secret.cloudfront_secret.id
  secret_string = random_password.cloudfront_secret.result
}

# S3 Bucket for CloudFront Logs
resource "aws_s3_bucket" "cloudfront_logs" {
  bucket = "${var.project_name}-cloudfront-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_ownership_controls" "cloudfront_logs" {
  bucket = aws_s3_bucket.cloudfront_logs.id
  
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_acl" "cloudfront_logs" {
  depends_on = [aws_s3_bucket_ownership_controls.cloudfront_logs]
  
  bucket = aws_s3_bucket.cloudfront_logs.id
  acl    = "private"
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudfront_logs" {
  bucket = aws_s3_bucket.cloudfront_logs.id
  
  rule {
    id     = "delete-old-logs"
    status = "Enabled"
    
    expiration {
      days = 30
    }
    
    transition {
      days          = 7
      storage_class = "GLACIER"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cloudfront_logs" {
  bucket = aws_s3_bucket.cloudfront_logs.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Route53 Record (if managing DNS with Route53)
data "aws_route53_zone" "domain" {
  count = var.manage_dns ? 1 : 0
  name  = var.parent_domain_name
}

resource "aws_route53_record" "runtime" {
  count   = var.manage_dns ? 1 : 0
  zone_id = data.aws_route53_zone.domain[0].zone_id
  name    = var.domain_name
  type    = "A"
  
  alias {
    name                   = aws_cloudfront_distribution.runtime.domain_name
    zone_id                = aws_cloudfront_distribution.runtime.hosted_zone_id
    evaluate_target_health = false
  }
}

# WAF Web ACL for CloudFront
resource "aws_wafv2_web_acl" "cloudfront" {
  name  = "${var.project_name}-waf"
  scope = "CLOUDFRONT"
  
  default_action {
    allow {}
  }
  
  # Rule 1: Rate limiting per IP
  rule {
    name     = "rate-limit"
    priority = 1
    
    action {
      block {}
    }
    
    statement {
      rate_based_statement {
        limit              = 2000  # 2000 requests per 5 minutes
        aggregate_key_type = "IP"
      }
    }
    
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitRule"
      sampled_requests_enabled   = true
    }
  }
  
  # Rule 2: AWS Managed Rules - Core Rule Set
  rule {
    name     = "aws-managed-rules"
    priority = 2
    
    override_action {
      none {}
    }
    
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRules"
      sampled_requests_enabled   = true
    }
  }
  
  # Rule 3: Known Bad Inputs
  rule {
    name     = "known-bad-inputs"
    priority = 3
    
    override_action {
      none {}
    }
    
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "KnownBadInputs"
      sampled_requests_enabled   = true
    }
  }
  
  # Rule 4: Bot Control (optional, additional cost)
  # rule {
  #   name     = "bot-control"
  #   priority = 4
  #   
  #   override_action {
  #     none {}
  #   }
  #   
  #   statement {
  #     managed_rule_group_statement {
  #       name        = "AWSManagedRulesBotControlRuleSet"
  #       vendor_name = "AWS"
  #     }
  #   }
  #   
  #   visibility_config {
  #     cloudwatch_metrics_enabled = true
  #     metric_name                = "BotControl"
  #     sampled_requests_enabled   = true
  #   }
  # }
  
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "LinkRuntimeWAF"
    sampled_requests_enabled   = true
  }
}

# Associate WAF with CloudFront
resource "aws_wafv2_web_acl_association" "cloudfront" {
  resource_arn = aws_cloudfront_distribution.runtime.arn
  web_acl_arn  = aws_wafv2_web_acl.cloudfront.arn
}

Kinesis Firehose
terraform/firehose.tf:
hcl# S3 Bucket for Click Events
resource "aws_s3_bucket" "click_events" {
  bucket = "${var.project_name}-click-events-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_lifecycle_configuration" "click_events" {
  bucket = aws_s3_bucket.click_events.id
  
  rule {
    id     = "archive-old-events"
    status = "Enabled"
    
    transition {
      days          = 30
      storage_class = "GLACIER"
    }
    
    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_public_access_block" "click_events" {
  bucket = aws_s3_bucket.click_events.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Kinesis Firehose Delivery Stream
resource "aws_kinesis_firehose_delivery_stream" "click_events" {
  name        = "${var.project_name}-click-events"
  destination = "extended_s3"
  
  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_role.arn
    bucket_arn = aws_s3_bucket.click_events.arn
    
    # S3 prefix pattern (partition by date)
    prefix              = "click-events/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "click-events-errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    
    # Buffering
    buffering_size     = 5    # MB
    buffering_interval = 60   # seconds
    
    # Compression
    compression_format = "GZIP"
    
    # Data format conversion (JSON to Parquet for Snowflake)
    data_format_conversion_configuration {
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = "SNAPPY"
          }
        }
      }
      
      schema_configuration {
        database_name = aws_glue_catalog_database.click_events.name
        table_name    = aws_glue_catalog_table.click_events.name
        role_arn      = aws_iam_role.firehose_role.arn
      }
    }
    
    # CloudWatch Logging
    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose.name
      log_stream_name = "S3Delivery"
    }
  }
}

# CloudWatch Log Group for Firehose
resource "aws_cloudwatch_log_group" "firehose" {
  name              = "/aws/kinesisfirehose/${var.project_name}-click-events"
  retention_in_days = 7
}

# Glue Catalog Database
resource "aws_glue_catalog_database" "click_events" {
  name = "${var.project_name}_click_events"
}

# Glue Catalog Table (Schema for Parquet conversion)
resource "aws_glue_catalog_table" "click_events" {
  database_name = aws_glue_catalog_database.click_events.name
  name          = "click_events"
  
  table_type = "EXTERNAL_TABLE"
  
  parameters = {
    "classification" = "parquet"
  }
  
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.click_events.id}/click-events/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    
    columns {
      name = "event_id"
      type = "string"
    }
    
    columns {
      name = "event_type"
      type = "string"
    }
    
    columns {
      name = "timestamp"
      type = "double"
    }
    
    columns {
      name = "link_id"
      type = "string"
    }
    
    columns {
      name = "domain"
      type = "string"
    }
    
    columns {
      name = "slug"
      type = "string"
    }
    
    columns {
      name = "campaign_id"
      type = "string"
    }
    
    columns {
      name = "keyword"
      type = "string"
    }
    
    columns {
      name = "channel"
      type = "string"
    }
    
    columns {
      name = "click_session_id"
      type = "string"
    }
    
    columns {
      name = "user_agent"
      type = "string"
    }
    
    columns {
      name = "referer"
      type = "string"
    }
    
    columns {
      name = "ip_hash"
      type = "string"
    }
    
    columns {
      name = "geo_country"
      type = "string"
    }
    
    columns {
      name = "final_url_hash"
      type = "string"
    }
    
    columns {
      name = "routing_reason"
      type = "string"
    }
    
    columns {
      name = "is_bot"
      type = "boolean"
    }
    
    columns {
      name = "fraud_score"
      type = "double"
    }
    
    columns {
      name = "redirect_latency_ms"
      type = "int"
    }
    # Optional: present when link was opened from SMS with ?sms_msg_id= (journey tracking)
    columns {
      name = "sms_msg_id"
      type = "string"
    }
  }
}

# IAM Role for Firehose
resource "aws_iam_role" "firehose_role" {
  name = "${var.project_name}-firehose-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "firehose.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for Firehose
resource "aws_iam_role_policy" "firehose_policy" {
  name = "${var.project_name}-firehose-policy"
  role = aws_iam_role.firehose_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.click_events.arn,
          "${aws_s3_bucket.click_events.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetTable",
          "glue:GetTableVersion",
          "glue:GetTableVersions"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.click_events.name}",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.click_events.name}/${aws_glue_catalog_table.click_events.name}"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          aws_cloudwatch_log_group.firehose.arn,
          "${aws_cloudwatch_log_group.firehose.arn}:*"
        ]
      }
    ]
  })
}

# CloudWatch Alarm - Firehose Delivery Failures
resource "aws_cloudwatch_metric_alarm" "firehose_delivery_errors" {
  alarm_name          = "${var.project_name}-firehose-delivery-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "DeliveryToS3.DataFreshness"
  namespace           = "AWS/Firehose"
  period              = "300"
  statistic           = "Maximum"
  threshold           = "900"  # 15 minutes
  alarm_description   = "Firehose delivery lag detected"
  
  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.click_events.name
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

IAM Roles
terraform/iam.tf:
hcl# ECS Execution Role (for pulling images, secrets, logs)
resource "aws_iam_role" "ecs_execution_role" {
  name = "${var.project_name}-ecs-execution-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Additional permissions for Secrets Manager
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "${var.project_name}-ecs-execution-secrets"
  role = aws_iam_role.ecs_execution_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.cloudfront_secret.arn
        ]
      }
    ]
  })
}

# ECS Task Role (what the container can do)
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name}-ecs-task-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

# DynamoDB Read Access
resource "aws_iam_role_policy" "ecs_task_dynamodb" {
  name = "${var.project_name}-ecs-task-dynamodb"
  role = aws_iam_role.ecs_task_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.link_runtime.arn,
          "${aws_dynamodb_table.link_runtime.arn}/index/*"
        ]
      }
    ]
  })
}

# Firehose Write Access
resource "aws_iam_role_policy" "ecs_task_firehose" {
  name = "${var.project_name}-ecs-task-firehose"
  role = aws_iam_role.ecs_task_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "firehose:PutRecord",
          "firehose:PutRecordBatch"
        ]
        Resource = [
          aws_kinesis_firehose_delivery_stream.click_events.arn
        ]
      }
    ]
  })
}

# CloudWatch Metrics
resource "aws_iam_role_policy" "ecs_task_cloudwatch" {
  name = "${var.project_name}-ecs-task-cloudwatch"
  role = aws_iam_role.ecs_task_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "LinkRuntime"
          }
        }
      }
    ]
  })
}

# Secrets Manager Read (for signature validation)
resource "aws_iam_role_policy" "ecs_task_secrets" {
  name = "${var.project_name}-ecs-task-secrets"
  role = aws_iam_role.ecs_task_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:link-signatures/*"
        ]
      }
    ]
  })
}

# CloudWatch Logs
resource "aws_iam_role_policy_attachment" "ecs_task_logs" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

Monitoring & Alarms
terraform/monitoring.tf:
hcl# SNS Topic for Alerts
resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# CloudWatch Dashboard
resource "aws_cloudwatch_dashboard" "runtime" {
  dashboard_name = "${var.project_name}-dashboard"
  
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", { stat = "Average" }],
            [".", "MemoryUtilization", { stat = "Average" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "ECS Resource Utilization"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", { stat = "Average" }],
            ["...", { stat = "p99" }]
          ]
          period = 60
          stat   = "Average"
          region = var.aws_region
          title  = "Response Time"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", { stat = "Sum" }],
            [".", "HTTPCode_Target_2XX_Count", { stat = "Sum" }],
            [".", "HTTPCode_Target_4XX_Count", { stat = "Sum" }],
            [".", "HTTPCode_Target_5XX_Count", { stat = "Sum" }]
          ]
          period = 60
          stat   = "Sum"
          region = var.aws_region
          title  = "Request Count & Status Codes"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", { stat = "Sum" }],
            [".", "UserErrors", { stat = "Sum" }],
            [".", "SystemErrors", { stat = "Sum" }]
          ]
          period = 300
          stat   = "Sum"
          region = var.aws_region
          title  = "DynamoDB Metrics"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/Firehose", "DeliveryToS3.Success", { stat = "Average" }],
            [".", "DeliveryToS3.DataFreshness", { stat = "Maximum" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "Firehose Delivery"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["LinkRuntime", "RequestLatency", { stat = "Average" }],
            ["...", { stat = "p99" }]
          ]
          period = 60
          stat   = "Average"
          region = var.aws_region
          title  = "Custom Metrics - Latency"
        }
      }
    ]
  })
}

# CloudWatch Alarms

# Alarm: High Error Rate
resource "aws_cloudwatch_metric_alarm" "high_error_rate" {
  alarm_name          = "${var.project_name}-high-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = "60"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "High 5xx error rate detected"
  treat_missing_data  = "notBreaching"
  
  dimensions = {
    LoadBalancer = aws_lb.runtime.arn_suffix
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alarm: High Latency (p99)
resource "aws_cloudwatch_metric_alarm" "high_latency" {
  alarm_name          = "${var.project_name}-high-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  
  metric_query {
    id          = "m1"
    return_data = true
    
    metric {
      metric_name = "TargetResponseTime"
      namespace   = "AWS/ApplicationELB"
      period      = "60"
      stat        = "p99"
      
      dimensions = {
        LoadBalancer = aws_lb.runtime.arn_suffix
      }
    }
  }
  
  threshold         = "0.5"  # 500ms
  alarm_description = "p99 latency exceeds 500ms"
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alarm: High CPU Utilization
resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "${var.project_name}-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "ECS CPU utilization above 80%"
  
  dimensions = {
    ServiceName = aws_ecs_service.runtime.name
    ClusterName = aws_ecs_cluster.runtime.name
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alarm: No Healthy Targets
resource "aws_cloudwatch_metric_alarm" "no_healthy_targets" {
  alarm_name          = "${var.project_name}-no-healthy-targets"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = "60"
  statistic           = "Average"
  threshold           = "1"
  alarm_description   = "No healthy targets in target group"
  treat_missing_data  = "breaching"
  
  dimensions = {
    TargetGroup  = aws_lb_target_group.runtime.arn_suffix
    LoadBalancer = aws_lb.runtime.arn_suffix
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alarm: WAF Blocked Requests
resource "aws_cloudwatch_metric_alarm" "waf_blocked_requests" {
  alarm_name          = "${var.project_name}-waf-blocked-requests"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "BlockedRequests"
  namespace           = "AWS/WAFV2"
  period              = "300"
  statistic           = "Sum"
  threshold           = "1000"
  alarm_description   = "High number of blocked requests by WAF"
  
  dimensions = {
    Rule   = "rate-limit"
    WebACL = aws_wafv2_web_acl.cloudfront.name
    Region = "us-east-1"  # CloudFront metrics are in us-east-1
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alarm: CloudFront 4xx Error Rate
resource "aws_cloudwatch_metric_alarm" "cloudfront_4xx_errors" {
  alarm_name          = "${var.project_name}-cloudfront-4xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "4xxErrorRate"
  namespace           = "AWS/CloudFront"
  period              = "300"
  statistic           = "Average"
  threshold           = "5"  # 5% error rate
  alarm_description   = "High 4xx error rate on CloudFront"
  
  dimensions = {
    DistributionId = aws_cloudfront_distribution.runtime.id
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alarm: CloudFront 5xx Error Rate
resource "aws_cloudwatch_metric_alarm" "cloudfront_5xx_errors" {
  alarm_name          = "${var.project_name}-cloudfront-5xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "5xxErrorRate"
  namespace           = "AWS/CloudFront"
  period              = "300"
  statistic           = "Average"
  threshold           = "1"  # 1% error rate
  alarm_description   = "High 5xx error rate on CloudFront"
  
  dimensions = {
    DistributionId = aws_cloudfront_distribution.runtime.id
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Custom Metric Filter - Application Errors
resource "aws_cloudwatch_log_metric_filter" "application_errors" {
  name           = "${var.project_name}-application-errors"
  log_group_name = aws_cloudwatch_log_group.runtime.name
  pattern        = "[time, request_id, level=ERROR*, ...]"
  
  metric_transformation {
    name      = "ApplicationErrors"
    namespace = "LinkRuntime"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "application_errors" {
  alarm_name          = "${var.project_name}-application-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "ApplicationErrors"
  namespace           = "LinkRuntime"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "High number of application errors in logs"
  treat_missing_data  = "notBreaching"
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

Outputs
terraform/outputs.tf:
hcloutput "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.runtime.id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain name"
  value       = aws_cloudfront_distribution.runtime.domain_name
}

output "alb_dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.runtime.dns_name
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.runtime.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.runtime.name
}

output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.link_runtime.name
}

output "firehose_stream_name" {
  description = "Firehose delivery stream name"
  value       = aws_kinesis_firehose_delivery_stream.click_events.name
}

output "ecr_repository_url" {
  description = "ECR repository URL"
  value       = aws_ecr_repository.runtime.repository_url
}

output "s3_click_events_bucket" {
  description = "S3 bucket for click events"
  value       = aws_s3_bucket.click_events.id
}

output "waf_web_acl_id" {
  description = "WAF Web ACL ID"
  value       = aws_wafv2_web_acl.cloudfront.id
}

output "sns_alerts_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = aws_sns_topic.alerts.arn
}

Deployment
Build & Deploy Script
deploy.sh:
bash#!/bin/bash
set -e

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-production}"
ECR_REPO_NAME="link-runtime"

echo "=========================================="
echo "Link Runtime Service Deployment"
echo "Environment: $ENVIRONMENT"
echo "Region: $AWS_REGION"
echo "=========================================="

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

echo "Step 1: Building Docker image..."
docker build -t ${ECR_REPO_NAME}:latest .

echo "Step 2: Tagging image..."
docker tag ${ECR_REPO_NAME}:latest ${ECR_REPO}:latest
docker tag ${ECR_REPO_NAME}:latest ${ECR_REPO}:$(git rev-parse --short HEAD)

echo "Step 3: Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${ECR_REPO}

echo "Step 4: Pushing image to ECR..."
docker push ${ECR_REPO}:latest
docker push ${ECR_REPO}:$(git rev-parse --short HEAD)

echo "Step 5: Updating ECS service..."
aws ecs update-service \
    --cluster link-runtime-cluster \
    --service link-runtime-service \
    --force-new-deployment \
    --region ${AWS_REGION}

echo "Step 6: Waiting for deployment to complete..."
aws ecs wait services-stable \
    --cluster link-runtime-cluster \
    --services link-runtime-service \
    --region ${AWS_REGION}

echo "=========================================="
echo "Deployment completed successfully!"
echo "=========================================="

# Show running tasks
echo "Running tasks:"
aws ecs list-tasks \
    --cluster link-runtime-cluster \
    --service-name link-runtime-service \
    --region ${AWS_REGION}
Terraform Deployment
terraform/deploy-infrastructure.sh:
bash#!/bin/bash
set -e

cd terraform

echo "Initializing Terraform..."
terraform init

echo "Validating configuration..."
terraform validate

echo "Planning infrastructure changes..."
terraform plan -out=tfplan

echo "Apply changes? (yes/no)"
read -r REPLY
if [[ $REPLY =~ ^[Yy]es$ ]]; then
    echo "Applying infrastructure changes..."
    terraform apply tfplan
    
    echo "Infrastructure deployment complete!"
    echo "Outputs:"
    terraform output
else
    echo "Deployment cancelled"
    rm tfplan
fi
CI/CD Pipeline (GitHub Actions)
.github/workflows/deploy.yml:
yamlname: Deploy Runtime Service

on:
  push:
    branches:
      - main
    paths:
      - 'app/**'
      - 'Dockerfile'
      - 'requirements.txt'
      - '.github/workflows/deploy.yml'

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: link-runtime
  ECS_CLUSTER: link-runtime-cluster
  ECS_SERVICE: link-runtime-service

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}
      
      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v1
      
      - name: Build, tag, and push image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
      
      - name: Update ECS service
        run: |
          aws ecs update-service \
            --cluster ${{ env.ECS_CLUSTER }} \
            --service ${{ env.ECS_SERVICE }} \
            --force-new-deployment
      
      - name: Wait for service stability
        run: |
          aws ecs wait services-stable \
            --cluster ${{ env.ECS_CLUSTER }} \
            --services ${{ env.ECS_SERVICE }}
      
      - name: Notify deployment
        if: success()
        run: echo "Deployment successful!"

Testing
Load Testing Script
tests/load_test.py:
pythonimport asyncio
import aiohttp
import time
from typing import List
import statistics

async def make_request(session: aiohttp.ClientSession, url: str) -> dict:
    """Make a single request and measure latency"""
    start_time = time.time()
    
    try:
        async with session.get(url, allow_redirects=False) as response:
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                'status': response.status,
                'latency_ms': latency_ms,
                'success': response.status in [302, 301]
            }
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return {
            'status': 0,
            'latency_ms': latency_ms,
            'success': False,
            'error': str(e)
        }

async def load_test(
    base_url: str,
    slug: str,
    concurrent_requests: int = 100,
    total_requests: int = 1000
):
    """Run load test"""
    
    url = f"{base_url}/{slug}"
    results: List[dict] = []
    
    print(f"Starting load test...")
    print(f"URL: {url}")
    print(f"Concurrent: {concurrent_requests}")
    print(f"Total Requests: {total_requests}")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        # Create batches
        batches = [
            total_requests // concurrent_requests
            for _ in range(concurrent_requests)
        ]
        
        start_time = time.time()
        
        for batch_idx, batch_size in enumerate(batches):
            tasks = [
                make_request(session, url)
                for _ in range(batch_size)
            ]
            
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            
            if (batch_idx + 1) % 10 == 0:
                print(f"Completed {len(results)}/{total_requests} requests...")
        
        total_time = time.time() - start_time
    
    # Calculate statistics
    latencies = [r['latency_ms'] for r in results]
    successes = [r for r in results if r['success']]
    
    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"Total Requests: {len(results)}")
    print(f"Successful: {len(successes)} ({len(successes)/len(results)*100:.2f}%)")
    print(f"Failed: {len(results) - len(successes)}")
    print(f"Total Time: {total_time:.2f}s")
    print(f"Requests/sec: {len(results)/total_time:.2f}")
    print()
    print("Latency Statistics:")
    print(f"  Mean: {statistics.mean(latencies):.2f}ms")
    print(f"  Median: {statistics.median(latencies):.2f}ms")
    print(f"  p95: {sorted(latencies)[int(len(latencies)*0.95)]:.2f}ms")
    print(f"  p99: {sorted(latencies)[int(len(latencies)*0.99)]:.2f}ms")
    print(f"  Min: {min(latencies):.2f}ms")
    print(f"  Max: {max(latencies):.2f}ms")

if __name__ == "__main__":
    asyncio.run(load_test(
        base_url="https://go.novaura.io",
        slug="TEST123",
        concurrent_requests=100,
        total_requests=10000
    ))

Runbooks
Runbook: High Error Rate
runbooks/high-error-rate.md:
markdown# Runbook: High Error Rate

**Alert**: `link-runtime-high-error-rate`

## Symptoms
- CloudWatch alarm triggered
- 5xx errors > 10 in 1 minute
- Users unable to access short links

## Investigation Steps

### 1. Check ECS Service Health
```bash
aws ecs describe-services \
  --cluster link-runtime-cluster \
  --services link-runtime-service \
  --query 'services[0].{DesiredCount:desiredCount,RunningCount:runningCount,HealthyTargets:loadBalancers[0].containerPort}'
```

### 2. Check Recent Deployments
```bash
aws ecs describe-services \
  --cluster link-runtime-cluster \
  --services link-runtime-service \
  --query 'services[0].deployments'
```

### 3. Check Application Logs
```bash
aws logs tail /ecs/link-runtime --follow --since 5m
```

Look for:
- Python exceptions
- DynamoDB errors
- Firehose errors

### 4. Check DynamoDB Health
```bash
aws dynamodb describe-table \
  --table-name link-runtime-production \
  --query 'Table.{Status:TableStatus,ItemCount:ItemCount}'
```

### 5. Check Target Health
```bash
aws elbv2 describe-target-health \
  --target-group-arn 
```

## Common Causes & Resolutions

### Cause: DynamoDB Throttling
**Symptoms**: Logs show `ProvisionedThroughputExceededException`

**Resolution**:
```bash
# Temporarily increase capacity
aws dynamodb update-table \
  --table-name link-runtime-production \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=100,WriteCapacityUnits=10
```

### Cause: ECS Task Failures
**Symptoms**: Running count < Desired count

**Resolution**:
```bash
# Force new deployment
aws ecs update-service \
  --cluster link-runtime-cluster \
  --service link-runtime-service \
  --force-new-deployment
```

### Cause: Bad Deployment
**Symptoms**: Errors started after recent deploy

**Resolution**:
```bash
# Rollback to previous task definition
PREVIOUS_TASK_DEF=$(aws ecs describe-services \
  --cluster link-runtime-cluster \
  --services link-runtime-service \
  --query 'services[0].deployments[1].taskDefinition' \
  --output text)

aws ecs update-service \
  --cluster link-runtime-cluster \
  --service link-runtime-service \
  --task-definition $PREVIOUS_TASK_DEF
```

## Escalation
If issue persists after 15 minutes:
1. Page on-call engineer
2. Consider enabling maintenance mode
3. Notify stakeholders

Runbook: High Latency
runbooks/high-latency.md:
markdown# Runbook: High Latency

**Alert**: `link-runtime-high-latency`

## Symptoms
- p99 latency > 500ms
- Slow redirect responses
- Users experiencing delays

## Investigation Steps

### 1. Check Current Latency
```bash
# CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name TargetResponseTime \
  --dimensions Name=LoadBalancer,Value= \
  --statistics Average,Maximum \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60
```

### 2. Check DynamoDB Latency
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name SuccessfulRequestLatency \
  --dimensions Name=TableName,Value=link-runtime-production Name=Operation,Value=GetItem \
  --statistics Average,Maximum \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60
```

### 3. Check ECS CPU/Memory
```bash
aws ecs describe-services \
  --cluster link-runtime-cluster \
  --services link-runtime-service \
  --query 'services[0].{CPU:runningCount,Memory:pendingCount}'
```

### 4. Check Cache Hit Rate
Look in application logs for cache metrics:
```bash
aws logs filter-pattern /ecs/link-runtime --filter-pattern "Cache hit"
```

## Common Causes & Resolutions

### Cause: Cold Cache
**Symptoms**: High DynamoDB read latency, low cache hits

**Resolution**:
- Cache will warm up naturally
- Consider pre-warming for high-traffic links
- Increase cache size if needed

### Cause: High CPU
**Symptoms**: ECS CPU > 80%

**Resolution**:
```bash
# Scale up task count
aws ecs update-service \
  --cluster link-runtime-cluster \
  --service link-runtime-service \
  --desired-count 10
```

### Cause: DynamoDB Hot Partition
**Symptoms**: Specific slugs are slow, others are fast

**Resolution**:
- Check if one link is getting disproportionate traffic
- Consider enabling DynamoDB DAX (caching layer)
- Increase cache TTL for hot links

## Prevention
- Monitor cache hit rates
- Set up auto-scaling alerts
- Regular load testing

This completes the Runtime/Processor Service specification including:
✅ Complete FastAPI application code
✅ Full Terraform infrastructure (DynamoDB, ECS, CloudFront, Firehose, WAF, IAM)
✅ Monitoring & alerting setup
✅ Deployment scripts & CI/CD
✅ Load testing tools
✅ Operational runbooks
Your team now has everything needed to:

Deploy the infrastructure with Terraform
Build and deploy the runtime service
Monitor performance and health
Respond to incidents with runbooks