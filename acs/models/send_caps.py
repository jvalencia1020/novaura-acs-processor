"""Send-cap configuration and live counter buckets for nurturing campaigns.

These models encode the *contract* between this repository (which owns
configuration storage and CRUD) and the external dispatcher (which owns the
actual claim/refund logic at send time). The dispatcher is expected to:

1. Read enabled :class:`NurturingCampaignSendCap` rows for a given campaign,
   filtered by channel and optionally by ``message_type``.
2. For each cap, derive the active window via :meth:`compute_window` and
   atomically ``SELECT ... FOR UPDATE`` the matching
   :class:`NurturingCampaignSendBucket` row (creating it if absent for
   ``boundary='calendar'`` caps).
3. If every applicable cap has remaining capacity, increment each bucket's
   ``count`` by 1 inside a single transaction.
4. If any cap is exhausted, roll back, defer the message
   (``status='scheduled'`` + ``next_eligible_at`` + ``deferral_reason``), and
   return the earliest ``window_end`` as the ``next_reset_at``.

For ``boundary='rolling'`` caps the bucket table is *not* a counter -
dispatchers must aggregate :attr:`acs.BulkCampaignMessage.sent_at` against the
window each time. See ``docs/NURTURING_SEND_CAPS_DISPATCHER_CONTRACT.md`` for
the full contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

_OPT_OUT_MESSAGE_TYPES = {'opt_out_notice', 'opt_out_confirmation'}


class NurturingCampaignSendCap(models.Model):
    """A single send-rate ceiling for a :class:`LeadNurturingCampaign`.

    Multiple caps may exist per campaign (multi-tier - e.g. 100/hour AND
    1000/day). The dispatcher must satisfy *every* enabled cap for a send to
    be released.
    """

    PERIOD_HOURLY = 'hourly'
    PERIOD_DAILY = 'daily'
    PERIOD_WEEKLY = 'weekly'
    PERIOD_MONTHLY = 'monthly'
    PERIOD_CUSTOM = 'custom'

    PERIOD_CHOICES = (
        (PERIOD_HOURLY, 'Hourly'),
        (PERIOD_DAILY, 'Daily'),
        (PERIOD_WEEKLY, 'Weekly'),
        (PERIOD_MONTHLY, 'Monthly'),
        (PERIOD_CUSTOM, 'Custom (custom_window_seconds)'),
    )

    BOUNDARY_CALENDAR = 'calendar'
    BOUNDARY_ROLLING = 'rolling'

    BOUNDARY_CHOICES = (
        (BOUNDARY_CALENDAR, 'Calendar (tz-aligned period)'),
        (BOUNDARY_ROLLING, 'Rolling (last N seconds from now)'),
    )

    CHANNEL_CHOICES = (
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('voice', 'Voice'),
        ('chat', 'Chat'),
    )

    campaign = models.ForeignKey(
        'external_models.LeadNurturingCampaign',
        on_delete=models.CASCADE,
        related_name='send_caps',
        help_text='Campaign this cap applies to.',
    )
    channel = models.CharField(
        max_length=10,
        choices=CHANNEL_CHOICES,
        null=True,
        blank=True,
        help_text=(
            'Optional channel filter. When null, the cap applies to whichever channel '
            'the campaign is configured for at send time.'
        ),
    )
    period = models.CharField(
        max_length=10,
        choices=PERIOD_CHOICES,
        help_text=(
            'Window length type. Use period=custom with custom_window_seconds for '
            "non-standard intervals. Weekly windows start on Monday in the cap's "
            'effective timezone.'
        ),
    )
    custom_window_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            'Window length in seconds when period=custom. Must be null for other '
            'periods. Buckets are anchored at the UNIX epoch in UTC, so sub-hour '
            'windows align on the wall clock only in zones whose UTC offset is a '
            'multiple of the window length (most whole-hour zones; misaligned in '
            'zones like Asia/Kolkata, America/St_Johns, Asia/Kathmandu).'
        ),
    )
    boundary = models.CharField(
        max_length=10,
        choices=BOUNDARY_CHOICES,
        default=BOUNDARY_CALENDAR,
        help_text=(
            'calendar = tz-aligned period boundaries (e.g. midnight to midnight). '
            'rolling = last N seconds from now. Rolling is only valid for hourly/custom.'
        ),
    )
    timezone_name = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=(
            'IANA timezone for calendar boundary alignment. When blank, falls back to '
            'campaign.crm_campaign.default_timezone, then UTC.'
        ),
    )
    max_messages = models.PositiveIntegerField(
        help_text='Maximum messages allowed within one window. Must be >= 1.',
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text='Disable to leave the cap configured but inactive (dispatcher must skip when False).',
    )
    counts_message_types = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'List of BulkCampaignMessage.message_type values this cap counts. '
            'Empty list = ["regular"] only. opt_out_notice / opt_out_confirmation are '
            'always exempt regardless of this list.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'acs_nurturingcampaignsendcap'
        ordering = ['campaign_id', 'period', 'custom_window_seconds']
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'channel', 'period', 'custom_window_seconds'],
                name='unique_cap_per_campaign_channel_period',
            ),
        ]
        indexes = [
            models.Index(fields=['campaign', 'is_enabled']),
        ]

    def __str__(self) -> str:
        ch = self.channel or 'all'
        if self.period == self.PERIOD_CUSTOM:
            return f'cap[{self.campaign_id}/{ch}] {self.max_messages} per {self.custom_window_seconds}s'
        return f'cap[{self.campaign_id}/{ch}] {self.max_messages} per {self.period}'

    def clean(self) -> None:
        super().clean()

        if self.max_messages is not None and self.max_messages < 1:
            raise ValidationError({'max_messages': 'max_messages must be >= 1.'})

        if self.period == self.PERIOD_CUSTOM:
            if not self.custom_window_seconds or self.custom_window_seconds <= 0:
                raise ValidationError(
                    {'custom_window_seconds': 'custom_window_seconds is required and must be > 0 when period=custom.'}
                )
        else:
            if self.custom_window_seconds is not None:
                raise ValidationError(
                    {'custom_window_seconds': 'custom_window_seconds may only be set when period=custom.'}
                )

        if self.boundary == self.BOUNDARY_ROLLING and self.period not in (
            self.PERIOD_HOURLY,
            self.PERIOD_CUSTOM,
        ):
            raise ValidationError(
                {'boundary': 'rolling boundary is only valid for period in (hourly, custom).'}
            )

        if self.timezone_name:
            try:
                ZoneInfo(self.timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValidationError(
                    {'timezone_name': f'Unknown IANA timezone: {self.timezone_name!r}.'}
                ) from exc

        types = self.counts_message_types or []
        if not isinstance(types, list):
            raise ValidationError(
                {'counts_message_types': 'counts_message_types must be a list of message_type strings.'}
            )

        from external_models.models.nurturing_campaigns import BulkCampaignMessage  # local import to avoid cycle

        valid_types = {choice for choice, _ in BulkCampaignMessage.MESSAGE_TYPES}
        for t in types:
            if not isinstance(t, str):
                raise ValidationError(
                    {'counts_message_types': 'Each entry must be a string message_type key.'}
                )
            if t not in valid_types:
                raise ValidationError(
                    {'counts_message_types': f'Unknown message_type: {t!r}.'}
                )
            if t in _OPT_OUT_MESSAGE_TYPES:
                raise ValidationError(
                    {'counts_message_types': f'opt-out types ({t}) are always exempt and cannot be listed here.'}
                )

    def effective_timezone(self) -> ZoneInfo:
        """Resolve the IANA zone used for calendar-boundary alignment."""
        if self.timezone_name:
            try:
                return ZoneInfo(self.timezone_name)
            except ZoneInfoNotFoundError:
                pass
        crm_tz = getattr(getattr(self.campaign, 'crm_campaign', None), 'default_timezone', None)
        if crm_tz:
            try:
                return ZoneInfo(crm_tz)
            except ZoneInfoNotFoundError:
                pass
        return ZoneInfo('UTC')

    def effective_counted_message_types(self) -> Tuple[str, ...]:
        """Resolve the message_type keys this cap counts (excluding opt-outs)."""
        if not self.counts_message_types:
            return ('regular',)
        return tuple(t for t in self.counts_message_types if t not in _OPT_OUT_MESSAGE_TYPES)

    def compute_window(self, now: datetime | None = None) -> Tuple[datetime, datetime, str]:
        """Return ``(window_start, window_end, period_key)`` for the active window.

        ``period_key`` is suitable for use as a dedupe key in
        :class:`NurturingCampaignSendBucket` for ``boundary='calendar'``. For
        ``boundary='rolling'`` the bucket table should not be used as a counter -
        dispatchers must aggregate ``BulkCampaignMessage.sent_at`` instead.
        """
        if now is None:
            now = timezone.now()
        if timezone.is_naive(now):
            now = now.replace(tzinfo=ZoneInfo('UTC'))

        if self.boundary == self.BOUNDARY_ROLLING:
            seconds = self._rolling_window_seconds()
            window_end = now
            window_start = window_end - timedelta(seconds=seconds)
            return window_start, window_end, f'rolling:{int(window_end.timestamp())}'

        tz = self.effective_timezone()
        local_now = now.astimezone(tz)
        window_start_local, window_end_local = self._calendar_window_bounds(local_now)
        period_key = window_start_local.isoformat()
        return window_start_local, window_end_local, period_key

    def _rolling_window_seconds(self) -> int:
        if self.period == self.PERIOD_HOURLY:
            return 3600
        if self.period == self.PERIOD_CUSTOM and self.custom_window_seconds:
            return int(self.custom_window_seconds)
        raise ValidationError('Rolling boundary requires period=hourly or period=custom with custom_window_seconds.')

    def _calendar_window_bounds(self, local_now: datetime) -> Tuple[datetime, datetime]:
        # Daily/weekly/monthly arithmetic must run on naive datetimes and be
        # re-localized via ``naive.replace(tzinfo=tz)`` so ``zoneinfo``
        # re-resolves ``utcoffset()`` for the destination date. Adding a
        # ``timedelta`` to a tz-aware datetime preserves the original offset
        # and silently drifts by an hour across DST transitions.
        tz = local_now.tzinfo
        if self.period == self.PERIOD_HOURLY:
            start = local_now.replace(minute=0, second=0, microsecond=0)
            return start, start + timedelta(hours=1)
        if self.period == self.PERIOD_DAILY:
            naive_start = local_now.replace(tzinfo=None).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            naive_end = naive_start + timedelta(days=1)
            return naive_start.replace(tzinfo=tz), naive_end.replace(tzinfo=tz)
        if self.period == self.PERIOD_WEEKLY:
            day_of_week = local_now.weekday()  # Monday=0
            naive_start = (
                local_now.replace(tzinfo=None) - timedelta(days=day_of_week)
            ).replace(hour=0, minute=0, second=0, microsecond=0)
            naive_end = naive_start + timedelta(days=7)
            return naive_start.replace(tzinfo=tz), naive_end.replace(tzinfo=tz)
        if self.period == self.PERIOD_MONTHLY:
            naive_start = local_now.replace(tzinfo=None).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if naive_start.month == 12:
                naive_end = naive_start.replace(year=naive_start.year + 1, month=1)
            else:
                naive_end = naive_start.replace(month=naive_start.month + 1)
            return naive_start.replace(tzinfo=tz), naive_end.replace(tzinfo=tz)
        if self.period == self.PERIOD_CUSTOM:
            seconds = int(self.custom_window_seconds or 0)
            if seconds <= 0:
                raise ValidationError('custom_window_seconds must be > 0 when period=custom.')
            epoch = datetime(1970, 1, 1, tzinfo=tz)
            elapsed = int((local_now - epoch).total_seconds())
            bucket_index = elapsed // seconds
            start = epoch + timedelta(seconds=bucket_index * seconds)
            return start, start + timedelta(seconds=seconds)
        raise ValidationError(f'Unknown period: {self.period!r}')


class NurturingCampaignSendBucket(models.Model):
    """The atomic counter for an in-flight calendar window of a cap.

    The external dispatcher creates / locks one row per
    ``(cap, period_key)`` and increments :attr:`count` by 1 per claim.
    Rolling-boundary caps do not use this table as a counter (they aggregate
    ``BulkCampaignMessage.sent_at`` directly).
    """

    cap = models.ForeignKey(
        NurturingCampaignSendCap,
        on_delete=models.CASCADE,
        related_name='buckets',
    )
    period_key = models.CharField(
        max_length=64,
        help_text='Stable key for this window (e.g. "2026-05-10T19:00:00-04:00" for hourly calendar).',
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField(db_index=True)
    count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'acs_nurturingcampaignsendbucket'
        ordering = ['-window_end']
        constraints = [
            models.UniqueConstraint(fields=['cap', 'period_key'], name='unique_bucket_per_cap_period'),
        ]
        indexes = [
            models.Index(fields=['cap', 'window_end']),
        ]

    def __str__(self) -> str:
        return f'bucket[cap={self.cap_id}] {self.period_key} count={self.count}'
