"""Django settings — development."""

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += [  # noqa: F405
    "django.contrib.admin",
]

# Dev email console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Celery eager mode for local dev (optional, uncomment for faster local testing)
# CELERY_TASK_ALWAYS_EAGER = True
# CELERY_TASK_EAGER_PROPAGATES = True
