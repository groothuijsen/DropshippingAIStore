"""Django settings — base (shared by dev, test, prod)."""

from pathlib import Path

import environ

env = environ.Env(
    DJANGO_SETTINGS_MODULE=(str, "config.settings.dev"),
    DJANGO_ALLOWED_HOSTS=(list[str], ["localhost"]),
    SHOPIFY_API_VERSION=(str, "2026-07"),
    SHOPIFY_BILLING_TEST=(bool, True),
    SHOPIFY_DISCOUNT_FUNCTION_HANDLE=(str, "bundle-discount"),
    LLM_MODEL_RESEARCH=(str, "claude-sonnet-5-5"),
    LLM_MODEL_COPY=(str, "claude-sonnet-5-5"),
    LLM_MODEL_CHECK=(str, "claude-haiku-4-5-20251001"),
    GOOGLE_CLOUD_LOCATION=(str, "eu"),
    IMAGE_MODEL_PRIMARY=(str, "gemini-3.1-flash-image"),
    IMAGE_MODEL_ESCALATE=(str, "gemini-3-pro-image"),
    IMAGE_MODEL_FALLBACK=(str, "gpt-image-2.5-sunburst"),
    AI_COST_ALERT_USD_PER_STORE=(float, 1.00),
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

environ.Env.read_env(BASE_DIR / ".env", override=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_celery_beat",
    # Local apps
    "apps.core",
    "apps.billing",
    "apps.webhooks",
    "apps.sources",
    "apps.generator",
    "apps.ai",
    "apps.themes",
    "apps.offers",
    "apps.compliance",
    "apps.templates_lib",
    "apps.analytics",
    "apps.support",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database — overridden in test.py and prod.py
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://mosaiq:mosaiq@db:5432/mosaiq"),
}

# Cache + broker
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_TASK_ROUTES = {
    "apps.ai.tasks.*": {"queue": "ai"},
    "apps.generator.tasks.run_*": {"queue": "shopify"},
    "apps.core.tasks.*": {"queue": "default"},
    "apps.billing.tasks.*": {"queue": "default"},
    "apps.webhooks.tasks.*": {"queue": "default"},
    "apps.compliance.tasks.*": {"queue": "low"},
}

# Auth
AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []

# i18n
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("nl", "Dutch"),
    ("en", "English"),
    ("de", "German"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

# Static
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Shopify
SHOPIFY_API_KEY = env("SHOPIFY_API_KEY", default="")
SHOPIFY_API_SECRET = env("SHOPIFY_API_SECRET", default="")
SHOPIFY_API_VERSION = env("SHOPIFY_API_VERSION")
SHOPIFY_BILLING_TEST = env("SHOPIFY_BILLING_TEST")
SHOPIFY_DISCOUNT_FUNCTION_HANDLE = env("SHOPIFY_DISCOUNT_FUNCTION_HANDLE")
APP_URL = env("APP_URL", default="https://localhost")

# AI providers
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
LLM_MODEL_RESEARCH = env("LLM_MODEL_RESEARCH")
LLM_MODEL_COPY = env("LLM_MODEL_COPY")
LLM_MODEL_CHECK = env("LLM_MODEL_CHECK")
GOOGLE_CLOUD_PROJECT = env("GOOGLE_CLOUD_PROJECT", default="")
GOOGLE_CLOUD_LOCATION = env("GOOGLE_CLOUD_LOCATION")
GOOGLE_APPLICATION_CREDENTIALS = env("GOOGLE_APPLICATION_CREDENTIALS", default="")
IMAGE_MODEL_PRIMARY = env("IMAGE_MODEL_PRIMARY")
IMAGE_MODEL_ESCALATE = env("IMAGE_MODEL_ESCALATE")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
IMAGE_MODEL_FALLBACK = env("IMAGE_MODEL_FALLBACK")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", default="")

# C2PA
C2PA_SIGNING_CERT_PATH = env("C2PA_SIGNING_CERT_PATH", default="")
C2PA_SIGNING_KEY_PATH = env("C2PA_SIGNING_KEY_PATH", default="")

# Fernet encryption
FERNET_KEYS = env("FERNET_KEYS", default="").split(",") if env("FERNET_KEYS", default="") else []

# Email
EMAIL_URL = env.email_url("EMAIL_URL", default="smtp://localhost:1025")

# Sentry / GlitchTip
SENTRY_DSN = env("SENTRY_DSN", default="")

# AI cost alert
AI_COST_ALERT_USD_PER_STORE = env("AI_COST_ALERT_USD_PER_STORE")

# Security — overridden in prod.py
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
