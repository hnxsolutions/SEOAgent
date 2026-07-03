"""CLI runner for one production scheduler tick.

Use this from cron or the optional Docker scheduler service:
    python -m app.jobs.scheduler_tick
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.core.database import get_db_session
from app.services.scheduler import SchedulerService


async def run(limit: int = 50) -> dict[str, Any]:
    async with get_db_session() as db:
        result = await SchedulerService(db).tick_with_monitor_details(limit=limit)
        await db.commit()
        return _summary_payload(result)


def _summary_payload(result: dict[str, Any]) -> dict[str, Any]:
    runs = list(result.get("runs") or [])
    gsc_jobs = list(result.get("gsc_monitor_jobs") or [])
    return {
        "due_count": int(result.get("due_count") or 0),
        "runs_created": int(result.get("runs_created") or 0),
        "run_ids": [str(getattr(item, "id", "")) for item in runs],
        "gsc_monitor_due_count": int(result.get("gsc_monitor_due_count") or 0),
        "gsc_monitor_jobs_created": int(result.get("gsc_monitor_jobs_created") or 0),
        "gsc_sync_job_ids": [str(getattr(item, "id", "")) for item in gsc_jobs],
        "gsc_sync_job_statuses": [_enum_value(getattr(item, "status", None)) for item in gsc_jobs],
    }


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one SEOAgent scheduler tick.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum due schedules and monitor settings to evaluate.")
    args = parser.parse_args()
    limit = max(1, min(args.limit, 200))
    print(json.dumps(asyncio.run(run(limit=limit)), sort_keys=True))


if __name__ == "__main__":
    main()
