from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.copy_review import (
    SeoCopyApprovalReadiness,
    SeoCopyComplianceProfile,
    SeoCopyRevisionStatus,
    SeoCopySourceType,
)
from app.models.repo_agent import SeoCodePatchRisk, SeoCodePatchStatus, SeoCodePatchType
from app.services.copy_review import SeoCopyReviewService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeLLMService:
    def __init__(self, payload=None, fail=False):
        self.payload = payload or {
            "json": {
                "title": "Better B2B Supply Metadata | Novakos Healthcare",
                "description": "Novakos Healthcare supports verified B2B buyers with catalog access, bulk inquiry options, and distribution support.",
                "reason": "Mocked local Ollama refinement.",
                "compliance_notes": ["No blocked compliance claims detected."],
            }
        }
        self.fail = fail
        self.called = False

    async def generate_json(self, *args, **kwargs):
        self.called = True
        if self.fail:
            raise ValueError("ollama unavailable")
        return self.payload


class FakeCopyReviewRepository:
    def __init__(self, tenant_id, project, repo_root: Path | None = None):
        self.tenant_id = tenant_id
        self.project = project
        self.repo_root = repo_root
        self.policy = None
        self.patch = None
        self.connection = None
        self.blog_draft = None
        self.reviews = []
        self.revisions = []

    async def get_project(self, project_id, tenant_id):
        if tenant_id == self.tenant_id and project_id == self.project.id:
            return self.project
        return None

    async def get_policy(self, project_id, tenant_id):
        return self.policy if tenant_id == self.tenant_id and project_id == self.project.id else None

    async def create_review(self, values):
        review = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
        self.reviews.append(review)
        return review

    async def create_revision(self, values):
        revision = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
        self.revisions.append(revision)
        return revision

    async def get_repo_patch(self, patch_id, tenant_id):
        if self.patch and self.patch.id == patch_id and tenant_id == self.tenant_id:
            return self.patch
        return None

    async def get_repo_connection(self, connection_id, tenant_id):
        if self.connection and self.connection.id == connection_id and tenant_id == self.tenant_id:
            return self.connection
        return None

    async def list_repo_patches_for_scan(self, scan_id, tenant_id, limit=1000):
        if self.patch and self.patch.scan_run_id == scan_id and tenant_id == self.tenant_id:
            return [self.patch]
        return []

    async def update_repo_patch_content(self, patch, proposed_content, diff_text, explanation):
        patch.proposed_content = proposed_content
        patch.diff_text = diff_text
        patch.explanation = explanation
        patch.updated_at = datetime.utcnow()
        return patch

    async def get_blog_draft(self, draft_id, tenant_id):
        if self.blog_draft and self.blog_draft.id == draft_id and tenant_id == self.tenant_id:
            return self.blog_draft
        return None


