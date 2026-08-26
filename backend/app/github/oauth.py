"""Real GitHub OAuth authorization-code exchange and identity lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import PUBLIC_PLACEHOLDER, Settings
from app.errors import CloudWardError

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105
USER_URL = "https://api.github.com/user"
EMAILS_URL = "https://api.github.com/user/emails"


@dataclass(frozen=True, slots=True)
class GitHubIdentity:
    external_id: str
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None


class GitHubOAuthClient:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    def authorization_url(self, state: str) -> str:
        if not self._configured:
            raise CloudWardError(
                "OAUTH_NOT_CONFIGURED", "GitHub OAuth is not configured", status_code=503
            )
        query = urlencode(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": str(self.settings.github_redirect_uri),
                "scope": "read:user user:email",
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange(self, code: str) -> GitHubIdentity:
        client_id = self.settings.github_client_id
        client_secret = self.settings.github_client_secret
        if (
            not client_id
            or not client_secret
            or client_id == PUBLIC_PLACEHOLDER
            or client_secret.get_secret_value() == PUBLIC_PLACEHOLDER
        ):
            raise CloudWardError(
                "OAUTH_NOT_CONFIGURED", "GitHub OAuth is not configured", status_code=503
            )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            token_response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": str(self.settings.github_redirect_uri),
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_payload: Any = token_response.json()
            if not isinstance(token_payload, dict) or not isinstance(
                token_payload.get("access_token"), str
            ):
                raise CloudWardError(
                    "OAUTH_EXCHANGE_FAILED", "GitHub did not issue an access token", status_code=401
                )
            authorization = {"Authorization": f"Bearer {token_payload['access_token']}"}
            user_response = await client.get(USER_URL, headers=authorization)
            user_response.raise_for_status()
            user = user_response.json()
            email = user.get("email")
            if email is None:
                email_response = await client.get(EMAILS_URL, headers=authorization)
                email_response.raise_for_status()
                emails = email_response.json()
                email = next(
                    (
                        candidate.get("email")
                        for candidate in emails
                        if candidate.get("primary") and candidate.get("verified")
                    ),
                    None,
                )
            return GitHubIdentity(
                external_id=str(user["id"]),
                login=str(user["login"]),
                name=user.get("name"),
                email=email,
                avatar_url=user.get("avatar_url"),
            )
        except CloudWardError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise CloudWardError(
                "OAUTH_EXCHANGE_FAILED", "GitHub OAuth exchange failed", status_code=401
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    @property
    def _configured(self) -> bool:
        if not self.settings.github_client_id or not self.settings.github_client_secret:
            return False
        return (
            self.settings.github_client_id != PUBLIC_PLACEHOLDER
            and self.settings.github_client_secret.get_secret_value() != PUBLIC_PLACEHOLDER
        )
