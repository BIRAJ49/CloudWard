from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.alerts.schemas import AlertmanagerAlert, NormalizedAlert
from app.config import Settings
from app.demo.scenarios import get_scenario
from app.errors import CloudWardError
from app.observability.providers import TelemetryWindow
from app.remediation.actions import ActionType
from app.remediation.execution import RollbackCoordinator, RollbackDisposition, action_idempotency_key
from app.remediation.gitops import CONTROLLED_BAD_TAG, LocalGitOpsImageWriter


def test_alert_fingerprint_uses_only_stable_labels() -> None:
    now = datetime.now(UTC)
    first = AlertmanagerAlert(
        status="firing",
        labels={
            "alertname": "HighHTTPErrorRate",
            "service": "cloudward-demo-api",
            "environment": "staging",
            "namespace": "cloudward-staging",
            "pod": "pod-a",
        },
        startsAt=now,
        fingerprint="untrusted-one",
    )
    second = first.model_copy(
        update={"labels": {**first.labels, "pod": "pod-b"}, "fingerprint": "untrusted-two"}
    )
    assert NormalizedAlert.from_alertmanager(first).fingerprint == NormalizedAlert.from_alertmanager(second).fingerprint


def test_telemetry_window_rejects_unbounded_query() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        TelemetryWindow(start=now - timedelta(hours=2), end=now)


def test_chaos_catalog_has_exact_part2_safety_target() -> None:
    scenario = get_scenario("reliability.cpu-saturation")
    assert scenario.target_namespace == "cloudward-staging"
    assert scenario.target_selector == {"cloudward.io/demo-target": "true"}
    assert scenario.max_runtime_seconds <= 600


def test_settings_reject_incident_lab_namespace_override() -> None:
    with pytest.raises(ValueError):
        Settings(APP_ENV="test", INCIDENT_LAB_NAMESPACE="cloudward-production")


def test_rollback_requires_low_risk_reversible_action() -> None:
    coordinator = RollbackCoordinator(automatic_max_risk=39)
    assert coordinator.decide(
        action=ActionType.SCALE_STAGING_DEPLOYMENT,
        risk_score=20,
        rollback_enabled=True,
        policy_allows_rollback=True,
    ) == RollbackDisposition.AUTOMATIC
    assert coordinator.decide(
        action=ActionType.SCALE_STAGING_DEPLOYMENT,
        risk_score=50,
        rollback_enabled=True,
        policy_allows_rollback=True,
    ) == RollbackDisposition.AWAITING_APPROVAL
    assert coordinator.decide(
        action=ActionType.REVERT_IMAGE,
        risk_score=20,
        rollback_enabled=True,
        policy_allows_rollback=True,
    ) == RollbackDisposition.AWAITING_APPROVAL


def test_action_idempotency_key_is_canonical() -> None:
    incident_id = uuid.uuid4()
    target = {"namespace": "cloudward-staging", "deployment": "cloudward-demo"}
    first = action_idempotency_key(
        incident_id=incident_id,
        runbook_id="reliability.cpu-saturation",
        action=ActionType.SCALE_STAGING_DEPLOYMENT,
        target=target,
        attempt=1,
    )
    duplicate = action_idempotency_key(
        incident_id=incident_id,
        runbook_id="reliability.cpu-saturation",
        action=ActionType.SCALE_STAGING_DEPLOYMENT,
        target=dict(reversed(list(target.items()))),
        attempt=1,
    )
    assert first == duplicate


def test_arbitrary_scenario_is_not_in_catalog() -> None:
    with pytest.raises(CloudWardError):
        get_scenario("reliability.user-supplied-yaml")


@pytest.mark.asyncio
async def test_gitops_rollback_requires_approval_before_git_is_called() -> None:
    writer = LocalGitOpsImageWriter(
        Settings(APP_ENV="test", LOCAL_GITOPS_WRITE_ENABLED=True)
    )
    with pytest.raises(CloudWardError) as caught:
        await writer.approved_rollback(
            incident_id=uuid.uuid4(),
            recorded_previous_tag=CONTROLLED_BAD_TAG,
            approved=False,
        )
    assert caught.value.code == "GITOPS_ROLLBACK_APPROVAL_REQUIRED"


def test_gitops_writer_rejects_any_other_repository() -> None:
    with pytest.raises(ValueError):
        Settings(
            APP_ENV="test",
            LOCAL_GITOPS_WRITE_ENABLED=True,
            LOCAL_GITOPS_REPO_URL="git://example.invalid/other.git",
        )
