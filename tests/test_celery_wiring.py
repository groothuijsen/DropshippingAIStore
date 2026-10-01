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


class TestQueueRouting:
    """Every task must land on a queue the worker actually consumes.

    The worker starts with -Q default,ai,shopify,low. Celery's built-in
    default queue is named "celery" — if task_default_queue is left
    unset, unrouted tasks (e.g. core.tasks.run_on_install, whose route
    pattern apps.core.tasks.* does not match its explicit name) go to
    the "celery" queue and are never executed (seen in the dev store:
    run_on_install stuck PENDING, 3 messages orphaned in queue celery).
    """

    WORKER_QUEUES = {"default", "ai", "shopify", "low"}

    def test_default_queue_is_consumed_by_worker(self, settings):
        assert settings.CELERY_TASK_DEFAULT_QUEUE == "default"

    def test_every_registered_task_routes_to_worker_queue(self):
        from config.celery import app

        app.loader.import_default_modules()
        router = app.amqp.router
        for name in app.tasks:
            if name.startswith("celery."):
                continue  # built-ins (ping, revoke, ...) are never routed
            queue = router.route({}, name).get("queue", "default")
            queue_name = getattr(queue, "name", queue)
            assert queue_name in self.WORKER_QUEUES, (
                f"Task {name} routes to queue {queue_name!r}, "
                f"which the worker does not consume"
            )
