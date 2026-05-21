"""SEO impact experiment service."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.impact import (
    SeoImpactDataSource,
    SeoImpactExperimentStatus,
    SeoImpactOutcome,
    SeoImpactSnapshotType,
)
from app.models.search_console import SearchConsoleSourceType
from app.repositories.impact import SeoImpactRepository
from app.services.search_console import normalize_url

MISSING_GSC_MESSAGE = "Connect GSC OAuth or upload Search Console CSV to track rank impact."


class SeoImpactService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SeoImpactRepository(db)

    async def create_experiment(self, tenant_id: UUID, payload) :
        project = await self.repository.get_project(payload.project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        values = payload.model_dump()
        values["tenant_id"] = tenant_id
        values["target_page_url"] = normalize_url(values["target_page_url"])
        values["status"] = SeoImpactExperimentStatus.baseline_pending
        experiment = await self.repository.create_experiment(values)
        await self.db.commit()
        await self.db.refresh(experiment)
        return experiment

    async def list_experiments(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        return await self.repository.list_experiments(project_id, tenant_id, limit=limit, offset=offset)

    async def get_experiment(self, experiment_id: UUID, tenant_id: UUID):
        return await self.repository.get_experiment(experiment_id, tenant_id)

    async def capture_baseline(self, experiment_id: UUID, tenant_id: UUID):
        experiment = await self._get_required(experiment_id, tenant_id)
        snapshot = await self._capture_snapshot(
            experiment,
            SeoImpactSnapshotType.baseline,
            experiment.baseline_start_date,
            experiment.baseline_end_date,
        )
        status = SeoImpactExperimentStatus.baseline_captured if snapshot.impressions else SeoImpactExperimentStatus.failed
        await self.repository.set_status(experiment, status)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    async def mark_action_applied(self, experiment_id: UUID, tenant_id: UUID, action_date: datetime | None = None):
        experiment = await self._get_required(experiment_id, tenant_id)
        action_date = action_date or datetime.utcnow()
        review_start = experiment.review_start_date or action_date
        review_end = experiment.review_end_date or action_date + timedelta(days=experiment.review_after_days)
        updated = await self.repository.update_experiment(
            experiment,
            {
                "action_date": action_date,
                "review_start_date": review_start,
                "review_end_date": review_end,
                "status": SeoImpactExperimentStatus.monitoring,
            },
        )
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def evaluate(self, experiment_id: UUID, tenant_id: UUID):
        experiment = await self._get_required(experiment_id, tenant_id)
        baseline = await self.repository.latest_snapshot(experiment.id, SeoImpactSnapshotType.baseline)
        if not baseline:
            baseline = await self.capture_baseline(experiment.id, tenant_id)
        if not baseline.impressions:
            result = await self._create_result(experiment, baseline, None, SeoImpactOutcome.inconclusive, MISSING_GSC_MESSAGE)
            await self.repository.set_status(experiment, SeoImpactExperimentStatus.inconclusive)
            await self.db.commit()
            return result
        review_start = experiment.review_start_date or experiment.action_date or datetime.utcnow()
        review_end = experiment.review_end_date or (review_start + timedelta(days=experiment.review_after_days))
        followup = await self._capture_snapshot(experiment, SeoImpactSnapshotType.followup, review_start, review_end)
        outcome, summary = self._outcome(baseline, followup)
        result = await self._create_result(experiment, baseline, followup, outcome, summary)
        await self.repository.set_status(
            experiment,
            SeoImpactExperimentStatus.completed if outcome != SeoImpactOutcome.inconclusive else SeoImpactExperimentStatus.inconclusive,
        )
        await self.db.commit()
        await self.db.refresh(result)
        return result

    async def evaluate_ready_experiments(self, now: datetime | None = None, limit: int = 100):
        ready = await self.repository.ready_for_review(now or datetime.utcnow(), limit=limit)
        results = []
        for experiment in ready:
            results.append(await self.evaluate(experiment.id, experiment.tenant_id))
        return results

    async def summary(self, project_id: UUID, tenant_id: UUID):
        experiments = await self.repository.list_experiments(project_id, tenant_id, limit=1000)
        results = await self.repository.list_results(project_id, tenant_id)
        return {
            "project_id": project_id,
            "total_experiments": len(experiments),
            "by_status": dict(Counter(self._enum_value(item.status) for item in experiments)),
            "by_outcome": dict(Counter(self._enum_value(item.outcome) for item in results)),
            "ready_for_review": len([item for item in experiments if self._enum_value(item.status) == "ready_for_review"]),
            "message": None if experiments else MISSING_GSC_MESSAGE,
        }

    async def _capture_snapshot(self, experiment, snapshot_type, date_start, date_end):
        rows = await self.repository.rows_for_window(experiment, date_start, date_end)
        aggregate = self._aggregate(rows)
        source = self._data_source(rows)
        return await self.repository.create_snapshot(
            {
                "tenant_id": experiment.tenant_id,
                "project_id": experiment.project_id,
                "experiment_id": experiment.id,
                "snapshot_type": snapshot_type,
                "date_start": date_start,
                "date_end": date_end,
                "query": experiment.target_query,
                "page_url": experiment.target_page_url,
                "clicks": aggregate["clicks"],
                "impressions": aggregate["impressions"],
                "ctr": aggregate["ctr"],
                "position": aggregate["position"],
                "data_source": source,
            }
        )

    async def _create_result(self, experiment, baseline, followup, outcome, summary):
        clicks_delta = (followup.clicks if followup else 0) - baseline.clicks
        impressions_delta = (followup.impressions if followup else 0) - baseline.impressions
        ctr_delta = (followup.ctr if followup else 0) - baseline.ctr
        position_delta = (followup.position if followup else 0) - baseline.position if followup and baseline.position else 0
        return await self.repository.create_result(
            {
                "tenant_id": experiment.tenant_id,
                "project_id": experiment.project_id,
                "experiment_id": experiment.id,
                "clicks_delta": clicks_delta,
                "impressions_delta": impressions_delta,
                "ctr_delta": round(ctr_delta, 6),
                "position_delta": round(position_delta, 3),
                "percentage_clicks_change": self._pct(clicks_delta, baseline.clicks),
                "percentage_impressions_change": self._pct(impressions_delta, baseline.impressions),
                "outcome": outcome,
                "confidence_score": self._confidence(baseline, followup),
                "summary": summary,
            }
        )

    def _aggregate(self, rows: Iterable[object]) -> dict:
        clicks = impressions = 0
        position_sum = 0.0
        weight_sum = 0
        for row in rows:
            row_clicks = int(getattr(row, "clicks", 0) or 0)
            row_impressions = int(getattr(row, "impressions", 0) or 0)
            clicks += row_clicks
            impressions += row_impressions
            weight = max(row_impressions, 1)
            position_sum += float(getattr(row, "position", 0) or 0) * weight
            weight_sum += weight
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(clicks / impressions, 6) if impressions else 0,
            "position": round(position_sum / weight_sum, 3) if weight_sum else 0,
        }

    def _outcome(self, baseline, followup) -> tuple[SeoImpactOutcome, str]:
        if not followup.impressions:
            return SeoImpactOutcome.inconclusive, MISSING_GSC_MESSAGE
        position_delta = followup.position - baseline.position if baseline.position else 0
        clicks_delta = followup.clicks - baseline.clicks
        ctr_delta = followup.ctr - baseline.ctr
        if position_delta <= -0.5 or clicks_delta >= 3 or ctr_delta >= 0.01:
            return SeoImpactOutcome.improved, "Follow-up GSC metrics improved versus baseline."
        if position_delta >= 0.5 or clicks_delta <= -3 or ctr_delta <= -0.01:
            return SeoImpactOutcome.declined, "Follow-up GSC metrics declined versus baseline."
        return SeoImpactOutcome.neutral, "Follow-up GSC metrics were broadly neutral versus baseline."

    def _data_source(self, rows) -> SeoImpactDataSource:
        if any(self._enum_value(getattr(row, "source_type", "")) == SearchConsoleSourceType.gsc_api.value for row in rows):
            return SeoImpactDataSource.gsc_api
        if rows:
            return SeoImpactDataSource.csv_import
        return SeoImpactDataSource.manual

    def _pct(self, delta: float, baseline: float):
        return round(delta / baseline, 4) if baseline else None

    def _confidence(self, baseline, followup) -> float:
        impressions = (baseline.impressions or 0) + (getattr(followup, "impressions", 0) or 0)
        if impressions >= 1000:
            return 85
        if impressions >= 100:
            return 68
        if impressions > 0:
            return 45
        return 10

    async def _get_required(self, experiment_id: UUID, tenant_id: UUID):
        experiment = await self.repository.get_experiment(experiment_id, tenant_id)
        if not experiment:
            raise ValueError("SEO impact experiment not found")
        return experiment

    def _enum_value(self, value) -> str:
        return value.value if hasattr(value, "value") else str(value)
