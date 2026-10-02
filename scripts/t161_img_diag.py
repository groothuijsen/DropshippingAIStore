"""Diagnose image provider failures on the VPS."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

print("OPENAI_API_KEY set:", bool(os.environ.get("OPENAI_API_KEY")))
print("GOOGLE_APPLICATION_CREDENTIALS:", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
print("cred file exists:", bool(cred) and os.path.exists(cred))

from apps.generator.images_step import _generate_with_providers  # noqa: E402

result = _generate_with_providers("A red ball on a white table, studio photo", "1024x1024")
print("success:", result.success)
print("error:", str(result.error)[:400])
