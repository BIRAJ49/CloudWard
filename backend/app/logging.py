"""JSON logging, correlation context, and reusable secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.security.redaction import redact_untrusted

request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
correlation_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def redact(value: Any) -> Any:
    """Redact secret keys and embedded credentials with bounded recursion."""
    return redact_untrusted(value)


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
