"""SEO copy quality and compliance review engine."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.copy_review import (
    SeoCopyApprovalReadiness,
    SeoCopyComplianceProfile,
    SeoCopyRevisionStatus,
    SeoCopySourceType,
)
from app.models.repo_agent import SeoCodePatchType
from app.repo_agent.scanner import build_unified_diff, read_repo_text, resolve_repo_root, safe_child_path
from app.repositories.copy_review import SeoCopyReviewRepository
from app.services.local_llm import LocalLLMError, LocalLLMService

logger = structlog.get_logger(__name__)


GENERIC_PHRASES = [
    "learn about",
    "clear service details and next steps",
    "your trusted partner",
    "best services",
    "top quality",
    "we provide solutions",
    "website page",
]

BASE_BLOCKED_PHRASES = [
    "guaranteed results",
    "best services",
    "top quality",
]

PHARMA_B2B_BLOCKED_PHRASES = [
    "medical advice",
    "dosage",
    "dose ",
    "treatment",
    "treat ",
    "cure",
    "disease claims",
    "efficacy",
    "patient advice",
    "best",
    "top",
    "guaranteed",
    "unsupported quality",
    "sourcing claims",
]

PHARMA_B2B_ALLOWED_TOPICS = [
    "b2b supply",
    "wholesale",
    "verified buyer",
    "catalog",
    "bulk inquiry",
    "compliance workflow",
    "service area",
    "distribution support",
    "request quote",
    "registration",
]

TARGETED_PHARMA_COPY = {
    "/pcd-pharma-company-in-haryana": {
        "title": "PCD Pharma Company in Haryana | Novakos Healthcare",
        "description": (
            "Explore Novakos Healthcare\u2019s B2B PCD pharma support in Haryana, including wholesale medicine "
            "supply, verified buyer registration, product catalog access, and bulk order inquiries."
        ),
    },
    "/pharma-franchise-haryana": {
        "title": "Pharma Franchise in Haryana | Novakos Healthcare",
        "description": (
            "Connect with Novakos Healthcare for B2B pharma franchise and distribution support in Haryana, "
            "with catalog access, bulk inquiry options, and verified buyer registration."
        ),
    },
    "/wholesale-medicine-supplier": {
        "title": "Wholesale Medicine Supplier in India | Novakos Healthcare",
        "description": (
            "Novakos Healthcare supports verified B2B buyers with wholesale medicine supply, product catalog "
            "browsing, bulk order inquiries, and pharma distribution support across Haryana and PAN India."
        ),
    },
}


@dataclass
class CopyAnalysis:
    quality_score: float
    compliance_score: float
    readiness: SeoCopyApprovalReadiness
    issues: list[dict[str, Any]]
    reviewed_title: Optional[str]
    reviewed_description: Optional[str]
    reason: str
    compliance_notes: list[str]


class SeoCopyReviewService:
    """Review and refine SEO copy before approval recommendations."""

    def __init__(self, db: AsyncSession, llm_service: Optional[LocalLLMService] = None):
        self.db = db
        self.repository = SeoCopyReviewRepository(db)
        self.llm_service = llm_service or LocalLLMService()

    async def review_copy(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        source_type: SeoCopySourceType = SeoCopySourceType.metadata,
        source_reference_id: Optional[UUID] = None,
        page_url: Optional[str] = None,
        target_keyword: Optional[str] = None,
        original_title: Optional[str] = None,
        original_description: Optional[str] = None,
        compliance_profile: Optional[SeoCopyComplianceProfile] = None,
        apply_revision: bool = False,
    ) -> dict:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        profile = compliance_profile or await self._project_profile(project_id, tenant_id, project)
        analysis = await self.analyze_and_refine(
            project=project,
            title=original_title,
            description=original_description,
            page_url=page_url,
            target_keyword=target_keyword,
            compliance_profile=profile,
        )
        review = await self.repository.create_review(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "source_type": source_type,
                "source_reference_id": source_reference_id,
                "page_url": page_url,
                "target_keyword": target_keyword,
                "original_title": original_title,
                "original_description": original_description,
                "reviewed_title": analysis.reviewed_title,
                "reviewed_description": analysis.reviewed_description,
                "quality_score": analysis.quality_score,
                "compliance_score": analysis.compliance_score,
                "approval_readiness": analysis.readiness,
                "issues": analysis.issues,
                "revision_notes": analysis.reason,
            }
        )
        revision = None
        if analysis.reviewed_title or analysis.reviewed_description:
            revision = await self.repository.create_revision(
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "review_id": review.id,
                    "source_type": source_type,
                    "source_reference_id": source_reference_id,
                    "revised_title": analysis.reviewed_title,
                    "revised_description": analysis.reviewed_description,
                    "reason": analysis.reason,
                    "compliance_notes": analysis.compliance_notes,
                    "status": SeoCopyRevisionStatus.pending,
                }
            )
        await self.db.commit()
        await self.db.refresh(review)
        if revision:
            await self.db.refresh(revision)
        return {"review": review, "revision": revision, "source_updated": False}

    async def review_repo_patch(
        self,
        patch_id: UUID,
        tenant_id: UUID,
        *,
        compliance_profile: Optional[SeoCopyComplianceProfile] = None,
        apply_revision: bool = True,
    ) -> dict:
        patch = await self.repository.get_repo_patch(patch_id, tenant_id)
        if not patch:
            raise ValueError("SEO code patch not found")
        if patch.patch_type not in {SeoCodePatchType.metadata_update, SeoCodePatchType.og_twitter_addition}:
            return await self.review_copy(
                tenant_id=tenant_id,
                project_id=patch.project_id,
                source_type=SeoCopySourceType.repo_patch,
                source_reference_id=patch.id,
                page_url=self._page_url_from_patch(patch),
                compliance_profile=compliance_profile,
                apply_revision=False,
            )

        project = await self.repository.get_project(patch.project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        profile = compliance_profile or await self._project_profile(patch.project_id, tenant_id, project)
        page_url = self._page_url_from_patch(patch, project.domain)
        proposed_content = patch.proposed_content or ""
        title, description = self._metadata_copy(proposed_content)
        target_keyword = self._keyword_from_page(page_url, title)
        metadata_block = self._metadata_block(proposed_content) or proposed_content
        generic_metadata_matches = self._generic_matches(metadata_block)
        analysis = await self.analyze_and_refine(
            project=project,
            title=title,
            description=description,
            page_url=page_url,
            target_keyword=target_keyword,
            compliance_profile=profile,
            force_revision=bool(generic_metadata_matches),
            forced_issue=(
                self._issue(
                    "generic_copy",
                    "high",
                    f"Generic SEO phrase detected in metadata patch: {', '.join(generic_metadata_matches[:3])}.",
                    {"matches": generic_metadata_matches},
                )
                if generic_metadata_matches
                else None
            ),
        )
        review = await self.repository.create_review(
            {
                "tenant_id": tenant_id,
                "project_id": patch.project_id,
                "source_type": SeoCopySourceType.repo_patch,
                "source_reference_id": patch.id,
                "page_url": page_url,
                "target_keyword": target_keyword,
                "original_title": title,
                "original_description": description,
                "reviewed_title": analysis.reviewed_title,
                "reviewed_description": analysis.reviewed_description,
                "quality_score": analysis.quality_score,
                "compliance_score": analysis.compliance_score,
                "approval_readiness": analysis.readiness,
                "issues": analysis.issues,
                "revision_notes": analysis.reason,
            }
        )
        revision = None
        if analysis.reviewed_title or analysis.reviewed_description:
            revision = await self.repository.create_revision(
                {
                    "tenant_id": tenant_id,
                    "project_id": patch.project_id,
                    "review_id": review.id,
                    "source_type": SeoCopySourceType.repo_patch,
                    "source_reference_id": patch.id,
                    "revised_title": analysis.reviewed_title,
                    "revised_description": analysis.reviewed_description,
                    "reason": analysis.reason,
                    "compliance_notes": analysis.compliance_notes,
                    "status": SeoCopyRevisionStatus.pending,
                }
            )
        source_updated = False
        if apply_revision and revision and analysis.readiness in {
            SeoCopyApprovalReadiness.ready,
            SeoCopyApprovalReadiness.needs_revision,
        }:
            source_updated = await self._apply_repo_patch_revision(patch, analysis)
        await self.db.commit()
        await self.db.refresh(review)
        if revision:
            await self.db.refresh(revision)
        return {"review": review, "revision": revision, "source_updated": source_updated}

    async def review_scan_patches(
        self,
        scan_id: UUID,
        tenant_id: UUID,
        *,
        compliance_profile: Optional[SeoCopyComplianceProfile] = None,
    ) -> dict:
        patches = await self.repository.list_repo_patches_for_scan(scan_id, tenant_id)
        reviews = []
        updated = 0
        for patch in patches:
            if patch.patch_type not in {SeoCodePatchType.metadata_update, SeoCodePatchType.og_twitter_addition}:
                continue
            result = await self.review_repo_patch(
                patch.id,
                tenant_id,
                compliance_profile=compliance_profile,
                apply_revision=True,
            )
            reviews.append(result["review"])
            if result["source_updated"]:
                updated += 1
        counts = {item.value: 0 for item in SeoCopyApprovalReadiness}
        for review in reviews:
            counts[getattr(review.approval_readiness, "value", review.approval_readiness)] += 1
        return {
            "scan_id": scan_id,
            "patches_reviewed": len(reviews),
            "patches_updated": updated,
            "ready": counts[SeoCopyApprovalReadiness.ready.value],
            "needs_revision": counts[SeoCopyApprovalReadiness.needs_revision.value],
            "manual_review": counts[SeoCopyApprovalReadiness.manual_review.value],
            "rejected": counts[SeoCopyApprovalReadiness.rejected.value],
            "reviews": reviews,
        }

    async def review_blog_draft(
        self,
        draft_id: UUID,
        tenant_id: UUID,
        *,
        compliance_profile: Optional[SeoCopyComplianceProfile] = None,
    ) -> dict:
        draft = await self.repository.get_blog_draft(draft_id, tenant_id)
        if not draft:
            raise ValueError("Blog draft not found")
        project = await self.repository.get_project(draft.project_id, tenant_id) if draft.project_id else None
        profile = compliance_profile or await self._project_profile(draft.project_id, tenant_id, project)
        title = draft.meta_title or draft.title
        description = draft.meta_description
        body_issues = self._compliance_issues(draft.draft_markdown or "", profile)
        result = await self.review_copy(
            tenant_id=tenant_id,
            project_id=draft.project_id,
            source_type=SeoCopySourceType.blog_draft,
            source_reference_id=draft.id,
            page_url=f"/blogs/{draft.slug}",
            target_keyword=None,
            original_title=title,
            original_description=description,
            compliance_profile=profile,
            apply_revision=False,
        )
        review = result["review"]
        if body_issues:
            issues = list(review.issues or []) + body_issues
            review.issues = issues
            review.compliance_score = min(review.compliance_score, 45)
            review.approval_readiness = SeoCopyApprovalReadiness.manual_review
            review.revision_notes = "Blog draft contains compliance-sensitive phrases and needs manual review."
            await self.db.commit()
            await self.db.refresh(review)
        return result

    async def list_reviews(
        self,
        project_id: UUID,
        tenant_id: UUID,
        readiness: Optional[SeoCopyApprovalReadiness] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        return await self.repository.list_reviews(project_id, tenant_id, readiness=readiness, limit=limit, offset=offset)

    async def get_review(self, review_id: UUID, tenant_id: UUID):
        return await self.repository.get_review(review_id, tenant_id)

    async def accept_revision(self, review_id: UUID, tenant_id: UUID):
        review = await self._required_review(review_id, tenant_id)
        revision = await self.repository.latest_revision(review.id, tenant_id)
        if not revision:
            raise ValueError("SEO copy revision not found")
        source_updated = False
        if review.source_type == SeoCopySourceType.repo_patch and review.source_reference_id:
            patch = await self.repository.get_repo_patch(review.source_reference_id, tenant_id)
            if patch:
                source_updated = await self._apply_repo_patch_revision(
                    patch,
                    CopyAnalysis(
                        quality_score=review.quality_score,
                        compliance_score=review.compliance_score,
                        readiness=SeoCopyApprovalReadiness.ready,
                        issues=review.issues or [],
                        reviewed_title=revision.revised_title,
                        reviewed_description=revision.revised_description,
                        reason=revision.reason or "Accepted SEO copy revision.",
                        compliance_notes=revision.compliance_notes or [],
                    ),
                )
        await self.repository.set_revision_status(revision, SeoCopyRevisionStatus.accepted)
        await self.repository.update_review_readiness(review, SeoCopyApprovalReadiness.ready, "Revision accepted.")
        await self.db.commit()
        return {"review": review, "revision": revision, "source_updated": source_updated}

    async def reject_revision(self, review_id: UUID, tenant_id: UUID):
        review = await self._required_review(review_id, tenant_id)
        revision = await self.repository.latest_revision(review.id, tenant_id)
        if revision:
            await self.repository.set_revision_status(revision, SeoCopyRevisionStatus.rejected)
        await self.repository.update_review_readiness(review, SeoCopyApprovalReadiness.manual_review, "Revision rejected for manual review.")
        await self.db.commit()
        return {"review": review, "revision": revision, "source_updated": False}

    async def analyze_and_refine(
        self,
        *,
        project,
        title: Optional[str],
        description: Optional[str],
        page_url: Optional[str],
        target_keyword: Optional[str],
        compliance_profile: SeoCopyComplianceProfile,
        force_revision: bool = False,
        forced_issue: Optional[dict[str, Any]] = None,
    ) -> CopyAnalysis:
        title = (title or "").strip()
        description = (description or "").strip()
        quality_score, quality_issues = self._quality_score(title, description, page_url, target_keyword)
        compliance_score, compliance_issues = self._compliance_score(title, description, compliance_profile)
        issues = quality_issues + compliance_issues
        if forced_issue and not any(issue.get("code") == forced_issue.get("code") for issue in issues):
            issues.append(forced_issue)
        needs_revision = force_revision or quality_score < 78 or any(issue["code"] == "generic_copy" for issue in issues)
        compliance_blocked = any(issue.get("severity") == "critical" for issue in compliance_issues)
        if compliance_blocked:
            readiness = SeoCopyApprovalReadiness.manual_review
            return CopyAnalysis(
                quality_score=quality_score,
                compliance_score=compliance_score,
                readiness=readiness,
                issues=issues,
                reviewed_title=None,
                reviewed_description=None,
                reason="Compliance-sensitive copy requires manual review before approval.",
                compliance_notes=[issue["message"] for issue in compliance_issues],
            )
        if not needs_revision and compliance_score >= 80:
            return CopyAnalysis(
                quality_score=quality_score,
                compliance_score=compliance_score,
                readiness=SeoCopyApprovalReadiness.ready,
                issues=issues,
                reviewed_title=title,
                reviewed_description=description,
                reason="Copy meets quality and compliance thresholds.",
                compliance_notes=["No blocked compliance claims detected."],
            )

        revised = await self._refine_copy(
            project=project,
            title=title,
            description=description,
            page_url=page_url,
            target_keyword=target_keyword,
            compliance_profile=compliance_profile,
        )
        revised_title = revised.get("title") or title
        revised_description = revised.get("description") or description
        revised_quality, revised_quality_issues = self._quality_score(
            revised_title,
            revised_description,
            page_url,
            target_keyword,
        )
        revised_compliance, revised_compliance_issues = self._compliance_score(
            revised_title,
            revised_description,
            compliance_profile,
        )
        revised_issues = revised_quality_issues + revised_compliance_issues
        readiness = (
            SeoCopyApprovalReadiness.ready
            if revised_quality >= 78 and revised_compliance >= 80 and not any(item.get("severity") == "critical" for item in revised_issues)
            else SeoCopyApprovalReadiness.needs_revision
        )
        return CopyAnalysis(
            quality_score=revised_quality,
            compliance_score=revised_compliance,
            readiness=readiness,
            issues=revised_issues or issues,
            reviewed_title=revised_title,
            reviewed_description=revised_description,
            reason=revised.get("reason") or "Weak or generic SEO copy was refined before approval.",
            compliance_notes=revised.get("compliance_notes") or ["No blocked compliance claims detected."],
        )

    def _quality_score(
        self,
        title: str,
        description: str,
        page_url: Optional[str],
        target_keyword: Optional[str],
    ) -> tuple[float, list[dict[str, Any]]]:
        score = 100.0
        issues: list[dict[str, Any]] = []
        title_lower = title.lower()
        description_lower = description.lower()
        combined = f"{title_lower} {description_lower}"

        if not title:
            score -= 30
            issues.append(self._issue("missing_title", "high", "SEO title is missing."))
        elif len(title) < 30:
            score -= 15
            issues.append(self._issue("title_too_short", "medium", "SEO title is shorter than the preferred range."))
        elif len(title) > 70:
            score -= 12
            issues.append(self._issue("title_too_long", "medium", "SEO title is longer than the preferred range."))

        if not description:
            score -= 30
            issues.append(self._issue("missing_description", "high", "Meta description is missing."))
        elif len(description) < 90:
            score -= 16
            issues.append(self._issue("description_too_short", "medium", "Meta description is shorter than the preferred range."))
        elif len(description) > 190:
            score -= 8
            issues.append(self._issue("description_too_long", "low", "Meta description is longer than the preferred range."))

        generic_matches = self._generic_matches(combined)
        if generic_matches:
            score -= 26
            issues.append(
                self._issue(
                    "generic_copy",
                    "high",
                    f"Generic SEO phrase detected: {', '.join(generic_matches[:3])}.",
                    {"matches": generic_matches},
                )
            )

        keyword = (target_keyword or self._keyword_from_page(page_url, title) or "").lower()
        if keyword and not self._keyword_tokens_present(keyword, combined):
            score -= 14
            issues.append(self._issue("keyword_relevance", "medium", "Copy does not clearly reflect the target keyword or page intent."))

        route = self._route_from_url(page_url)
        if route and route not in {"/", ""}:
            route_tokens = [part for part in re.split(r"[-/]+", route.lower()) if len(part) > 3]
            if route_tokens and not any(token in combined for token in route_tokens):
                score -= 8
                issues.append(self._issue("page_intent_match", "medium", "Copy does not clearly match the page route intent."))

        if "novakos" not in combined and "brand" not in combined:
            score -= 6
            issues.append(self._issue("brand_missing", "low", "Brand is missing from the SEO copy."))

        if combined.count("pharma") > 5 or (keyword and combined.count(keyword) > 2):
            score -= 12
            issues.append(self._issue("keyword_stuffing", "medium", "Copy may repeat the same keyword too often."))

        b2b_terms = ["b2b", "wholesale", "verified buyer", "bulk", "catalog", "distribution", "inquiry", "registration"]
        if not any(term in combined for term in b2b_terms):
            score -= 10
            issues.append(self._issue("b2b_clarity", "medium", "B2B value proposition is not clear."))

        ctr_terms = ["explore", "connect", "browse", "request", "support", "inquiries", "registration"]
        if not any(term in combined for term in ctr_terms):
            score -= 5
            issues.append(self._issue("ctr_appeal", "low", "Copy has limited action-oriented appeal."))

        return max(0, min(100, round(score, 2))), issues

    def _generic_matches(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        return [phrase for phrase in GENERIC_PHRASES if phrase in lowered]

    def _compliance_score(
        self,
        title: str,
        description: str,
        compliance_profile: SeoCopyComplianceProfile,
    ) -> tuple[float, list[dict[str, Any]]]:
        text = f"{title} {description}".lower()
        blocked = list(BASE_BLOCKED_PHRASES)
        if compliance_profile in {SeoCopyComplianceProfile.healthcare, SeoCopyComplianceProfile.pharma_b2b}:
            blocked.extend(PHARMA_B2B_BLOCKED_PHRASES)
        matches = [phrase for phrase in blocked if phrase in text]
        issues = [
            self._issue("blocked_compliance_phrase", "critical", f"Blocked compliance phrase detected: {phrase}.", {"phrase": phrase})
            for phrase in matches
        ]
        score = max(0.0, 100.0 - (35.0 * len(matches)))
        return round(score, 2), issues

    def _compliance_issues(self, text: str, compliance_profile: SeoCopyComplianceProfile) -> list[dict[str, Any]]:
        _score, issues = self._compliance_score("", text or "", compliance_profile)
        return issues

    async def _refine_copy(
        self,
        *,
        project,
        title: str,
        description: str,
        page_url: Optional[str],
        target_keyword: Optional[str],
        compliance_profile: SeoCopyComplianceProfile,
    ) -> dict[str, Any]:
        deterministic = self._deterministic_revision(
            project=project,
            title=title,
            description=description,
            page_url=page_url,
            target_keyword=target_keyword,
            compliance_profile=compliance_profile,
        )
        det_quality, det_quality_issues = self._quality_score(
            deterministic["title"],
            deterministic["description"],
            page_url,
            target_keyword,
        )
        det_compliance, det_compliance_issues = self._compliance_score(
            deterministic["title"],
            deterministic["description"],
            compliance_profile,
        )
        if det_quality >= 78 and det_compliance >= 80 and not det_compliance_issues:
            return deterministic
        try:
            response = await self.llm_service.generate_json(
                self._llm_prompt(project, title, description, page_url, target_keyword, compliance_profile),
                schema_hint='{"title":"string","description":"string","reason":"string","compliance_notes":["string"]}',
                model=settings.OLLAMA_DEFAULT_MODEL,
            )
            payload = response.get("json") or {}
            if isinstance(payload, dict):
                return {
                    "title": str(payload.get("title") or deterministic["title"]).strip(),
                    "description": str(payload.get("description") or deterministic["description"]).strip(),
                    "reason": str(payload.get("reason") or "Local Ollama refined weak SEO copy.").strip(),
                    "compliance_notes": payload.get("compliance_notes") or ["Local-only copy review completed."],
                }
        except (LocalLLMError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.info("Falling back to deterministic SEO copy revision", error=str(exc))
        return deterministic

    def _deterministic_revision(
        self,
        *,
        project,
        title: str,
        description: str,
        page_url: Optional[str],
        target_keyword: Optional[str],
        compliance_profile: SeoCopyComplianceProfile,
    ) -> dict[str, Any]:
        route = self._route_from_url(page_url)
        if compliance_profile == SeoCopyComplianceProfile.pharma_b2b and route in TARGETED_PHARMA_COPY:
            return {
                **TARGETED_PHARMA_COPY[route],
                "reason": "Deterministic pharma-B2B template replaced generic SEO copy with page-specific compliant copy.",
                "compliance_notes": [
                    "B2B pharma supply language only.",
                    "No dosage, cure, treatment, patient advice, or guaranteed claims.",
                ],
            }
        brand = getattr(project, "name", None) or "Website"
        keyword = (target_keyword or self._keyword_from_page(page_url, title) or "B2B service").strip()
        clean_keyword = self._title_case_keyword(keyword)
        revised_title = f"{clean_keyword} | {brand}"
        if len(revised_title) > 70:
            revised_title = clean_keyword[:62].rstrip()
        revised_description = (
            f"Explore {brand} for {clean_keyword.lower()}, including service details, audience-fit information, "
            "and clear inquiry options."
        )
        return {
            "title": revised_title,
            "description": revised_description[:180].rstrip(),
            "reason": "Deterministic fallback replaced generic SEO copy with keyword- and brand-specific copy.",
            "compliance_notes": ["No blocked compliance phrases detected in deterministic fallback."],
        }

    async def _project_profile(
        self,
        project_id: Optional[UUID],
        tenant_id: UUID,
        project=None,
    ) -> SeoCopyComplianceProfile:
        policy = await self.repository.get_policy(project_id, tenant_id)
        if policy:
            return policy.compliance_profile
        text = " ".join(
            str(value or "")
            for value in [
                getattr(project, "name", None),
                getattr(project, "domain", None),
                getattr(project, "description", None),
                " ".join(getattr(project, "keywords", None) or []),
            ]
        ).lower()
        if any(term in text for term in ["pharma", "medicine", "healthcare", "pcd"]):
            return SeoCopyComplianceProfile.pharma_b2b
        return SeoCopyComplianceProfile.default

    async def _apply_repo_patch_revision(self, patch, analysis: CopyAnalysis) -> bool:
        if not analysis.reviewed_title and not analysis.reviewed_description:
            return False
        connection = await self.repository.get_repo_connection(patch.repo_connection_id, patch.tenant_id)
        if not connection or not connection.local_path:
            return False
        root = resolve_repo_root(connection.local_path)
        path = safe_child_path(root, patch.file_path)
        original = read_repo_text(path) if path.exists() else ""
        proposed = self._replace_metadata_copy(
            patch.proposed_content or "",
            title=analysis.reviewed_title,
            description=analysis.reviewed_description,
        )
        if proposed == (patch.proposed_content or ""):
            return False
        explanation = (
            f"{patch.explanation}\n\nSEO copy review: {analysis.reason} "
            f"Quality score {analysis.quality_score:.0f}; compliance score {analysis.compliance_score:.0f}; "
            f"readiness {analysis.readiness.value}."
        )
        diff_text = build_unified_diff(patch.file_path, original, proposed)
        await self.repository.update_repo_patch_content(patch, proposed, diff_text, explanation)
        return True

    def _metadata_copy(self, content: str) -> tuple[Optional[str], Optional[str]]:
        block = self._metadata_block(content)
        source = block or content
        title = self._first_property(source, "title")
        description = self._first_property(source, "description")
        return title, description

    def _replace_metadata_copy(
        self,
        content: str,
        *,
        title: Optional[str],
        description: Optional[str],
    ) -> str:
        start, end = self._metadata_block_span(content)
        if start is None or end is None:
            return self._replace_properties(content, title=title, description=description)
        prefix = content[:start]
        block = content[start:end]
        suffix = content[end:]
        return prefix + self._replace_properties(block, title=title, description=description) + suffix

    def _replace_properties(self, text: str, *, title: Optional[str], description: Optional[str]) -> str:
        if title:
            text = re.sub(
                r'(title\s*:\s*)(["\'])(.*?)(\2)',
                lambda match: f"{match.group(1)}{match.group(2)}{self._escape_ts(title, match.group(2))}{match.group(4)}",
                text,
            )
        if description:
            text = re.sub(
                r'(description\s*:\s*)(["\'])(.*?)(\2)',
                lambda match: f"{match.group(1)}{match.group(2)}{self._escape_ts(description, match.group(2))}{match.group(4)}",
                text,
            )
        return text

    def _metadata_block(self, content: str) -> str:
        start, end = self._metadata_block_span(content)
        return content[start:end] if start is not None and end is not None else ""

    def _metadata_block_span(self, content: str) -> tuple[Optional[int], Optional[int]]:
        match = re.search(r"export\s+const\s+metadata[^=]*=", content)
        if not match:
            return None, None
        brace_start = content.find("{", match.end())
        if brace_start == -1:
            return None, None
        depth = 0
        quote = None
        escaped = False
        for index in range(brace_start, len(content)):
            char = content[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in {'"', "'", "`"}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return brace_start, index + 1
        return None, None

    def _first_property(self, text: str, property_name: str) -> Optional[str]:
        match = re.search(rf"{property_name}\s*:\s*([\"'])(.*?)(\1)", text, re.DOTALL)
        return match.group(2).strip() if match else None

    def _llm_prompt(
        self,
        project,
        title: str,
        description: str,
        page_url: Optional[str],
        target_keyword: Optional[str],
        compliance_profile: SeoCopyComplianceProfile,
    ) -> str:
        return (
            "You are a local-only SEO copy reviewer. Rewrite weak metadata safely.\n"
            f"Project: {getattr(project, 'name', '')}\n"
            f"Page URL: {page_url or ''}\n"
            f"Target keyword: {target_keyword or ''}\n"
            f"Compliance profile: {compliance_profile.value}\n"
            f"Current title: {title}\n"
            f"Current description: {description}\n"
            "Rules: no medical claims, no dosage, no cure/treatment/efficacy/patient advice, no best/top/guaranteed. "
            "Prefer B2B supply, catalog, bulk inquiry, verified buyer registration, service area, and distribution support. "
            "Title 45-65 characters preferred. Description 120-170 characters preferred."
        )

    def _issue(self, code: str, severity: str, message: str, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"code": code, "severity": severity, "message": message, **(extra or {})}

    def _route_from_url(self, page_url: Optional[str]) -> str:
        if not page_url:
            return ""
        parsed = urlsplit(page_url if page_url.startswith(("http://", "https://")) else f"https://x.local{page_url}")
        return parsed.path.rstrip("/") or "/"

    def _page_url_from_patch(self, patch, site_url: Optional[str] = None) -> Optional[str]:
        route = patch.file_path.replace("\\", "/").removeprefix("app/")
        if route == "page.tsx":
            path = "/"
        elif route.endswith("/layout.tsx"):
            path = "/" + route.removesuffix("/layout.tsx").strip("/")
        elif route.endswith("/page.tsx"):
            path = "/" + route.removesuffix("/page.tsx").strip("/")
        else:
            path = "/" + route.strip("/")
        if site_url:
            base = site_url.rstrip("/")
            if not base.startswith(("http://", "https://")):
                base = f"https://{base}"
            return base + ("" if path == "/" else path)
        return path

    def _keyword_from_page(self, page_url: Optional[str], title: Optional[str]) -> Optional[str]:
        route = self._route_from_url(page_url)
        if route and route != "/":
            return route.strip("/").replace("-", " ")
        return title

    def _keyword_tokens_present(self, keyword: str, text: str) -> bool:
        tokens = [token for token in re.findall(r"[a-z0-9]+", keyword.lower()) if len(token) > 2]
        if not tokens:
            return True
        return len([token for token in tokens if token in text]) >= max(1, min(3, len(tokens)))

    def _title_case_keyword(self, keyword: str) -> str:
        small = {"in", "and", "for", "with", "of", "to"}
        words = []
        for index, word in enumerate(keyword.replace("-", " ").split()):
            lower = word.lower()
            words.append(lower if index and lower in small else lower.upper() if lower == "b2b" else lower.capitalize())
        return " ".join(words)

    def _escape_ts(self, value: str, quote: str) -> str:
        return value.replace("\\", "\\\\").replace(quote, f"\\{quote}")

    async def _required_review(self, review_id: UUID, tenant_id: UUID):
        review = await self.repository.get_review(review_id, tenant_id)
        if not review:
            raise ValueError("SEO copy review not found")
        return review
