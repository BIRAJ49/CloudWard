"""Strict, fail-closed client for OPA's remediation decision API."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.remediation.actions import ActionType
from app.risk.engine import RiskFactors

logger = logging.getLogger(__name__)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool = False
    approval_id: str | None = None
    approved_by: str | None = None


class TargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str
    pod_name: str
    labels: dict[str, str]
    controller_managed: bool
    target_pods: int = Field(ge=0, le=1000)


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str
    action: ActionType
    risk_score: int = Field(ge=0, le=100)
    risk_factors: RiskFactors
    confidence: float = Field(ge=0, le=1)
    blast_radius: int = Field(ge=0)
    reversible: bool
    service_criticality: str
    target: TargetInput
    approval: ApprovalInput = Field(default_factory=ApprovalInput)

    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PolicyResult(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    allowed: bool
    requires_approval: bool
    reason: str = Field(min_length=1, max_length=2000)
    decision_id: str | None = None
    error_code: str | None = None

    @classmethod
    def denied(cls, reason: str, error_code: str) -> PolicyResult:
        return cls(
            allowed=False,
            requires_approval=False,
            reason=reason,
            error_code=error_code,
        )


class OPAClient:
    def __init__(
        self,
        base_url: str,
        decision_path: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}{decision_path}"
        self._client = client
        self.timeout = timeout

    async def evaluate(self, policy_input: PolicyInput) -> PolicyResult:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                self.url,
                json={"input": policy_input.model_dump(mode="json")},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload: Any = response.json()
            if not isinstance(payload, dict) or "result" not in payload:
                return PolicyResult.denied("OPA returned no decision", "OPA_UNDEFINED_DECISION")
            try:
                return PolicyResult.model_validate(payload["result"])
            except ValidationError:
                return PolicyResult.denied(
                    "OPA returned an invalid decision", "OPA_INVALID_RESPONSE"
                )
        except (httpx.HTTPError, ValueError) as exc:
            logger.error(
                "opa_evaluation_failed", extra={"fields": {"error_type": type(exc).__name__}}
            )
            return PolicyResult.denied(
                "Policy engine unavailable; action denied", "OPA_UNAVAILABLE"
            )
        finally:
            if owns_client:
                await client.aclose()
