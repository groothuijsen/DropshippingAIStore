"""Support app — contact form, status page link, FAQ.

See docs/09-ui-screens.md (GET /app/support/).
Contact form sends email to support; status page link; FAQ section.
"""

from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.support"
    verbose_name = "Support"
