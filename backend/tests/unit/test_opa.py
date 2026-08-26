import httpx
import pytest

from app.policies.opa import OPAClient, PolicyInput, TargetInput
from app.remediation.actions import ActionType
from app.risk.engine import RiskFactors


def input_payload(score: int = 12) -> PolicyInput:
    return PolicyInput(
        environment="staging",
        action=ActionType.DELETE_UNHEALTHY_POD,
        risk_score=score,
        risk_factors=RiskFactors(
            environment=4,
            blast_radius=3,
            destructiveness=3,
            reversibility=2,
            uncertainty=0,
            sensitivity=0,
        ),
        confidence=0.98,
        blast_radius=1,
        reversible=True,
        service_criticality="low",
        target=TargetInput(
            namespace="cloudward-staging",
            pod_name="demo-abc",
            labels={"cloudward.io/demo-target": "true"},
            controller_managed=True,
            target_pods=1,
        ),
    )


@pytest.mark.asyncio
async def test_valid_opa_decision_is_parsed_and_input_contract_sent() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "result": {
                    "allowed": True,
                    "requires_approval": False,
                    "reason": "safe staging action",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await OPAClient(
            "http://opa:8181", "/v1/data/cloudward/remediation/decision", client=http
        ).evaluate(input_payload())
    assert result.allowed
    sent = captured["input"]
    assert isinstance(sent, dict)
    assert sent["risk_score"] == sum(sent["risk_factors"].values())
    assert sent["target"]["namespace"] == "cloudward-staging"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={}),
        httpx.Response(200, json={"result": {"allowed": True}}),
        httpx.Response(500, json={"error": "broken"}),
    ],
)
async def test_invalid_undefined_or_failed_opa_response_denies(response: httpx.Response) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as http:
        result = await OPAClient(
            "http://opa:8181", "/v1/data/cloudward/remediation/decision", client=http
        ).evaluate(input_payload())
    assert not result.allowed
    assert result.error_code


@pytest.mark.asyncio
async def test_opa_transport_error_denies() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        result = await OPAClient(
            "http://opa:8181", "/v1/data/cloudward/remediation/decision", client=http
        ).evaluate(input_payload())
    assert not result.allowed
    assert result.error_code == "OPA_UNAVAILABLE"


def test_policy_input_digest_is_deterministic() -> None:
    assert input_payload().digest() == input_payload().digest()
    assert len(input_payload().digest()) == 64
