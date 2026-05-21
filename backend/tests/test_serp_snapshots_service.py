from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.serp import SerpSnapshotAssetType, SerpSnapshotDevice
from app.schemas.serp_snapshots import SerpSnapshotCreate, SerpSnapshotResultInput
from app.services import serp_snapshots as serp_module
from app.services.serp_snapshots import SerpSnapshotService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeSerpRepository:
    def __init__(self, tenant_id, project_id):
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.snapshots = []
        self.results_by_snapshot = {}
        self.assets_by_snapshot = {}

    async def get_project(self, project_id, tenant_id):
        return SimpleNamespace(id=project_id, tenant_id=tenant_id) if project_id == self.project_id else None

    async def create_snapshot(self, values, results):
        snapshot = SimpleNamespace(id=uuid4(), captured_at=datetime.utcnow(), **values)
        created = [SimpleNamespace(id=uuid4(), snapshot_id=snapshot.id, **record) for record in results]
        self.snapshots.append(snapshot)
        self.results_by_snapshot[snapshot.id] = created
        return snapshot, created

    async def list_snapshots(self, project_id, tenant_id, limit=100, offset=0):
        return self.snapshots[offset : offset + limit]

    async def get_snapshot(self, snapshot_id, tenant_id):
        return next((snapshot for snapshot in self.snapshots if snapshot.id == snapshot_id), None)

    async def results(self, snapshot_id, tenant_id):
        return self.results_by_snapshot.get(snapshot_id, [])

    async def assets(self, snapshot_id, tenant_id):
        return self.assets_by_snapshot.get(snapshot_id, [])

    async def previous_snapshot(self, snapshot):
        previous = [item for item in self.snapshots if item.id != snapshot.id and item.keyword == snapshot.keyword and item.captured_at < snapshot.captured_at]
        return previous[-1] if previous else None

    async def add_asset(self, values):
        asset = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **values)
        self.assets_by_snapshot.setdefault(values["snapshot_id"], []).append(asset)
        return asset


@pytest.mark.asyncio
async def test_manual_serp_snapshot_detects_target_rank_competitors_and_screenshot(tmp_path, monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    repository = FakeSerpRepository(tenant_id, project_id)
    service = SerpSnapshotService(FakeDB())
    service.repository = repository
    monkeypatch.setattr(serp_module, "UPLOAD_ROOT", tmp_path)

    previous = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        keyword="pcd pharma company in haryana",
        country="India",
        device=SerpSnapshotDevice.desktop,
        captured_at=datetime.utcnow() - timedelta(days=7),
        observed_target_rank=9,
    )
    repository.snapshots.append(previous)

    payload = SerpSnapshotCreate(
        keyword="pcd pharma company in haryana",
        target_domain="novakoshealthcare.com",
        country="India",
        device=SerpSnapshotDevice.desktop,
        results=[
            SerpSnapshotResultInput(position=1, title="Competitor 1", url="https://competitor1.com", snippet=""),
            SerpSnapshotResultInput(position=2, title="Competitor 2", url="https://competitor2.com", snippet=""),
            SerpSnapshotResultInput(position=3, title="Competitor 3", url="https://competitor3.com", snippet=""),
            SerpSnapshotResultInput(position=4, title="Competitor 4", url="https://competitor4.com", snippet=""),
            SerpSnapshotResultInput(position=5, title="Competitor 5", url="https://competitor5.com", snippet=""),
            SerpSnapshotResultInput(position=6, title="Competitor 6", url="https://competitor6.com", snippet=""),
            SerpSnapshotResultInput(position=7, title="Novakos Healthcare", url="https://www.novakoshealthcare.com/pcd-pharma-company-in-haryana", snippet=""),
        ],
    )

    snapshot = await service.create_snapshot(project_id, tenant_id, payload)
    asset = await service.add_screenshot(snapshot["id"], tenant_id, "serp.png", "image/png", b"fake")

    assert snapshot["observed_target_rank"] == 7
    assert snapshot["previous_rank"] == 9
    assert snapshot["rank_delta"] == -2
    assert len(snapshot["competitors_above_target"]) == 6
    assert asset.asset_type == SerpSnapshotAssetType.screenshot
    assert (tmp_path / str(project_id) / str(snapshot["id"]) / "serp.png").exists()
