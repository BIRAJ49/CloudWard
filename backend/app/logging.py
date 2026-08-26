"""JSON logging, correlation context, and reusable secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
correlation_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "session",
        "api_key",
    }
)


def _is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(sensitive in normalized for sensitive in SENSITIVE_KEYS)


def redact(value: Any) -> Any:
    """Recursively redact values associated with secret-like keys."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Stable machine-readable formatter for application and access logs."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "module": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
            "correlation_id": correlation_id_context.get(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, Mapping):
            data.update(redact(fields))
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(data), default=str, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service=settings.app_name, environment=settings.app_env))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
