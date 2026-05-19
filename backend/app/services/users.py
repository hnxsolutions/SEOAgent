"""
SEO Agent SaaS - User Service
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from uuid import UUID

from app.models.user import User
from app.models.tenant import Tenant, tenant_members
from app.schemas.users import UserUpdate


class UserService:
    """User service for business logic"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> Optional[User]:
        """Update user profile"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        
        update_data = user_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        
        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def get_user_tenants(self, user_id: UUID) -> List[Tenant]:
        """Get all tenants the user belongs to"""
        result = await self.db.execute(
            select(Tenant)
            .join(tenant_members, Tenant.id == tenant_members.c.tenant_id)
            .where(tenant_members.c.user_id == user_id)
        )
        return result.scalars().all()
