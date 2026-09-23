"""Compatibility exports for the shared secret-redaction boundary."""

from app.security.redaction import redact_text, redact_untrusted

__all__ = ["redact_text", "redact_untrusted"]
