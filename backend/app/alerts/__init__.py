"""Authenticated Alertmanager ingestion and deterministic deduplication."""

from app.alerts.schemas import AlertmanagerPayload, NormalizedAlert
from app.alerts.service import AlertIngestionResult, ingest_alerts

__all__ = ["AlertIngestionResult", "AlertmanagerPayload", "NormalizedAlert", "ingest_alerts"]
