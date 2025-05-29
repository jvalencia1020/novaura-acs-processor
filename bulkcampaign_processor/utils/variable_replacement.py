from django.utils import timezone
from external_models.models.messages import TemplateVariable

def replace_variables(content, context):
    """
    Replaces variables in content with values from the context.
    
    Args:
        content (str): The content containing variables to be replaced
        context (dict): Dictionary containing values for variables.
                       Should be structured as: {'lead': {...}, 'campaign': {...}, etc.}
    
    Returns:
        str: Content with variables replaced with their values
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
                # Handle system variables
                if var.name == 'current_date':
                    value = timezone.now().strftime('%Y-%m-%d')
                elif var.name == 'current_time':
                    value = timezone.now().strftime('%I:%M %p')
            else:
                # Get value from context using the model and field information
                model_data = context.get(category, {})
                if isinstance(model_data, dict):
                    value = model_data.get(var.name, '')
                else:
                    # If model_data is an actual model instance
                    value = getattr(model_data, var.field_name, '')
            
            content = content.replace(placeholder, str(value))
    
    return content 