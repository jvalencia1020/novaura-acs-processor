Yes. The intended model is:
Your other systems create/update records in the same DynamoDB table the link runtime service uses.
The link runtime service only reads from that table (by PK/SK) and performs the redirect. It does not create or update link records.
So you “feed” the data by having whatever owns link configuration write items into that DynamoDB table in the shape the runtime expects.
Flow
Publish side (your systems)
When a short link is created or updated (e.g. “slug HELP on go.example.com → https://example.com/landing” with UTM, fallback, etc.):
Your system builds a single DynamoDB item with the expected keys and attributes.
It PutItem (or equivalent) into the table configured in DYNAMODB_TABLE_NAME.
Runtime side (this service)
When a user hits https://go.example.com/HELP:
The runtime does GetItem with PK = "DOMAIN#go.example.com", SK = "SLUG#HELP".
If an item exists and is valid (e.g. active, not expired, signature OK if required), it builds the final URL and returns a 302 to it.
If no item or invalid → redirect to fallback.
So: you feed the data by publishing the right DynamoDB items from your other systems; the link runtime only consumes those records to process redirects.
Who can publish
The docs describe a Django control plane (link_tracking) that resolves UTM, manages campaigns/links, and publishes via LinkPublisher into this table. That’s one valid “other system.”
**ACS processor (novaura-acs-processor)** is another publisher: when it sends messages that contain short redirect links to responders or users (SMS today; email/journey when they use short links), it publishes those links to the same DynamoDB table before send. It uses `link_tracking.services.runtime_publisher.ensure_link_published(link)` so the link runtime can resolve the redirect when the recipient clicks. The table name is set via `LINK_RUNTIME_TABLE_NAME` (must match the runtime service’s `DYNAMODB_TABLE_NAME`, e.g. `link-runtime-production` or `link-runtime-${env}`).
Any other system (another API, admin tool, Lambda, etc.) can also write items to the same table, as long as:
Table name is the one the runtime uses (DYNAMODB_TABLE_NAME).
Keys are PK = DOMAIN#<domain>, SK = SLUG#<slug>.
Required/optional attributes match what the runtime expects (e.g. destination_url, active, and optionally resolved_query_params, dynamic_param_allowlist, fallback_url, etc.).
The runtime does not care who wrote the item; it only cares that the item exists and has the right structure.
Summary
Role	Responsibility
Your systems (control plane / any publisher)	Create and update DynamoDB items (PutItem) for each short link so the table is the “source of truth” for redirect config.
Link runtime service	Read items by domain + slug (GetItem), apply policy/routing/params, and return 302.
So yes: your other systems should publish/create (and update) the records in DynamoDB; that is how you feed the data so the link runtime service can process the redirects successfully.