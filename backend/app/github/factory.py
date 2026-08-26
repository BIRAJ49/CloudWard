"""Server-side construction of allowlisted GitHub App clients."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.errors import CloudWardError
from app.github.app import (
    GitHubAppClient,
    GitHubInstallationTokenProvider,
    RS256AppJWTSource,
)
from app.github.policy import GitHubAutomationPolicy


def build_github_app_client(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> GitHubAppClient:
    """Build a client without exposing App credentials beyond backend memory."""

    if (
        settings.github_app_id is None
        or settings.github_app_installation_id is None
        or settings.github_app_private_key is None
    ):
        raise CloudWardError(
            "GITHUB_APP_NOT_CONFIGURED",
            "GitHub App credentials are not configured",
            status_code=503,
        )
    policy = GitHubAutomationPolicy(
        read_repositories=set(_csv(settings.github_app_read_repositories)),
        issue_repositories=set(_csv(settings.github_app_issue_repositories)),
        write_paths=_write_allowlist(settings.github_app_write_allowlist),
    )
    jwt_source = RS256AppJWTSource(
        app_id=settings.github_app_id,
        private_key=SecretStr(
            settings.github_app_private_key.get_secret_value().replace("\\n", "\n")
        ),
    )
    token_source = GitHubInstallationTokenProvider(
        installation_id=settings.github_app_installation_id,
        app_jwt_source=jwt_source,
        client=client,
    )
    return GitHubAppClient(token_source=token_source, policy=policy, client=client)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _write_allowlist(value: str) -> dict[str, list[str]]:
    try:
        raw: Any = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CloudWardError(
            "GITHUB_ALLOWLIST_INVALID",
            "GitHub write allowlist is not valid JSON",
            status_code=503,
        ) from exc
    if not isinstance(raw, dict) or any(
        not isinstance(repository, str)
        or not isinstance(patterns, list)
        or any(not isinstance(pattern, str) for pattern in patterns)
        for repository, patterns in raw.items()
    ):
        raise CloudWardError(
            "GITHUB_ALLOWLIST_INVALID",
            "GitHub write allowlist must map repositories to path lists",
            status_code=503,
        )
    return raw
