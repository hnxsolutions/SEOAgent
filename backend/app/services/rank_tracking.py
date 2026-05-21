"""GSC average-position rank tracking and movement analysis."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_console import SearchConsolePeriod
from app.repositories.rank_tracking import RankTrackingRepository
from app.schemas.rank_tracking import (
    RankTrackingKeywordRow,
    RankTrackingPageRow,
    RankTrackingRow,
)
from app.services.search_console import comparison_dates, GSCComparisonWindow


class RankTrackingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = RankTrackingRepository(db)

    async def rankings(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        movement: Optional[str] = None,
        sort: str = "highest_impressions",
        query: Optional[str] = None,
        page_url: Optional[str] = None,
        device: Optional[str] = None,
        country: Optional[str] = None,
        comparison_window: Optional[GSCComparisonWindow] = None,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[RankTrackingRow], bool]:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        window_start, window_end = self._window_dates(comparison_window, date_start, date_end)
        rows = await self.repository.list_rows(
            project_id,
            tenant_id,
            date_start=window_start,
            date_end=window_end,
            device=device,
            country=country,
            query=query,
            page_url=page_url,
        )
        ranked = self._ranking_rows(rows)
        ranked = self._filter_movement(ranked, movement)
        ranked = self._sort(ranked, sort)
        page = ranked[offset : offset + limit]
        return page, len(ranked) > offset + limit

    async def movements(self, project_id: UUID, tenant_id: UUID, **kwargs) -> tuple[list[RankTrackingRow], bool]:
        kwargs.setdefault("sort", "movement")
        return await self.rankings(project_id, tenant_id, **kwargs)

    async def pages(self, project_id: UUID, tenant_id: UUID, *, limit: int = 100, offset: int = 0, **kwargs):
        ranked, _ = await self.rankings(project_id, tenant_id, limit=10000, offset=0, **kwargs)
        by_page = self._group_rows(ranked, key=lambda item: item.page_url)
        pages = [self._page_row(page_url, items) for page_url, items in by_page.items()]
        pages.sort(key=lambda item: item.current_impressions, reverse=True)
        return pages[offset : offset + limit], len(pages) > offset + limit

    async def keywords(self, project_id: UUID, tenant_id: UUID, *, limit: int = 100, offset: int = 0, **kwargs):
        ranked, _ = await self.rankings(project_id, tenant_id, limit=10000, offset=0, **kwargs)
        by_keyword = self._group_rows(ranked, key=lambda item: item.query.lower())
        keywords = [self._keyword_row(items[0].query, items) for items in by_keyword.values()]
        keywords.sort(key=lambda item: item.current_impressions, reverse=True)
        return keywords[offset : offset + limit], len(keywords) > offset + limit

    async def summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        rows = await self.repository.list_rows(project_id, tenant_id)
        ranked = self._ranking_rows(rows)
        total_clicks = sum(row.current_clicks for row in ranked)
        total_impressions = sum(row.current_impressions for row in ranked)
        return {
            "project_id": project_id,
            "total_keywords": len({row.query.lower() for row in ranked}),
            "total_pages": len({row.page_url for row in ranked}),
            "total_rows": len(ranked),
            "improved_keywords": len([row for row in ranked if row.position_delta < -0.1]),
            "dropped_keywords": len([row for row in ranked if row.position_delta > 0.1]),
            "striking_distance_keywords": len([row for row in ranked if 8 <= row.current_position <= 20]),
            "low_ctr_keywords": len([row for row in ranked if row.current_impressions > 0 and row.current_ctr < self._expected_ctr(row.current_position) * 0.65]),
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "average_ctr": round(total_clicks / total_impressions, 6) if total_impressions else 0,
            "average_position": self._weighted_position(ranked),
            "message": None if ranked else "Connect GSC OAuth or upload CSV.",
            "top_movements": self._sort(ranked, "movement")[:10],
        }

    def _window_dates(self, comparison_window, date_start, date_end) -> tuple[Optional[datetime], Optional[datetime]]:
        if date_start or date_end:
            return date_start, date_end
        if comparison_window:
            current_start, current_end, previous_start, _previous_end = comparison_dates(comparison_window)
            return previous_start, current_end
        return None, None

    def _ranking_rows(self, rows: Iterable[object]) -> list[RankTrackingRow]:
        buckets = defaultdict(list)
        for row in rows:
            key = (
                (getattr(row, "query", "") or "").strip().lower(),
                getattr(row, "page_url", "") or "",
            )
            if key[0] and key[1]:
                buckets[key].append(row)
        ranked = []
        for (_query_key, page_url), items in buckets.items():
            current = self._aggregate_period(items, SearchConsolePeriod.current)
            previous = self._aggregate_period(items, SearchConsolePeriod.previous)
            query = str(getattr(items[0], "query", "") or "")
            ranked.append(
                RankTrackingRow(
                    query=query,
                    page_url=page_url,
                    country=self._single_or_none(getattr(item, "country", None) for item in items),
                    device=self._single_or_none(getattr(item, "device", None) for item in items),
                    search_appearance=self._single_or_none(getattr(item, "search_appearance", None) for item in items),
                    current_clicks=current["clicks"],
                    current_impressions=current["impressions"],
                    current_ctr=current["ctr"],
                    current_position=current["position"],
                    previous_clicks=previous["clicks"],
                    previous_impressions=previous["impressions"],
                    previous_ctr=previous["ctr"],
                    previous_position=previous["position"],
                    position_delta=round(current["position"] - previous["position"], 3) if previous["position"] else 0,
                    clicks_delta=current["clicks"] - previous["clicks"],
                    impressions_delta=current["impressions"] - previous["impressions"],
                    ctr_delta=round(current["ctr"] - previous["ctr"], 6),
                    date_start=min((getattr(row, "date_start", None) for row in items if getattr(row, "date_start", None)), default=None),
                    date_end=max((getattr(row, "date_end", None) for row in items if getattr(row, "date_end", None)), default=None),
                )
            )
        return ranked

    def _aggregate_period(self, rows: Iterable[object], period: SearchConsolePeriod) -> dict:
        clicks = impressions = 0
        position_sum = 0.0
        position_weight = 0
        for row in rows:
            row_period = getattr(getattr(row, "period", None), "value", getattr(row, "period", None))
            if row_period != period.value:
                continue
            row_clicks = int(getattr(row, "clicks", 0) or 0)
            row_impressions = int(getattr(row, "impressions", 0) or 0)
            clicks += row_clicks
            impressions += row_impressions
            weight = max(row_impressions, 1)
            position_sum += float(getattr(row, "position", 0) or 0) * weight
            position_weight += weight
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(clicks / impressions, 6) if impressions else 0,
            "position": round(position_sum / position_weight, 3) if position_weight else 0,
        }

    def _filter_movement(self, rows: list[RankTrackingRow], movement: Optional[str]) -> list[RankTrackingRow]:
        if movement == "improved":
            return [row for row in rows if row.position_delta < -0.1]
        if movement == "dropped":
            return [row for row in rows if row.position_delta > 0.1]
        if movement == "striking_distance":
            return [row for row in rows if 8 <= row.current_position <= 20]
        if movement == "low_ctr":
            return [row for row in rows if row.current_impressions > 0 and row.current_ctr < self._expected_ctr(row.current_position) * 0.65]
        return rows

    def _sort(self, rows: list[RankTrackingRow], sort: str) -> list[RankTrackingRow]:
        if sort == "improved":
            return sorted(rows, key=lambda row: row.position_delta)
        if sort == "dropped":
            return sorted(rows, key=lambda row: row.position_delta, reverse=True)
        if sort == "movement":
            return sorted(rows, key=lambda row: abs(row.position_delta), reverse=True)
        if sort == "clicks":
            return sorted(rows, key=lambda row: row.current_clicks, reverse=True)
        if sort == "position":
            return sorted(rows, key=lambda row: row.current_position or 999)
        return sorted(rows, key=lambda row: row.current_impressions, reverse=True)

    def _group_rows(self, rows: list[RankTrackingRow], key):
        grouped = defaultdict(list)
        for row in rows:
            grouped[key(row)].append(row)
        return grouped

    def _page_row(self, page_url: str, rows: list[RankTrackingRow]) -> RankTrackingPageRow:
        current_clicks = sum(row.current_clicks for row in rows)
        current_impressions = sum(row.current_impressions for row in rows)
        previous_clicks = sum(row.previous_clicks for row in rows)
        previous_impressions = sum(row.previous_impressions for row in rows)
        current_position = self._weighted_position(rows)
        previous_position = self._weighted_position(rows, previous=True)
        return RankTrackingPageRow(
            page_url=page_url,
            query_count=len({row.query.lower() for row in rows}),
            current_clicks=current_clicks,
            current_impressions=current_impressions,
            current_ctr=round(current_clicks / current_impressions, 6) if current_impressions else 0,
            current_position=current_position,
            previous_clicks=previous_clicks,
            previous_impressions=previous_impressions,
            previous_ctr=round(previous_clicks / previous_impressions, 6) if previous_impressions else 0,
            previous_position=previous_position,
            position_delta=round(current_position - previous_position, 3) if previous_position else 0,
            clicks_delta=current_clicks - previous_clicks,
            impressions_delta=current_impressions - previous_impressions,
        )

    def _keyword_row(self, query: str, rows: list[RankTrackingRow]) -> RankTrackingKeywordRow:
        page = self._page_row(query, rows)
        return RankTrackingKeywordRow(
            query=query,
            page_count=len({row.page_url for row in rows}),
            current_clicks=page.current_clicks,
            current_impressions=page.current_impressions,
            current_ctr=page.current_ctr,
            current_position=page.current_position,
            previous_clicks=page.previous_clicks,
            previous_impressions=page.previous_impressions,
            previous_ctr=page.previous_ctr,
            previous_position=page.previous_position,
            position_delta=page.position_delta,
            clicks_delta=page.clicks_delta,
            impressions_delta=page.impressions_delta,
        )

    def _weighted_position(self, rows: list[RankTrackingRow], previous: bool = False) -> float:
        numerator = 0.0
        denominator = 0
        for row in rows:
            impressions = row.previous_impressions if previous else row.current_impressions
            position = row.previous_position if previous else row.current_position
            weight = max(impressions, 1) if position else 0
            numerator += position * weight
            denominator += weight
        return round(numerator / denominator, 3) if denominator else 0

    def _expected_ctr(self, position: float) -> float:
        if position <= 1:
            return 0.28
        if position <= 3:
            return 0.1
        if position <= 10:
            return 0.04
        if position <= 20:
            return 0.02
        return 0.01

    def _single_or_none(self, values: Iterable[Optional[str]]) -> Optional[str]:
        distinct = {value for value in values if value}
        return next(iter(distinct)) if len(distinct) == 1 else None
