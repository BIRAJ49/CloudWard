"""OPA authority for Incident Lab target and duration decisions."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.errors import CloudWardError


class ChaosPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    actor_role: str
    namespace: str
    selector: dict[str, str]
    duration_seconds: int = Field(ge=1, le=600)


class ChaosPolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason: str


class ChaosPolicyClient:
    def __init__(self, base_url: str, decision_path: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.decision_path = decision_path

    async def evaluate(self, policy_input: ChaosPolicyInput) -> ChaosPolicyResult:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=3.0) as client:
                response = await client.post(
                    self.decision_path, json={"input": policy_input.model_dump(mode="json")}
                )
                response.raise_for_status()
                envelope: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CloudWardError(
                "OPA_UNAVAILABLE", "Chaos policy evaluation is unavailable", status_code=503
            ) from exc
        if not isinstance(envelope, dict) or not isinstance(envelope.get("result"), dict):
            raise CloudWardError(
                "INVALID_OPA_RESPONSE", "OPA returned no chaos decision", status_code=502
            )
        try:
            return ChaosPolicyResult.model_validate(envelope["result"])
        except ValueError as exc:
            raise CloudWardError(
                "INVALID_OPA_RESPONSE", "OPA chaos decision was invalid", status_code=502
            ) from exc
