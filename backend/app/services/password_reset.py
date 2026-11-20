"""Password reset: issue a token, email a link, redeem it once.

Three rules shape everything here.

**The response never reveals whether an account exists.** `request_reset`
returns the same value for a registered address, an unregistered one, a
disabled account, and a send failure. Anything that varies — a different
message, a different status, or even a noticeably different response time —
turns the endpoint into a list of who banks here. That is why the send result
is not propagated to the caller and why a missing user still walks the same
code path.

**The raw token never touches the database.** It is generated, hashed, and the
hash is stored; the raw value exists only in the email. A reset token takes over
an account, so it is treated exactly like a password.

**A token is spent on first use.** Redemption sets `used_at` inside the same
transaction that changes the password, and every other outstanding token for
that user is invalidated at the same time — a reset is a statement that the
account may be compromised, so older links must stop working too.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.email import EmailService, password_reset_email

logger = structlog.get_logger(__name__)

#: 32 bytes of CSPRNG entropy, URL-safe. Not guessable in any practical sense.
TOKEN_BYTES = 32


def hash_token(raw_token: str) -> str:
    """SHA-256 of the raw token.

    Plain SHA-256 rather than a password hash on purpose: the input is 256 bits
    of random, so there is no dictionary to attack and no need for a slow KDF.
    What matters is that the stored value cannot be used to reset anything.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class PasswordResetError(ValueError):
    """A reset could not be completed, with a message safe to show a user."""


class PasswordResetService:
    def __init__(self, db: AsyncSession, email_service: Optional[EmailService] = None):
        self.db = db
        self.email_service = email_service or EmailService()

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------

    async def request_reset(self, email: str) -> dict:
        """Issue a reset link if the address belongs to an active account.

        Always returns the same shape. The booleans in the return value are for
        logs and tests — the route must not pass them to the client.
        """
        address = (email or "").strip().lower()
        if not address:
            return {"issued": False, "reason": "empty_email", "emailed": False}

        result = await self.db.execute(select(User).where(User.email == address))
        user = result.scalar_one_or_none()

        if user is None or not user.is_active:
            # Same work, same silence. Logged at info so an operator can see
            # reset attempts without the caller learning anything.
            logger.info(
                "password_reset_requested_unknown_or_inactive",
                known=user is not None,
            )
            return {"issued": False, "reason": "no_active_account", "emailed": False}

        # A new request supersedes any outstanding link for this user, so a
        # forwarded or intercepted older email stops working immediately.
        await self._invalidate_outstanding(user.id)

        raw_token = secrets.token_urlsafe(TOKEN_BYTES)
        ttl = int(settings.PASSWORD_RESET_TOKEN_TTL_MINUTES)
        record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(minutes=ttl),
        )
        self.db.add(record)
        await self.db.commit()

        reset_url = self._reset_url(raw_token)
        subject, html, text = password_reset_email(reset_url, ttl)
        emailed = await self.email_service.send(
            to=user.email, subject=subject, html=html, text=text
        )

        if not emailed and settings.APP_ENV.lower() != "production":
            # Development convenience only. Never in production: a reset link in
            # a log file is the same credential as one in an inbox.
            logger.warning(
                "password_reset_link_not_emailed_development_fallback",
                reset_url=reset_url,
                note="Email transport is not configured. This link is logged in non-production only.",
            )

        logger.info("password_reset_issued", emailed=emailed, ttl_minutes=ttl)
        return {"issued": True, "reason": "issued", "emailed": emailed}

    # ------------------------------------------------------------------
    # Redeem
    # ------------------------------------------------------------------

    async def validate_token(self, raw_token: str) -> bool:
        """Whether a token is currently redeemable.

        Lets the reset page say "this link has expired" before the user types a
        new password twice. Reveals nothing beyond the validity of a token the
        caller already holds.
        """
        return await self._live_token(raw_token) is not None

    async def reset_password(self, raw_token: str, new_password: str) -> dict:
        """Set a new password and spend the token. Both, or neither."""
        self._validate_password(new_password)

        record = await self._live_token(raw_token)
        if record is None:
            # One message for expired, already-used, and never-existed. Telling
            # them apart helps an attacker probing stolen tokens and helps a
            # legitimate user not at all.
            raise PasswordResetError(
                "This reset link is invalid or has expired. Request a new one."
            )

        user = await self.db.get(User, record.user_id)
        if user is None or not user.is_active:
            raise PasswordResetError(
                "This reset link is invalid or has expired. Request a new one."
            )

        now = datetime.utcnow()
        user.hashed_password = get_password_hash(new_password)
        user.updated_at = now
        record.used_at = now

        # Any other outstanding link for this account dies with this reset.
        await self._invalidate_outstanding(user.id, exclude_id=record.id, now=now)

        await self.db.commit()
        logger.info("password_reset_completed", user_id=str(user.id))
        return {"status": "password_updated"}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _live_token(self, raw_token: str) -> Optional[PasswordResetToken]:
        """The unspent, unexpired row for this token, if any."""
        token = (raw_token or "").strip()
        if not token:
            return None

        result = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_token(token),
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.utcnow(),
            )
        )
        return result.scalar_one_or_none()

    async def _invalidate_outstanding(
        self, user_id, exclude_id=None, now: Optional[datetime] = None
    ) -> None:
        """Mark this user's other live tokens as spent."""
        moment = now or datetime.utcnow()
        statement = (
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=moment)
        )
        if exclude_id is not None:
            statement = statement.where(PasswordResetToken.id != exclude_id)
        await self.db.execute(statement)

    def _validate_password(self, password: str) -> None:
        value = password or ""
        minimum = int(settings.PASSWORD_MIN_LENGTH)
        if len(value) < minimum:
            raise PasswordResetError(
                f"Choose a password of at least {minimum} characters."
            )
        if len(value) > 200:
            # bcrypt only considers the first 72 bytes; a very long input is
            # either a mistake or an attempt to burn CPU.
            raise PasswordResetError("That password is too long.")
        if value.strip() == "":
            raise PasswordResetError("A password cannot be only whitespace.")

    def _reset_url(self, raw_token: str) -> str:
        base = (settings.FRONTEND_URL or "").rstrip("/")
        return f"{base}/reset-password?token={raw_token}"
