"""GitHub App installation-token client with bounded source and controlled writes."""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import jwt
from pydantic import SecretStr, ValidationError

from app.ai.redaction import redact_text
from app.errors import CloudWardError
from app.github.policy import GitHubAutomationPolicy, normalize_path
from app.github.schemas import (
    CommitEvidence,
    ComparisonEvidence,
    FileDiffEvidence,
    GitHubIssueContent,
    GitHubIssueResult,
    GitHubPRContent,
    GitHubPullRequestResult,
    SourceFileEvidence,
)

SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,253}[A-Za-z0-9])?$")
MAX_SOURCE_BYTES = 20_000


@dataclass(frozen=True, slots=True)
class InstallationToken:
    value: SecretStr
    expires_at: datetime


class AppJWTSource(Protocol):
    async def get_app_jwt(self) -> SecretStr: ...


class InstallationTokenSource(Protocol):
    async def get_token(self) -> SecretStr: ...


class GitHubInstallationTokenProvider:
    """Installation tokens are cached in memory only and evicted before expiry."""

    def __init__(
        self,
        *,
        installation_id: int,
        app_jwt_source: AppJWTSource,
        client: httpx.AsyncClient | None = None,
        api_url: str = "https://api.github.com",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if installation_id <= 0:
            raise ValueError("installation_id must be positive")
        self._installation_id = installation_id
        self._app_jwt_source = app_jwt_source
        self._client = client
        self._api_url = api_url.rstrip("/")
        self._now = now or (lambda: datetime.now(UTC))
        self._cached: InstallationToken | None = None

    async def get_token(self) -> SecretStr:
        if self._cached and self._cached.expires_at - self._now() > timedelta(seconds=60):
            return self._cached.value
        app_jwt = await self._app_jwt_source.get_app_jwt()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0, follow_redirects=False)
        try:
            response = await client.post(
                f"{self._api_url}/app/installations/{self._installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt.get_secret_value()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            payload: Any = response.json()
            token = payload.get("token") if isinstance(payload, dict) else None
            expires_at = payload.get("expires_at") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not isinstance(expires_at, str):
                raise TypeError("installation token response is incomplete")
            parsed_expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if parsed_expiry.tzinfo is None:
                parsed_expiry = parsed_expiry.replace(tzinfo=UTC)
            self._cached = InstallationToken(value=SecretStr(token), expires_at=parsed_expiry)
            return self._cached.value
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise CloudWardError(
                "GITHUB_INSTALLATION_TOKEN_FAILED",
                "GitHub App installation token could not be obtained",
                status_code=503,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    def clear(self) -> None:
        self._cached = None


class RS256AppJWTSource:
    """Create the short-lived RS256 bearer used only to mint installation tokens."""

    def __init__(
        self,
        *,
        app_id: int,
        private_key: SecretStr,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if app_id <= 0:
            raise ValueError("app_id must be positive")
        if not private_key.get_secret_value().strip():
            raise ValueError("private_key must not be empty")
        self._app_id = app_id
        self._private_key = private_key
        self._now = now or (lambda: datetime.now(UTC))

    async def get_app_jwt(self) -> SecretStr:
        now = self._now()
        issued_at = int(now.timestamp()) - 60
        claims = {
            "iat": issued_at,
            "exp": issued_at + 600,
            "iss": str(self._app_id),
        }
        try:
            encoded = await asyncio.to_thread(
                jwt.encode,
                claims,
                self._private_key.get_secret_value(),
                algorithm="RS256",
            )
        except (jwt.PyJWTError, TypeError, ValueError) as exc:
            raise CloudWardError(
                "GITHUB_APP_JWT_FAILED",
                "GitHub App authentication could not be signed",
                status_code=503,
            ) from exc
        return SecretStr(encoded)


class GitHubAppClient:
    def __init__(
        self,
        *,
        token_source: InstallationTokenSource,
        policy: GitHubAutomationPolicy,
        client: httpx.AsyncClient | None = None,
        api_url: str = "https://api.github.com",
    ) -> None:
        self._token_source = token_source
        self._policy = policy
        self._client = client
        self._api_url = api_url.rstrip("/")

    async def read_commit(self, repository: str, sha: str) -> CommitEvidence:
        repository = self._policy.require_read(repository)
        _require_sha(sha)
        payload = await self._request("GET", f"/repos/{repository}/commits/{sha}")
        commit_payload = payload.get("commit")
        commit: dict[str, Any] = commit_payload if isinstance(commit_payload, dict) else {}
        author_payload = commit.get("author")
        author: dict[str, Any] = author_payload if isinstance(author_payload, dict) else {}
        message = redact_text(str(commit.get("message", "")))[:1000]
        committed_at = _parse_datetime(author.get("date"))
        try:
            return CommitEvidence(
                repository=repository,
                sha=str(payload.get("sha", sha)),
                message=message,
                author=str(author.get("name"))[:255] if author.get("name") else None,
                committed_at=committed_at,
                url=str(payload.get("html_url"))[:2048] if payload.get("html_url") else None,
            )
        except ValidationError as exc:
            raise CloudWardError(
                "GITHUB_RESPONSE_INVALID", "GitHub commit response is invalid", status_code=502
            ) from exc

    async def compare_commits(
        self, repository: str, base_sha: str, head_sha: str
    ) -> ComparisonEvidence:
        repository = self._policy.require_read(repository)
        _require_sha(base_sha)
        _require_sha(head_sha)
        payload = await self._request("GET", f"/repos/{repository}/compare/{base_sha}...{head_sha}")
        files_payload = payload.get("files")
        raw_files: list[Any] = files_payload if isinstance(files_payload, list) else []
        files: list[FileDiffEvidence] = []
        for item in raw_files[:20]:
            if not isinstance(item, dict):
                continue
            path = normalize_path(str(item.get("filename", "")))
            files.append(
                FileDiffEvidence(
                    path=path,
                    status=str(item.get("status", "unknown"))[:32],
                    additions=_safe_int(item.get("additions")),
                    deletions=_safe_int(item.get("deletions")),
                    patch=redact_text(str(item.get("patch", "")))[:4000],
                )
            )
        return ComparisonEvidence(
            repository=repository,
            base_sha=base_sha,
            head_sha=head_sha,
            ahead_by=_safe_int(payload.get("ahead_by")),
            total_commits=_safe_int(payload.get("total_commits")),
            files=files,
            truncated=len(raw_files) > len(files),
        )

    async def read_file(self, repository: str, path: str, *, ref: str) -> SourceFileEvidence:
        repository = self._policy.require_read(repository)
        path = normalize_path(path)
        payload = await self._request(
            "GET",
            f"/repos/{repository}/contents/{quote(path, safe='/')}",
            params={"ref": ref},
        )
        encoded = payload.get("content")
        if payload.get("encoding") != "base64" or not isinstance(encoded, str):
            raise CloudWardError(
                "GITHUB_RESPONSE_INVALID", "GitHub content response is invalid", status_code=502
            )
        try:
            decoded = base64.b64decode(encoded, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise CloudWardError(
                "GITHUB_RESPONSE_INVALID", "GitHub content response is invalid", status_code=502
            ) from exc
        if len(decoded) > MAX_SOURCE_BYTES:
            raise CloudWardError(
                "GITHUB_SOURCE_TOO_LARGE", "Source file exceeds diagnosis bound", status_code=422
            )
        content = redact_text(decoded.decode("utf-8", errors="replace"))
        return SourceFileEvidence(
            repository=repository,
            path=path,
            ref=ref,
            content=content,
            sha=str(payload.get("sha")) if payload.get("sha") else None,
        )

    async def create_issue(self, repository: str, content: GitHubIssueContent) -> GitHubIssueResult:
        repository = self._policy.require_issue_write(repository)
        payload = await self._request(
            "POST",
            f"/repos/{repository}/issues",
            json={
                "title": redact_text(content.title),
                "body": redact_text(content.body),
                "labels": [redact_text(item)[:50] for item in content.labels],
            },
        )
        return GitHubIssueResult(
            repository=repository,
            number=_positive_int(payload.get("number")),
            url=str(payload.get("html_url")),
            title=content.title,
        )

    def require_issue_write(self, repository: str) -> str:
        return self._policy.require_issue_write(repository)

    async def update_file(
        self,
        repository: str,
        path: str,
        *,
        branch: str,
        message: str,
        content: str,
        expected_blob_sha: str | None,
    ) -> str:
        repository, path = self._policy.require_path_write(repository, path)
        body: dict[str, Any] = {
            "message": redact_text(message)[:500],
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if expected_blob_sha:
            _require_sha(expected_blob_sha)
            body["sha"] = expected_blob_sha
        payload = await self._request(
            "PUT", f"/repos/{repository}/contents/{quote(path, safe='/')}", json=body
        )
        commit_payload = payload.get("commit")
        commit: dict[str, Any] = commit_payload if isinstance(commit_payload, dict) else {}
        sha = commit.get("sha")
        if not isinstance(sha, str):
            raise CloudWardError(
                "GITHUB_RESPONSE_INVALID", "GitHub write response is invalid", status_code=502
            )
        return sha

    def require_path_write(self, repository: str, path: str) -> tuple[str, str]:
        """Validate a write target before any mutating GitHub request is attempted."""

        return self._policy.require_path_write(repository, path)

    async def create_branch(self, repository: str, branch: str, *, from_sha: str) -> None:
        repository = self._policy.require_pull_request(repository)
        _require_branch(branch)
        _require_sha(from_sha)
        await self._request(
            "POST",
            f"/repos/{repository}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    async def create_pull_request(
        self, repository: str, content: GitHubPRContent
    ) -> GitHubPullRequestResult:
        repository = self._policy.require_pull_request(repository)
        body = redact_text(content.body)
        marker = "Created by CloudWard"
        if marker not in body:
            body = f"{marker}\n\n{body}"
        payload = await self._request(
            "POST",
            f"/repos/{repository}/pulls",
            json={
                "title": redact_text(content.title),
                "body": body,
                "head": content.head,
                "base": content.base,
                "draft": content.draft,
            },
        )
        return GitHubPullRequestResult(
            repository=repository,
            number=_positive_int(payload.get("number")),
            url=str(payload.get("html_url")),
            head=content.head,
            base=content.base,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._token_source.get_token()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20.0, follow_redirects=False)
        try:
            response = await client.request(
                method,
                f"{self._api_url}{path}",
                params=params,
                json=json,
                headers={
                    "Authorization": f"Bearer {token.get_secret_value()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            payload: Any = response.json()
            if not isinstance(payload, dict):
                raise TypeError("GitHub response root is not an object")
            return payload
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise CloudWardError(
                "GITHUB_API_FAILURE", "GitHub App request failed", status_code=502
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


def _require_sha(value: str) -> None:
    if not SHA_PATTERN.fullmatch(value):
        raise CloudWardError(
            "GITHUB_REF_INVALID", "GitHub commit reference is invalid", status_code=422
        )


def _require_branch(value: str) -> None:
    if (
        not BRANCH_PATTERN.fullmatch(value)
        or ".." in value
        or "//" in value
        or value.endswith(".lock")
    ):
        raise CloudWardError("GITHUB_REF_INVALID", "GitHub branch name is invalid", status_code=422)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _safe_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _positive_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CloudWardError(
            "GITHUB_RESPONSE_INVALID", "GitHub response has no record number", status_code=502
        )
    return value
