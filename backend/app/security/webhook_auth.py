"""HMAC authentication, replay protection, and rate control for Tetragon intake."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from fastapi import Request
from redis.exceptions import RedisError

from app.config import Settings
from app.errors import CloudWardError

_development_nonces: dict[str, float] = {}
_development_rates: dict[int, int] = {}


async def read_bounded_body(
    request: Request,
    maximum: int,
    *,
    error_code: str = "SECURITY_EVENT_TOO_LARGE",
) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
            if length < 0:
                raise ValueError("negative Content-Length")
            if length > maximum:
                raise CloudWardError(
                    error_code,
                    "Request exceeds the body limit",
                    status_code=413,
                )
        except ValueError as exc:
            raise CloudWardError(
                "INVALID_CONTENT_LENGTH", "Invalid Content-Length header", status_code=400
            ) from exc
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise CloudWardError(error_code, "Request exceeds the body limit", status_code=413)
        body.extend(chunk)
    return bytes(body)


async def authenticate_tetragon_request(request: Request, body: bytes, settings: Settings) -> None:
    timestamp_text = request.headers.get("X-CloudWard-Timestamp", "")
    nonce = request.headers.get("X-CloudWard-Nonce", "")
    supplied = request.headers.get("X-CloudWard-Signature", "")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise CloudWardError(
            "WEBHOOK_AUTHENTICATION_FAILED", "Invalid webhook authentication", status_code=401
        ) from exc
    now = int(time.time())
    if abs(now - timestamp) > settings.tetragon_webhook_max_clock_skew_seconds:
        raise CloudWardError(
            "WEBHOOK_AUTHENTICATION_FAILED", "Invalid webhook authentication", status_code=401
        )
    if not (16 <= len(nonce) <= 128) or not nonce.replace("-", "").isalnum():
        raise CloudWardError(
            "WEBHOOK_AUTHENTICATION_FAILED", "Invalid webhook authentication", status_code=401
        )
    signed = timestamp_text.encode() + b"." + nonce.encode() + b"." + body
    expected = hmac.new(
        settings.tetragon_webhook_secret.get_secret_value().encode(),
        signed,
        hashlib.sha256,
    ).hexdigest()
    normalized_supplied = supplied.removeprefix("sha256=")
    if len(normalized_supplied) != 64 or not hmac.compare_digest(expected, normalized_supplied):
        raise CloudWardError(
            "WEBHOOK_AUTHENTICATION_FAILED", "Invalid webhook authentication", status_code=401
        )
    await _claim_nonce(request, nonce, settings)
    await _check_rate(request, settings)


async def _claim_nonce(request: Request, nonce: str, settings: Settings) -> None:
    redis_client: Any = getattr(request.app.state, "redis", None)
    key = f"cloudward:tetragon:nonce:{hashlib.sha256(nonce.encode()).hexdigest()}"
    if redis_client is not None:
        try:
            claimed = await redis_client.set(
                key,
                "1",
                ex=settings.tetragon_webhook_max_clock_skew_seconds * 2,
                nx=True,
            )
            if not claimed:
                raise CloudWardError(
                    "WEBHOOK_REPLAY_DETECTED", "Webhook nonce was already used", status_code=409
                )
            return
        except CloudWardError:
            raise
        except (RedisError, AttributeError):
            pass
    if settings.app_env not in {"development", "test"}:
        raise CloudWardError(
            "WEBHOOK_REPLAY_PROTECTION_UNAVAILABLE",
            "Webhook replay protection is unavailable",
            status_code=503,
        )
    now = time.monotonic()
    expired = [key for key, expiry in _development_nonces.items() if expiry <= now]
    for expired_key in expired:
        _development_nonces.pop(expired_key, None)
    if nonce in _development_nonces:
        raise CloudWardError(
            "WEBHOOK_REPLAY_DETECTED", "Webhook nonce was already used", status_code=409
        )
    _development_nonces[nonce] = now + settings.tetragon_webhook_max_clock_skew_seconds * 2


async def _check_rate(request: Request, settings: Settings) -> None:
    minute = int(time.time()) // 60
    redis_client: Any = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        try:
            key = f"cloudward:tetragon:rate:{minute}"
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, 61)
            if count > settings.tetragon_webhook_max_events_per_minute:
                raise CloudWardError(
                    "SECURITY_EVENT_RATE_LIMITED", "Security event rate exceeded", status_code=429
                )
            return
        except CloudWardError:
            raise
        except RedisError:
            pass
    if settings.app_env not in {"development", "test"}:
        raise CloudWardError(
            "SECURITY_RATE_CONTROL_UNAVAILABLE",
            "Security event rate control is unavailable",
            status_code=503,
        )
    for bucket in [bucket for bucket in _development_rates if bucket < minute - 1]:
        _development_rates.pop(bucket, None)
    _development_rates[minute] = _development_rates.get(minute, 0) + 1
    if _development_rates[minute] > settings.tetragon_webhook_max_events_per_minute:
        raise CloudWardError(
            "SECURITY_EVENT_RATE_LIMITED", "Security event rate exceeded", status_code=429
        )
