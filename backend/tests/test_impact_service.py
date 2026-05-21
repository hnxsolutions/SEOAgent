from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.impact import (
    SeoImpactExperimentStatus,
    SeoImpactExperimentType,
    SeoImpactOutcome,
    SeoImpactSnapshotType,
    SeoImpactSourceType,
)
from app.models.search_console import SearchConsoleSourceType
from app.schemas.impact import SeoImpactExperimentCreate
from app.services.impact import SeoImpactService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeImpactRepository:
    def __init__(self, tenant_id, project_id):
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.experiment = None
        self.snapshots = []
        self.results = []

    async def get_project(self, project_id, tenant_id):
        return SimpleNamespace(id=project_id, tenant_id=tenant_id) if project_id == self.project_id else None

    async def create_experiment(self, values):
        self.experiment = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
        return self.experiment

    async def list_experiments(self, project_id, tenant_id, limit=100, offset=0):
        return [self.experiment] if self.experiment else []

    async def get_experiment(self, experiment_id, tenant_id):
        return self.experiment if self.experiment and self.experiment.id == experiment_id else None

    async def set_status(self, experiment, status):
        experiment.status = status
        return experiment

    async def update_experiment(self, experiment, values):
        for key, value in values.items():
            setattr(experiment, key, value)
        return experiment

    async def rows_for_window(self, experiment, date_start, date_end):
        if date_end <= datetime(2026, 5, 7):
            return [metric_row(experiment, clicks=3, impressions=100, ctr=0.03, position=14.2)]
        return [metric_row(experiment, clicks=12, impressions=160, ctr=0.075, position=8.9)]

    async def create_snapshot(self, values):
        snapshot = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **values)
        self.snapshots.append(snapshot)
        return snapshot

    async def latest_snapshot(self, experiment_id, snapshot_type):
        matching = [item for item in self.snapshots if item.experiment_id == experiment_id and item.snapshot_type == snapshot_type]
        return matching[-1] if matching else None

    async def create_result(self, values):
        result = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **values)
        self.results.append(result)
        return result

    async def list_results(self, project_id, tenant_id):
        return self.results

    async def ready_for_review(self, now, limit=100):
        return []


def metric_row(experiment, clicks, impressions, ctr, position):
    return SimpleNamespace(
        tenant_id=experiment.tenant_id,
        project_id=experiment.project_id,
        query=experiment.target_query,
        page_url=experiment.target_page_url,
        clicks=clicks,
        impressions=impressions,
        ctr=ctr,
        position=position,
        source_type=SearchConsoleSourceType.gsc_api,
    )


@pytest.mark.asyncio
async def test_impact_experiment_lifecycle_improved_outcome():
    tenant_id = uuid4()
    project_id = uuid4()
    repository = FakeImpactRepository(tenant_id, project_id)
    service = SeoImpactService(FakeDB())
    service.repository = repository

    experiment = await service.create_experiment(
        tenant_id,
        SeoImpactExperimentCreate(
            project_id=project_id,
            experiment_type=SeoImpactExperimentType.metadata_update,
            source_type=SeoImpactSourceType.manual,
            target_page_url="https://example.com/pcd-pharma-company-in-haryana",
            target_query="pcd pharma company in haryana",
            baseline_start_date=datetime(2026, 5, 1),
            baseline_end_date=datetime(2026, 5, 7),
            review_start_date=datetime(2026, 5, 15),
            review_end_date=datetime(2026, 5, 21),
        ),
    )
    baseline = await service.capture_baseline(experiment.id, tenant_id)
    monitoring = await service.mark_action_applied(experiment.id, tenant_id, action_date=datetime(2026, 5, 8))
    monitoring_status = monitoring.status
    result = await service.evaluate(experiment.id, tenant_id)

    assert baseline.snapshot_type == SeoImpactSnapshotType.baseline
    assert monitoring_status == SeoImpactExperimentStatus.monitoring
    assert result.outcome == SeoImpactOutcome.improved
    assert result.clicks_delta == 9
    assert result.position_delta == -5.3
