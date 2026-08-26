"""Stable, explainable incident fingerprint construction."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_STABLE_LABELS = frozenset(
    {
        "app",
        "app.kubernetes.io/name",
        "app.kubernetes.io/component",
        "cloudward.io/scenario",
        "team",
    }
)


def select_stable_labels(value: object) -> dict[str, str]:
    """Drop high-cardinality and non-text labels before fingerprint validation."""

    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item[:255]
        for key, item in value.items()
        if key in DEFAULT_STABLE_LABELS and isinstance(item, str)
    }


def normalize_component(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = re.sub(r"\s+", "-", value.strip().lower())
    normalized = re.sub(r"[^a-z0-9._/-]", "", normalized)
    return normalized[:255] or "unknown"


class FingerprintInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str = Field(min_length=1, max_length=255)
    incident_type: str = Field(min_length=1, max_length=128)
    alert_name: str = Field(min_length=1, max_length=255)
    namespace: str | None = Field(default=None, max_length=253)
    root_cause_category: str | None = Field(default=None, max_length=128)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("labels")
    @classmethod
    def bound_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 50:
            raise ValueError("fingerprint labels exceed the collection bound")
        if any(len(str(key)) > 255 or len(str(item)) > 255 for key, item in value.items()):
            raise ValueError("fingerprint labels exceed the field bound")
        return value

    def canonical(
        self, allowed_labels: frozenset[str] = DEFAULT_STABLE_LABELS
    ) -> dict[str, object]:
        stable_labels = {
            key: normalize_component(value)
            for key, value in sorted(self.labels.items())
            if key in allowed_labels
        }
        return {
            "service": normalize_component(self.service),
            "incident_type": normalize_component(self.incident_type),
            "alert_name": normalize_component(self.alert_name),
            "namespace": normalize_component(self.namespace),
            "root_cause_category": normalize_component(self.root_cause_category),
            "labels": stable_labels,
        }


def incident_fingerprint(
    value: FingerprintInput,
    *,
    allowed_labels: frozenset[str] = DEFAULT_STABLE_LABELS,
) -> str:
    canonical = json.dumps(value.canonical(allowed_labels), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
