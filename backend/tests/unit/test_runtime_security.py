from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from kubernetes_asyncio.client.exceptions import ApiException

from app.db.models import SecurityCategory
from app.kubernetes.executor import KubernetesExecutor
from app.policies.opa import PolicyResult
from app.security.normalization import event_fingerprint, normalized_payload
from app.security.schemas import TetragonSecurityEvent
from app.security.service import ingest_security_event


def event_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "tetragon",
        "event_type": "SUSPICIOUS_PROCESS",
        "severity": "high",
        "environment": "staging",
        "namespace": "cloudward-staging",
        "pod": "cloudward-demo-abcde",
        "workload": "cloudward-demo",
        "container": "api",
        "process": {"binary": "/bin/sh", "parent_binary": "/usr/local/bin/python"},
        "policy": "cloudward-s1-unexpected-shell",
        "timestamp": "2026-08-22T00:00:00Z",
        "evidence_ref": "tetragon:node-1:1",
        "workload_labels": {"cloudward.io/demo-target": "true"},
        "secrets_or_data_exposure": False,
    }
    payload.update(overrides)
    return payload


def test_invalid_or_unsupported_event_is_rejected() -> None:
    with pytest.raises(ValueError):
        TetragonSecurityEvent.model_validate(event_payload(policy="unrelated-policy"))
    with pytest.raises(ValueError):
        TetragonSecurityEvent.model_validate(event_payload(namespace="kube-system"))
    with pytest.raises(ValueError):
        TetragonSecurityEvent.model_validate(event_payload(unexpected="raw-command"))


def test_redaction_and_server_fingerprint_are_deterministic() -> None:
    event = TetragonSecurityEvent.model_validate(
        event_payload(
            process={
                "binary": "postgres://user:password@database/private",
                "parent_binary": "token=secret-value",
            }
        )
    )
    payload = normalized_payload(event)
    assert "password" not in json.dumps(payload)
    assert "secret-value" not in json.dumps(payload)
    assert event_fingerprint(event, window_seconds=60) == event_fingerprint(
        event, window_seconds=60
    )


class FakeOPA:
    async def evaluate(self, _policy_input: object) -> PolicyResult:
        return PolicyResult(
            allowed=True,
            requires_approval=False,
            reason="controlled staging target",
            decision="ALLOW",
        )


@pytest.mark.asyncio
async def test_duplicate_events_aggregate_without_duplicate_incident(session, settings) -> None:  # type: ignore[no-untyped-def]
    event = TetragonSecurityEvent.model_validate(event_payload())
    first = await ingest_security_event(session, event, settings=settings, opa=FakeOPA())  # type: ignore[arg-type]
    second = await ingest_security_event(session, event, settings=settings, opa=FakeOPA())  # type: ignore[arg-type]
    assert not first.duplicate
    assert second.duplicate
    assert second.event.id == first.event.id
    assert second.event.dedup_count == 2


class FakeCore:
    def __init__(self, *, demo: bool = True) -> None:
        self.labels = {"cloudward.io/demo-target": "true"} if demo else {}

    async def read_namespaced_pod(self, name: str, namespace: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            metadata=SimpleNamespace(
                name=name,
                namespace=namespace,
                labels=self.labels,
                owner_references=[SimpleNamespace(controller=True, kind="ReplicaSet")],
            ),
            status=SimpleNamespace(
                phase="Running",
                conditions=[SimpleNamespace(type="Ready", status="True")],
                container_statuses=[],
            ),
        )

    async def patch_namespaced_pod(self, _name: str, _namespace: str, body: dict):  # type: ignore[no-untyped-def]
        for key, value in body["metadata"]["labels"].items():
            if value is None:
                self.labels.pop(key, None)
            else:
                self.labels[key] = value


class FakeCustom:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    async def create_namespaced_custom_object(self, **kwargs):  # type: ignore[no-untyped-def]
        body = kwargs["body"]
        name = body["metadata"]["name"]
        if name in self.objects:
            raise ApiException(status=409)
        self.objects[name] = body

    async def get_namespaced_custom_object(self, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return self.objects[kwargs["name"]]
        except KeyError as exc:
            raise ApiException(status=404) from exc

    async def delete_namespaced_custom_object(self, **kwargs):  # type: ignore[no-untyped-def]
        self.objects.pop(kwargs["name"], None)


@pytest.mark.asyncio
async def test_quarantine_is_targeted_reversible_and_wrong_namespace_is_denied() -> None:
    core = FakeCore()
    custom = FakeCustom()
    executor = KubernetesExecutor(
        core,
        SimpleNamespace(),
        allowed_namespaces=frozenset({"cloudward-staging"}),
        custom_api=custom,
    )
    result = await executor.apply_quarantine_policy(
        "cloudward-staging",
        "cloudward-demo-abcde",
        quarantine_id="a1b2c3d4e5f6",
        incident_id=str(uuid.uuid4()),
    )
    state = await executor.get_quarantine_policy_state(
        result.namespace,
        result.pod_name,
        policy_name=result.policy_name,
        quarantine_id=result.quarantine_id,
    )
    assert state.enforced
    removed = await executor.remove_quarantine_policy(
        result.namespace,
        result.pod_name,
        policy_name=result.policy_name,
        quarantine_id=result.quarantine_id,
    )
    assert not removed.policy_exists
    assert not removed.target_label_matches
    with pytest.raises(Exception):
        await executor.apply_quarantine_policy(
            "cloudward-production",
            "cloudward-demo-abcde",
            quarantine_id="a1b2c3d4e5f6",
            incident_id=str(uuid.uuid4()),
        )


def signed_headers(secret: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + nonce.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return {
        "X-CloudWard-Timestamp": timestamp,
        "X-CloudWard-Nonce": nonce,
        "X-CloudWard-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_webhook_rejects_unauthenticated_invalid_and_oversized_payloads(
    api_client, settings
) -> None:  # type: ignore[no-untyped-def]
    response = await api_client.post("/api/v1/webhooks/security/tetragon", json={})
    assert response.status_code == 401

    invalid = json.dumps({"source": "tetragon", "event_type": "DO_ANYTHING"}).encode()
    response = await api_client.post(
        "/api/v1/webhooks/security/tetragon",
        content=invalid,
        headers=signed_headers(settings.tetragon_webhook_secret.get_secret_value(), invalid),
    )
    assert response.status_code == 422

    oversized = b"x" * (settings.tetragon_webhook_max_body_bytes + 1)
    response = await api_client.post(
        "/api/v1/webhooks/security/tetragon", content=oversized
    )
    assert response.status_code == 413
