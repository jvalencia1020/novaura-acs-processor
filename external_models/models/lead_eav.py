"""
Direct copies of novaura_crm_backend CRM EAV models with Meta.managed = False only.

Imports use ``external_models`` paths. Table names match CRM: ``lead_field_definition``,
``lead_field_value``, ``campaign_lead_field_mapping``, ``intake_section``, ``intake_field``,
``lead_intake_value``.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.db import models

from .external_references import Account, Campaign, CampaignModel, Lead


class LeadFieldDefinition(models.Model):
    FIELD_TYPE_CHOICES = (
        ('text', 'Text'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('dropdown', 'Dropdown'),
    )

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='lead_field_definitions')
    campaign_model = models.ForeignKey(CampaignModel, on_delete=models.CASCADE, related_name='lead_field_definitions')
    name = models.CharField(max_length=100)
    api_name = models.CharField(max_length=100)
    field_type = models.CharField(max_length=50, choices=FIELD_TYPE_CHOICES)
    required = models.BooleanField(default=False)
    dropdown_options = models.JSONField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'lead_field_definition'
        unique_together = ('campaign_model', 'api_name', 'account')
        ordering = ['order']

    def clean(self):
        if self.field_type == 'dropdown' and not self.dropdown_options:
            raise ValidationError('Dropdown fields must have options specified.')

    def __str__(self) -> str:
        return f'{self.name} ({self.api_name})'

    def save(self, *args, **kwargs):
        if not self.api_name:
            self.api_name = re.sub(r'[^a-z0-9_]', '', self.name.lower().replace(' ', '_'))
        if not self.id:
            self.order = LeadFieldDefinition.objects.filter(campaign_model=self.campaign_model).count()
        super().save(*args, **kwargs)


class LeadFieldValue(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='field_values')
    field_definition = models.ForeignKey(LeadFieldDefinition, on_delete=models.CASCADE)
    value = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'lead_field_value'
        indexes = [
            models.Index(fields=['lead', 'field_definition'], name='lead_field_lookup_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.lead} - {self.field_definition.name}: {self.value}'


class CampaignLeadFieldMapping(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    lead_field_definition = models.ForeignKey(LeadFieldDefinition, on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'campaign_lead_field_mapping'
        unique_together = ('campaign', 'lead_field_definition')

    def __str__(self) -> str:
        return f'{self.campaign.name} - {self.lead_field_definition.name}'


class IntakeSection(models.Model):
    name = models.CharField(max_length=255)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='intake_sections')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'intake_section'
        ordering = ['order']

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.id:
            self.order = IntakeSection.objects.filter(campaign=self.campaign).count()
        super().save(*args, **kwargs)


class IntakeField(models.Model):
    FIELD_TYPES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('dropdown', 'Dropdown'),
    ]

    intake_section = models.ForeignKey(IntakeSection, on_delete=models.CASCADE, related_name='intake_fields')
    name = models.CharField(max_length=100)
    intake_question = models.CharField(max_length=300, null=True)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    api_name = models.CharField(max_length=100)
    required = models.BooleanField(default=False)
    dropdown_options = models.JSONField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'intake_field'
        ordering = ['order']

    def clean(self):
        if self.field_type == 'dropdown' and not self.dropdown_options:
            raise ValidationError('Dropdown fields must have options specified.')
        if not re.match(r'^[a-z0-9_]+$', self.api_name):
            raise ValidationError(
                'API Name must contain only lowercase letters, numbers, and underscores.'
            )

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.id:
            self.order = IntakeField.objects.filter(intake_section=self.intake_section).count()
        super().save(*args, **kwargs)


class LeadIntakeValue(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='intake_values')
    intake_field = models.ForeignKey(
        IntakeField,
        on_delete=models.CASCADE,
        related_name='lead_values',
    )
    value = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'lead_intake_value'
        unique_together = ('lead', 'intake_field')

    def __str__(self) -> str:
        return f'{self.lead} - {self.intake_field} - {self.value}'
