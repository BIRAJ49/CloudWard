"""Celery application and queue boundaries for CloudWard workflows."""

from __future__ import annotations

import os

from celery import Celery
from kombu import Exchange, Queue

QUEUE_NAMES = (
    "incident-ingestion",
    "evidence",
    "remediation",
    "verification",
    "notifications",
)

broker_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
exchange = Exchange("cloudward", type="direct", durable=True)

celery_app = Celery(
    "cloudward-worker",
    broker=broker_url,
    backend=result_backend,
    include=(
        "worker.tasks.health",
        "worker.tasks.reliability",
        "worker.tasks.security",
        "worker.tasks.finops",
        "worker.tasks.notifications",
        "worker.tasks.ai",
    ),
)

celery_app.conf.update(
    accept_content=("json",),
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_accept_content=("json",),
    result_expires=3600,
    result_serializer="json",
    task_acks_late=True,
    task_default_exchange=exchange.name,
    task_default_exchange_type=exchange.type,
    task_default_queue="incident-ingestion",
    task_default_routing_key="incident-ingestion",
    task_queues=tuple(
        Queue(name, exchange=exchange, routing_key=name, durable=True)
        for name in QUEUE_NAMES
    ),
    task_reject_on_worker_lost=True,
    task_routes={
        "cloudward.tasks.healthcheck": {
            "queue": "verification",
            "routing_key": "verification",
        },
        "cloudward.tasks.alerts.process": {
            "queue": "incident-ingestion",
            "routing_key": "incident-ingestion",
        },
        "cloudward.tasks.scenarios.monitor": {
            "queue": "verification",
            "routing_key": "verification",
        },
        "cloudward.tasks.security.process": {
            "queue": "incident-ingestion",
            "routing_key": "incident-ingestion",
        },
        "cloudward.tasks.finops.scenario": {
            "queue": "evidence",
            "routing_key": "evidence",
        },
        "cloudward.tasks.notifications.deliver": {
            "queue": "notifications",
            "routing_key": "notifications",
        },
        "cloudward.tasks.ai.diagnose": {
            "queue": "evidence",
            "routing_key": "evidence",
        },
    },
    task_serializer="json",
    task_track_started=True,
    timezone="UTC",
    worker_prefetch_multiplier=1,
)
