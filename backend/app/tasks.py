"""Celery task publisher; worker implementation remains a separate runtime concern."""

from __future__ import annotations

from celery import Celery

from app.config import Settings

HEALTHCHECK_TASK = "cloudward.tasks.healthcheck"
HEALTHCHECK_QUEUE = "verification"
AI_DIAGNOSIS_TASK = "cloudward.tasks.ai.diagnose"
AI_DIAGNOSIS_QUEUE = "evidence"
DEFAULT_QUEUE = "incident-ingestion"


def create_task_publisher(settings: Settings) -> Celery:
    publisher = Celery("cloudward-api", broker=settings.redis_url, backend=settings.redis_url)
    publisher.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_default_queue=DEFAULT_QUEUE,
        task_routes={
            HEALTHCHECK_TASK: {"queue": HEALTHCHECK_QUEUE},
            "cloudward.tasks.evidence.*": {"queue": "evidence"},
            "cloudward.tasks.ai.*": {"queue": AI_DIAGNOSIS_QUEUE},
            "cloudward.tasks.remediation.*": {"queue": "remediation"},
            "cloudward.tasks.verification.*": {"queue": "verification"},
            "cloudward.tasks.notifications.*": {"queue": "notifications"},
            "cloudward.tasks.alerts.*": {"queue": "incident-ingestion"},
            "cloudward.tasks.scenarios.*": {"queue": "verification"},
            "cloudward.tasks.security.*": {"queue": "incident-ingestion"},
            "cloudward.tasks.finops.*": {"queue": "evidence"},
        },
        task_publish_retry=True,
    )
    return publisher
