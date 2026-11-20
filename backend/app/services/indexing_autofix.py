"""One action that works a project's indexing backlog end to end.

By hand this is three passes in a fixed order — inspect the site for current
problems, raise a fix for each new one, then ask Google whether the earlier
fixes took — and each pass is a different button. Run out of order they appear
to contradict each other: issues fixed last week still show as open, and freshly
found ones have no fix attached.

**What "fix" means here, precisely.** A fix plan creates a planner task and,
where the issue maps to a file in a connected repository, a proposed code patch.
It does not apply the patch, open a pull request, or publish anything — those
stay behind explicit approval, deliberately. The agent finds the problem and
prepares the change; a person still decides to ship it.

Every pass is bounded by Google's URL inspection quota and reports its own
outcome, because a throttled URL in the middle of a backlog must not discard the
work either side of it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.indexing import GSCIndexingIssueStatus
from app.services.indexing import IndexingService

logger = structlog.get_logger(__name__)

#: Issues worth preparing a fix for. Anything already proposed, fixed, validated
#: or ignored has had its decision made.
PLANNABLE_STATUSES = (
    GSCIndexingIssueStatus.open,
    GSCIndexingIssueStatus.in_progress,
)


class IndexingAutofixService:
    """Inspect, raise fixes, and re-check — in the order that makes them agree."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.indexing = IndexingService(db)

    async def run(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        budget = int(limit or settings.GSC_URL_INSPECTION_MAX_URLS_PER_RUN)
        steps: List[Dict[str, Any]] = []

        steps.append(await self._inspect(project_id, tenant_id, budget))
        steps.append(await self._plan_fixes(project_id, tenant_id, budget))
        steps.append(await self._revalidate(project_id, tenant_id, budget))

        summary: Dict[str, Any] = {}
        try:
            summary = await self.indexing.summary(project_id, tenant_id)
        except Exception as exc:  # pragma: no cover - reporting only
            logger.warning("indexing_autofix_summary_failed", error=str(exc)[:200])

        failed = [s for s in steps if s["status"] == "failed"]
        return {
            "status": "completed" if not failed else "partial",
            "steps": steps,
            "issues_remaining": summary.get("issues_count"),
            "issues_by_type": summary.get("issues_by_type"),
        }

    # ------------------------------------------------------------------

    async def _inspect(self, project_id: UUID, tenant_id: UUID, budget: int) -> Dict[str, Any]:
        """Ask Google the current indexing state of the project's URLs."""
        try:
            run = await self.indexing.inspect_project(
                tenant_id=tenant_id, project_id=project_id, limit=budget
            )
            return {
                "step": "inspect_urls",
                "status": "ok",
                "detail": f"{run.inspected_url_count} URL(s) inspected"
                          + (f", {run.failed_url_count} failed" if run.failed_url_count else ""),
            }
        except Exception as exc:
            return self._failed("inspect_urls", exc)

    async def _plan_fixes(self, project_id: UUID, tenant_id: UUID, budget: int) -> Dict[str, Any]:
        """Prepare a fix for every issue that does not already have one."""
        planned = failed = 0
        try:
            for status in PLANNABLE_STATUSES:
                if planned + failed >= budget:
                    break
                issues = await self.indexing.repository.list_issues(
                    project_id, tenant_id, status=status, limit=budget
                )
                for issue in issues:
                    if planned + failed >= budget:
                        break
                    try:
                        await self.indexing.create_fix_plan(issue.id, tenant_id)
                        planned += 1
                    except Exception as exc:
                        failed += 1
                        logger.warning(
                            "indexing_autofix_plan_failed",
                            issue_id=str(issue.id),
                            error=str(exc)[:200],
                        )
        except Exception as exc:
            return self._failed("prepare_fixes", exc)

        if planned == 0 and failed == 0:
            return {
                "step": "prepare_fixes",
                "status": "skipped",
                "detail": "No issue needed a new fix plan.",
            }
        return {
            "step": "prepare_fixes",
            "status": "ok" if not failed else "partial",
            "detail": f"{planned} fix plan(s) prepared"
                      + (f", {failed} could not be prepared" if failed else ""),
            "planned": planned,
            "failed": failed,
        }

    async def _revalidate(self, project_id: UUID, tenant_id: UUID, budget: int) -> Dict[str, Any]:
        """Ask Google whether issues raised earlier are actually resolved."""
        try:
            result = await self.indexing.revalidate_open_issues(
                project_id, tenant_id, limit=budget
            )
        except Exception as exc:
            return self._failed("recheck_with_google", exc)

        if result["checked"] == 0:
            return {
                "step": "recheck_with_google",
                "status": "skipped",
                "detail": "Nothing was waiting to be re-checked.",
            }
        return {
            "step": "recheck_with_google",
            "status": "ok" if not result["failed"] else "partial",
            "detail": f"{result['checked']} re-checked · {result['resolved']} resolved · "
                      f"{result['still_failing']} still failing",
            **result,
        }

    @staticmethod
    def _failed(step: str, exc: Exception) -> Dict[str, Any]:
        logger.warning("indexing_autofix_step_failed", step=step, error=str(exc)[:200])
        return {"step": step, "status": "failed", "detail": str(exc)[:300]}
