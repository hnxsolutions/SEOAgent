"""Manual-assisted SERP snapshot tracking service."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.serp import SerpSnapshotAssetType, SerpSnapshotStatus
from app.repositories.serp_snapshots import SerpSnapshotRepository
from app.services.search_console import normalize_url

UPLOAD_ROOT = Path("var/uploads/serp-snapshots")


class SerpSnapshotService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SerpSnapshotRepository(db)

    async def create_snapshot(self, project_id: UUID, tenant_id: UUID, payload):
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        target_domain = self._normalize_domain(payload.target_domain or payload.target_url)
        target_url = normalize_url(payload.target_url) if payload.target_url else None
        result_values = []
        observed_rank = None
        for item in payload.results:
            url = normalize_url(item.url)
            domain = self._normalize_domain(url)
            is_target_domain = domain == target_domain or domain.endswith(f".{target_domain}")
            is_target_url = bool(target_url and normalize_url(url) == target_url)
            if observed_rank is None and (is_target_url or is_target_domain):
                observed_rank = item.position
            result_values.append(
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "position": item.position,
                    "title": item.title,
                    "url": url,
                    "domain": domain,
                    "snippet": item.snippet,
                    "is_target_domain": is_target_domain,
                    "is_target_url": is_target_url,
                }
            )
        status = SerpSnapshotStatus.captured if observed_rank else SerpSnapshotStatus.missing_target
        snapshot, _results = await self.repository.create_snapshot(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "keyword": payload.keyword.strip(),
                "target_url": target_url,
                "target_domain": target_domain,
                "search_engine": payload.search_engine,
                "country": payload.country.strip(),
                "city": payload.city,
                "device": payload.device,
                "language": payload.language,
                "capture_mode": payload.capture_mode,
                "observed_target_rank": observed_rank,
                "status": status,
                "notes": payload.notes,
            },
            result_values,
        )
        await self.db.commit()
        return await self.enrich(snapshot, tenant_id)

    async def list_snapshots(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        snapshots = await self.repository.list_snapshots(project_id, tenant_id, limit=limit, offset=offset)
        return [await self.enrich(snapshot, tenant_id) for snapshot in snapshots]

    async def get_snapshot(self, snapshot_id: UUID, tenant_id: UUID):
        snapshot = await self.repository.get_snapshot(snapshot_id, tenant_id)
        return await self.enrich(snapshot, tenant_id) if snapshot else None

    async def history(self, project_id: UUID, tenant_id: UUID, keyword: Optional[str] = None):
        snapshots = await self.repository.list_snapshots(project_id, tenant_id, limit=1000)
        if keyword:
            snapshots = [snapshot for snapshot in snapshots if snapshot.keyword.lower() == keyword.lower()]
        snapshots = sorted(snapshots, key=lambda item: item.captured_at)
        return [await self.enrich(snapshot, tenant_id) for snapshot in snapshots]

    async def summary(self, project_id: UUID, tenant_id: UUID):
        snapshots = await self.list_snapshots(project_id, tenant_id, limit=10)
        all_snapshots = await self.repository.list_snapshots(project_id, tenant_id, limit=1000)
        return {
            "project_id": project_id,
            "total_snapshots": len(all_snapshots),
            "keywords_tracked": len({snapshot.keyword.lower() for snapshot in all_snapshots}),
            "latest_snapshots": snapshots,
            "message": "SERP snapshots are manual evidence. Official rank tracking uses GSC average position.",
        }

    async def add_screenshot(self, snapshot_id: UUID, tenant_id: UUID, filename: str, content_type: str, content: bytes):
        snapshot = await self.repository.get_snapshot(snapshot_id, tenant_id)
        if not snapshot:
            raise ValueError("SERP snapshot not found")
        safe_name = Path(filename or "screenshot").name.replace("\\", "_").replace("/", "_")
        folder = UPLOAD_ROOT / str(snapshot.project_id) / str(snapshot.id)
        folder.mkdir(parents=True, exist_ok=True)
        path = (folder / safe_name).resolve()
        if not path.is_relative_to(folder.resolve()):
            raise ValueError("Screenshot path is not safe")
        path.write_bytes(content)
        asset = await self.repository.add_asset(
            {
                "tenant_id": snapshot.tenant_id,
                "project_id": snapshot.project_id,
                "snapshot_id": snapshot.id,
                "asset_type": SerpSnapshotAssetType.screenshot,
                "file_path": str(path),
                "original_filename": filename,
                "mime_type": content_type,
            }
        )
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def enrich(self, snapshot, tenant_id: UUID) -> dict:
        results = await self.repository.results(snapshot.id, tenant_id)
        assets = await self.repository.assets(snapshot.id, tenant_id)
        previous = await self.repository.previous_snapshot(snapshot)
        competitors = [
            result
            for result in results
            if snapshot.observed_target_rank and result.position < snapshot.observed_target_rank and not result.is_target_domain
        ]
        return {
            **snapshot.__dict__,
            "results": results,
            "assets": assets,
            "competitors_above_target": competitors,
            "previous_rank": previous.observed_target_rank if previous else None,
            "rank_delta": (
                snapshot.observed_target_rank - previous.observed_target_rank
                if previous and previous.observed_target_rank and snapshot.observed_target_rank
                else None
            ),
        }

    def _normalize_domain(self, value: Optional[str]) -> str:
        raw = (value or "").strip().lower()
        parsed = urlsplit(raw if raw.startswith(("http://", "https://")) else f"https://{raw}")
        domain = parsed.netloc or parsed.path
        return domain.removeprefix("www.").split("/", 1)[0]
