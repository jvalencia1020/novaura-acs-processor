from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import Group
from .accounts import User

# External CRM models
class Account(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_accounts')
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through='AccountMembership', related_name='accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'account'

    def __str__(self):
        return self.name

class AccountMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    role = models.ForeignKey(Group, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'account_membership'
        unique_together = ('user', 'account')


class CampaignModel(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'campaign_model'

    def __str__(self):
        return self.name

class Campaign(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='campaigns')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    campaign_model = models.ForeignKey(CampaignModel, on_delete=models.PROTECT, null=False, blank=False)
    active = models.BooleanField(default=True)
    start_date = models.DateTimeField(null=True, blank=True, default=None)
    end_date = models.DateTimeField(null=True, blank=True, default=None)
    data_retention_period = models.IntegerField(null=True, blank=True, default=90)
    campaign_from_number = models.CharField(max_length=20, null=True, blank=True)
    default_timezone = models.CharField(
        max_length=50,
        default='US/Eastern',
        help_text='Default timezone for the campaign (e.g., US/Eastern)'
    )
    appointment_deduplication_window = models.IntegerField(
        default=60,  # Default to 1 hour
        help_text='Number of minutes to use as a buffer when scheduling appointments to prevent overlapping',
        null=True,
        blank=True
    )
    is_24_7 = models.BooleanField(
        default=False,
        help_text='If True, the campaign operates 24/7 and individual day settings will be ignored'
    )

    class Meta:
        managed = False
        db_table = 'campaign'

    def __str__(self):
        return self.name

class Funnel(models.Model):
    INBOUND_OUTBOUND_CHOICES = [
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='funnels')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    direction = models.CharField(max_length=10, choices=INBOUND_OUTBOUND_CHOICES)
    active = models.BooleanField(default=True)
    start_date = models.DateTimeField(null=True, blank=True, default=None)
    end_date = models.DateTimeField(null=True, blank=True, default=None)
    data_retention_period = models.IntegerField(null=True, blank=True, default=90)
    pathway_id = models.CharField(max_length=250, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_funnels')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'funnel'

    def __str__(self):
        return self.name

class Step(models.Model):
    STEP_TYPE_CHOICES = [
        ('awareness', 'Awareness'),
        ('interest', 'Interest'),
        ('decision', 'Decision'),
        ('conversion', 'Conversion'),
        ('lost', 'Lost'),
    ]

    funnel = models.ForeignKey(Funnel, on_delete=models.CASCADE, related_name='steps')
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    step_type = models.CharField(
        max_length=20,
        choices=STEP_TYPE_CHOICES,
        default='awareness'
    )

    class Meta:
        managed = False
        db_table = 'step'
        ordering = ['order']
        unique_together = ['funnel', 'order']

    def __str__(self):
        return f"{self.funnel.name} - {self.name}"

    def save(self, *args, **kwargs):
        # If this step is being set as default
        if self.is_default:
            # Remove default status from other steps in the same funnel
            Step.objects.filter(
                funnel=self.funnel,
                is_default=True
            ).exclude(
                pk=self.pk
            ).update(is_default=False)
        
        super().save(*args, **kwargs)

        # If no default step exists for this funnel, make this one default
        if not Step.objects.filter(funnel=self.funnel, is_default=True).exists():
            self.is_default = True
            super().save(*args, **kwargs)

class LeadStatus(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'lead_status'

    def __str__(self):
        return self.name


class Lead(models.Model):
    LEAD_TYPE_CHOICES = (
        ('b2b', 'B2B'),
        ('d2c', 'D2C'),
    )

    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE, related_name='leads')
    funnel = models.ForeignKey('Funnel', on_delete=models.CASCADE, related_name='leads_funnels', null=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    current_step = models.ForeignKey('Step', on_delete=models.SET_NULL, null=True, related_name='leads')
    status = models.ForeignKey(LeadStatus, on_delete=models.SET_NULL, null=True, related_name='leads')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='assigned_leads')
    channel = models.CharField(max_length=100, blank=True, null=True)
    source = models.CharField(max_length=100, blank=True, null=True)
    score = models.FloatField(default=0)
    conversion_probability = models.FloatField(default=0)
    lead_type = models.CharField(max_length=10, choices=LEAD_TYPE_CHOICES, default='d2c')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='updated_leads')
    last_contact_date = models.DateTimeField(null=True, blank=True, default=timezone.now)
    daily_followup_done = models.BooleanField(default=False)
    alternate_followup_done = models.BooleanField(default=False)
    weekly_followup_done = models.BooleanField(default=False)
    is_qualified = models.BooleanField(default=False)
    is_disqualified = models.BooleanField(default=False)
    is_dead = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'lead'
        ordering = ['-last_contact_date']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['campaign_id', 'funnel_id']),
            models.Index(fields=['first_name', 'last_name', 'email']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def update_follow_up_status(self):
        if not self.last_contact_date:
            return

        days_since_contact = (timezone.now() - self.last_contact_date).days

        if days_since_contact <= 7:
            self.daily_followup_done = False
            self.alternate_followup_done = False
            self.weekly_followup_done = False
        elif days_since_contact <= 14:
            self.daily_followup_done = True
            self.alternate_followup_done = False
            self.weekly_followup_done = False
        elif days_since_contact <= 30:
            self.daily_followup_done = True
            self.alternate_followup_done = True
            self.weekly_followup_done = False
        else:
            self.is_dead = True

        self.save()

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # Set default status if not provided for new leads
        if is_new and not self.status_id:
            self.status_id = 1

        # If this is a new lead and no step is set but funnel is set
        if is_new and not self.current_step and self.funnel:
            try:
                self.current_step = Step.objects.get(funnel=self.funnel, is_default=True)
            except Step.DoesNotExist:
                # If no default step, try to get the first step in order
                first_step = Step.objects.filter(funnel=self.funnel).order_by('order').first()
                if first_step:
                    self.current_step = first_step

        if not is_new:
            try:
                # Use select_related to get all related fields in one query
                previous = Lead.objects.select_related(
                    'current_step',
                    'status',
                    'assigned_to'
                ).get(pk=self.pk)
                old_step = previous.current_step
            except Lead.DoesNotExist:
                old_step = None
        else:
            old_step = None

        # Save the instance
        super().save(*args, **kwargs)

        # Handle stage history
        if is_new:
            if self.current_step:
                LeadStageHistory.objects.create(
                    lead=self,
                    step=self.current_step,
                    entered_at=timezone.now()
                )
        else:
            # Only create new history if the step has changed
            if old_step != self.current_step and self.current_step is not None:
                LeadStageHistory.objects.filter(
                    lead=self,
                    exited_at__isnull=True
                ).update(exited_at=timezone.now())

                LeadStageHistory.objects.create(
                    lead=self,
                    step=self.current_step,
                    entered_at=timezone.now()
                )

    def get_subclass(self):
        if self.lead_type == 'b2b':
            try:
                return self.b2blead
            except B2BLead.DoesNotExist:
                return self
        elif self.lead_type == 'd2c':
            try:
                return self.d2clead
            except D2CLead.DoesNotExist:
                return self
        else:
            return self  # Return self if no subclass exists

class LeadStageHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='stage_history')
    step = models.ForeignKey(Step, on_delete=models.SET_NULL, null=True)
    entered_at = models.DateTimeField()
    exited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'lead_stage_history'
        ordering = ['-entered_at'] 


class ScheduledReachOut(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='scheduled_reachouts')
    lead = models.ForeignKey(Lead, null=True, on_delete=models.CASCADE, related_name='scheduled_reachouts')
    scheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scheduled_reachouts'
    )
    scheduled_date = models.DateTimeField()
    reason = models.TextField(blank=True, null=True)
    description = models.CharField(max_length=500, null=True, blank=True)
    notes = models.CharField(max_length=300, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    google_event_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'scheduled_reachout'
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"Scheduled follow-up for {self.lead} on {self.scheduled_date} ({self.get_status_display()})"
