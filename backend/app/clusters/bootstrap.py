"""Idempotent local inventory bootstrap for the development demo."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.models import Cluster, Environment, Service


async def seed_development_inventory(session: AsyncSession, settings: Settings) -> bool:
    """Create the known local cluster/service only in explicit development mode.

    Production/staging inventory remains controlled data and is never fabricated.
    Returns whether any row was created, which makes idempotency directly testable.
    """

    if settings.app_env != "development":
        return False
    cluster = (
        await session.execute(
            select(Cluster).where(
                Cluster.name == "cloudward-local", Cluster.environment == Environment.LOCAL
            )
        )
    ).scalar_one_or_none()
    changed = False
    if cluster is None:
        cluster = Cluster(
            name="cloudward-local",
            environment=Environment.LOCAL,
            context_name=settings.kubernetes_context or "k3d-cloudward",
            status="CONFIGURED",
            labels={"provider": "k3d", "managed_by": "cloudward-development-bootstrap"},
        )
        session.add(cluster)
        await session.flush()
        changed = True
    service = (
        await session.execute(
            select(Service).where(
                Service.cluster_id == cluster.id,
                Service.namespace == "cloudward-staging",
                Service.name == "cloudward-demo",
            )
        )
    ).scalar_one_or_none()
    if service is None:
        session.add(
            Service(
                cluster_id=cluster.id,
                name="cloudward-demo",
                namespace="cloudward-staging",
                deployment_name="cloudward-demo",
                health_url=None,
                criticality="low",
                labels={"cloudward.io/demo-target": "true"},
            )
        )
        changed = True
    if changed:
        await record_audit(
            session,
            event_type="DEVELOPMENT_INVENTORY_SEEDED",
            correlation_id="development-bootstrap",
            result="SUCCEEDED",
            metadata={
                "cluster": "cloudward-local",
                "service": "cloudward-demo",
                "namespace": "cloudward-staging",
            },
        )
    await session.commit()
    return changed
