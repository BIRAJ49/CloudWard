"""Bounded internal HTTP calls that never forward credentials through redirects."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE_BYTES = 1_048_576


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def internal_url(base: str, path: str) -> str:
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"api", "127.0.0.1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/api/v1/internal"
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
        or any(segment in {".", ".."} for segment in path.split("/"))
        or "//" in path
    ):
        raise RuntimeError("worker internal API URL is outside the allowed boundary")
    return base.rstrip("/") + path


def post_json(
    url: str, token: str, payload: dict[str, Any], *, timeout: float
) -> dict[str, Any]:
    # Validate even when the caller constructed the URL without internal_url.
    parsed = urlsplit(url)
    prefix = "/api/v1/internal"
    internal_url(
        f"{parsed.scheme}://{parsed.netloc}{prefix}", parsed.path.removeprefix(prefix)
    )
    if parsed.query or parsed.fragment or not parsed.path.startswith(prefix + "/"):
        raise RuntimeError("worker internal API URL is outside the allowed boundary")
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # Internal service traffic must not inherit an external HTTP proxy or redirect.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError("internal API response exceeds byte limit")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise RuntimeError("internal API returned a non-object response")
    return result
