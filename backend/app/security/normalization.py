"""Canonical fingerprints and defense-in-depth redaction for security events."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC
from typing import Any

from app.logging import redact
from app.security.schemas import TetragonSecurityEvent

SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(?:password|passwd|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://[^\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def redact_security_value(value: Any) -> Any:
    redacted = redact(value)
    if isinstance(redacted, str):
        result = redacted
        for pattern in SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result
    if isinstance(redacted, dict):
        return {str(key): redact_security_value(item) for key, item in redacted.items()}
    if isinstance(redacted, list):
        return [redact_security_value(item) for item in redacted]
    return redacted


def normalized_payload(event: TetragonSecurityEvent) -> dict[str, Any]:
    """Return only stable allowlisted fields; process args and environment never enter it."""

    payload: dict[str, Any] = {
        "process": event.process.model_dump(mode="json") if event.process else None,
        "network": event.network.model_dump(mode="json") if event.network else None,
        "workload_labels": event.workload_labels,
        "secrets_or_data_exposure": event.secrets_or_data_exposure,
    }
    redacted = redact_security_value(payload)
    return redacted if isinstance(redacted, dict) else {}


def event_fingerprint(event: TetragonSecurityEvent, *, window_seconds: int) -> str:
    occurred = event.timestamp.astimezone(UTC)
    bucket = int(occurred.timestamp()) // window_seconds
    canonical = {
        "source": event.source,
        "event_type": event.event_type.value,
        "namespace": event.namespace,
        "pod": event.pod,
        "container": event.container,
        "policy": event.policy,
        "process": event.process.model_dump(mode="json") if event.process else None,
        "network": event.network.model_dump(mode="json") if event.network else None,
        "bucket": bucket,
    }
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()
