"""Typed local-only GitOps writer for the controlled R1 demo repository."""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.errors import CloudWardError

LOCAL_REPOSITORY_URL = "git://host.docker.internal:19418/cloudward-gitops.git"
LOCAL_BRANCH = "main"
LOCAL_VALUES_PATH = Path("cloudward-gitops/environments/local/values.yaml")
KNOWN_GOOD_TAG = "local"
CONTROLLED_BAD_TAG = "local-bad"
_writer_lock = asyncio.Lock()


class GitOpsImageOperation(StrEnum):
    DEPLOY_CONTROLLED_BAD = "DEPLOY_CONTROLLED_BAD"
    REVERT_TO_KNOWN_GOOD = "REVERT_TO_KNOWN_GOOD"
    APPROVED_ROLLBACK = "APPROVED_ROLLBACK"


class GitOpsImageWriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: GitOpsImageOperation
    repository: str = LOCAL_REPOSITORY_URL
    branch: str = LOCAL_BRANCH
    values_path: str = str(LOCAL_VALUES_PATH)
    previous_tag: str
    target_tag: str
    previous_revision: str
    revision: str
    changed: bool


class LocalGitOpsImageWriter:
    """Mutate one known YAML field in one ephemeral, loopback-only Git source."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.local_gitops_write_enabled
        self.repository_url = settings.local_gitops_repo_url
        self.timeout_seconds = settings.local_gitops_timeout_seconds
        self.environment = settings.app_env

    def require_available(self) -> None:
        if not self.enabled:
            raise CloudWardError(
                "LOCAL_GITOPS_WRITER_DISABLED",
                "The typed local GitOps writer is disabled",
                status_code=503,
            )
        if self.environment not in {"development", "test"}:
            raise CloudWardError(
                "LOCAL_GITOPS_WRITER_DENIED",
                "The local GitOps writer is forbidden outside local/test",
                status_code=403,
            )
        if self.repository_url != LOCAL_REPOSITORY_URL:
            raise CloudWardError(
                "LOCAL_GITOPS_REPOSITORY_DENIED",
                "Only the fixed ephemeral CloudWard demo repository is allowed",
                status_code=403,
            )

    async def deploy_controlled_bad(self, *, execution_id: uuid.UUID) -> GitOpsImageWriteResult:
        return await self._write(
            operation=GitOpsImageOperation.DEPLOY_CONTROLLED_BAD,
            expected_tags=frozenset({KNOWN_GOOD_TAG, CONTROLLED_BAD_TAG}),
            target_tag=CONTROLLED_BAD_TAG,
            audit_reference=f"scenario-{execution_id}",
        )

    async def revert_to_known_good(self, *, incident_id: uuid.UUID) -> GitOpsImageWriteResult:
        return await self._write(
            operation=GitOpsImageOperation.REVERT_TO_KNOWN_GOOD,
            expected_tags=frozenset({CONTROLLED_BAD_TAG, KNOWN_GOOD_TAG}),
            target_tag=KNOWN_GOOD_TAG,
            audit_reference=f"incident-{incident_id}",
        )

    async def ensure_known_good(self, *, execution_id: uuid.UUID) -> GitOpsImageWriteResult:
        return await self._write(
            operation=GitOpsImageOperation.REVERT_TO_KNOWN_GOOD,
            expected_tags=frozenset({CONTROLLED_BAD_TAG, KNOWN_GOOD_TAG}),
            target_tag=KNOWN_GOOD_TAG,
            audit_reference=f"cleanup-{execution_id}",
        )

    async def approved_rollback(
        self,
        *,
        incident_id: uuid.UUID,
        recorded_previous_tag: str,
        approved: bool,
    ) -> GitOpsImageWriteResult:
        if not approved or recorded_previous_tag != CONTROLLED_BAD_TAG:
            raise CloudWardError(
                "GITOPS_ROLLBACK_APPROVAL_REQUIRED",
                "A persistent image rollback requires explicit approval and the recorded prior tag",
                status_code=403,
            )
        return await self._write(
            operation=GitOpsImageOperation.APPROVED_ROLLBACK,
            expected_tags=frozenset({KNOWN_GOOD_TAG}),
            target_tag=CONTROLLED_BAD_TAG,
            audit_reference=f"approved-rollback-{incident_id}",
        )

    async def _write(
        self,
        *,
        operation: GitOpsImageOperation,
        expected_tags: frozenset[str],
        target_tag: str,
        audit_reference: str,
    ) -> GitOpsImageWriteResult:
        self.require_available()
        async with _writer_lock:
            with tempfile.TemporaryDirectory(prefix="cloudward-gitops-") as temporary:
                worktree = Path(temporary) / "repository"
                await self._git(
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--branch",
                    LOCAL_BRANCH,
                    "--",
                    self.repository_url,
                    str(worktree),
                )
                previous_revision = (await self._git("rev-parse", "HEAD", cwd=worktree)).strip()
                values_path = (worktree / LOCAL_VALUES_PATH).resolve()
                if not values_path.is_relative_to(worktree.resolve()) or not values_path.is_file():
                    raise CloudWardError(
                        "GITOPS_VALUES_PATH_INVALID",
                        "The fixed CloudWard local values file is unavailable",
                        status_code=409,
                    )
                document = self._load_values(values_path)
                image = document["cloudward-demo"]["image"]
                previous_tag = image["tag"]
                if previous_tag not in expected_tags:
                    raise CloudWardError(
                        "STALE_GITOPS_TARGET",
                        "The current image tag is outside the recorded R1 transition",
                        status_code=409,
                        details={"expected_tags": sorted(expected_tags), "actual_tag": previous_tag},
                    )
                if previous_tag == target_tag:
                    return GitOpsImageWriteResult(
                        operation=operation,
                        previous_tag=previous_tag,
                        target_tag=target_tag,
                        previous_revision=previous_revision,
                        revision=previous_revision,
                        changed=False,
                    )
                image["tag"] = target_tag
                self._atomic_write(values_path, document)
                await self._git("add", "--", str(LOCAL_VALUES_PATH), cwd=worktree)
                message = f"CloudWard {operation.value}: {audit_reference}"
                await self._git(
                    "-c",
                    "user.name=CloudWard Reliability",
                    "-c",
                    "user.email=reliability@cloudward.invalid",
                    "commit",
                    "--no-gpg-sign",
                    "-m",
                    message,
                    cwd=worktree,
                )
                revision = (await self._git("rev-parse", "HEAD", cwd=worktree)).strip()
                await self._git(
                    "push", "origin", f"HEAD:refs/heads/{LOCAL_BRANCH}", cwd=worktree
                )
                remote = (
                    await self._git("ls-remote", "origin", f"refs/heads/{LOCAL_BRANCH}", cwd=worktree)
                ).split()
                if not remote or remote[0] != revision:
                    raise CloudWardError(
                        "GITOPS_REVISION_NOT_VISIBLE",
                        "The pushed GitOps revision is not visible to Argo CD",
                        status_code=502,
                    )
                return GitOpsImageWriteResult(
                    operation=operation,
                    previous_tag=previous_tag,
                    target_tag=target_tag,
                    previous_revision=previous_revision,
                    revision=revision,
                    changed=True,
                )

    @staticmethod
    def _load_values(path: Path) -> dict[str, Any]:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            image = document["cloudward-demo"]["image"]
            tag = image["tag"]
        except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
            raise CloudWardError(
                "INVALID_GITOPS_VALUES",
                "The fixed CloudWard values document has an invalid shape",
                status_code=409,
            ) from exc
        if not isinstance(document, dict) or not isinstance(image, dict) or not isinstance(tag, str):
            raise CloudWardError(
                "INVALID_GITOPS_VALUES",
                "The fixed CloudWard image tag is invalid",
                status_code=409,
            )
        return document

    @staticmethod
    def _atomic_write(path: Path, document: dict[str, object]) -> None:
        rendered = yaml.safe_dump(document, sort_keys=False)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".cloudward-values-",
                suffix=".yaml",
                delete=False,
            ) as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    async def _git(self, *arguments: str, cwd: Path | None = None) -> str:
        environment = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "git",
        }
        process = await asyncio.create_subprocess_exec(
            "git",
            *arguments,
            cwd=str(cwd) if cwd else None,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise CloudWardError(
                "GITOPS_OPERATION_TIMEOUT",
                "The bounded local GitOps operation timed out",
                status_code=504,
            ) from exc
        if process.returncode != 0:
            raise CloudWardError(
                "GITOPS_OPERATION_FAILED",
                "The fixed local Git operation failed",
                status_code=502,
                details={"operation": arguments[0] if arguments else "unknown"},
            )
        return stdout.decode("utf-8", errors="replace")[:8192]
