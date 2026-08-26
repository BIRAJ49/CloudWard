"""Registered CloudWard Celery tasks."""

from worker.tasks.health import healthcheck

__all__ = ["healthcheck"]
