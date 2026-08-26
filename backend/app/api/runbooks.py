from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_runbook_loader
from app.auth.schemas import Principal
from app.rbac import Permission, require_permission
from app.runbooks import RunbookDocument, RunbookLoader

router = APIRouter(prefix="/runbooks", tags=["runbooks"])


@router.get("", response_model=list[RunbookDocument])
async def runbooks(
    _: Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))],
    loader: Annotated[RunbookLoader, Depends(get_runbook_loader)],
) -> tuple[RunbookDocument, ...]:
    return loader.runbooks
