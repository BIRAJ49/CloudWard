"""Request identity and correlation middleware."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging import correlation_id_context, request_id_context

VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger(__name__)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        supplied_request_id = headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if VALID_REQUEST_ID.fullmatch(supplied_request_id)
            else str(uuid.uuid4())
        )
        supplied_correlation_id = headers.get("x-correlation-id", "")
        correlation_id = (
            supplied_correlation_id
            if VALID_REQUEST_ID.fullmatch(supplied_correlation_id)
            else request_id
        )
        request_token = request_id_context.set(request_id)
        correlation_token = correlation_id_context.set(correlation_id)
        started = time.monotonic()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                response_headers.append((b"x-correlation-id", correlation_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request_completed",
                extra={
                    "fields": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status_code": status_code,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                },
            )
            request_id_context.reset(request_token)
            correlation_id_context.reset(correlation_token)
