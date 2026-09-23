import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(
    shutil.which("helm") is None, reason="Helm is required for chart contract validation"
)
def test_agent_chart_renders_no_privileged_or_mutating_rbac():
    helm = shutil.which("helm")
    assert helm is not None
    rendered = subprocess.run(  # noqa: S603 - fixed, read-only chart render
        [
            helm,
            "template",
            "test",
            str(ROOT / "helm/cloudward-agent"),
            "--namespace",
            "cloudward-system",
            "--set",
            "enabled=true",
            "--set-string",
            "clusterId=11111111-1111-4111-8111-111111111111",
            "--set-string",
            "controlPlaneUrl=https://cloudward.example",
            "--set-string",
            "image.digest=sha256:" + "1" * 64,
            "--set-string",
            "controlPlaneCIDRs[0]=198.51.100.10/32",
            "--set-string",
            "kubernetesApiCIDRs[0]=10.0.0.10/32",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    objects = list(yaml.safe_load_all(rendered.stdout))
    assert not any(
        item["kind"] in {"ClusterRole", "ClusterRoleBinding", "Secret", "Service", "Ingress"}
        for item in objects
    )
    roles = [item for item in objects if item["kind"] == "Role"]
    assert roles
    for role in roles:
        assert role["metadata"]["namespace"] == "cloudward-staging"
        for rule in role["rules"]:
            assert set(rule["verbs"]) <= {"get", "list"}
            assert set(rule["resources"]) <= {"pods", "deployments"}
    deployment = next(item for item in objects if item["kind"] == "Deployment")
    spec = deployment["spec"]["template"]["spec"]
    assert not spec["automountServiceAccountToken"]
    container = spec["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"]
    assert not container["securityContext"]["allowPrivilegeEscalation"]
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["image"].endswith("@sha256:" + "1" * 64)
    network = next(item for item in objects if item["kind"] == "NetworkPolicy")
    assert network["spec"]["ingress"] == []
