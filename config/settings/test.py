"""Django settings — test."""

from .base import *  # noqa: F401, F403
from .base import BASE_DIR, env  # noqa: F401

DEBUG = False

ALLOWED_HOSTS = ["testserver"]

# Test database — Postgres in CI/Docker, SQLite fallback for local development
# CI sets DATABASE_URL to Postgres; locally falls back to SQLite for convenience.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://mosaiq:mosaiq@localhost:5432/mosaiq_test",
    )
}
try:
    import psycopg2  # noqa: F401

    conn = psycopg2.connect(dbname="mosaiq_test", user="mosaiq", password="mosaiq", host="localhost")
    conn.close()
except Exception:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test.db",
        }
    }

# Celery eager — tasks run synchronously in-process
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# No network in tests (pytest-socket enforces this)
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Faster password hashing
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
