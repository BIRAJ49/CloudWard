"""Shared bounded redaction for logs, stored evidence, and model inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
MAX_REDACTION_DEPTH = 16

SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "cookie",
        "credential",
        "database_url",
        "private_key",
        "password",
        "secret",
        "session",
        "token",
        "webhook_url",
    }
)

STRING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{8,}"),
    re.compile(r"(?i)\bgithub_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"(?i)\bsk-(?:or-v1-)?[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{12,20}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"(?is)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^\s]+"),
    re.compile(r"(?i)\b(?:https?|amqps?|kafka)://[^\s/@:]+:[^\s/@]+@[^\s]+"),
    re.compile(r"(?i)\b(?:password|passwd|pwd|api[_-]?key|secret|token)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\b(?:cookie|set-cookie)\s*:\s*[^\r\n]+"),
)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in STRING_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)(authorization"):
            redacted = pattern.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact_untrusted(value: Any, *, _depth: int = 0) -> Any:
    """Return a redacted copy. Input is never mutated."""

    if _depth >= MAX_REDACTION_DEPTH:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED
            if _sensitive_key(str(key))
            else redact_untrusted(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_untrusted(item, _depth=_depth + 1) for item in value]
    return value
