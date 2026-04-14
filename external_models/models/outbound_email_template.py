"""Unmanaged mirrors of CRM ACS outbound email template tables."""

import uuid

from django.db import models

from .accounts import User
from .communications import ContactEndpoint
from .external_references import Account


class EmailImportSession(models.Model):
    """
    Minimal stub so OutboundEmailTemplateVersion.import_session FK resolves.
    Full row lives in CRM; only primary key is mirrored here.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        managed = False
        db_table = 'acs_email_import_session'


EDITOR_TYPE_VISUAL_BUILDER = 'visual_builder'
EDITOR_TYPE_RAW_HTML = 'raw_html'
EDITOR_TYPE_CHOICES = (
    (EDITOR_TYPE_VISUAL_BUILDER, 'Visual builder'),
    (EDITOR_TYPE_RAW_HTML, 'Raw HTML'),
)
DEFAULT_EDITOR_SCHEMA_VERSION = 1


def _default_variables_schema():
    return []


class OutboundEmailTemplate(models.Model):
    """Stable identity for a stored email template (content lives on versions). Unmanaged mirror."""

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='outbound_email_templates',
        null=True,
        blank=True,
        help_text='Null for system-wide templates',
    )
    lead_nurturing_campaign = models.ForeignKey(
        'external_models.LeadNurturingCampaign',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='outbound_email_templates',
        help_text='When set, template is scoped to this nurturing campaign (account must match)',
    )
    slug = models.SlugField(max_length=120, help_text='Unique per account; used in naming and URLs')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    default_from_endpoint = models.ForeignKey(
        ContactEndpoint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='Optional hint for preview/sync; sends use EmailConfig.from_endpoint',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='outbound_email_templates_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    mailgun_template_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Mailgun domain template name (shared by all revisions); set on first sync',
    )

    class Meta:
        managed = False
        db_table = 'acs_outbound_email_template'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['slug'],
                condition=models.Q(account__isnull=True, lead_nurturing_campaign__isnull=True),
                name='acs_outbound_tpl_unique_slug_system',
            ),
            models.UniqueConstraint(
                fields=['account', 'slug'],
                condition=models.Q(lead_nurturing_campaign__isnull=True) & models.Q(account__isnull=False),
                name='acs_outbound_tpl_unique_slug_account',
            ),
            models.UniqueConstraint(
                fields=['lead_nurturing_campaign', 'slug'],
                condition=models.Q(lead_nurturing_campaign__isnull=False),
                name='acs_outbound_tpl_unique_slug_campaign',
            ),
        ]

    def __str__(self):
        if self.lead_nurturing_campaign_id:
            return f'{self.slug} (campaign={self.lead_nurturing_campaign_id})'
        if self.account_id:
            return f'{self.slug} ({self.account_id})'
        return f'{self.slug} (system)'


class OutboundEmailTemplateVersion(models.Model):
    """Single revision of template HTML/text. Unmanaged mirror (no CRM save/checksum logic)."""

    STATUS_DRAFT = 'draft'
    STATUS_PENDING_REVIEW = 'pending_review'
    STATUS_APPROVED = 'approved'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = (
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING_REVIEW, 'Pending review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_ARCHIVED, 'Archived'),
    )

    template = models.ForeignKey(
        OutboundEmailTemplate,
        on_delete=models.CASCADE,
        related_name='versions',
    )
    editor_type = models.CharField(
        max_length=32,
        choices=EDITOR_TYPE_CHOICES,
        default=EDITOR_TYPE_RAW_HTML,
        help_text='Authoring source for this version. visual_builder stores design_json and compiled html/text.',
    )
    editor_schema_version = models.PositiveSmallIntegerField(default=DEFAULT_EDITOR_SCHEMA_VERSION)
    design_json = models.JSONField(default=dict, blank=True)
    revision = models.PositiveIntegerField(
        help_text='Monotonic per template (1, 2, …); set by API on create',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    subject_text = models.CharField(
        max_length=998,
        blank=True,
        null=True,
        help_text='Default subject when EmailConfig.subject is empty (static v1)',
    )
    html_body = models.TextField()
    text_body = models.TextField(blank=True, null=True)
    text_body_override = models.TextField(blank=True, null=True)
    variables_schema = models.JSONField(
        default=_default_variables_schema,
        blank=True,
        help_text='List of allowed t:variables keys, e.g. ["first_name","company"]',
    )
    content_checksum = models.CharField(max_length=64, blank=True, help_text='sha256 of canonical payload')
    mailgun_version_tag = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text='Optional Mailgun template version tag',
    )
    source_html = models.TextField(blank=True, help_text='Original HTML as imported (optional)')
    import_source = models.CharField(max_length=32, blank=True)
    asset_manifest = models.JSONField(default=list, blank=True)
    import_session = models.ForeignKey(
        EmailImportSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_versions',
    )
    synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, null=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='outbound_email_template_versions_approved',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'acs_outbound_email_template_version'
        ordering = ['template', '-revision']
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'revision'],
                name='acs_outbound_email_ver_unique_revision',
            ),
        ]

    def __str__(self):
        return f'{self.template.slug} r{self.revision} ({self.status})'
