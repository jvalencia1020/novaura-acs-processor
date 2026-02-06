"""
Seed the ACS template variable category "link" and variable "short_link" for SMS short-link placeholders.
Use placeholder {{link.short_link}} in templates when the rule has a short link assigned.
Idempotent: safe to run multiple times (uses get_or_create).
"""
from django.core.management.base import BaseCommand
from external_models.models.messages import TemplateVariableCategory, TemplateVariable


class Command(BaseCommand):
    help = 'Seed link template variable category and short_link variable for {{link.short_link}} placeholder.'

    def handle(self, *args, **options):
        category, created = TemplateVariableCategory.objects.get_or_create(
            name='link',
            defaults={
                'description': 'Short link / tracking URL for SMS',
                'model_name': 'link_tracking.Link',
                'is_active': True,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created TemplateVariableCategory: link'))
        else:
            self.stdout.write('TemplateVariableCategory "link" already exists.')

        variable, created = TemplateVariable.objects.get_or_create(
            category=category,
            name='short_link',
            defaults={
                'field_name': 'short_link',
                'description': 'Campaign short link with message tracking (only available when the rule has a short link assigned)',
                'is_active': True,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created TemplateVariable: {variable.get_placeholder()}'))
        else:
            self.stdout.write(f'TemplateVariable "short_link" already exists. Placeholder: {variable.get_placeholder()}')

        self.stdout.write(self.style.SUCCESS('Done. Use {{link.short_link}} in SMS templates when the rule has a short link.'))
