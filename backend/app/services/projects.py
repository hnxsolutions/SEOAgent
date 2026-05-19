"""
SEO Agent SaaS - Project Service
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from uuid import UUID

from app.models.project import Project
from app.schemas.projects import ProjectCreate, ProjectUpdate


class ProjectService:
    """Project service for business logic"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_project(
        self,
        project_data: ProjectCreate,
        tenant_id: UUID,
        user_id: UUID
    ) -> Project:
        """Create a new project"""
        project = Project(
            name=project_data.name,
            domain=project_data.domain,
            description=project_data.description,
            keywords=project_data.keywords,
            tenant_id=tenant_id,
            owner_id=user_id,
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project
    
    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        """Get project by ID"""
        result = await self.db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def get_tenant_projects(self, tenant_id: UUID) -> List[Project]:
        """Get all projects for a tenant"""
        result = await self.db.execute(
            select(Project).where(Project.tenant_id == tenant_id)
        )
        return result.scalars().all()
    
    async def update_project(
        self,
        project_id: UUID,
        project_data: ProjectUpdate,
        tenant_id: UUID
    ) -> Optional[Project]:
        """Update a project"""
        project = await self.get_project(project_id, tenant_id)
        if not project:
            return None
        
        update_data = project_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
        
        await self.db.commit()
        await self.db.refresh(project)
        return project
    
    async def delete_project(self, project_id: UUID, tenant_id: UUID) -> bool:
        """Delete a project"""
        project = await self.get_project(project_id, tenant_id)
        if not project:
            return False
        
        await self.db.delete(project)
        await self.db.commit()
        return True