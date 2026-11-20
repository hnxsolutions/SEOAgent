"""JWT round trip: login -> access_token -> an authenticated endpoint.

The reported symptom was that `/api/v1/auth/login` returned a token which
`/api/v1/projects` then rejected with "Could not validate credentials". That
message is raised for several unrelated reasons — a signature mismatch, the
wrong token type, a missing claim, or no token arriving at all — so these tests
pin each one separately. When it next happens, the failing test names the cause
instead of leaving "credentials" to be guessed at.

No secret value appears in this file or in its output. Where a key has to be
compared, it is compared by behaviour (does a token signed with it verify) or by
identity, never by printing it.
"""
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import PLACEHOLDER_SECRET_KEY, Settings, settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    verify_refresh_token,
)


def login_claims(**overrides) -> dict:
    """What `/auth/login` puts in a token. Mirrors routes/auth.py."""
    values = {
        "sub": "qa@example.com",
        "user_id": str(uuid4()),
        "tenant_id": str(uuid4()),
    }
    values.update(overrides)
    return values


# ---------------------------------------------------------------------------
# The core requirement: one key, one algorithm, both directions
# ---------------------------------------------------------------------------

def test_access_token_round_trips_through_the_same_settings():
    """Encode and decode must agree. This is the bug the report describes."""
    claims = login_claims()
    token = create_access_token(data=claims)

    payload = decode_token(token)

    assert payload is not None, "a freshly minted token failed to verify"
    assert payload["sub"] == claims["sub"]
    assert payload["user_id"] == claims["user_id"]
    assert payload["tenant_id"] == claims["tenant_id"]
    assert payload["type"] == "access"


def test_token_is_signed_with_the_configured_key_and_algorithm():
    """Verifying with the configured values must succeed; a wrong key must not."""
    token = create_access_token(data=login_claims())

    # Succeeds with what the application is configured with.
    assert jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    # And a different key does not verify — proving the signature is real and
    # the round trip above is not passing for some unrelated reason.
    from jose import JWTError

    with pytest.raises(JWTError):
        jwt.decode(token, settings.SECRET_KEY + "-wrong", algorithms=[settings.ALGORITHM])


def test_a_token_signed_with_another_key_is_rejected():
    """The failure mode the report suspected, reproduced deliberately."""
    foreign = jwt.encode(
        {**login_claims(), "type": "access", "exp": 9999999999},
        "a-different-deployments-key",
        algorithm=settings.ALGORITHM,
    )
    assert decode_token(foreign) is None


# ---------------------------------------------------------------------------
# The endpoint, end to end
# ---------------------------------------------------------------------------

@pytest.fixture
def protected_app() -> FastAPI:
    """A route guarded by the real `get_current_user`, nothing stubbed."""
    app = FastAPI()

    @app.get("/api/v1/projects/")
    async def list_projects(current_user: dict = Depends(get_current_user)):
        return {"email": current_user["email"], "tenant_id": str(current_user["tenant_id"])}

    return app


def test_login_token_is_accepted_by_a_protected_endpoint(protected_app):
    """login -> access_token -> authenticated request succeeds."""
    claims = login_claims()
    token = create_access_token(data=claims)

    response = TestClient(protected_app).get(
        "/api/v1/projects/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == claims["sub"]
    assert response.json()["tenant_id"] == claims["tenant_id"]


def test_missing_authorization_header_is_rejected(protected_app):
    """The same 401 the report saw — this is what a dropped header looks like.

    Worth pinning: a redirect that strips the Authorization header produces
    exactly this response, which is indistinguishable from a bad token unless
    you know to look for it.
    """
    response = TestClient(protected_app).get("/api/v1/projects/")

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_refresh_token_is_not_accepted_as_an_access_token(protected_app):
    """Token type is enforced, so a refresh token cannot be used to call the API."""
    refresh = create_refresh_token(data=login_claims())

    response = TestClient(protected_app).get(
        "/api/v1/projects/", headers={"Authorization": f"Bearer {refresh}"}
    )

    assert response.status_code == 401


def test_expired_token_is_rejected(protected_app):
    token = create_access_token(data=login_claims(), expires_delta=timedelta(seconds=-30))

    response = TestClient(protected_app).get(
        "/api/v1/projects/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


def test_token_without_user_id_is_rejected(protected_app):
    """A claim the login route must supply. Its absence reads as a bad token."""
    token = create_access_token(data={"sub": "qa@example.com", "tenant_id": str(uuid4())})

    response = TestClient(protected_app).get(
        "/api/v1/projects/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Refresh tokens keep working
# ---------------------------------------------------------------------------

def test_refresh_token_round_trips_and_is_typed():
    claims = login_claims()
    refresh = create_refresh_token(data=claims)

    payload = verify_refresh_token(refresh)

    assert payload is not None
    assert payload["type"] == "refresh"
    assert payload["sub"] == claims["sub"]


def test_access_token_is_not_accepted_as_a_refresh_token():
    assert verify_refresh_token(create_access_token(data=login_claims())) is None


# ---------------------------------------------------------------------------
# No placeholder secret reaches production
# ---------------------------------------------------------------------------

def test_production_refuses_to_boot_on_the_placeholder_secret():
    """A shared default signing key is a forgeable one."""
    with pytest.raises(Exception) as exc:
        Settings(APP_ENV="production", SECRET_KEY=PLACEHOLDER_SECRET_KEY)
    assert "SECRET_KEY" in str(exc.value)


def test_development_still_runs_without_configuration():
    """The guard must not make a fresh clone unrunnable."""
    assert Settings(APP_ENV="development", SECRET_KEY=PLACEHOLDER_SECRET_KEY).SECRET_KEY
