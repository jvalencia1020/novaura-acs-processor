import os
import django
import pytest
from django.conf import settings

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'acs_personalization.settings.test')

# Configure Django
django.setup()

@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass 