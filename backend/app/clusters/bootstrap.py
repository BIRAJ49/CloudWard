"""Idempotent inventory bootstrap for local development and configured AWS deployments."""

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


async def seed_configured_inventory(session: AsyncSession, settings: Settings) -> bool:
    """Register the explicitly configured EKS cluster without AWS discovery or credentials."""

    if not settings.inventory_bootstrap_enabled:
        return False
    environment = Environment(settings.inventory_cluster_environment)
    cluster = (
        await session.execute(
            select(Cluster).where(
                Cluster.name == settings.inventory_cluster_name,
                Cluster.environment == environment,
            )
        )
    ).scalar_one_or_none()
    changed = False
    if cluster is None:
        cluster = Cluster(
            name=settings.inventory_cluster_name,
            environment=environment,
            context_name=settings.inventory_cluster_context,
            status="CONFIGURED",
            labels={
                "provider": "amazon-eks",
                "region": settings.inventory_aws_region,
                "staging_namespace": "cloudward-staging",
                "production_namespace": "cloudward-production",
                "managed_by": "cloudward-configured-bootstrap",
            },
        )
        session.add(cluster)
        await session.flush()
        changed = True
    for namespace, criticality, labels in (
        (
            "cloudward-staging",
            "low",
            {"cloudward.io/demo-target": "true", "cloudward.io/environment": "staging"},
        ),
        (
            "cloudward-production",
            "high",
            {"cloudward.io/environment": "production"},
        ),
    ):
        service = (
            await session.execute(
                select(Service).where(
                    Service.cluster_id == cluster.id,
                    Service.namespace == namespace,
                    Service.name == "cloudward-demo",
                )
            )
        ).scalar_one_or_none()
        if service is None:
            session.add(
                Service(
                    cluster_id=cluster.id,
                    name="cloudward-demo",
                    namespace=namespace,
                    deployment_name="cloudward-demo",
                    health_url=None,
                    criticality=criticality,
                    labels=labels,
                )
            )
            changed = True
    if changed:
        await record_audit(
            session,
            event_type="CONFIGURED_INVENTORY_SEEDED",
            correlation_id="configured-inventory-bootstrap",
            result="SUCCEEDED",
            metadata={
                "cluster": settings.inventory_cluster_name,
                "provider": "amazon-eks",
                "region": settings.inventory_aws_region,
                "namespaces": ["cloudward-staging", "cloudward-production"],
            },
        )
    await session.commit()
    return changed
