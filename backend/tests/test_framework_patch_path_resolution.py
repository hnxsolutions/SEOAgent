"""Regression tests for repository-aware framework patch target resolution.

These cover the failure that shipped against a real project: a Next.js repo
using ``src/app/`` received framework patches targeting a parallel ``app/``
root, marked safe / passed / ready_for_pr. Next.js resolves ``app/`` before
``src/app/``, so applying them would have stopped the real application being
served.

Every fixture here is a disposable tree under pytest's ``tmp_path``. No test
touches a real connected repository.
"""
from pathlib import Path

import pytest

from app.framework_patches.generators import GeneratedPatchContent
from app.models.generated_patch import GeneratedPatchValidation
from app.repo_agent.project_structure import (
    PAGES_DIR_PREFIXES,
    REJECTED,
    RESOLVED,
    detect_structure,
    resolve_target,
    shadow_root_risk,
    strip_target_hint,
)
from app.repo_agent.scanner import PathSafetyError
from app.services.framework_patch_generator import FrameworkPatchGeneratorService


def write(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# -- fixtures -----------------------------------------------------------------

def app_router_root(root: Path) -> Path:
    """Next.js App Router at the repository root."""
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(root / "tsconfig.json", "{}")
    write(root / "app" / "layout.tsx", "export default function L(){return null}")
    write(root / "app" / "page.tsx", "export default function P(){return null}")
    return root


def app_router_src(root: Path) -> Path:
    """Next.js App Router under src/ — the HNX Solutions shape."""
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(root / "tsconfig.json", "{}")
    write(root / "src" / "app" / "layout.tsx", "export default function L(){return null}")
    write(root / "src" / "app" / "page.tsx", "export default function P(){return null}")
    return root


def pages_router_root(root: Path) -> Path:
    write(root / "package.json", '{"dependencies":{"next":"13.0.0"}}')
    write(root / "tsconfig.json", "{}")
    write(root / "pages" / "index.tsx", "export default function P(){return null}")
    write(root / "pages" / "_document.tsx", "export default function D(){return null}")
    return root


def pages_router_src(root: Path) -> Path:
    write(root / "package.json", '{"dependencies":{"next":"13.0.0"}}')
    write(root / "tsconfig.json", "{}")
    write(root / "src" / "pages" / "index.tsx", "export default function P(){return null}")
    return root


def content(surface="sitemap", target="app/sitemap.ts", *, is_new_file=True,
            code="export default function sitemap(){ return []; }", language="typescript"):
    return GeneratedPatchContent(
        framework="nextjs", surface=surface,
        patch_type={"sitemap": "sitemap_update", "robots": "robots_update",
                    "metadata": "metadata_update", "schema": "schema_addition",
                    "og_twitter": "og_twitter_addition"}[surface],
        target_file=target, language=language, code=code, is_new_file=is_new_file,
    )


def validate(c, resolved, structure, seen=None):
    service = FrameworkPatchGeneratorService.__new__(FrameworkPatchGeneratorService)
    from app.repo_agent.architecture import RepoArchitectureDetector

    service._safety = RepoArchitectureDetector()
    safe, reason = service._safety_check(resolved.path or c.target_file)
    return service._validate(c, safe, reason, resolved, structure, seen or {})


# -- structure detection ------------------------------------------------------

def test_detects_app_router_at_root(tmp_path):
    s = detect_structure(str(app_router_root(tmp_path)))
    assert s.router == "app" and s.app_prefix == "app"
    assert not s.ambiguous and s.typescript


def test_detects_app_router_under_src(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    assert s.router == "app" and s.app_prefix == "src/app"
    assert not s.ambiguous


def test_detects_pages_router_at_root(tmp_path):
    s = detect_structure(str(pages_router_root(tmp_path)))
    assert s.router == "pages" and s.pages_prefix == "pages"
    assert not s.ambiguous


def test_detects_pages_router_under_src(tmp_path):
    s = detect_structure(str(pages_router_src(tmp_path)))
    assert s.router == "pages" and s.pages_prefix == "src/pages"


def test_detects_javascript_project(tmp_path):
    write(tmp_path / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(tmp_path / "app" / "page.jsx", "export default function P(){return null}")
    s = detect_structure(str(tmp_path))
    assert s.typescript is False
    assert s.code_extension == ".js" and s.component_extension == ".jsx"


def test_records_existing_seo_files(tmp_path):
    root = app_router_src(tmp_path)
    write(root / "src" / "app" / "sitemap.ts", "export default function s(){return []}")
    write(root / "src" / "app" / "robots.ts", "export default function r(){return {}}")
    write(root / "src" / "lib" / "seo.ts", "export const SITE_URL='https://x.test'")
    s = detect_structure(str(root))
    assert s.existing["sitemap"] == "src/app/sitemap.ts"
    assert s.existing["robots"] == "src/app/robots.ts"
    assert s.existing["seo_helper"] == "src/lib/seo.ts"
    assert s.existing["layout"] == "src/app/layout.tsx"


# -- the HNX regression -------------------------------------------------------

def test_src_app_project_never_gets_a_parallel_app_root(tmp_path):
    """The exact HNX failure: template app/… must map onto src/app/…, never create app/."""
    s = detect_structure(str(app_router_src(tmp_path)))
    for template in ("app/sitemap.ts", "app/robots.ts", "app/components/JsonLd.tsx"):
        r = resolve_target(template, s)
        assert r.status == RESOLVED, f"{template}: {r.reason}"
        assert r.path.startswith("src/app/"), f"{template} resolved to {r.path}"
        assert not r.path.startswith("app/")
        assert shadow_root_risk(r.path, s) is None
    # and the unmapped template path would have been caught as a shadow root
    assert shadow_root_risk("app/sitemap.ts", s) is not None


def test_metadata_target_hint_is_stripped_and_mapped(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target("app/page.tsx (metadata export)", s)
    assert r.status == RESOLVED and r.path == "src/app/page.tsx"
    assert r.exists is True and r.is_new_file is False


def test_root_app_project_is_left_alone(tmp_path):
    s = detect_structure(str(app_router_root(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    assert r.status == RESOLVED and r.path == "app/sitemap.ts"
    assert shadow_root_risk("src/app/sitemap.ts", s) is not None


def test_pages_template_maps_onto_src_pages(tmp_path):
    s = detect_structure(str(pages_router_src(tmp_path)))
    r = resolve_target("pages/_document.tsx", s)
    assert r.status == RESOLVED and r.path == "src/pages/_document.tsx"


def test_extension_follows_a_javascript_project(tmp_path):
    write(tmp_path / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(tmp_path / "app" / "page.jsx", "export default function P(){return null}")
    s = detect_structure(str(tmp_path))
    assert resolve_target("app/sitemap.ts", s).path == "app/sitemap.js"
    assert resolve_target("app/components/JsonLd.tsx", s).path == "app/components/JsonLd.jsx"


# -- refusals -----------------------------------------------------------------

def test_app_template_rejected_when_project_is_pages_router(tmp_path):
    s = detect_structure(str(pages_router_root(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    assert r.status == REJECTED and "no App Router" in r.reason


def test_ambiguous_dual_app_roots_refuse_generation(tmp_path):
    root = app_router_root(tmp_path)
    write(root / "src" / "app" / "page.tsx", "export default function P(){return null}")
    s = detect_structure(str(root))
    assert s.ambiguous and "src/app" in s.ambiguity_reason
    assert resolve_target("app/sitemap.ts", s).status == REJECTED


def test_ambiguous_dual_pages_roots_refuse_generation(tmp_path):
    root = pages_router_root(tmp_path)
    write(root / "src" / "pages" / "index.tsx", "export default function P(){return null}")
    s = detect_structure(str(root))
    assert s.ambiguous
    assert resolve_target("pages/index.tsx", s).status == REJECTED


def test_no_application_root_is_ambiguous(tmp_path):
    write(tmp_path / "package.json", "{}")
    s = detect_structure(str(tmp_path))
    assert s.router == "unknown" and s.ambiguous
    assert resolve_target("app/sitemap.ts", s).status == REJECTED


def test_missing_repository_is_not_guessed(tmp_path):
    with pytest.raises(PathSafetyError):
        detect_structure(str(tmp_path / "does-not-exist"))


@pytest.mark.parametrize("evil", ["../../etc/passwd", "app/../../escape.ts", "..\\..\\escape.ts"])
def test_path_traversal_is_rejected(tmp_path, evil):
    """Anything climbing out of the checkout must be refused outright."""
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target(evil, s)
    assert r.status == REJECTED, f"{evil} resolved to {r.path}"


def test_absolute_path_is_contained_inside_the_repository(tmp_path):
    """A leading slash is treated as repo-relative, never as a host path."""
    root = app_router_src(tmp_path)
    s = detect_structure(str(root))
    r = resolve_target("/etc/passwd", s)
    assert r.status == RESOLVED and r.path == "etc/passwd"
    # the important guarantee: it stays under the checkout
    assert (root / r.path).resolve().is_relative_to(root.resolve())


def test_empty_target_is_rejected(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    assert resolve_target("   ", s).status == REJECTED


# -- validation ---------------------------------------------------------------

def test_validation_fails_for_shadow_root_target(tmp_path):
    """A patch still carrying the template path must never pass validation."""
    s = detect_structure(str(app_router_src(tmp_path)))
    from app.repo_agent.project_structure import ResolvedTarget

    unmapped = ResolvedTarget(original="app/sitemap.ts", path="app/sitemap.ts",
                              exists=False, is_new_file=True, status=RESOLVED, reason="forced")
    status, notes = validate(content(), unmapped, s)
    assert status == GeneratedPatchValidation.failed
    assert "shadow_root" in notes and any("shadow_root" in f for f in notes["failures"])


def test_validation_fails_when_repository_unavailable(tmp_path):
    from app.repo_agent.project_structure import ResolvedTarget

    unresolved = ResolvedTarget(original="app/sitemap.ts", status=REJECTED,
                                reason="No repository is connected to this project")
    status, notes = validate(content(), unresolved, None)
    assert status == GeneratedPatchValidation.failed
    assert notes["project_structure"] == "unavailable"


def test_validation_fails_when_new_file_already_exists(tmp_path):
    root = app_router_src(tmp_path)
    write(root / "src" / "app" / "sitemap.ts", "export default function s(){return []}")
    s = detect_structure(str(root))
    r = resolve_target("app/sitemap.ts", s)
    assert r.exists is True
    status, notes = validate(content(is_new_file=True), r, s)
    assert status == GeneratedPatchValidation.failed
    assert any("new_file_conflict" in f for f in notes["failures"])


def test_validation_passes_for_a_correctly_mapped_new_file(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    status, notes = validate(content(is_new_file=True), r, s)
    assert status == GeneratedPatchValidation.passed
    assert notes["target_remapped_from"] == "app/sitemap.ts"
    assert notes["shadow_root"].startswith("none")
    assert notes["file_mode"] == "create"


def test_validation_rejects_duplicate_targets(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    status, notes = validate(content(), r, s, seen={"src/app/sitemap.ts": "sitemap"})
    assert status == GeneratedPatchValidation.failed
    assert any("duplicate_target" in f for f in notes["failures"])


def test_validation_rejects_patch_type_mismatch(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target("app/page.tsx", s)
    status, notes = validate(content(surface="sitemap", target="app/page.tsx"), r, s)
    assert status == GeneratedPatchValidation.failed
    assert any("patch_type" in f for f in notes["failures"])


def test_validation_never_claims_checks_it_did_not_run(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    _, notes = validate(content(), r, s)
    for key in ("typecheck", "lint", "build"):
        assert notes[key].startswith("gated"), f"{key} must not claim to have passed"


def test_validation_fails_on_unbalanced_code(tmp_path):
    s = detect_structure(str(app_router_src(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    status, notes = validate(content(code="export default function s(){ return [ ;"), r, s)
    assert status == GeneratedPatchValidation.failed
    assert notes["static_structure"].startswith("failed")


def test_failures_are_explicit_and_actionable(tmp_path):
    """Review UI needs a reason string, not just a status."""
    s = detect_structure(str(pages_router_root(tmp_path)))
    r = resolve_target("app/sitemap.ts", s)
    status, notes = validate(content(), r, s)
    assert status == GeneratedPatchValidation.failed
    assert notes["summary"] and "No App Router" in notes["summary"] or "no App Router" in notes["summary"]


def test_strip_target_hint():
    assert strip_target_hint("app/page.tsx (metadata export)") == "app/page.tsx"
    assert strip_target_hint("app/robots.ts") == "app/robots.ts"
    assert strip_target_hint("") == ""


def test_pages_prefixes_constant_is_root_first():
    assert PAGES_DIR_PREFIXES == ("pages", "src/pages")
