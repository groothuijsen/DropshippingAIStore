"""Tests for the Celery app wiring (config/__init__.py)."""

from django.conf import settings


class TestCeleryWiring:
    """The web process must load the Celery app with Django settings.

    Without `from .celery import app as celery_app` in config/__init__.py,
    shared_task falls back to Celery's default broker (amqp://localhost)
    in the gunicorn process — tasks are then undeliverable (seen in the
    dev store: run_on_install.delay() -> ConnectionRefused on port 5672).
    """

    def test_celery_app_exposed_on_package(self):
        import config

        assert hasattr(config, "celery_app"), (
            "config/__init__.py must import the Celery app: "
            "from .celery import app as celery_app"
        )

    def test_celery_app_broker_matches_settings(self):
        from config.celery import app

        assert app.conf.broker_url == settings.CELERY_BROKER_URL

    def test_task_registered_on_package_app(self):
        import config
        from apps.core.tasks import run_on_install

        assert run_on_install.name in config.celery_app.tasks
