from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.kubernetes import KubernetesExecutor
from app.policies import OPAClient
from app.policies.chaos import ChaosPolicyClient
from app.runbooks import RunbookLoader


def get_runbook_loader(request: Request) -> RunbookLoader:
    return cast(RunbookLoader, request.app.state.runbooks)


def get_opa_client(settings: Annotated[Settings, Depends(get_settings)]) -> OPAClient:
    return OPAClient(str(settings.opa_url), settings.opa_decision_path)


def get_chaos_policy_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChaosPolicyClient:
    return ChaosPolicyClient(str(settings.opa_url), settings.opa_chaos_decision_path)


async def get_kubernetes_executor(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[KubernetesExecutor]:
    executor = await KubernetesExecutor.create(
        context=settings.kubernetes_context,
        allowed_namespaces=settings.allowed_namespaces,
    )
    try:
        yield executor
    finally:
        await executor.close()
