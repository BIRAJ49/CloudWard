from pathlib import Path

import pytest

from app.errors import CloudWardError
from app.remediation.actions import ActionType
from app.runbooks import RunbookLoader

VALID = """\
id: reliability.unhealthy-pod
version: 1
environments: [local, staging]
match:
  incident_type: reliability
  conditions: [pod_unhealthy]
evidence:
  required: [kubernetes_state, readiness]
preconditions:
  max_target_pods: 1
  controller_managed: true
action:
  type: DELETE_UNHEALTHY_POD
verify:
  timeout: 120s
  conditions: [ready_replicas_restored, health_endpoint_healthy]
rollback:
  enabled: false
"""


def write_runbook(path: Path, content: str) -> RunbookLoader:
    path.mkdir()
    (path / "runbook.yaml").write_text(content, encoding="utf-8")
    return RunbookLoader(path)


def test_valid_runbook_loads_and_matches(tmp_path: Path) -> None:
    loader = write_runbook(tmp_path / "valid", VALID)
    runbooks = loader.load()
    assert len(runbooks) == 1
    assert runbooks[0].action.type == ActionType.DELETE_UNHEALTHY_POD
    assert (
        loader.match(
            incident_type="reliability",
            conditions={"pod_unhealthy"},
            environment="staging",
        ).id
        == "reliability.unhealthy-pod"
    )


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        ("DELETE_UNHEALTHY_POD", "INVALID_RUNBOOK"),
        ("SHELL_COMMAND", "INVALID_RUNBOOK"),
    ],
)
def test_unknown_or_embedded_action_rejected(tmp_path: Path, replacement: str, code: str) -> None:
    content = VALID.replace("type: DELETE_UNHEALTHY_POD", f"type: {replacement}")
    if replacement == "DELETE_UNHEALTHY_POD":
        content += "shell: kubectl delete pod arbitrary\n"
    loader = write_runbook(tmp_path / replacement.lower(), content)
    with pytest.raises(CloudWardError) as caught:
        loader.load()
    assert caught.value.code == code


def test_missing_verification_rejected(tmp_path: Path) -> None:
    verification_block = (
        "verify:\n  timeout: 120s\n"
        "  conditions: [ready_replicas_restored, health_endpoint_healthy]\n"
    )
    content = VALID.replace(verification_block, "")
    loader = write_runbook(tmp_path / "missing", content)
    with pytest.raises(CloudWardError):
        loader.load()


def test_unsupported_environment_rejected(tmp_path: Path) -> None:
    loader = write_runbook(
        tmp_path / "production", VALID.replace("[local, staging]", "[production]")
    )
    with pytest.raises(CloudWardError, match="does not support"):
        loader.load()


def test_duplicate_yaml_keys_rejected(tmp_path: Path) -> None:
    loader = write_runbook(
        tmp_path / "duplicate", VALID.replace("version: 1", "version: 1\nversion: 2")
    )
    with pytest.raises(CloudWardError, match="duplicate key"):
        loader.load()


def test_no_runbook_match_is_controlled(tmp_path: Path) -> None:
    loader = write_runbook(tmp_path / "no-match", VALID)
    loader.load()
    with pytest.raises(CloudWardError) as caught:
        loader.match(incident_type="security", conditions=set(), environment="staging")
    assert caught.value.code == "RUNBOOK_NOT_FOUND"
