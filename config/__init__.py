"""Mosaiq project package.

Import the Celery app here so that every entry point (gunicorn/WSGI,
manage.py, celery worker) shares the same app instance, configured from
Django settings. Without this import, shared_task in the web process
falls back to Celery's default broker (amqp://localhost:5672) and task
delivery fails with ConnectionRefused.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
