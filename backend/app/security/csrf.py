"""Enforce exact browser origins on state-changing requests."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.errors import error_body


class CSRFProtectionMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.cookie_name = settings.session_cookie_name
        frontend = urlsplit(str(settings.frontend_url))
        self.allowed_origins = {
            f"{frontend.scheme}://{frontend.netloc}",
            *(origin.rstrip("/") for origin in settings.cors_origin_list if origin != "*"),
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            request = Request(scope)
            origin = request.headers.get("origin")
            # Browsers supply Origin on mutating fetches. Machine-to-machine callers
            # authenticate with headers and do not need a browser session cookie.
            if (origin is not None and origin not in self.allowed_origins) or (
                self.cookie_name in request.cookies and origin is None
            ):
                response = JSONResponse(
                    error_body("CSRF_ORIGIN_DENIED", "Request origin is not trusted"),
                    status_code=403,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
