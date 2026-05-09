from django.db import models


class MediaType(models.Model):
    """Media type model for categories like Connected TV, Audio, Digital Display"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)  # e.g., "Video", "Audio", "Display"
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        ordering = ['category', 'name']
        verbose_name = 'Media Type'
        verbose_name_plural = 'Media Types'

    def __str__(self):
        return f"{self.category} - {self.name}" if self.category else self.name
