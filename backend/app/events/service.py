"""Database-backed SSE outbox with in-process fanout for local Part 2."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StreamEvent
from app.logging import redact

_stream_condition = asyncio.Condition()


async def append_stream_event(
    session: AsyncSession,
    *,
    event_type: str,
    incident_id: uuid.UUID | None,
    payload: dict[str, Any],
) -> StreamEvent:
    event = StreamEvent(
        event_type=event_type,
        incident_id=incident_id,
        payload=redact(
            {
                "type": event_type,
                "event_type": event_type,
                "incident_id": str(incident_id) if incident_id else None,
                **payload,
            }
        ),
    )
    session.add(event)
    await session.flush()
    async with _stream_condition:
        _stream_condition.notify_all()
    return event


async def wait_for_stream_event(timeout_seconds: float) -> bool:
    try:
        async with asyncio.timeout(timeout_seconds):
            async with _stream_condition:
                await _stream_condition.wait()
        return True
    except TimeoutError:
        return False
