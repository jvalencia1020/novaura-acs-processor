from .base import *

# Use SQLite for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# AWS configuration for testing
import os
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
os.environ.setdefault('AWS_ACCESS_KEY_ID', 'test-access-key')
os.environ.setdefault('AWS_SECRET_ACCESS_KEY', 'test-secret-key')

# Disable password hashing for faster tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Quiet logging during tests (root NullHandler + CRITICAL).
# disable_existing_loggers=False avoids muting loggers that already existed
# when this config is applied (import order varies by environment). A logger
# left disabled breaks unittest.assertLogs on Python 3.12 because assertLogs
# does not set logger.disabled back to False.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'null': {
            'class': 'logging.NullHandler',
        },
    },
    'root': {
        'handlers': ['null'],
        'level': 'CRITICAL',
    },
}

# Use console email backend for testing
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Disable cache during testing
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Use a fast password hasher for testing
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Disable celery during testing
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Send caps: deterministic tests (enable in specific tests with override_settings)
SEND_CAPS_ENFORCEMENT_ENABLED = True
SEND_CAP_CLAIM_STALE_AFTER_SECONDS = 300
SEND_CAP_REFUND_WHEN_NO_THREAD_MESSAGE = False 