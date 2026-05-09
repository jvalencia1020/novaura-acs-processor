from django.db import models


class HasTargetingMixin(models.Model):
    """
    Mixin that provides targeting configuration functionality.
    
    Models that inherit from this mixin will have a targeting_configuration field
    and a resolved_targeting() method that can be overridden for precedence resolution.
    """
    targeting_configuration = models.ForeignKey(
        "targeting.TargetingConfiguration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)ss",
        help_text="Targeting configuration for this object"
    )
    
    class Meta:
        abstract = True
    
    def resolved_targeting(self):
        """
        Get the resolved targeting configuration.
        Override this method in child classes to implement precedence resolution.
        """
        return self.targeting_configuration
