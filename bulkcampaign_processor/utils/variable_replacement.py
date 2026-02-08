from django.utils import timezone
from external_models.models.messages import TemplateVariable


def _get_context_value(context, category, name, field_name):
    """Get value for a category/name from context, trying both 'link' and 'Link' for link category."""
    model_data = context.get(category)
    if model_data is None and category and category.lower() == 'link':
        model_data = context.get('Link') if category == 'link' else context.get('link')
    if model_data is None:
        model_data = {}
    if isinstance(model_data, dict):
        return model_data.get(name, '')
    return getattr(model_data, field_name, '')


def replace_variables(content, context):
    """
    Replaces variables in content with values from the context.
    Supports {{link.short_link}} / {{Link.short_link}} for drip/reminder messages;
    works with or without TemplateVariable seed (fallback replaces from context).
    """
    if not content:
        return ""

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
                if var.name == 'current_date':
                    value = timezone.now().strftime('%Y-%m-%d')
                elif var.name == 'current_time':
                    value = timezone.now().strftime('%I:%M %p')
                else:
                    value = ''
            else:
                value = _get_context_value(context, category, var.name, var.field_name)
            content = content.replace(placeholder, str(value))

    # Fallback: resolve {{link.short_link}} / {{Link.short_link}} from context even if not in TemplateVariable
    link_placeholders = [
        ('{{link.short_link}}', 'link'),
        ('{{Link.short_link}}', 'Link'),
    ]
    for placeholder, key in link_placeholders:
        if placeholder in content:
            link_data = context.get(key) or context.get('Link' if key == 'link' else 'link')
            if isinstance(link_data, dict):
                value = link_data.get('short_link', '')
            else:
                value = getattr(link_data, 'short_link', '') if link_data else ''
            content = content.replace(placeholder, str(value))

    return content 