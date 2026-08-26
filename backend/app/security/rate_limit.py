"""Redis-backed fixed-window rate limiting for sensitive local trigger/auth routes."""

from __future__ import annotations

import hashlib
import time

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.errors import CloudWardError


class RateLimit:
    def __init__(self, name: str, *, limit: int, window_seconds: int) -> None:
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds
        self._development_counts: dict[str, tuple[int, float]] = {}

    async def __call__(self, request: Request) -> None:
        address = request.client.host if request.client else "unknown"
        identity = hashlib.sha256(address.encode()).hexdigest()[:24]
        window = int(time.time()) // self.window_seconds
        key = f"cloudward:rate:{self.name}:{identity}:{window}"
        redis_client: Redis | None = getattr(request.app.state, "redis", None)
        if redis_client is not None:
            try:
                count = await redis_client.incr(key)
                if count == 1:
                    await redis_client.expire(key, self.window_seconds + 1)
                if count > self.limit:
                    raise CloudWardError("RATE_LIMITED", "Too many requests", status_code=429)
                return
            except CloudWardError:
                raise
            except RedisError:
                pass
        settings = getattr(request.app.state, "settings", get_settings())
        if settings.app_env not in {"development", "test"}:
            raise CloudWardError(
                "RATE_LIMIT_UNAVAILABLE",
                "Rate limit service unavailable",
                status_code=503,
            )
        count, expires = self._development_counts.get(identity, (0, 0))
        now = time.monotonic()
        if expires <= now:
            count, expires = 0, now + self.window_seconds
        count += 1
        self._development_counts[identity] = (count, expires)
        if count > self.limit:
            raise CloudWardError("RATE_LIMITED", "Too many requests", status_code=429)


auth_rate_limit = RateLimit("auth", limit=20, window_seconds=60)
demo_rate_limit = RateLimit("demo-trigger", limit=5, window_seconds=60)
alertmanager_rate_limit = RateLimit("alertmanager-webhook", limit=120, window_seconds=60)
