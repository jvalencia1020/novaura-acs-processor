from django.db import models
from django.conf import settings
from django.utils import timezone
from .external_references import Account, Campaign, Lead
import re


class TemplateVariableCategory(models.Model):
    """Categories for template variables (e.g., Lead, Campaign, etc.)"""
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    model_name = models.CharField(max_length=100, help_text="Django model name this category is associated with")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'acs_templatevariablecategory'
        verbose_name_plural = "Template Variable Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class TemplateVariable(models.Model):
    """Individual variables that can be used in message templates"""
    category = models.ForeignKey(TemplateVariableCategory, on_delete=models.CASCADE, related_name='variables')
    name = models.CharField(max_length=100, help_text="Variable name as it appears in templates (e.g., first_name)")
    field_name = models.CharField(max_length=100, help_text="Actual field name in the model")
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'acs_templatevariable'
        unique_together = ['category', 'name']
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.category.name}.{self.name}"

    def get_placeholder(self):
        """Returns the variable placeholder format"""
        return f"{{{{{self.category.name}.{self.name}}}}}"


class MessageTemplate(models.Model):
    CHANNEL_CHOICES = [
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('voice', 'Voice'),
        ('chat', 'Chat'),
    ]

    CATEGORY_CHOICES = [
        ('awareness', 'Awareness'),
        ('interest', 'Interest'),
        ('decision', 'Decision'),
        ('conversion', 'Conversion'),
        ('lost', 'Lost'),
    ]

    account = models.ForeignKey(
        Account, 
        on_delete=models.CASCADE, 
        related_name='message_templates',
        null=True, 
        blank=True  # Null means it's a system-wide template
    )
    name = models.CharField(max_length=255)
    content = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    is_system_template = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'acs_messagetemplate'
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'account'],
                condition=models.Q(account__isnull=False),
                name='unique_name_per_account'
            ),
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(account__isnull=True),
                name='unique_name_for_system_templates'
            )
        ]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['channel']),
            models.Index(fields=['category']),
            models.Index(fields=['is_system_template']),
        ]

    def __str__(self):
        if self.account:
            return f"{self.name} ({self.account.name})"
        return f"{self.name} (System Template)"

    @classmethod
    def get_available_variables(cls):
        """Returns a dictionary of all available variables that can be used in templates."""
        variables = {}
        for category in TemplateVariableCategory.objects.filter(is_active=True):
            variables[category.name] = {
                var.name: {
                    'field': var.field_name,
                    'model': category.model_name,
                    'description': var.description
                }
                for var in category.variables.filter(is_active=True)
            }
        return variables

    def validate_variables(self):
        """Validates that all variables in the template content are valid."""
        # Find all variables in the content using regex
        variable_pattern = r'{{([^}]+)}}'
        variables = re.findall(variable_pattern, self.content)
        
        # Get all valid variables with their categories
        valid_variables = {}
        for category in TemplateVariableCategory.objects.filter(is_active=True):
            valid_variables[category.name] = {
                var.name: var
                for var in category.variables.filter(is_active=True)
            }
        
        # Check each variable
        invalid_vars = []
        for var in variables:
            # Split the variable into category and name
            parts = var.split('.')
            if len(parts) != 2:
                invalid_vars.append(var)
                continue
                
            category_name, var_name = parts
            
            # Check if category exists and variable is valid in that category
            if (category_name not in valid_variables or 
                var_name not in valid_variables[category_name]):
                invalid_vars.append(var)
        
        if invalid_vars:
            raise ValueError(f"Invalid variables found in template: {', '.join(invalid_vars)}")
        
        return True

    def replace_variables(self, context):
        """
        Replaces variables in the template content with values from the context.
        
        Args:
            context (dict): Dictionary containing values for variables.
                           Should be structured as: {'lead': {...}, 'campaign': {...}, etc.}
        
        Returns:
            str: Content with variables replaced with their values
        """
        content = self.content
        
        # Get all active variables
        variables = TemplateVariable.objects.filter(
            category__is_active=True,
            is_active=True
        ).select_related('category')
        
        # Replace each variable
        for var in variables:
            placeholder = var.get_placeholder()
            if placeholder in content:
                category = var.category.name
                if category == 'system':
                    # Handle system variables
                    if var.name == 'current_date':
                        value = timezone.now().strftime('%Y-%m-%d')
                    elif var.name == 'current_time':
                        value = timezone.now().strftime('%I:%M %p')
                else:
                    # Get value from context using the model and field information.
                    # Normalize 'Link' -> 'link' so context from callers using capital L still works.
                    model_data = context.get(category) or (
                        context.get('Link') if category == 'link' else context.get('link') if category == 'Link' else None
                    ) or {}
                    if isinstance(model_data, dict):
                        value = model_data.get(var.name, '')
                    else:
                        # If model_data is an actual model instance
                        value = getattr(model_data, var.field_name, '')
                
                content = content.replace(placeholder, str(value))
        
        return content

    def clean(self):
        """Validates the template before saving."""
        super().clean()
        self.validate_variables()