def make_project(tenant_id, **overrides):
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "name": "Novakos Healthcare",
        "domain": "https://www.novakoshealthcare.com",
        "description": "B2B pharmaceutical distribution and wholesale medicine supply.",
        "keywords": ["pcd pharma company in haryana", "wholesale medicine supplier"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_service(repository, llm_service=None):
    service = SeoCopyReviewService(FakeDB(), llm_service=llm_service or FakeLLMService())
    service.repository = repository
    return service


@pytest.mark.asyncio
async def test_generic_copy_detection_marks_needs_revision():
    tenant_id = uuid4()
    project = make_project(tenant_id)
    repository = FakeCopyReviewRepository(tenant_id, project)
    service = make_service(repository)

    result = await service.review_copy(
        tenant_id=tenant_id,
        project_id=project.id,
        source_type=SeoCopySourceType.metadata,
        page_url="/pcd-pharma-company-in-haryana",
        target_keyword="pcd pharma company in haryana",
        original_title="Learn about PCD Pharma Company in Haryana",
        original_description="Learn about pcd pharma company in haryana with clear service details and next steps.",
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )

    review = result["review"]
    assert review.approval_readiness == SeoCopyApprovalReadiness.ready
    assert review.reviewed_title == "PCD Pharma Company in Haryana | Novakos Healthcare"
    assert "verified buyer registration" in review.reviewed_description
    assert review.quality_score >= 78
    assert any("No dosage" in note for note in result["revision"].compliance_notes)


def test_pharma_b2b_blocks_medical_and_guaranteed_claims():
    tenant_id = uuid4()
    project = make_project(tenant_id)
    service = make_service(FakeCopyReviewRepository(tenant_id, project))

    score, issues = service._compliance_score(
        "Best Treatment and Cure Options | Novakos Healthcare",
        "Guaranteed efficacy and dosage advice for patient treatment.",
        SeoCopyComplianceProfile.pharma_b2b,
    )

    assert score < 80
    assert {issue["severity"] for issue in issues} == {"critical"}
    assert any("cure" in issue["message"] for issue in issues)


def test_title_and_meta_length_scoring():
    tenant_id = uuid4()
    project = make_project(tenant_id)
    service = make_service(FakeCopyReviewRepository(tenant_id, project))

    score, issues = service._quality_score(
        "Tiny",
        "Short",
        "/wholesale-medicine-supplier",
        "wholesale medicine supplier",
    )

    codes = {issue["code"] for issue in issues}
    assert score < 80
    assert "title_too_short" in codes
    assert "description_too_short" in codes


@pytest.mark.asyncio
async def test_unsafe_medical_claim_requires_manual_review():
    tenant_id = uuid4()
    project = make_project(tenant_id)
    repository = FakeCopyReviewRepository(tenant_id, project)
    service = make_service(repository)

    result = await service.review_copy(
        tenant_id=tenant_id,
        project_id=project.id,
        page_url="/wholesale-medicine-supplier",
        target_keyword="wholesale medicine supplier",
        original_title="Best Medicine Treatment Supplier | Novakos Healthcare",
        original_description="Guaranteed treatment efficacy, cure support, and dosage advice for patients.",
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )

    review = result["review"]
    assert review.approval_readiness == SeoCopyApprovalReadiness.manual_review
    assert result["revision"] is None
    assert any(issue["code"] == "blocked_compliance_phrase" for issue in review.issues)


@pytest.mark.asyncio
async def test_repo_metadata_patch_copy_review_updates_generic_social_copy(tmp_path):
    tenant_id = uuid4()
    project = make_project(tenant_id)
    repository = FakeCopyReviewRepository(tenant_id, project, tmp_path)
    service = make_service(repository)

    file_path = tmp_path / "app" / "pcd-pharma-company-in-haryana" / "page.tsx"
    file_path.parent.mkdir(parents=True)
    original = """export const metadata = {
  title: "PCD Pharma Company in Haryana | Novakos Healthcare",
  description: "Original description."
};

export default function Page() { return <main />; }
"""
    file_path.write_text(original, encoding="utf-8")
    proposed = """export const metadata = {
  title: "PCD Pharma Company in Haryana | Novakos Healthcare",
  description: "Original description.",
  openGraph: {
    title: "Learn about pcd pharma company in haryana",
    description: "Learn about pcd pharma company in haryana with clear service details and next steps."
  },
  twitter: {
    title: "Learn about pcd pharma company in haryana",
    description: "Learn about pcd pharma company in haryana with clear service details and next steps."
  }
};

export default function Page() { return <main />; }
"""
    connection_id = uuid4()
    repository.connection = SimpleNamespace(id=connection_id, tenant_id=tenant_id, local_path=str(tmp_path))
    repository.patch = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project.id,
        repo_connection_id=connection_id,
        scan_run_id=uuid4(),
        issue_id=uuid4(),
        file_path="app/pcd-pharma-company-in-haryana/page.tsx",
        patch_type=SeoCodePatchType.metadata_update,
        risk_level=SeoCodePatchRisk.low,
        status=SeoCodePatchStatus.proposed,
        original_content_hash="abc",
        proposed_content=proposed,
        diff_text="diff",
        explanation="Safe metadata patch.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    result = await service.review_repo_patch(repository.patch.id, tenant_id, apply_revision=True)

    assert result["source_updated"] is True
    assert "clear service details and next steps" not in repository.patch.proposed_content
    assert repository.patch.proposed_content.count("PCD Pharma Company in Haryana | Novakos Healthcare") >= 3
    assert "verified buyer registration" in repository.patch.proposed_content
    assert "SEO copy review:" in repository.patch.explanation


@pytest.mark.asyncio
async def test_blog_draft_compliance_review_flags_medical_claims():
    tenant_id = uuid4()
    project = make_project(tenant_id)
    repository = FakeCopyReviewRepository(tenant_id, project)
    repository.blog_draft = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project.id,
        title="PCD Pharma Support in Haryana",
        slug="pcd-pharma-support-haryana",
        meta_title="PCD Pharma Support in Haryana | Novakos Healthcare",
        meta_description="Novakos Healthcare supports verified B2B pharma buyers with catalog access and bulk inquiries.",
        draft_markdown="# PCD Pharma Support\n\nThis draft makes cure and dosage claims for patients.",
    )
    service = make_service(repository)

    result = await service.review_blog_draft(
        repository.blog_draft.id,
        tenant_id,
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )

    assert result["review"].approval_readiness == SeoCopyApprovalReadiness.manual_review
    assert any(issue["code"] == "blocked_compliance_phrase" for issue in result["review"].issues)


@pytest.mark.asyncio
async def test_mocked_ollama_refinement_used_when_deterministic_copy_is_weak(monkeypatch):
    tenant_id = uuid4()
    project = make_project(tenant_id, name="Example")
    llm = FakeLLMService()
    service = make_service(FakeCopyReviewRepository(tenant_id, project), llm_service=llm)

    def weak_revision(**kwargs):
        return {
            "title": "Tiny",
            "description": "Short",
            "reason": "Weak deterministic copy.",
            "compliance_notes": [],
        }

    monkeypatch.setattr(service, "_deterministic_revision", weak_revision)
    analysis = await service.analyze_and_refine(
        project=project,
        title="Learn about services",
        description="Learn about services with clear service details and next steps.",
        page_url="/services",
        target_keyword="services",
        compliance_profile=SeoCopyComplianceProfile.default,
    )

    assert llm.called is True
    assert analysis.reviewed_title == "Better B2B Supply Metadata | Novakos Healthcare"
    assert analysis.readiness == SeoCopyApprovalReadiness.ready


@pytest.mark.asyncio
async def test_deterministic_fallback_refines_when_ollama_fails():
    tenant_id = uuid4()
    project = make_project(tenant_id)
    service = make_service(FakeCopyReviewRepository(tenant_id, project), llm_service=FakeLLMService(fail=True))

    analysis = await service.analyze_and_refine(
        project=project,
        title="Learn about pharma franchise",
        description="Learn about pharma franchise haryana with clear service details and next steps.",
        page_url="/pharma-franchise-haryana",
        target_keyword="pharma franchise haryana",
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )

    assert analysis.reviewed_title == "Pharma Franchise in Haryana | Novakos Healthcare"
    assert "catalog access" in analysis.reviewed_description
    assert analysis.compliance_score == 100
