"""Authentication endpoints. Development login is runtime-gated and production-impossible."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.schemas import DevLoginRequest, Principal, PrincipalResponse
from app.auth.session import SessionSigner
from app.config import Settings, get_settings
from app.db.models import OAuthIdentity, RoleMapping, User
from app.db.session import get_session
from app.errors import CloudWardError
from app.github.oauth import GitHubOAuthClient
from app.rbac import Role
from app.security.rate_limit import auth_rate_limit

router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_session_cookie(response: Response, settings: Settings, value: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        value,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.get("/github/login", response_class=RedirectResponse)
async def github_login(
    settings: Annotated[Settings, Depends(get_settings)],
    _rate_limit: Annotated[None, Depends(auth_rate_limit)],
) -> RedirectResponse:
    signer = SessionSigner(settings)
    state = signer.sign_oauth_state({"nonce": secrets.token_urlsafe(24)})
    response = RedirectResponse(
        GitHubOAuthClient(settings).authorization_url(state), status_code=302
    )
    response.set_cookie(
        "cloudward_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/api/v1/auth/github/callback",
    )
    return response


@router.get("/github/callback", response_class=RedirectResponse)
async def github_callback(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query(min_length=4, max_length=512)],
    state: Annotated[str, Query(min_length=8, max_length=2048)],
    _rate_limit: Annotated[None, Depends(auth_rate_limit)],
    state_cookie: Annotated[str | None, Cookie(alias="cloudward_oauth_state")] = None,
) -> RedirectResponse:
    if state_cookie is None or not secrets.compare_digest(state, state_cookie):
        raise CloudWardError("INVALID_OAUTH_STATE", "OAuth state does not match", status_code=401)
    SessionSigner(settings).read_oauth_state(state)
    github = await GitHubOAuthClient(settings).exchange(code)
    result = await session.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == "github",
            OAuthIdentity.external_user_id == github.external_id,
        )
    )
    oauth_identity = result.scalar_one_or_none()
    if oauth_identity is None:
        user = User(
            github_login=github.login,
            display_name=github.name,
            email=github.email,
            avatar_url=github.avatar_url,
        )
        session.add(user)
        await session.flush()
        session.add(
            OAuthIdentity(
                user_id=user.id,
                provider="github",
                external_user_id=github.external_id,
                provider_login=github.login,
            )
        )
        session.add(RoleMapping(user_id=user.id, role=Role.VIEWER, scope="global"))
    else:
        existing_user = await session.get(User, oauth_identity.user_id)
        if existing_user is None:
            raise CloudWardError("INVALID_IDENTITY", "OAuth identity has no user", status_code=500)
        user = existing_user
        user.github_login = github.login
        user.display_name = github.name
        user.email = github.email
        user.avatar_url = github.avatar_url
    await session.commit()
    role_result = await session.execute(
        select(RoleMapping.role).where(
            RoleMapping.user_id == user.id, RoleMapping.scope == "global"
        )
    )
    role = role_result.scalar_one()
    principal = Principal(user_id=user.id, login=user.github_login, role=role)
    response = RedirectResponse(
        f"{str(settings.frontend_url).rstrip('/')}/auth/callback", status_code=302
    )
    _set_session_cookie(response, settings, SessionSigner(settings).sign_principal(principal))
    response.delete_cookie("cloudward_oauth_state", path="/api/v1/auth/github/callback")
    return response


@router.post("/dev", response_model=PrincipalResponse)
async def development_login(
    request: Request,
    response: Response,
    payload: DevLoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _rate_limit: Annotated[None, Depends(auth_rate_limit)],
) -> Principal:
    del request
    if not settings.dev_auth_enabled or settings.app_env not in {"development", "test"}:
        raise CloudWardError(
            "DEV_AUTH_DISABLED", "Development authentication is disabled", status_code=404
        )
    result = await session.execute(select(User).where(User.github_login == payload.login))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(github_login=payload.login, display_name=payload.login)
        session.add(user)
        await session.flush()
    role_result = await session.execute(
        select(RoleMapping).where(RoleMapping.user_id == user.id, RoleMapping.scope == "global")
    )
    mapping = role_result.scalar_one_or_none()
    if mapping is None:
        mapping = RoleMapping(user_id=user.id, role=payload.role, scope="global")
        session.add(mapping)
    else:
        mapping.role = payload.role
    await session.commit()
    principal = Principal(user_id=user.id, login=user.github_login, role=mapping.role)
    _set_session_cookie(response, settings, SessionSigner(settings).sign_principal(principal))
    return principal


@router.get("/me", response_model=PrincipalResponse)
async def current_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    return principal


@router.post("/logout", status_code=204)
async def logout(response: Response, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
