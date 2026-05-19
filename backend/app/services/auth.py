"""
SEO Agent SaaS - Authentication Service
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, select
from typing import Optional
from uuid import UUID

from app.models.user import User
from app.models.tenant import Tenant, tenant_members
from app.schemas.auth import UserCreate
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)


class AuthService:
    """Authentication service"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user"""
        user = User(
            email=user_data.email,
            full_name=user_data.full_name,
            hashed_password=get_password_hash(user_data.password),
            is_active=True,
            is_verified=False,
        )
        self.db.add(user)
        await self.db.flush()

        tenant_name = (
            f"{user_data.full_name}'s Workspace"
            if user_data.full_name
            else f"{user_data.email.split('@')[0]}'s Workspace"
        )
        tenant_slug = await self._unique_tenant_slug(user_data.email.split("@")[0])
        tenant = Tenant(
            name=tenant_name,
            slug=tenant_slug,
            owner_id=user.id,
        )
        self.db.add(tenant)
        await self.db.flush()
        await self.db.execute(
            insert(tenant_members).values(
                tenant_id=tenant.id,
                user_id=user.id,
                role="owner",
            )
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user"""
        user = await self.get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
    
    def create_access_token(self, data: dict) -> str:
        """Create access token"""
        return create_access_token(data)
    
    def create_refresh_token(self, data: dict) -> str:
        """Create refresh token"""
        return create_refresh_token(data)
    
    def verify_refresh_token(self, token: str) -> Optional[dict]:
        """Verify refresh token"""
        return verify_refresh_token(token)

    async def get_default_tenant_id(self, user_id: UUID) -> Optional[str]:
        """Return or create the user's default tenant ID for tenant-scoped tokens."""
        result = await self.db.execute(
            select(tenant_members.c.tenant_id)
            .where(tenant_members.c.user_id == user_id)
            .limit(1)
        )
        tenant_id = result.scalar_one_or_none()
        if tenant_id:
            return str(tenant_id)

        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        tenant_slug = await self._unique_tenant_slug(user.email.split("@")[0])
        tenant = Tenant(
            name=f"{user.email.split('@')[0]}'s Workspace",
            slug=tenant_slug,
            owner_id=user.id,
        )
        self.db.add(tenant)
        await self.db.flush()
        await self.db.execute(
            insert(tenant_members).values(
                tenant_id=tenant.id,
                user_id=user.id,
                role="owner",
            )
        )
        await self.db.commit()
        return str(tenant.id)

    async def _unique_tenant_slug(self, base: str) -> str:
        """Create a simple unique tenant slug from an email prefix."""
        slug_base = "".join(
            char.lower() if char.isalnum() else "-"
            for char in base
        ).strip("-") or "workspace"
        slug = slug_base
        suffix = 2
        while await self._tenant_slug_exists(slug):
            slug = f"{slug_base}-{suffix}"
            suffix += 1
        return slug

    async def _tenant_slug_exists(self, slug: str) -> bool:
        result = await self.db.execute(select(Tenant.id).where(Tenant.slug == slug))
        return result.scalar_one_or_none() is not None
