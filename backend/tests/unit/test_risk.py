import pytest

from app.remediation.actions import ActionType
from app.risk.engine import (
    RecommendedMode,
    RiskClassification,
    RiskContext,
    RiskEngine,
    Sensitivity,
)


def test_low_risk_staging_pod_action() -> None:
    result = RiskEngine.calculate(
        RiskContext(
            environment="staging",
            action=ActionType.DELETE_UNHEALTHY_POD,
            confidence=0.98,
        )
    )
    assert result.score == 12
    assert result.classification == RiskClassification.LOW
    assert result.recommended_mode == RecommendedMode.AUTO_EXECUTE
    assert result.score == sum(result.factors.model_dump().values())


@pytest.mark.parametrize(
    ("context", "minimum", "expected_mode"),
    [
        (
            RiskContext(
                environment="production",
                action=ActionType.REVERT_IMAGE,
                target_count=3,
                confidence=0.8,
            ),
            31,
            RecommendedMode.APPROVAL_REQUIRED,
        ),
        (
            RiskContext(
                environment="production",
                action=ActionType.REVERT_IMAGE,
                target_count=100,
                confidence=0,
                sensitivity=Sensitivity.HIGH,
                destructive_override=True,
                reversible=False,
            ),
            70,
            RecommendedMode.BLOCK_AND_ESCALATE,
        ),
        (
            RiskContext(
                environment="staging",
                action=ActionType.DELETE_UNHEALTHY_POD,
                reversible=False,
            ),
            20,
            RecommendedMode.AUTO_EXECUTE,
        ),
        (
            RiskContext(
                environment="staging",
                action=ActionType.DELETE_UNHEALTHY_POD,
                confidence=0,
            ),
            20,
            RecommendedMode.AUTO_EXECUTE,
        ),
        (
            RiskContext(
                environment="staging",
                action=ActionType.APPLY_QUARANTINE,
                sensitivity=Sensitivity.HIGH,
            ),
            20,
            RecommendedMode.AUTO_EXECUTE,
        ),
    ],
)
def test_risk_factors_raise_score(
    context: RiskContext, minimum: int, expected_mode: RecommendedMode
) -> None:
    result = RiskEngine.calculate(context)
    assert result.score >= minimum
    assert result.recommended_mode == expected_mode


def test_high_blast_radius_scores_max_category() -> None:
    result = RiskEngine.calculate(
        RiskContext(environment="staging", action=ActionType.REVERT_IMAGE, target_count=50)
    )
    assert result.factors.blast_radius == 25
