"""Tests for the DeploymentEngine gate between merge and verification."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.deployment import DeploymentProvider, DeploymentStatus
from app.models.verification import VerificationStatus
from app.services.deployment import DeploymentEngine


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeDB:
    """Returns queued results in call order; records commit."""
    def __init__(self, results):
        self._results = list(results)
        self.committed = False

    async def execute(self, _query):
        return _Result(self._results.pop(0) if self._results else [])

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        return None


def test_coerce_provider_and_status():
    assert DeploymentEngine._coerce_provider("vercel") == DeploymentProvider.vercel
    assert DeploymentEngine._coerce_provider("nonsense") == DeploymentProvider.unknown
    assert DeploymentEngine._coerce_status("success") == DeploymentStatus.success
    with pytest.raises(ValueError):
        DeploymentEngine._coerce_status("bogus")


@pytest.mark.asyncio
async def test_success_accelerates_pending_verifications():
    pr_id = uuid4()
    tenant_id = uuid4()
    started = datetime.utcnow() - timedelta(seconds=42)
    deployment = SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id, pull_request_id=pr_id,
        status=DeploymentStatus.pending, started_at=started, completed_at=None,
        duration_seconds=None, deployment_url=None, logs=None, commit_sha=None,
        external_id=None, error_message=None,
    )
    future = datetime.utcnow() + timedelta(minutes=10)
    v1 = SimpleNamespace(status=VerificationStatus.pending, scheduled_at=future)
    v2 = SimpleNamespace(status=VerificationStatus.pending, scheduled_at=future)
    db = _FakeDB([[deployment], [v1, v2]])  # get deployment, then verifications
    engine = DeploymentEngine(db)

    result = await engine.update_status(deployment.id, tenant_id, "success", deployment_url="https://live.example.com")

    assert result.status == DeploymentStatus.success
    assert result.completed_at is not None
    assert result.duration_seconds >= 40                 # computed from started_at
    assert result.deployment_url == "https://live.example.com"
    # Both pending verifications are now due immediately.
    assert v1.scheduled_at <= datetime.utcnow()
    assert v2.scheduled_at <= datetime.utcnow()
    assert db.committed is True


@pytest.mark.asyncio
async def test_failed_deploy_flags_verifications_for_review():
    pr_id = uuid4()
    tenant_id = uuid4()
    deployment = SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id, pull_request_id=pr_id,
        status=DeploymentStatus.pending, started_at=datetime.utcnow(), completed_at=None,
        duration_seconds=None, deployment_url=None, logs=None, commit_sha=None,
        external_id=None, error_message=None,
    )
    v = SimpleNamespace(status=VerificationStatus.pending, details=None)
    db = _FakeDB([[deployment], [v]])
    engine = DeploymentEngine(db)

    await engine.update_status(deployment.id, tenant_id, "failed", error_message="build error")

    assert deployment.status == DeploymentStatus.failed
    assert deployment.error_message == "build error"
    assert v.status == VerificationStatus.needs_human_review
    assert v.details["deployment"] == "failed"


@pytest.mark.asyncio
async def test_update_missing_deployment_raises():
    db = _FakeDB([[]])
    engine = DeploymentEngine(db)
    with pytest.raises(ValueError):
        await engine.update_status(uuid4(), uuid4(), "success")
