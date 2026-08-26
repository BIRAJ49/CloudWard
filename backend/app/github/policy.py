"""Repository and path allowlists for all GitHub App operations."""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath

from app.errors import CloudWardError

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def normalize_repository(value: str) -> str:
    normalized = value.strip()
    if not REPOSITORY_PATTERN.fullmatch(normalized):
        raise CloudWardError(
            "GITHUB_REPOSITORY_FORBIDDEN", "GitHub repository is not valid", status_code=403
        )
    return normalized.lower()


def normalize_path(value: str) -> str:
    if not value or "\\" in value or value.startswith("/"):
        raise CloudWardError("GITHUB_PATH_FORBIDDEN", "GitHub path is forbidden", status_code=403)
    path = PurePosixPath(value)
    if ".." in path.parts or "." in path.parts:
        raise CloudWardError("GITHUB_PATH_FORBIDDEN", "GitHub path is forbidden", status_code=403)
    normalized = str(path)
    if len(normalized) > 1024:
        raise CloudWardError("GITHUB_PATH_FORBIDDEN", "GitHub path exceeds limit", status_code=403)
    return normalized


class GitHubAutomationPolicy:
    def __init__(
        self,
        *,
        read_repositories: set[str] | frozenset[str],
        issue_repositories: set[str] | frozenset[str],
        write_paths: dict[str, tuple[str, ...] | list[str]],
    ) -> None:
        self.read_repositories = frozenset(normalize_repository(item) for item in read_repositories)
        self.issue_repositories = frozenset(
            normalize_repository(item) for item in issue_repositories
        )
        self.write_paths = {
            normalize_repository(repository): tuple(patterns)
            for repository, patterns in write_paths.items()
        }
        for patterns in self.write_paths.values():
            if not patterns or any(
                pattern.startswith("/") or ".." in pattern for pattern in patterns
            ):
                raise ValueError("GitHub write allowlist patterns must be relative and non-empty")

    def require_read(self, repository: str) -> str:
        normalized = normalize_repository(repository)
        if normalized not in self.read_repositories:
            raise CloudWardError(
                "GITHUB_REPOSITORY_FORBIDDEN",
                "Repository is outside the GitHub read allowlist",
                status_code=403,
            )
        return normalized

    def require_issue_write(self, repository: str) -> str:
        normalized = normalize_repository(repository)
        if normalized not in self.issue_repositories:
            raise CloudWardError(
                "GITHUB_REPOSITORY_FORBIDDEN",
                "Repository is outside the GitHub Issue allowlist",
                status_code=403,
            )
        return normalized

    def require_path_write(self, repository: str, path: str) -> tuple[str, str]:
        normalized_repository = normalize_repository(repository)
        normalized_path = normalize_path(path)
        patterns = self.write_paths.get(normalized_repository, ())
        if not any(fnmatch.fnmatchcase(normalized_path, pattern) for pattern in patterns):
            raise CloudWardError(
                "GITHUB_PATH_FORBIDDEN",
                "Path is outside the GitHub write allowlist",
                status_code=403,
            )
        return normalized_repository, normalized_path

    def require_pull_request(self, repository: str) -> str:
        normalized = normalize_repository(repository)
        if normalized not in self.write_paths:
            raise CloudWardError(
                "GITHUB_REPOSITORY_FORBIDDEN",
                "Repository is outside the GitHub pull-request allowlist",
                status_code=403,
            )
        return normalized
