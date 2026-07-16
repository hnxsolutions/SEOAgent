"""Enterprise Mission Control overview route (tenant-wide composition)."""
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.mission_control import MissionControlService

router = APIRouter()


@router.get("/overview")
async def mission_control_overview(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    """One tenant-wide snapshot of the whole AI SEO system for the dashboard."""
    service = MissionControlService(db)
    return await service.overview(current_user["tenant_id"])
