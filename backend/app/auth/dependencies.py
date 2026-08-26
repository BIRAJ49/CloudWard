"""Resolve an authenticated principal and refresh its role from persistence."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Principal
from app.auth.session import SessionSigner
from app.config import Settings, get_settings
from app.db.models import RoleMapping, User
from app.db.session import get_session
from app.errors import CloudWardError
from app.rbac import Role


async def get_current_principal(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
    dev_user: Annotated[str | None, Header(alias="X-CloudWard-Dev-User")] = None,
    dev_role: Annotated[str | None, Header(alias="X-CloudWard-Dev-Role")] = None,
) -> Principal:
    session_cookie = request.cookies.get(settings.session_cookie_name)
    if dev_user is not None:
        if not settings.dev_auth_enabled or settings.app_env not in {"development", "test"}:
            raise CloudWardError(
                "DEV_AUTH_DISABLED", "Development authentication is disabled", status_code=401
            )
        try:
            role = Role(dev_role or Role.OPERATOR.value)
        except ValueError as exc:
            raise CloudWardError(
                "INVALID_ROLE", "Unknown development role", status_code=401
            ) from exc
        # Stable, non-secret UUID solely for local header authentication.
        import uuid

        return Principal(
            user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"cloudward-dev:{dev_user}"),
            login=dev_user,
            role=role,
            persisted=False,
        )

    if not session_cookie:
        raise CloudWardError(
            "AUTHENTICATION_REQUIRED", "Authentication is required", status_code=401
        )
    signed = SessionSigner(settings).read_principal(session_cookie)
    result = await session.execute(
        select(User, RoleMapping.role)
        .join(RoleMapping, RoleMapping.user_id == User.id)
        .where(User.id == signed.user_id, User.active.is_(True), RoleMapping.scope == "global")
    )
    row = result.first()
    if row is None:
        raise CloudWardError(
            "INVALID_SESSION", "User or role mapping no longer exists", status_code=401
        )
    user, role = row
    return Principal(user_id=user.id, login=user.github_login, role=role)
