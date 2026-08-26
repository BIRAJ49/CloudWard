"""Strict Alertmanager wire schema and command-free internal alert model."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AlertStatus, Environment
from app.logging import redact

MAX_LABELS = 64
MAX_ANNOTATIONS = 32
MAX_VALUE_LENGTH = 2048
STABLE_LABELS = ("alertname", "service", "environment", "namespace", "cluster", "deployment")


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = Field(default="", max_length=4096)
    fingerprint: str | None = Field(default=None, max_length=256)

    @field_validator("labels")
    @classmethod
    def bounded_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or len(value) > MAX_LABELS:
            raise ValueError("alert labels must contain between 1 and 64 entries")
        if any(len(key) > 128 or len(item) > MAX_VALUE_LENGTH for key, item in value.items()):
            raise ValueError("alert label exceeds maximum size")
        return value

    @field_validator("annotations")
    @classmethod
    def bounded_annotations(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_ANNOTATIONS:
            raise ValueError("too many alert annotations")
        if any(len(key) > 128 or len(item) > MAX_VALUE_LENGTH for key, item in value.items()):
            raise ValueError("alert annotation exceeds maximum size")
        return value


class AlertmanagerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["4"]
    groupKey: str = Field(max_length=2048)
    truncatedAlerts: int = Field(default=0, ge=0)
    status: Literal["firing", "resolved"]
    receiver: str = Field(max_length=255)
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = Field(default="", max_length=4096)
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=100)


class NormalizedAlert(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["prometheus"] = "prometheus"
    alert_name: str
    status: AlertStatus
    severity: str
    service: str
    environment: Environment
    namespace: str | None
    starts_at: datetime
    ends_at: datetime | None
    labels: dict[str, str]
    annotations: dict[str, str]
    fingerprint: str
    payload_digest: str

    @classmethod
    def from_alertmanager(cls, alert: AlertmanagerAlert) -> NormalizedAlert:
        labels = dict(alert.labels)
        alert_name = labels.get("alertname", "UnknownPrometheusAlert")[:128]
        service = (labels.get("service") or labels.get("job") or "unknown")[:255]
        raw_environment = labels.get("environment", "staging").lower()
        environment = (
            Environment(raw_environment)
            if raw_environment in {item.value for item in Environment}
            else Environment.STAGING
        )
        namespace = labels.get("namespace")
        stable = "\x1f".join(labels.get(key, "") for key in STABLE_LABELS)
        fingerprint = hashlib.sha256(stable.encode()).hexdigest()
        safe_annotations = redact(alert.annotations)
        digest_payload = {
            "status": alert.status,
            "starts_at": alert.startsAt.isoformat(),
            "ends_at": alert.endsAt.isoformat() if alert.endsAt else None,
            "labels": labels,
            "annotations": safe_annotations,
        }
        payload_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(
            alert_name=alert_name,
            status=AlertStatus(alert.status),
            severity=labels.get("severity", "warning")[:16],
            service=service,
            environment=environment,
            namespace=namespace[:253] if namespace else None,
            starts_at=alert.startsAt,
            ends_at=alert.endsAt,
            labels=labels,
            annotations=safe_annotations,
            fingerprint=fingerprint,
            payload_digest=payload_digest,
        )
