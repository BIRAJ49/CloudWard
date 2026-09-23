"""Bounded GitHub evidence and automation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommitEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    sha: str
    message: str = Field(max_length=1000)
    author: str | None = Field(default=None, max_length=255)
    committed_at: datetime | None = None
    url: str | None = Field(default=None, max_length=2048)


class FileDiffEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=32)
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    patch: str = Field(default="", max_length=4000)


class ComparisonEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    base_sha: str
    head_sha: str
    ahead_by: int = Field(default=0, ge=0)
    total_commits: int = Field(default=0, ge=0)
    files: list[FileDiffEvidence] = Field(default_factory=list, max_length=20)
    truncated: bool = False


class SourceFileEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    path: str
    ref: str
    content: str = Field(max_length=20_000)
    sha: str | None = None


class GitHubIssueResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    number: int = Field(ge=1)
    url: str
    title: str


class GitHubIssueAutomationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue: GitHubIssueResult
    created: bool


class GitHubPullRequestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    number: int = Field(ge=1)
    url: str
    head: str
    base: str


class SourceCorrelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    running_commit: str = Field(min_length=7, max_length=64)
    previous_healthy_commit: str = Field(min_length=7, max_length=64)
    branch: str | None = Field(default=None, max_length=255)
    image_digest: str | None = Field(default=None, max_length=255)


class SourceCorrelationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    running_commit: CommitEvidence
    previous_healthy_commit: str
    comparison: ComparisonEvidence
    branch: str | None = None
    image_digest: str | None = None
    caveat: str = "Temporal correlation is evidence, not proof of causation."


class GitHubIntegrationStatus(BaseModel):
    configured: bool
    installation_id_configured: bool
    read_repository_count: int
    issue_repository_count: int
    write_repository_count: int
    token_storage: str = "memory-only, short-lived installation token"  # noqa: S105
    authentication: str = "GitHub App installation token"
    required_permissions: dict[str, str] = Field(
        default_factory=lambda: {
            "metadata": "read",
            "contents": "read/write only for allowlisted paths",
            "issues": "write only for allowlisted repositories",
            "pull_requests": "write only for allowlisted repositories",
        }
    )
    writes_are_allowlisted: bool = True
    secrets_exposed: bool = False


class GitHubIssueContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)
    labels: list[str] = Field(default_factory=list, max_length=10)


class GitHubPRContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    head: str = Field(min_length=1, max_length=255)
    base: str = Field(min_length=1, max_length=255)
    draft: bool = True


class IncidentIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    recommended_follow_up: str = Field(min_length=1, max_length=2000)
    labels: list[str] = Field(default_factory=lambda: ["cloudward"], max_length=10)


class GitHubChangeProposalRequest(BaseModel):
    """One bounded file change followed by a human-reviewed pull request."""

    model_config = ConfigDict(extra="forbid")
    repository: str
    path: str = Field(min_length=1, max_length=1024)
    base: str = Field(default="main", min_length=1, max_length=255)
    base_commit_sha: str = Field(min_length=7, max_length=64)
    head: str = Field(
        min_length=12,
        max_length=255,
        pattern=r"^cloudward/[A-Za-z0-9][A-Za-z0-9._/-]*$",
    )
    expected_blob_sha: str | None = Field(default=None, min_length=7, max_length=64)
    proposed_content: str = Field(min_length=1, max_length=100_000)
    commit_message: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    current_state: dict[str, Any] = Field(default_factory=dict)
    proposed_state: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    risk_score: int = Field(ge=0, le=100)
    verification_plan: str = Field(min_length=1, max_length=2000)
    rollback_plan: str = Field(min_length=1, max_length=2000)
    draft: bool = True


class GitHubChangeProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: str
    path: str
    commit_sha: str
    pull_request: GitHubPullRequestResult
    created: bool


JsonObject = dict[str, Any]
