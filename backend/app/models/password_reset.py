"""Single-use, short-lived password reset tokens.

**The raw token is never stored.** Only a SHA-256 hash of it goes in the
database, exactly as a password would be. A reset token is a bearer credential
that can take over an account, so a leaked database dump — or anyone with read
access to this table — must not be able to use what they find. The raw value
exists only in the email that was sent and in the link the user clicks.

Single use is enforced by `used_at`: a token with it set is spent, whatever its
expiry says. Expiry alone is not enough, because a link sitting in an inbox
stays valid for its whole lifetime otherwise, and reset emails get forwarded.
"""
from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PasswordResetToken(Base):
    """One reset request. Verified by hash, spent once, then inert."""

    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: SHA-256 of the raw token. Unique so a lookup is a single indexed read and
    #: a collision cannot silently map two requests onto one row.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)

    expires_at = Column(DateTime, nullable=False, index=True)
    #: Set the moment the token is redeemed. Non-null means spent.
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        # The hot path is "find the live token for this hash", so the partial
        # shape of that query is what the index serves.
        Index("ix_password_reset_lookup", "token_hash", "used_at"),
        Index("ix_password_reset_user_created", "user_id", "created_at"),
    )

    def is_live(self, now: datetime | None = None) -> bool:
        """Usable: not spent and not expired."""
        moment = now or datetime.utcnow()
        return self.used_at is None and self.expires_at > moment
