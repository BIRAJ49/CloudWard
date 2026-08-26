"""Single OpenRouter adapter for all CloudWard model traffic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.ai.context import SYSTEM_PROMPT, IncidentContext, render_diagnosis_prompt
from app.ai.provider import LLMProvider, LLMProviderError
from app.ai.schemas import (
    ActionSuggestion,
    AIOperation,
    ChangeCorrelation,
    DiagnosisProposal,
    EvidenceSummary,
    ProviderResult,
    TokenUsage,
)

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class OpenRouterProvider(LLMProvider):
    """OpenAI-compatible structured-output client with bounded retries."""

    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        max_context_tokens: int = 16_000,
        base_url: str = "https://openrouter.ai/api/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key or "")
        self._timeout_seconds = min(max(timeout_seconds, 1.0), 120.0)
        self._max_retries = min(max(max_retries, 0), 3)
        self._max_context_tokens = min(max(max_context_tokens, 512), 131_072)
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def diagnose_incident(self, context: IncidentContext, *, model: str) -> ProviderResult:
        return await self._structured_completion(
            operation=AIOperation.DIAGNOSE_INCIDENT,
            context=context,
            model=model,
            schema=DiagnosisProposal,
        )

    async def summarize_evidence(self, context: IncidentContext, *, model: str) -> ProviderResult:
        return await self._structured_completion(
            operation=AIOperation.SUMMARIZE_EVIDENCE,
            context=context,
            model=model,
            schema=EvidenceSummary,
        )

    async def correlate_change(self, context: IncidentContext, *, model: str) -> ProviderResult:
        return await self._structured_completion(
            operation=AIOperation.CORRELATE_CHANGE,
            context=context,
            model=model,
            schema=ChangeCorrelation,
        )

    async def suggest_actions(self, context: IncidentContext, *, model: str) -> ProviderResult:
        return await self._structured_completion(
            operation=AIOperation.SUGGEST_ACTIONS,
            context=context,
            model=model,
            schema=ActionSuggestion,
        )

    async def _structured_completion(
        self,
        *,
        operation: AIOperation,
        context: IncidentContext,
        model: str,
        schema: type[StructuredOutput],
    ) -> ProviderResult:
        token = self._api_key.get_secret_value()
        if not token:
            raise LLMProviderError("AI_NOT_CONFIGURED", "AI provider is not configured")
        prompt = render_diagnosis_prompt(context)
        estimated_input_tokens = max(1, (len(SYSTEM_PROMPT) + len(prompt) + 3) // 4)
        if estimated_input_tokens + 256 > self._max_context_tokens:
            raise LLMProviderError(
                "AI_CONTEXT_TOO_LARGE",
                "Bounded incident context exceeds the configured provider context limit",
            )
        input_digest = hashlib.sha256(prompt.encode()).hexdigest()
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": min(4_096, self._max_context_tokens - estimated_input_tokens),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": operation.value,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        }
        started = time.monotonic()
        response = await self._post_with_retries(payload, token)
        latency_ms = max(0, round((time.monotonic() - started) * 1000))
        try:
            body: Any = response.json()
            if not isinstance(body, dict):
                raise TypeError("response root is not an object")
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise KeyError("choices")
            first = choices[0]
            if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
                raise TypeError("message is not an object")
            content = first["message"].get("content")
            if not isinstance(content, str):
                raise TypeError("message content is not a string")
            parsed = json.loads(content)
            output = schema.model_validate(parsed)
        except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
            raise LLMProviderError(
                "AI_OUTPUT_INVALID", "Provider returned invalid structured output"
            ) from exc

        usage_raw = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        usage = TokenUsage(
            prompt_tokens=_nonnegative_int(usage_raw.get("prompt_tokens")),
            completion_tokens=_nonnegative_int(usage_raw.get("completion_tokens")),
            total_tokens=_nonnegative_int(usage_raw.get("total_tokens")),
        )
        actual_model = body.get("model") if isinstance(body.get("model"), str) else model
        return ProviderResult(
            operation=operation,
            requested_model=model,
            actual_model=actual_model,
            output=output,
            latency_ms=latency_ms,
            usage=usage,
            input_digest=input_digest,
        )

    async def _post_with_retries(self, payload: dict[str, Any], token: str) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=False,
        )
        try:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://cloudward.local",
                            "X-Title": "CloudWard",
                        },
                        json=payload,
                    )
                    if response.status_code in {408, 409, 429} or response.status_code >= 500:
                        if attempt < self._max_retries:
                            await asyncio.sleep(min(0.1 * (2**attempt), 0.5))
                            continue
                    response.raise_for_status()
                    return response
                except httpx.TimeoutException as exc:
                    if attempt < self._max_retries:
                        continue
                    raise LLMProviderError(
                        "AI_TIMEOUT", "AI provider request timed out", retryable=True
                    ) from exc
                except httpx.HTTPStatusError as exc:
                    retryable = exc.response.status_code in {408, 409, 429} or (
                        exc.response.status_code >= 500
                    )
                    raise LLMProviderError(
                        "AI_PROVIDER_FAILURE",
                        f"AI provider returned HTTP {exc.response.status_code}",
                        retryable=retryable,
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt < self._max_retries:
                        continue
                    raise LLMProviderError(
                        "AI_PROVIDER_FAILURE", "AI provider request failed", retryable=True
                    ) from exc
        finally:
            if owns_client:
                await client.aclose()
        raise LLMProviderError("AI_PROVIDER_FAILURE", "AI provider request failed")


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
