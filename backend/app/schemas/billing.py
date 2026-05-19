"""
SEO Agent SaaS - Billing Schemas
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class SubscriptionResponse(BaseModel):
    """Schema for subscription details"""
    id: Optional[str] = None
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    plan_name: str
    amount: float
    currency: str
    cancel_at_period_end: bool = False


class CheckoutSessionResponse(BaseModel):
    """Schema for checkout session response"""
    checkout_url: str


class CheckoutSessionRequest(BaseModel):
    """Schema for creating a checkout session."""
    price_id: str


class InvoiceResponse(BaseModel):
    """Schema for invoice details"""
    id: str
    amount_due: float
    amount_paid: float
    currency: str
    status: str
    due_date: Optional[datetime] = None
    hosted_invoice_url: Optional[str] = None
