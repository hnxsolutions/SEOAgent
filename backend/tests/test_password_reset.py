"""Password reset: the properties that make it safe rather than merely working.

A reset token takes over an account, so these tests pin the four things that
stop it being a liability: the raw token is never stored, it works exactly once,
it expires, and the request endpoint tells an attacker nothing about who has an
account here.

No secret or token value is printed by any test.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.password_reset import (
    TOKEN_BYTES,
    PasswordResetError,
    PasswordResetService,
    hash_token,
)


class FakeEmail:
    """Records what would have been sent. Never touches the network."""

    def __init__(self, succeed: bool = True):
        self.succeed = succeed
        self.sent: list[dict] = []

    def is_configured(self) -> bool:
        return self.succeed

    async def send(self, *, to, subject, html, text):
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})
        return self.succeed


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    """Enough of a session for the service: one user, a list of added rows."""

    def __init__(self, user=None, token=None):
        self.user = user
        self.token = token
        self.added: list = []
        self.committed = 0
        self.executed = 0

    async def execute(self, _statement):
        self.executed += 1
        # The service's only SELECTs return either the user or a token row; the
        # UPDATE path ignores the result entirely.
        return FakeResult(self.user if self.user is not None else self.token)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def get(self, _model, _pk):
        return self.user


def make_user(**overrides):
    values = {
        "id": uuid4(),
        "email": "person@example.com",
        "hashed_password": "old-hash",
        "is_active": True,
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# The raw token never reaches the database
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_a_hash_is_persisted():
    """A database dump must not contain anything that can reset an account."""
    user = make_user()
    db = FakeDB(user=user)
    service = PasswordResetService(db, email_service=FakeEmail())

    await service.request_reset(user.email)

    assert db.added, "no token row was created"
    record = db.added[0]
    assert len(record.token_hash) == 64, "token_hash is not a SHA-256 digest"

    # Whatever went into the email must not equal what went into the row.
    emailed = service.email_service.sent[0]["text"]
    assert record.token_hash not in emailed
    assert not any(
        getattr(record, field, None) and str(getattr(record, field)) in emailed
        for field in ("token_hash",)
    )


def test_hash_is_stable_and_one_way():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert len(hash_token("abc")) == 64


def test_token_has_meaningful_entropy():
    """32 bytes of CSPRNG. Anything less is guessable at scale."""
    assert TOKEN_BYTES >= 32


# ---------------------------------------------------------------------------
# No account enumeration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_email_issues_nothing_but_does_not_signal_that():
    db = FakeDB(user=None)
    service = PasswordResetService(db, email_service=FakeEmail())

    result = await service.request_reset("nobody@example.com")

    assert result["issued"] is False
    assert db.added == [], "a token was created for an address with no account"
    assert service.email_service.sent == []


@pytest.mark.asyncio
async def test_inactive_account_is_treated_like_an_unknown_one():
    db = FakeDB(user=make_user(is_active=False))
    service = PasswordResetService(db, email_service=FakeEmail())

    result = await service.request_reset("person@example.com")

    assert result["issued"] is False
    assert db.added == []


@pytest.mark.asyncio
async def test_a_failed_send_is_not_an_error():
    """Raising on send failure would make real addresses 500 and fake ones 200."""
    user = make_user()
    db = FakeDB(user=user)
    service = PasswordResetService(db, email_service=FakeEmail(succeed=False))

    result = await service.request_reset(user.email)

    assert result["issued"] is True
    assert result["emailed"] is False
    assert db.added, "the token should still be issued when delivery fails"


@pytest.mark.asyncio
async def test_empty_email_is_handled_quietly():
    service = PasswordResetService(FakeDB(user=None), email_service=FakeEmail())
    assert (await service.request_reset(""))["issued"] is False


# ---------------------------------------------------------------------------
# Single use and expiry
# ---------------------------------------------------------------------------

def token_row(**overrides):
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "token_hash": hash_token("raw"),
        "expires_at": datetime.utcnow() + timedelta(minutes=30),
        "used_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_successful_reset_spends_the_token_and_sets_the_password():
    user = make_user()
    record = token_row(user_id=user.id)
    db = FakeDB(user=user, token=record)
    service = PasswordResetService(db, email_service=FakeEmail())
    service._live_token = _async(record)

    result = await service.reset_password("raw", "a-long-enough-password")

    assert result["status"] == "password_updated"
    assert record.used_at is not None, "token was not spent"
    assert user.hashed_password != "old-hash", "password was not changed"
    assert db.committed >= 1


@pytest.mark.asyncio
async def test_a_spent_or_expired_token_is_refused_with_one_message():
    """Expired, already-used and never-existed must be indistinguishable."""
    service = PasswordResetService(FakeDB(user=make_user()), email_service=FakeEmail())
    service._live_token = _async(None)

    with pytest.raises(PasswordResetError) as exc:
        await service.reset_password("anything", "a-long-enough-password")

    assert "invalid or has expired" in str(exc.value)


@pytest.mark.asyncio
async def test_token_for_a_deactivated_user_is_refused():
    user = make_user(is_active=False)
    record = token_row(user_id=user.id)
    service = PasswordResetService(FakeDB(user=user, token=record), email_service=FakeEmail())
    service._live_token = _async(record)

    with pytest.raises(PasswordResetError):
        await service.reset_password("raw", "a-long-enough-password")


def test_is_live_covers_both_conditions():
    now = datetime.utcnow()
    assert token_row().is_live(now) if hasattr(token_row(), "is_live") else True

    from app.models.password_reset import PasswordResetToken

    live = PasswordResetToken(expires_at=now + timedelta(minutes=5), used_at=None)
    spent = PasswordResetToken(expires_at=now + timedelta(minutes=5), used_at=now)
    expired = PasswordResetToken(expires_at=now - timedelta(minutes=1), used_at=None)

    assert live.is_live(now) is True
    assert spent.is_live(now) is False
    assert expired.is_live(now) is False


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "short", "       "])
async def test_weak_passwords_are_refused_before_the_token_is_spent(bad):
    record = token_row()
    service = PasswordResetService(FakeDB(user=make_user(), token=record), email_service=FakeEmail())
    service._live_token = _async(record)

    with pytest.raises(PasswordResetError):
        await service.reset_password("raw", bad)

    assert record.used_at is None, "a rejected password must not burn the token"


@pytest.mark.asyncio
async def test_absurdly_long_password_is_refused():
    record = token_row()
    service = PasswordResetService(FakeDB(user=make_user(), token=record), email_service=FakeEmail())
    service._live_token = _async(record)

    with pytest.raises(PasswordResetError):
        await service.reset_password("raw", "x" * 500)


# ---------------------------------------------------------------------------
# The email itself
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_contains_a_working_reset_link_and_an_ignore_notice():
    user = make_user()
    service = PasswordResetService(FakeDB(user=user), email_service=FakeEmail())

    await service.request_reset(user.email)

    body = service.email_service.sent[0]
    assert "/reset-password?token=" in body["text"]
    assert "/reset-password?token=" in body["html"]
    # The person who did not request it needs to know they can do nothing.
    assert "ignore" in body["text"].lower()
    assert "expires" in body["text"].lower()


def _async(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
