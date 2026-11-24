"""Detection of the two structural defects, and the patches they produce.

Both cases are drawn from a real site: a canonical in the root layout that every
canonical-less route inherits, and `/solutions/<slug>` links whose real route is
`/solutions/crm/<slug>`.

Every produced patch goes back through `patch_vocabulary.validate_patch`, so
these tests also prove the detectors cannot smuggle a change past the per-type
rules. Pure unit tests: no database, no git, no real repository.
"""
from pathlib import Path
from types import SimpleNamespace as S

import pytest

from app.repo_agent.project_structure import detect_structure
from app.repo_agent.structural_detectors import (
    build_patch,
    find_broken_internal_links,
    find_inherited_canonicals,
    routes_without_own_canonical,
    suggest_route,
)


def write(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def structure(tmp_path):
    write(tmp_path / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(tmp_path / "tsconfig.json", "{}")
    write(tmp_path / "src" / "app" / "layout.tsx", "x")
    write(tmp_path / "src" / "app" / "page.tsx", "x")
    return detect_structure(str(tmp_path))


def f(path, content="", **kw):
    return S(file_path=path, content=content, has_canonical=kw.get("has_canonical", False),
             metadata_facets_from_helper=kw.get("facets", frozenset()))


ROOT_LAYOUT = """\
export const metadata = {
  title: "HNX",
  description: "d",
  alternates: {
    canonical: "https://hnxsolutions.test",
  },
};

export default function RootLayout({ children }) {
  return <html><body>{children}</body></html>;
}
"""

ROOT_LAYOUT_CLEAN = """\
export const metadata = {
  title: "HNX",
  description: "d",
};

export default function RootLayout({ children }) {
  return <html><body>{children}</body></html>;
}
"""


# -- inherited canonical ------------------------------------------------------

def test_detects_canonical_in_the_root_layout(structure):
    found = find_inherited_canonicals([f("src/app/layout.tsx", ROOT_LAYOUT)], structure)
    assert len(found) == 1
    assert found[0].kind == "inherited_canonical"
    assert found[0].suggested_patch_type == "canonical_removal"
    assert found[0].actionable


def test_ignores_a_clean_root_layout(structure):
    assert find_inherited_canonicals([f("src/app/layout.tsx", ROOT_LAYOUT_CLEAN)], structure) == []


def test_ignores_a_nested_layout(structure):
    """A nested layout's canonical applies to a bounded subtree and is often deliberate."""
    found = find_inherited_canonicals(
        [f("src/app/blog/layout.tsx", ROOT_LAYOUT)], structure)
    assert found == []


def test_ignores_a_root_layout_in_the_wrong_root(tmp_path):
    """app/ layout in a src/app project is not the root this project serves."""
    write(tmp_path / "package.json", "{}")
    write(tmp_path / "tsconfig.json", "{}")
    write(tmp_path / "src" / "app" / "layout.tsx", "x")
    structure = detect_structure(str(tmp_path))
    assert find_inherited_canonicals([f("app/layout.tsx", ROOT_LAYOUT)], structure) == []


def test_routes_without_own_canonical_are_the_affected_set(structure):
    files = [
        f("src/app/layout.tsx", ROOT_LAYOUT),
        f("src/app/page.tsx", "x"),                               # no canonical -> affected
        f("src/app/about/page.tsx", "x", has_canonical=True),     # safe
        f("src/app/blog/page.tsx", "x", facets=frozenset({"canonical"})),  # helper -> safe
        f("src/app/x/layout.tsx", "x"),                           # not a page
    ]
    assert routes_without_own_canonical(files, structure) == ["src/app/page.tsx"]


def test_canonical_removal_patch_is_built_and_validates(structure):
    found = find_inherited_canonicals([f("src/app/layout.tsx", ROOT_LAYOUT)], structure)
    patch = build_patch(found[0], ROOT_LAYOUT, structure)
    assert patch.ok, patch.reasons
    assert "canonical" not in patch.after
    assert "alternates" not in patch.after          # the empty wrapper went too
    assert 'title: "HNX"' in patch.after            # everything else survived
    assert "RootLayout" in patch.after


def test_canonical_removal_leaves_an_unrecognised_shape_alone(structure):
    """If the stripper cannot do it cleanly, the vocabulary must reject the patch."""
    odd = 'export const metadata = { alternates: { canonical: "x", languages: {} } };\n'
    found = find_inherited_canonicals([f("src/app/layout.tsx", odd)], structure)
    patch = build_patch(found[0], odd, structure)
    # the canonical sits inline with another key; removal is not clean, so it fails
    assert not patch.ok
    assert patch.reasons


# -- broken internal links ----------------------------------------------------

ROUTES = ["/", "/solutions", "/solutions/crm/workflow-engine", "/solutions/crm/crmcore",
          "/crm-systems", "/about"]

COMPONENT = """\
export default function Grid() {
  return (
    <>
      <Link href="/solutions/workflow-engine">Explore Workflow Engine</Link>
      <Link href="/about">About</Link>
    </>
  );
}
"""


def test_detects_a_broken_link_and_suggests_the_real_route():
    found = find_broken_internal_links([f("src/components/Grid.tsx", COMPONENT)], ROUTES)
    assert len(found) == 1
    finding = found[0]
    assert finding.payload["old_href"] == "/solutions/workflow-engine"
    assert finding.payload["new_href"] == "/solutions/crm/workflow-engine"
    assert finding.actionable


def test_live_links_are_not_reported():
    content = '<Link href="/about">About</Link><Link href="/solutions">S</Link>'
    assert find_broken_internal_links([f("src/components/Ok.tsx", content)], ROUTES) == []


def test_external_and_dynamic_links_are_ignored():
    content = (
        '<a href="https://example.test/x">ext</a>'
        '<Link href="/blog/[slug]">dyn</Link>'
        '<Link href={`/solutions/${slug}`}>tpl</Link>'
    )
    assert find_broken_internal_links([f("src/components/X.tsx", content)], ROUTES) == []


def test_query_and_hash_are_stripped_before_matching():
    content = '<Link href="/about?x=1">a</Link><Link href="/about#top">b</Link>'
    assert find_broken_internal_links([f("src/components/X.tsx", content)], ROUTES) == []


def test_ambiguous_dead_link_is_reported_but_not_auto_fixed():
    routes = ["/a/contact", "/b/contact"]
    found = find_broken_internal_links([f("src/components/X.tsx", '<Link href="/contact">c</Link>')],
                                       routes)
    assert len(found) == 1
    assert found[0].suggested_patch_type is None
    assert not found[0].actionable
    assert "needs a human decision" in found[0].detail


def test_a_dead_link_with_no_candidate_is_reported_only():
    found = find_broken_internal_links([f("src/components/X.tsx", '<Link href="/ghost">g</Link>')],
                                       ROUTES)
    assert len(found) == 1 and not found[0].actionable


def test_each_dead_href_is_reported_once_per_file():
    content = ('<Link href="/solutions/workflow-engine">a</Link>'
               '<Link href="/solutions/workflow-engine">b</Link>')
    assert len(find_broken_internal_links([f("src/components/X.tsx", content)], ROUTES)) == 1


def test_ignore_list_suppresses_known_good_paths():
    found = find_broken_internal_links(
        [f("src/components/X.tsx", '<Link href="/ghost">g</Link>')], ROUTES, ignore=["/ghost"])
    assert found == []


def test_suggest_route_is_conservative():
    assert suggest_route("/solutions/workflow-engine",
                         {"/solutions/crm/workflow-engine"}) == "/solutions/crm/workflow-engine"
    assert suggest_route("/contact", {"/a/contact", "/b/contact"}) is None
    assert suggest_route("/nothing", {"/a", "/b"}) is None


def test_internal_link_patch_is_built_and_validates(structure):
    found = find_broken_internal_links([f("src/components/Grid.tsx", COMPONENT)], ROUTES)
    patch = build_patch(found[0], COMPONENT, structure)
    assert patch.ok, patch.reasons
    assert "/solutions/crm/workflow-engine" in patch.after
    assert "/solutions/workflow-engine\"" not in patch.after
    assert "About" in patch.after                 # the untouched link survived
    # and it really is a pure substitution
    assert patch.after == COMPONENT.replace("/solutions/workflow-engine",
                                            "/solutions/crm/workflow-engine")


def test_link_patch_in_a_forbidden_area_is_rejected_by_the_vocabulary(structure):
    api = '<Link href="/solutions/workflow-engine">x</Link>'
    found = find_broken_internal_links([f("src/app/api/x/route.ts", api)], ROUTES)
    patch = build_patch(found[0], api, structure)
    assert not patch.ok
    assert any("not permitted" in r for r in patch.reasons)


def test_every_finding_kind_exists_in_the_issue_type_enum(structure):
    """Guards against the detectors and the enum drifting apart.

    A finding whose kind has no enum member cannot be persisted as a scan issue,
    and a patch cannot exist without one (seo_code_patches.issue_id is NOT NULL).
    """
    from app.models.repo_agent import SeoCodeIssueType

    enum_values = {e.value for e in SeoCodeIssueType}
    kinds = set()
    kinds.update(f.kind for f in find_inherited_canonicals(
        [f("src/app/layout.tsx", ROOT_LAYOUT)], structure))
    kinds.update(f.kind for f in find_broken_internal_links(
        [f("src/components/Grid.tsx", COMPONENT)], ROUTES))
    assert kinds == {"inherited_canonical", "broken_internal_link"}
    for kind in kinds:
        assert kind in enum_values, f"{kind} is detected but has no SeoCodeIssueType member"


def test_non_actionable_finding_builds_no_patch(structure):
    found = find_broken_internal_links([f("src/components/X.tsx", '<Link href="/ghost">g</Link>')],
                                       ROUTES)
    patch = build_patch(found[0], "x", structure)
    assert not patch.ok
    assert "reported for review only" in patch.reasons[0]


# -- scanner wiring -----------------------------------------------------------

def _next_repo(tmp_path: Path) -> Path:
    """A disposable src/app project with both structural defects present."""
    write(tmp_path / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(tmp_path / "tsconfig.json", "{}")
    write(tmp_path / "src" / "app" / "layout.tsx", ROOT_LAYOUT)
    write(tmp_path / "src" / "app" / "page.tsx", "export default function P(){return null}\n")
    write(tmp_path / "src" / "app" / "solutions" / "crm" / "workflow-engine" / "page.tsx",
          "export default function W(){return null}\n")
    # a component holding a link to a route that does not exist
    write(tmp_path / "src" / "components" / "Grid.tsx", COMPONENT)
    return tmp_path


def test_scanner_emits_both_structural_issues(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType
    from app.repo_agent.scanner import NextJsRepoScanner

    root = _next_repo(tmp_path)
    scanner = NextJsRepoScanner()
    files = scanner.discover_files(root)
    structure = detect_structure(str(root))
    issues = scanner.analyze(files, structure)

    kinds = {i.issue_type for i in issues}
    assert SeoCodeIssueType.inherited_canonical in kinds
    assert SeoCodeIssueType.broken_internal_link in kinds

    canonical = next(i for i in issues if i.issue_type == SeoCodeIssueType.inherited_canonical)
    assert canonical.file_path == "src/app/layout.tsx"
    assert "inherit" in canonical.description

    link = next(i for i in issues if i.issue_type == SeoCodeIssueType.broken_internal_link)
    assert link.file_path == "src/components/Grid.tsx"
    assert "/solutions/crm/workflow-engine" in link.recommended_fix


def test_scanner_skips_structural_detectors_without_structure(tmp_path):
    """No structure means no guessing — the detectors simply do not run."""
    from app.models.repo_agent import SeoCodeIssueType
    from app.repo_agent.scanner import NextJsRepoScanner

    root = _next_repo(tmp_path)
    scanner = NextJsRepoScanner()
    issues = scanner.analyze(scanner.discover_files(root))  # structure omitted
    kinds = {i.issue_type for i in issues}
    assert SeoCodeIssueType.inherited_canonical not in kinds
    assert SeoCodeIssueType.broken_internal_link not in kinds


def test_scanner_finds_links_in_components_the_seo_walk_skips(tmp_path):
    """Components are not SEO-named, so only the link pass reaches them."""
    from app.repo_agent.scanner import NextJsRepoScanner

    root = _next_repo(tmp_path)
    scanner = NextJsRepoScanner()
    discovered = {f.file_path for f in scanner.discover_files(root)}
    assert "src/components/Grid.tsx" not in discovered, "fixture assumption changed"
    link_files = {f.file_path for f in scanner._discover_link_files(root, scanner.discover_files(root))}
    assert "src/components/Grid.tsx" in link_files


def test_link_scan_is_bounded(tmp_path):
    from app.repo_agent.scanner import NextJsRepoScanner

    root = _next_repo(tmp_path)
    for i in range(30):
        write(root / "src" / "components" / f"C{i}.tsx", "export default ()=>null")
    scanner = NextJsRepoScanner()
    scanner.LINK_SCAN_FILE_LIMIT = 5
    extra = scanner._discover_link_files(root, [])
    assert len(extra) <= 5


# -- dynamic routes (precision) ----------------------------------------------

def test_dynamic_route_serves_a_link_the_static_table_lacks():
    """Without this, every link served by [slug] is a false positive.

    On a real repository this single rule took the finding count from 161 to 8:
    153 of those links were served by dynamic routes.
    """
    from app.repo_agent.structural_detectors import dynamic_route_patterns

    files = [
        f("src/app/industries/[slug]/[solutionSlug]/page.tsx"),
        f("src/app/blog/[slug]/page.tsx"),
    ]
    patterns = dynamic_route_patterns(files)
    assert ["industries", "[slug]", "[solutionSlug]"] in patterns

    content = ('<Link href="/industries/healthcare/website">a</Link>'
               '<Link href="/blog/hello">b</Link>')
    found = find_broken_internal_links(
        [f("src/components/X.tsx", content)] + files, ["/"], dynamic_patterns=patterns)
    assert found == []


def test_dynamic_pattern_does_not_swallow_a_different_depth():
    from app.repo_agent.structural_detectors import dynamic_route_patterns

    files = [f("src/app/industries/[slug]/page.tsx")]
    patterns = dynamic_route_patterns(files)
    # one segment too many -> still broken
    found = find_broken_internal_links(
        [f("src/components/X.tsx", '<Link href="/industries/a/b/c">x</Link>')] + files,
        ["/"], dynamic_patterns=patterns)
    assert len(found) == 1


def test_dynamic_pattern_requires_the_literal_prefix_to_match():
    from app.repo_agent.structural_detectors import dynamic_route_patterns

    files = [f("src/app/industries/[slug]/page.tsx")]
    patterns = dynamic_route_patterns(files)
    found = find_broken_internal_links(
        [f("src/components/X.tsx", '<Link href="/sectors/a">x</Link>')] + files,
        ["/"], dynamic_patterns=patterns)
    assert len(found) == 1


def test_catch_all_route_matches_remaining_segments():
    from app.repo_agent.structural_detectors import dynamic_route_patterns

    files = [f("src/app/docs/[...path]/page.tsx")]
    patterns = dynamic_route_patterns(files)
    found = find_broken_internal_links(
        [f("src/components/X.tsx", '<Link href="/docs/a/b/c">x</Link>')] + files,
        ["/"], dynamic_patterns=patterns)
    assert found == []


def test_route_groups_are_not_part_of_the_url():
    from app.repo_agent.structural_detectors import dynamic_route_patterns

    patterns = dynamic_route_patterns([f("src/app/(marketing)/campaign/[id]/page.tsx")])
    assert ["campaign", "[id]"] in patterns


def test_patterns_are_derived_from_files_when_not_supplied():
    files = [f("src/app/blog/[slug]/page.tsx")]
    found = find_broken_internal_links(
        [f("src/components/X.tsx", '<Link href="/blog/hello">b</Link>')] + files, ["/"])
    assert found == []


# -- patch generation from a stored issue -------------------------------------

def _issue(issue_type, file_path):
    from uuid import uuid4

    return S(issue_type=issue_type, file_id=uuid4(), id=uuid4(), tenant_id=uuid4(),
             project_id=uuid4(), repo_connection_id=uuid4(), scan_run_id=uuid4())


def _svc():
    from app.services.repo_agent import RepoAgentService

    return RepoAgentService.__new__(RepoAgentService)


def test_inherited_canonical_issue_produces_a_removal_patch(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType, SeoCodePatchType

    root = _next_repo(tmp_path)
    issue = _issue(SeoCodeIssueType.inherited_canonical, "src/app/layout.tsx")
    values = _svc()._structural_patch_for_issue(
        issue, root, "src/app/layout.tsx", ["/"], [])
    assert values is not None
    assert values["patch_type"] == SeoCodePatchType.canonical_removal
    assert "canonical" not in values["proposed_content"]
    assert "RootLayout" in values["proposed_content"]
    assert values["diff_text"]
    # the hash is of the file as it is NOW, which the apply path re-checks
    from app.repo_agent.scanner import content_hash, read_repo_text
    assert values["original_content_hash"] == content_hash(
        read_repo_text(root / "src" / "app" / "layout.tsx"))


def test_broken_link_issue_produces_a_link_fix_patch(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType, SeoCodePatchType

    root = _next_repo(tmp_path)
    issue = _issue(SeoCodeIssueType.broken_internal_link, "src/components/Grid.tsx")
    values = _svc()._structural_patch_for_issue(
        issue, root, "src/components/Grid.tsx",
        ["/", "/solutions/crm/workflow-engine", "/about"], [])
    assert values is not None
    assert values["patch_type"] == SeoCodePatchType.internal_link_fix
    assert "/solutions/crm/workflow-engine" in values["proposed_content"]
    assert "About" in values["proposed_content"]


def test_other_issue_types_are_left_to_the_additive_flow(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType

    root = _next_repo(tmp_path)
    issue = _issue(SeoCodeIssueType.missing_canonical, "src/app/page.tsx")
    assert _svc()._structural_patch_for_issue(
        issue, root, "src/app/page.tsx", ["/"], []) is None


def test_no_patch_when_the_defect_is_already_gone(tmp_path):
    """Re-derivation means a stale issue simply yields nothing."""
    from app.models.repo_agent import SeoCodeIssueType

    root = _next_repo(tmp_path)
    write(root / "src" / "app" / "layout.tsx", ROOT_LAYOUT_CLEAN)   # someone fixed it
    issue = _issue(SeoCodeIssueType.inherited_canonical, "src/app/layout.tsx")
    assert _svc()._structural_patch_for_issue(
        issue, root, "src/app/layout.tsx", ["/"], []) is None


def test_no_patch_for_an_ambiguous_broken_link(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType

    root = _next_repo(tmp_path)
    write(root / "src" / "components" / "Grid.tsx", '<Link href="/ghost">g</Link>')
    issue = _issue(SeoCodeIssueType.broken_internal_link, "src/components/Grid.tsx")
    assert _svc()._structural_patch_for_issue(
        issue, root, "src/components/Grid.tsx", ["/", "/about"], []) is None


def test_no_patch_when_the_file_is_missing(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType

    root = _next_repo(tmp_path)
    issue = _issue(SeoCodeIssueType.inherited_canonical, "src/app/gone.tsx")
    assert _svc()._structural_patch_for_issue(
        issue, root, "src/app/gone.tsx", ["/"], []) is None


def test_path_traversal_in_a_stored_issue_yields_no_patch(tmp_path):
    from app.models.repo_agent import SeoCodeIssueType

    root = _next_repo(tmp_path)
    issue = _issue(SeoCodeIssueType.inherited_canonical, "../../etc/passwd")
    assert _svc()._structural_patch_for_issue(
        issue, root, "../../etc/passwd", ["/"], []) is None
