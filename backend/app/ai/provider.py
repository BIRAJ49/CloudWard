"""Provider-neutral LLM contract and controlled provider failures."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.ai.context import IncidentContext
from app.ai.schemas import ProviderResult


class LLMProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class LLMProvider(ABC):
    """Business modules depend on this interface, never on OpenRouter HTTP details."""

    name: str

    @abstractmethod
    async def diagnose_incident(self, context: IncidentContext, *, model: str) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    async def summarize_evidence(self, context: IncidentContext, *, model: str) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    async def correlate_change(self, context: IncidentContext, *, model: str) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    async def suggest_actions(self, context: IncidentContext, *, model: str) -> ProviderResult:
        raise NotImplementedError
