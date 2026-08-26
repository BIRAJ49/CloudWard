from sqlalchemy import func, select

from app.clusters.bootstrap import seed_development_inventory
from app.config import Settings
from app.db.models import Cluster, Service


async def test_development_inventory_seed_is_idempotent(session) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        app_env="development",
        dev_auth_enabled=True,
        database_url="sqlite+aiosqlite://",
        runbooks_path="../runbooks",
        kubernetes_context="k3d-cloudward",
    )
    assert await seed_development_inventory(session, settings)
    assert not await seed_development_inventory(session, settings)
    assert await session.scalar(select(func.count()).select_from(Cluster)) == 1
    assert await session.scalar(select(func.count()).select_from(Service)) == 1
    cluster = (await session.execute(select(Cluster))).scalar_one()
    service = (await session.execute(select(Service))).scalar_one()
    assert cluster.name == "cloudward-local"
    assert cluster.status == "CONFIGURED"
    assert service.name == "cloudward-demo"
    assert service.labels["cloudward.io/demo-target"] == "true"


async def test_inventory_seed_never_runs_outside_development(session) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(app_env="test", dev_auth_enabled=True, database_url="sqlite+aiosqlite://")
    assert not await seed_development_inventory(session, settings)
    assert await session.scalar(select(func.count()).select_from(Cluster)) == 0
