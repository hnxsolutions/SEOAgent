"""The SEO engine must NEVER modify UI, business logic, auth, payments, CRM, or
the database. These tests lock in the protected-path guard in the patch safety
classifier."""
from app.models.repo_agent import SeoCodeIssueType, SeoCodePatchType
from app.repo_agent.architecture import RepoArchitectureDetector


_DET = RepoArchitectureDetector()

# A high-confidence Next.js profile so only path safety (not confidence) decides.
_PROFILE = {
    "detected_stack": "nextjs_app_router",
    "framework": "nextjs_app_router",
    "confidence_score": 0.95,
    "safe_patch_zones": [],
    "manual_review_zones": [],
    "unsafe_patch_zones": [],
    "sitemap_strategy": {},
    "robots_strategy": {},
}


PROTECTED = [
    "app/checkout/page.tsx",
    "app/cart/CartSummary.tsx",
    "src/components/auth/LoginForm.tsx",
    "app/api/orders/route.ts",
    "src/lib/payments/stripe.ts",
    "app/admin/dashboard/page.tsx",
    "prisma/schema.prisma",
    "db/migrations/0007_add_users.sql",
    "src/middleware.ts",
    "app/account/settings/page.tsx",
]


def test_protected_paths_are_hard_rejected():
    for path in PROTECTED:
        assert _DET._is_unsafe_path(path), f"{path} must be classified unsafe"
        decision = _DET.classify_patch(
            _PROFILE, file_path=path,
            patch_type=SeoCodePatchType.metadata_update,
            issue_type=SeoCodeIssueType.missing_metadata,
        )
        assert decision.classification == "unsafe_skip", f"{path} -> {decision.classification}"
        assert not decision.is_safe


def test_legit_seo_files_are_not_flagged_by_the_guard():
    for path in ("app/robots.ts", "app/sitemap.ts", "app/layout.tsx",
                 "app/products/page.tsx", "app/blog/[slug]/page.tsx", "index.html"):
        assert not _DET._is_unsafe_path(path), f"{path} should stay eligible for SEO patches"
