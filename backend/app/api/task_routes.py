from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.schemas import TaskPublishResponse
from app.auth.schemas import Principal
from app.logging import request_id_context
from app.rbac import Permission, require_permission
from app.tasks import HEALTHCHECK_QUEUE, HEALTHCHECK_TASK

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/healthcheck", response_model=TaskPublishResponse, status_code=202)
async def publish_healthcheck(
    request: Request,
    _: Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))],
) -> TaskPublishResponse:
    result = await run_in_threadpool(
        request.app.state.task_publisher.send_task,
        HEALTHCHECK_TASK,
        kwargs={"value": request_id_context.get() or "api-healthcheck"},
        queue=HEALTHCHECK_QUEUE,
    )
    return TaskPublishResponse(
        task_id=str(result.id), task_name=HEALTHCHECK_TASK, queue=HEALTHCHECK_QUEUE
    )
