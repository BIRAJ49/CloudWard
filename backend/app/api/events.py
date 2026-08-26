"""Authorized Server-Sent Events with durable Last-Event-ID replay."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.db.models import StreamEvent
from app.db.session import get_session
from app.errors import CloudWardError
from app.events import wait_for_stream_event
from app.rbac import Permission, require_permission

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream", response_class=StreamingResponse)
async def event_stream(
    request: Request,
    _: Annotated[Principal, Depends(require_permission(Permission.PLATFORM_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    header_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    query_event_id: Annotated[int | None, Query(alias="last_event_id", ge=0)] = None,
) -> StreamingResponse:
    cursor = query_event_id or 0
    if header_event_id:
        try:
            cursor = max(cursor, int(header_event_id))
        except ValueError as exc:
            raise CloudWardError(
                "INVALID_EVENT_CURSOR", "Last-Event-ID must be a non-negative integer", status_code=422
            ) from exc
        if cursor < 0:
            raise CloudWardError(
                "INVALID_EVENT_CURSOR", "Last-Event-ID must be a non-negative integer", status_code=422
            )

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            records = list(
                (
                    await session.execute(
                        select(StreamEvent)
                        .where(StreamEvent.id > cursor)
                        .order_by(StreamEvent.id)
                        .limit(100)
                    )
                ).scalars()
            )
            if records:
                for record in records:
                    cursor = record.id
                    data = json.dumps(record.payload, separators=(",", ":"), default=str)
                    yield f"id: {record.id}\nevent: {record.event_type}\ndata: {data}\n\n"
                continue
            signaled = await wait_for_stream_event(15.0)
            if not signaled:
                yield ": keepalive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
