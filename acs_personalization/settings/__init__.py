"""
Default project settings when DJANGO_SETTINGS_MODULE is ``acs_personalization.settings``.

Production and some workers override this (e.g. ``acs_personalization.settings.prod``).
For isolated tests (SQLite, etc.), use ``--settings=acs_personalization.settings.test``.
"""

from .dev import *
