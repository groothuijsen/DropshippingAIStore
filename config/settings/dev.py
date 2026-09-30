"""Django settings — development."""

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Dev email console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
