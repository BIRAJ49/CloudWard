from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

os.environ.update(
    {
        "APP_ENV": "test",
        "DEV_AUTH_ENABLED": "true",
        "DATABASE_URL": "sqlite+aiosqlite://",
        "REDIS_URL": "redis://localhost:6379/15",
        "RUNBOOKS_PATH": str(Path(__file__).resolve().parents[2] / "runbooks"),
    }
)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        dev_auth_enabled=True,
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:6379/15",
        runbooks_path=Path(__file__).resolve().parents[2] / "runbooks",
        verification_timeout_seconds=1,
        verification_poll_seconds=0.05,
    )


@pytest.fixture
async def session_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    async with session_factory() as db_session:
        yield db_session


class FakeRedis:
    async def ping(self) -> bool:
        return True

    async def incr(self, _: str) -> int:
        return 1

    async def expire(self, _: str, __: int) -> bool:
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture
async def api_client(settings: Settings, session_factory) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_session] = override_session
    async with app.router.lifespan_context(app):
        app.state.redis = FakeRedis()
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client


@pytest.fixture
def operator_headers() -> dict[str, str]:
    return {
        "X-CloudWard-Dev-User": "test-operator",
        "X-CloudWard-Dev-Role": "Operator",
    }


@pytest.fixture
def viewer_headers() -> dict[str, str]:
    return {"X-CloudWard-Dev-User": "test-viewer", "X-CloudWard-Dev-Role": "Viewer"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-CloudWard-Dev-User": "test-admin", "X-CloudWard-Dev-Role": "Admin"}
