"""Opt-in live dependency contracts.

Run with CLOUDWARD_INTEGRATION=1 and URLs reachable from the test process. These
tests intentionally do not run against accidental developer infrastructure.
"""

from __future__ import annotations

import os

import pytest
from celery import Celery
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.policies.opa import OPAClient, PolicyInput, TargetInput
from app.remediation.actions import ActionType
from app.risk.engine import RiskFactors
from app.tasks import HEALTHCHECK_QUEUE, HEALTHCHECK_TASK

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("CLOUDWARD_INTEGRATION") != "1",
        reason="set CLOUDWARD_INTEGRATION=1 for live dependency tests",
    ),
]


@pytest.mark.asyncio
async def test_postgresql_round_trip() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_round_trip() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    key = "cloudward:integration:redis"
    try:
        await redis.set(key, "ok", ex=30)
        assert await redis.get(key) == "ok"
        await redis.delete(key)
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_opa_low_risk_contract() -> None:
    policy_input = PolicyInput(
        environment="staging",
        action=ActionType.DELETE_UNHEALTHY_POD,
        risk_score=12,
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
            pod_name="cloudward-demo-integration",
            labels={"cloudward.io/demo-target": "true"},
            controller_managed=True,
            target_pods=1,
        ),
    )
    result = await OPAClient(
        os.environ["OPA_URL"], "/v1/data/cloudward/remediation/decision"
    ).evaluate(policy_input)
    assert result.allowed, result.reason


def test_celery_worker_redis_round_trip() -> None:
    broker = os.environ["REDIS_URL"]
    backend = os.getenv("CELERY_RESULT_BACKEND", broker)
    publisher = Celery("cloudward-integration", broker=broker, backend=backend)
    result = publisher.send_task(
        HEALTHCHECK_TASK,
        kwargs={"value": "backend-integration"},
        queue=HEALTHCHECK_QUEUE,
    )
    assert result.get(timeout=20)["echo"] == "backend-integration"
