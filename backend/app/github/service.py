"""Source correlation and deduplicated GitHub automation services."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.redaction import redact_text, redact_untrusted
from app.audit import record_audit
from app.db.models import ActorType, EvidencePhase, EvidenceSnapshot, Incident
from app.errors import CloudWardError
from app.events import append_stream_event
from app.evidence.types import EvidenceType
from app.github.app import GitHubAppClient
from app.github.models import GitHubAutomationRecord
from app.github.schemas import (
    GitHubChangeProposalRequest,
    GitHubChangeProposalResponse,
    GitHubIssueContent,
    GitHubIssueResult,
    GitHubPRContent,
    GitHubPullRequestResult,
    SourceCorrelationEvidence,
    SourceCorrelationRequest,
)


class SourceCorrelationService:
    def __init__(self, client: GitHubAppClient) -> None:
        self._client = client

    async def correlate(self, request: SourceCorrelationRequest) -> SourceCorrelationEvidence:
        """Compare explicit running and previous-healthy revisions; never infer blame."""

        running = await self._client.read_commit(request.repository, request.running_commit)
        comparison = await self._client.compare_commits(
            request.repository,
            request.previous_healthy_commit,
            request.running_commit,
        )
        return SourceCorrelationEvidence(
            repository=running.repository,
            running_commit=running,
            previous_healthy_commit=request.previous_healthy_commit,
            comparison=comparison,
            branch=request.branch,
            image_digest=request.image_digest,
        )


class IncidentSourceCorrelationService:
    """Persist bounded source evidence without asserting that a change caused an incident."""

    def __init__(self, session: AsyncSession, client: GitHubAppClient) -> None:
        self._session = session
        self._source = SourceCorrelationService(client)

    async def correlate_and_store(
        self,
        *,
        incident: Incident,
        request: SourceCorrelationRequest,
        actor: str = "github-app",
    ) -> SourceCorrelationEvidence:
        evidence = await self._source.correlate(request)
        comparison = evidence.comparison
        reference = (
            f"github://{evidence.repository}/compare/"
            f"{evidence.previous_healthy_commit}...{evidence.running_commit.sha}"
        )
        existing = (
            await self._session.execute(
                select(EvidenceSnapshot).where(
                    EvidenceSnapshot.incident_id == incident.id,
                    EvidenceSnapshot.evidence_type == EvidenceType.GIT_CHANGE,
                    EvidenceSnapshot.reference == reference,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            self._session.add(
                EvidenceSnapshot(
                    incident_id=incident.id,
                    correlation_id=incident.correlation_id,
                    evidence_type=EvidenceType.GIT_CHANGE,
                    phase=EvidencePhase.INCIDENT,
                    summary=(
                        f"Bounded comparison of running {evidence.running_commit.sha[:12]} "
                        f"against previous healthy {evidence.previous_healthy_commit[:12]}; "
                        "correlation is not proof"
                    ),
                    reference=reference,
                    payload={
                        "repository": evidence.repository,
                        "commit": evidence.running_commit.sha,
                        "previous_commit": evidence.previous_healthy_commit,
                        "branch": evidence.branch,
                        "image_digest": evidence.image_digest,
                        "commit_message": evidence.running_commit.message,
                        "files": [item.model_dump(mode="json") for item in comparison.files],
                        "truncated": comparison.truncated,
                        "caveat": evidence.caveat,
                    },
                    collected_by=actor,
                )
            )
            await record_audit(
                self._session,
                event_type="GIT_EVIDENCE_COLLECTED",
                correlation_id=incident.correlation_id,
                incident_id=incident.id,
                actor=actor,
                actor_type=ActorType.SERVICE,
                result="SUCCEEDED",
                metadata={
                    "repository": evidence.repository,
                    "running_commit": evidence.running_commit.sha,
                    "previous_healthy_commit": evidence.previous_healthy_commit,
                    "files_returned": len(comparison.files),
                    "truncated": comparison.truncated,
                    "correlation_is_not_causation": True,
                },
            )
            await append_stream_event(
                self._session,
                event_type="incident.source_correlated",
                incident_id=incident.id,
                payload={
                    "repository": evidence.repository,
                    "running_commit": evidence.running_commit.sha,
                    "previous_healthy_commit": evidence.previous_healthy_commit,
                    "files_returned": len(comparison.files),
                    "truncated": comparison.truncated,
                    "correlation_is_not_causation": True,
                },
            )
            await self._session.flush()
        return evidence


SOURCE_METADATA_KEYS = frozenset(
    {
        "cloudward.io/source-repository",
        "github_repository",
        "repository",
        "cloudward.io/running-commit",
        "running_commit",
        "commit_sha",
        "revision",
        "cloudward.io/previous-healthy-commit",
        "previous_healthy_commit",
        "previous_commit_sha",
        "cloudward.io/source-branch",
        "branch",
        "cloudward.io/image-digest",
        "image_digest",
    }
)


def source_request_from_metadata(
    labels: Mapping[str, str],
    annotations: Mapping[str, str],
) -> SourceCorrelationRequest | None:
    """Build a request only from explicit bounded deployment/source metadata."""

    values = {**annotations, **labels}
    if not SOURCE_METADATA_KEYS.intersection(values):
        return None
    repository = _first_metadata(
        values,
        "cloudward.io/source-repository",
        "github_repository",
        "repository",
    )
    running = _first_metadata(
        values,
        "cloudward.io/running-commit",
        "running_commit",
        "commit_sha",
        "revision",
    )
    previous = _first_metadata(
        values,
        "cloudward.io/previous-healthy-commit",
        "previous_healthy_commit",
        "previous_commit_sha",
    )
    if not repository or not running or not previous:
        raise CloudWardError(
            "GITHUB_SOURCE_METADATA_INCOMPLETE",
            "Source correlation metadata requires repository, running commit, and previous healthy commit",
            status_code=422,
        )
    try:
        return SourceCorrelationRequest(
            repository=repository,
            running_commit=running,
            previous_healthy_commit=previous,
            branch=_first_metadata(values, "cloudward.io/source-branch", "branch"),
            image_digest=_first_metadata(values, "cloudward.io/image-digest", "image_digest"),
        )
    except ValidationError as exc:
        raise CloudWardError(
            "GITHUB_SOURCE_METADATA_INVALID",
            "Source correlation metadata is invalid",
            status_code=422,
        ) from exc


def _first_metadata(values: Mapping[str, str], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True, slots=True)
class IssueAutomationResult:
    issue: GitHubIssueResult
    created: bool


class GitHubIssueService:
    def __init__(self, session: AsyncSession, client: GitHubAppClient) -> None:
        self._session = session
        self._client = client

    async def create_once(
        self,
        *,
        incident_id: uuid.UUID,
        correlation_id: str,
        repository: str,
        content: GitHubIssueContent,
    ) -> IssueAutomationResult:
        repository = self._client.require_issue_write(repository)
        dedupe_key = hashlib.sha256(
            f"incident-issue:{incident_id}:{repository}".encode()
        ).hexdigest()
        existing = (
            await self._session.execute(
                select(GitHubAutomationRecord).where(
                    GitHubAutomationRecord.dedupe_key == dedupe_key
                )
            )
        ).scalar_one_or_none()
        if existing and existing.external_number and existing.external_url:
            return IssueAutomationResult(
                issue=GitHubIssueResult(
                    repository=existing.repository,
                    number=existing.external_number,
                    url=existing.external_url,
                    title=existing.title or "CloudWard incident",
                ),
                created=False,
            )
        issue = await self._client.create_issue(repository, content)
        record = existing or GitHubAutomationRecord(
            dedupe_key=dedupe_key,
            incident_id=incident_id,
            operation="ISSUE",
            repository=issue.repository,
        )
        record.external_number = issue.number
        record.external_url = issue.url
        record.status = "CREATED"
        record.title = redact_text(issue.title)[:255]
        record.summary = redact_text(content.body)[:2000]
        record.details = {"labels": [redact_text(item)[:50] for item in content.labels]}
        self._session.add(record)
        await self._session.flush()
        await record_audit(
            self._session,
            event_type="GITHUB_ISSUE_CREATED",
            correlation_id=correlation_id,
            incident_id=incident_id,
            action="CREATE_GITHUB_ISSUE",
            result="SUCCEEDED",
            metadata={
                "repository": issue.repository,
                "issue_number": issue.number,
                "issue_url": issue.url,
                "dedupe_key": dedupe_key,
            },
        )
        return IssueAutomationResult(issue=issue, created=True)


class GitHubChangeProposalService:
    """Create one allowlisted Git change and draft PR; never merge it."""

    def __init__(self, session: AsyncSession, client: GitHubAppClient) -> None:
        self._session = session
        self._client = client

    async def create_once(
        self,
        *,
        subject_id: uuid.UUID,
        operation: str,
        request: GitHubChangeProposalRequest,
        correlation_id: str,
        incident_id: uuid.UUID | None = None,
    ) -> GitHubChangeProposalResponse:
        repository, path = self._client.require_path_write(request.repository, request.path)
        dedupe_key = hashlib.sha256(
            f"change-pr:{operation}:{subject_id}:{repository}:{path}".encode()
        ).hexdigest()
        existing = (
            await self._session.execute(
                select(GitHubAutomationRecord).where(
                    GitHubAutomationRecord.dedupe_key == dedupe_key
                )
            )
        ).scalar_one_or_none()
        if existing and existing.external_number and existing.external_url:
            commit_sha = str(existing.details.get("commit_sha", ""))
            if not commit_sha:
                raise CloudWardError(
                    "GITHUB_AUTOMATION_RECORD_INVALID",
                    "Stored GitHub automation record is incomplete",
                    status_code=500,
                )
            return GitHubChangeProposalResponse(
                subject_id=str(subject_id),
                path=path,
                commit_sha=commit_sha,
                pull_request=GitHubPullRequestResult(
                    repository=existing.repository,
                    number=existing.external_number,
                    url=existing.external_url,
                    head=str(existing.details.get("head", request.head)),
                    base=str(existing.details.get("base", request.base)),
                ),
                created=False,
            )

        await self._client.create_branch(
            repository,
            request.head,
            from_sha=request.base_commit_sha,
        )
        commit_sha = await self._client.update_file(
            repository,
            path,
            branch=request.head,
            message=request.commit_message,
            content=request.proposed_content,
            expected_blob_sha=request.expected_blob_sha,
        )
        content = GitHubPRContent(
            title=request.title,
            body=_change_pr_body(subject_id, operation, request),
            head=request.head,
            base=request.base,
            draft=request.draft,
        )
        pull_request = await self._client.create_pull_request(repository, content)
        record = GitHubAutomationRecord(
            dedupe_key=dedupe_key,
            incident_id=incident_id,
            operation=operation[:32],
            repository=pull_request.repository,
            external_number=pull_request.number,
            external_url=pull_request.url,
            status="CREATED",
            title=content.title,
            summary=redact_text(content.body)[:2000],
            details={
                "subject_id": str(subject_id),
                "path": path,
                "head": request.head,
                "base": request.base,
                "commit_sha": commit_sha,
            },
        )
        self._session.add(record)
        await record_audit(
            self._session,
            event_type="GITHUB_PR_CREATED",
            correlation_id=correlation_id,
            incident_id=incident_id,
            action="CREATE_GITOPS_PR",
            risk_score=request.risk_score,
            result="SUCCEEDED",
            metadata={
                "subject_id": str(subject_id),
                "operation": operation,
                "repository": repository,
                "path": path,
                "commit_sha": commit_sha,
                "pull_request_number": pull_request.number,
                "pull_request_url": pull_request.url,
                "direct_change": False,
            },
        )
        await self._session.flush()
        return GitHubChangeProposalResponse(
            subject_id=str(subject_id),
            path=path,
            commit_sha=commit_sha,
            pull_request=pull_request,
            created=True,
        )


def _change_pr_body(
    subject_id: uuid.UUID,
    operation: str,
    request: GitHubChangeProposalRequest,
) -> str:
    evidence = redact_untrusted(request.evidence)
    current = redact_untrusted(request.current_state)
    proposed = redact_untrusted(request.proposed_state)
    return "\n\n".join(
        [
            "Created by CloudWard",
            f"Automation: `{redact_text(operation)[:64]}`",
            f"Subject ID: `{subject_id}`",
            f"Reason: {redact_text(request.reason)[:2000]}",
            f"Current state:\n```json\n{json.dumps(current, sort_keys=True)[:3000]}\n```",
            f"Proposed state:\n```json\n{json.dumps(proposed, sort_keys=True)[:3000]}\n```",
            f"Risk: {request.risk_score}/100",
            f"Evidence:\n```json\n{json.dumps(evidence, sort_keys=True)[:3000]}\n```",
            f"Verification plan: {redact_text(request.verification_plan)}",
            f"Rollback plan: {redact_text(request.rollback_plan)}",
            "CloudWard made no direct persistent change; merge remains a human decision.",
        ]
    )
