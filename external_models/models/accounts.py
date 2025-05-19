
from django.db import models
from django.contrib.auth.models import AbstractUser
import pytz

class User(AbstractUser):
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    timezone = models.CharField(
        max_length=50,
        choices=[(tz, tz) for tz in pytz.all_timezones],
        default='UTC'
    )

    class Meta:
        managed = False
        db_table = 'accounts_user'

    def __str__(self):
        return self.username