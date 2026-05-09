from django.db import models


class TargetingConfiguration(models.Model):
    """Unmanaged stub; real table and columns are owned by the targeting service."""

    class Meta:
        managed = False
        db_table = 'targeting_targetingconfiguration'
