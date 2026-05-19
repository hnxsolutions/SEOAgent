"""
SEO Agent SaaS - Billing Routes (Stripe Integration)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.core.database import get_db
from app.schemas.billing import (
    SubscriptionResponse,
    CheckoutSessionResponse,
    CheckoutSessionRequest,
)
from app.services.billing import BillingService
from app.core.security import get_current_user
from app.core.config import settings

router = APIRouter()


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get current subscription details"""
    billing_service = BillingService(db)
    subscription = await billing_service.get_subscription(current_user["user_id"])
    return subscription


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    checkout_request: CheckoutSessionRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create Stripe checkout session for subscription"""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured"
        )
    
    billing_service = BillingService(db)
    session = await billing_service.create_checkout_session(
        user_id=current_user["user_id"],
        price_id=checkout_request.price_id
    )
    
    return {"checkout_url": session["url"]}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    """Handle Stripe webhook events"""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing webhook is not configured"
        )
    
    billing_service = BillingService(db)
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = billing_service.process_webhook(payload, sig_header)
        # Process event asynchronously
        await billing_service.handle_webhook_event(event)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return {"status": "success"}


@router.delete("/subscription")
async def cancel_subscription(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Cancel current subscription"""
    billing_service = BillingService(db)
    await billing_service.cancel_subscription(current_user["user_id"])
    return {"status": "subscription cancelled"}
