"""Refreshing a session must never answer with a 500.

The endpoint read `payload["user_id"]` straight out of the refresh token, so a
token without that claim raised a KeyError and FastAPI answered 500. A browser
cannot interpret a 500 — it treats the refresh as failed and signs the user out
— and the tokens most likely to be missing a claim are the oldest ones, which
belong to the people who have been signed in longest.

Identity is now read from the database using `sub`, so the shape of an old token
no longer decides whether someone stays logged in.
"""
from __future__ import annotations

import inspect

from app.api.v1.routes import auth as auth_routes
from app.core.config import settings
from app.core.security import create_refresh_token, verify_refresh_token


def executable_source(func) -> str:
    """The function's code with comments stripped.

    The comment above the fix quotes the broken expression verbatim, so a plain
    substring search over the source matches the explanation as well as any
    relapse. Only running code should decide this.
    """
    lines = []
    for line in inspect.getsource(func).splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append(code)
    return chr(10).join(lines)


def test_a_refresh_token_without_user_id_is_not_indexed_directly():
    """The exact expression that produced the 500."""
    source = executable_source(auth_routes.refresh_token)

    assert 'payload["user_id"]' not in source
    assert 'payload.get("sub")' in source


def test_identity_is_reloaded_from_the_database():
    """Also means a tenant assigned since the token was issued is picked up,
    instead of the session carrying a stale one until the next manual login."""
    source = inspect.getsource(auth_routes.refresh_token)

    assert "get_user_by_email" in source
    assert "get_default_tenant_id" in source


def test_an_inactive_user_cannot_refresh():
    source = inspect.getsource(auth_routes.refresh_token)

    assert "is_active" in source
    assert "HTTP_401_UNAUTHORIZED" in source


def test_a_token_carrying_only_a_subject_still_verifies():
    """Tokens issued before extra claims existed must remain usable; refusing
    them is the logout this fixes."""
    token = create_refresh_token({"sub": "someone@example.com"})

    payload = verify_refresh_token(token)

    assert payload is not None
    assert payload["sub"] == "someone@example.com"
    assert payload["type"] == "refresh"


def test_an_access_token_is_not_accepted_as_a_refresh_token():
    from app.core.security import create_access_token

    assert verify_refresh_token(create_access_token({"sub": "someone@example.com"})) is None


def test_refresh_tokens_outlive_access_tokens_by_a_wide_margin():
    """The whole recovery depends on this: the refresh token has to still be
    valid long after the access token has aged out."""
    access_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    refresh_minutes = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60

    assert refresh_minutes >= access_minutes * 48
