"""
SEO Agent SaaS - Project Schemas
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class ProjectBase(BaseModel):
    """Base project schema"""
    name: str
    domain: str
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    """Schema for creating a project"""
    keywords: Optional[List[str]] = None


class ProjectUpdate(BaseModel):
    """Schema for updating a project"""
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None


class ProjectResponse(ProjectBase):
    """Schema for project response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    owner_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
