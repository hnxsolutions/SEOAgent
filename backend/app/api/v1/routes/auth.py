"""
SEO Agent SaaS - Authentication Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.core.database import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    ResetTokenCheckResponse,
    Token,
    UserCreate,
    UserResponse,
)
from app.services.auth import AuthService
from app.services.password_reset import PasswordResetError, PasswordResetService

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Register a new user"""
    auth_service = AuthService(db)
    
    # Check if user already exists
    existing_user = await auth_service.get_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    user = await auth_service.create_user(user_data)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Login and get access token"""
    auth_service = AuthService(db)
    
    # Authenticate user
    user = await auth_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    tenant_id = await auth_service.get_default_tenant_id(user.id)
    token_data = {
        "sub": user.email,
        "user_id": str(user.id),
        "tenant_id": tenant_id,
    }

    # Generate tokens
    access_token = auth_service.create_access_token(data=token_data)
    refresh_token = auth_service.create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_request: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Refresh access token"""
    auth_service = AuthService(db)
    
    # Validate refresh token
    payload = auth_service.verify_refresh_token(refresh_request.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Identity comes from the database, not from the token.
    #
    # This used to read `payload["user_id"]` directly, so a refresh token
    # without that claim raised a KeyError and the endpoint answered 500. A
    # client cannot interpret a 500 — the browser treats the refresh as failed
    # and signs the user out — and the tokens most likely to be missing a claim
    # are the ones issued before it was added, which is exactly the session
    # someone has been carrying for days.
    #
    # Looking the user up by `sub` also means a tenant assigned since the token
    # was issued is picked up here, rather than the session carrying a stale
    # tenant until the next manual login.
    email = payload.get("sub")
    user = await auth_service.get_user_by_email(email) if email else None
    if not user or not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant_id = await auth_service.get_default_tenant_id(user.id)
    access_token = auth_service.create_access_token(
        data={
            "sub": user.email,
            "user_id": str(user.id),
            "tenant_id": tenant_id,
        }
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_request.refresh_token,  # Return same refresh token
        "token_type": "bearer"
    }


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a password reset.

    **Always returns the same response.** A registered address, an unregistered
    one, a disabled account and a mail-transport failure are indistinguishable
    from the outside. Anything else would let someone submit a list of addresses
    and learn which ones have accounts here.

    For the same reason this never returns an error for a delivery problem: the
    service logs it, and the caller is told only that a link has been sent if an
    account exists.
    """
    try:
        await PasswordResetService(db).request_reset(payload.email)
    except Exception:  # pragma: no cover - defensive
        # Even an unexpected failure must not change the reply, or the shape of
        # the error becomes the oracle this endpoint exists to avoid.
        logger.exception("forgot_password_failed")
    return ForgotPasswordResponse()


@router.get("/reset-password/validate", response_model=ResetTokenCheckResponse)
async def validate_reset_token(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Whether a reset link is still usable.

    Lets the page say "this link has expired" up front instead of after the user
    has typed a new password twice. It discloses nothing: the caller already
    holds the token, and the answer is only its validity.
    """
    return ResetTokenCheckResponse(valid=await PasswordResetService(db).validate_token(token))


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set a new password using a reset token, spending the token.

    400 covers every refusal — expired, already used, never existed, or a
    password that fails validation — with one message for the token cases, so a
    stolen token cannot be probed for its exact state.
    """
    try:
        await PasswordResetService(db).reset_password(payload.token, payload.new_password)
    except PasswordResetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ResetPasswordResponse()
