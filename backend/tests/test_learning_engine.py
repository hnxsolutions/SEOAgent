"""Tests for the evidence-based LearningEngine confidence."""
from uuid import uuid4

import pytest

from app.models.verification import VerificationStatus
from app.services.learning import LearningEngine, MIN_EVIDENCE


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """Returns canned grouped rows for the engine's aggregate queries."""
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_evidence_confidence_none_when_insufficient_history():
    # Only 2 finalized (< MIN_EVIDENCE) -> fall back to heuristic (None).
    assert MIN_EVIDENCE >= 3
    db = _FakeDB([(VerificationStatus.verified_success, 2)])
    engine = LearningEngine(db)
    assert await engine.evidence_confidence("schema_addition", uuid4()) is None


@pytest.mark.asyncio
async def test_evidence_confidence_from_success_and_failure():
    # 8 success, 2 failed -> 80%.
    db = _FakeDB([
        (VerificationStatus.verified_success, 8),
        (VerificationStatus.failed, 2),
    ])
    engine = LearningEngine(db)
    assert await engine.evidence_confidence("metadata_update", uuid4()) == 80


@pytest.mark.asyncio
async def test_evidence_confidence_counts_partial_as_half():
    # 4 success, 4 partial, 2 failed -> (4 + 2)/10 = 60%.
    db = _FakeDB([
        (VerificationStatus.verified_success, 4),
        (VerificationStatus.partially_successful, 4),
        (VerificationStatus.failed, 2),
    ])
    engine = LearningEngine(db)
    assert await engine.evidence_confidence("schema_addition", uuid4()) == 60


@pytest.mark.asyncio
async def test_confidence_map_flags_evidence_based():
    db = _FakeDB([
        ("schema_addition", VerificationStatus.verified_success, 5),
        ("schema_addition", VerificationStatus.failed, 1),
        ("robots_update", VerificationStatus.verified_success, 1),  # only 1 -> not evidence-based
    ])
    engine = LearningEngine(db)
    cmap = await engine.confidence_map(uuid4())
    assert cmap["schema_addition"]["evidence_based"] is True
    assert cmap["schema_addition"]["confidence"] == 83  # 5/6
    assert cmap["robots_update"]["evidence_based"] is False
