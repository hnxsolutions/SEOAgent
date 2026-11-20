from pathlib import Path

import pytest

from app.models.repo_agent import RepoFilePurpose, SeoCodeIssueType
from app.repo_agent.scanner import (
    NextJsRepoScanner,
    PathSafetyError,
    build_metadata_helper_profile,
    repo_relative,
    static_routes_from_pages,
    has_metadata_export,
    has_jsonld,
    read_repo_text,
    resolve_repo_root,
    safe_child_path,
    metadata_patch_content,
    schema_patch_content,
    sitemap_patch_content,
)


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_next_fixture(root: Path):
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(
        root / "app" / "layout.tsx",
        'export const metadata = { title: "Example", description: "Example site" };\nexport default function RootLayout({ children }) { return <html><body>{children}</body></html>; }\n',
    )
    write(
        root / "app" / "page.tsx",
        "export default function Page() {\n  return (\n    <main><h1>Home</h1><img src=\"/hero.png\" /></main>\n  );\n}\n",
    )
    write(
        root / "app" / "services" / "page.tsx",
        "export const metadata = { title: \"Services\" };\nexport default function Services() {\n  return (\n    <main><h1>Services</h1></main>\n  );\n}\n",
    )
    write(root / "app" / "robots.ts", "export default function robots() { return { rules: { userAgent: '*', allow: '/' } }; }\n")
    write(root / "app" / "sitemap.ts", "export default function sitemap() { return [{ url: 'https://example.com/' }]; }\n")
    write(root / "node_modules" / "ignored" / "page.tsx", "export default function Ignored() { return null; }\n")


def test_nextjs_framework_detection_and_file_discovery(tmp_path):
    create_next_fixture(tmp_path)
    scanner = NextJsRepoScanner()

    assert scanner.detect_framework(tmp_path) == "nextjs_app_router"
    files = scanner.discover_files(tmp_path)
    paths = {file.file_path for file in files}

    assert "app/layout.tsx" in paths
    assert "app/page.tsx" in paths
    assert "app/services/page.tsx" in paths
    assert "app/sitemap.ts" in paths
    assert "app/robots.ts" in paths
    assert all("node_modules" not in path for path in paths)


def test_metadata_jsonld_sitemap_and_robots_detection(tmp_path):
    create_next_fixture(tmp_path)
    write(
        tmp_path / "components" / "JsonLd.tsx",
        'export function JsonLd() { return <script type="application/ld+json" />; }\n',
    )
    scanner = NextJsRepoScanner()
    files = {file.file_path: file for file in scanner.discover_files(tmp_path)}

    assert files["app/layout.tsx"].has_metadata is True
    assert files["app/sitemap.ts"].has_sitemap is True
    assert files["app/robots.ts"].has_robots is True
    assert files["components/JsonLd.tsx"].has_jsonld is True
    assert has_metadata_export(files["app/services/page.tsx"].content)
    assert has_jsonld(files["components/JsonLd.tsx"].content)


def test_repo_text_normalizes_utf8_bom(tmp_path):
    path = tmp_path / "app" / "page.tsx"
    write(path, "\ufeffexport default function Page() { return null; }")

    assert read_repo_text(path).startswith("export default")


def test_path_safety_rejects_traversal(tmp_path):
    resolve_repo_root(str(tmp_path))
    with pytest.raises(PathSafetyError):
        safe_child_path(tmp_path, "../outside.tsx")


def test_repo_scan_issue_creation(tmp_path):
    create_next_fixture(tmp_path)
    scanner = NextJsRepoScanner()
    files = scanner.discover_files(tmp_path)
    issues = scanner.analyze(files)
    issue_types = {issue.issue_type for issue in issues}

    assert SeoCodeIssueType.missing_metadata in issue_types
    assert SeoCodeIssueType.weak_metadata in issue_types
    assert SeoCodeIssueType.missing_schema in issue_types
    assert SeoCodeIssueType.missing_alt_pattern in issue_types
    assert SeoCodeIssueType.route_not_in_sitemap in issue_types


def test_schema_patch_wraps_jsonld_in_fragment_without_visible_dom():
    original = "export default function Page() {\n  return (\n    <main><h1>Home</h1></main>\n  );\n}\n"

    proposed = schema_patch_content(original, "Home", "https://example.com")

    assert "type=\"application/ld+json\"" in proposed
    assert "    <>" in proposed
    assert "    </>" in proposed


def test_schema_patch_skips_client_components():
    original = '"use client";\n\nexport default function Page() {\n  return <main><h1>Home</h1></main>;\n}\n'

    assert schema_patch_content(original, "Home", "https://example.com") == original


def test_metadata_patch_skips_client_components_and_respects_multiline_imports():
    client = '"use client";\n\nimport {\n  A,\n  B,\n} from "x";\n\nexport default function Page() { return null; }\n'
    assert metadata_patch_content(client, "Bulk Order", "https://example.com/bulk-order") == client

    server = 'import {\n  A,\n  B,\n} from "x";\n\nexport default function Page() { return null; }\n'
    proposed = metadata_patch_content(server, "Services", "https://example.com/services")

    assert 'from "x";\n\nexport const metadata' in proposed
    assert "export const metadata" in proposed


def test_metadata_patch_adds_missing_fields_to_existing_metadata():
    original = 'import type { Metadata } from "next";\n\nexport const metadata: Metadata = {\n  title: "Services",\n};\n'

    proposed = metadata_patch_content(original, "Services", "https://example.com/services")

    assert 'description: "Learn about services' in proposed
    assert "alternates:" in proposed
    assert "openGraph:" in proposed
    assert "twitter:" in proposed


def test_sitemap_patch_extends_static_routes_without_replacing_rich_logic():
    original = (
        'import { blogs } from "@/lib/blogs";\n'
        "export default function sitemap() {\n"
        '  const baseUrl = "https://example.com";\n'
        "  const now = new Date();\n"
        "  const staticRoutes: MetadataRoute.Sitemap = [\n"
        "    { url: baseUrl, lastModified: now },\n"
        "  ];\n"
        "  const blogRoutes = blogs.map((blog) => ({ url: `${baseUrl}/blogs/${blog.slug}` }));\n"
        "  return [...staticRoutes, ...blogRoutes];\n"
        "}\n"
    )

    proposed = sitemap_patch_content(["/", "/services"], "https://example.com", original=original)

    assert 'import { blogs } from "@/lib/blogs";' in proposed
    assert "...blogRoutes" in proposed
    assert "`${baseUrl}/services`" in proposed


def create_src_next_fixture(root: Path):
    """The same project as create_next_fixture, kept under src/.

    Both layouts are first-class in Next.js. The scanner used to look only at
    the repository root, so a src/-based repo scanned as "unknown" and every
    patch was vetoed for low architecture confidence.
    """
    write(root / "package.json", '{"dependencies":{"next":"15.0.0"}}')
    write(
        root / "src" / "lib" / "seo.ts",
        "export function createMetadata({ title, description, path }) {\n"
        "  return {\n"
        "    title,\n"
        "    description,\n"
        "    alternates: { canonical: path },\n"
        "    openGraph: { title, description, url: path },\n"
        '    twitter: { card: "summary_large_image", title },\n'
        "  };\n"
        "}\n",
    )
    write(
        root / "src" / "app" / "layout.tsx",
        'export const metadata = { title: "Example", description: "Example site" };\n'
        "export default function RootLayout({ children }) { return <html><body>{children}</body></html>; }\n",
    )
    write(
        root / "src" / "app" / "page.tsx",
        "export default function Page() {\n  return (\n    <main><h1>Home</h1></main>\n  );\n}\n",
    )
    write(
        root / "src" / "app" / "services" / "layout.tsx",
        'import { createMetadata } from "@/lib/seo";\n'
        "export const metadata = createMetadata({\n"
        '  title: "Services",\n'
        '  description: "What we do.",\n'
        '  path: "/services",\n'
        "});\n"
        "export default function ServicesLayout({ children }) { return <>{children}</>; }\n",
    )
    write(
        root / "src" / "app" / "services" / "page.tsx",
        "export default function Services() {\n  return (\n    <main><h1>Services</h1></main>\n  );\n}\n",
    )
    write(
        root / "src" / "app" / "robots.ts",
        "export default function robots() { return { rules: { userAgent: '*', allow: '/' } }; }\n",
    )
    write(
        root / "src" / "app" / "sitemap.ts",
        "export default function sitemap() { return [{ url: 'https://example.com/' }]; }\n",
    )


def test_src_app_router_is_detected_and_discovered(tmp_path):
    create_src_next_fixture(tmp_path)
    scanner = NextJsRepoScanner()

    assert scanner.detect_framework(tmp_path) == "nextjs_app_router"
    paths = {file.file_path for file in scanner.discover_files(tmp_path)}

    assert "src/app/layout.tsx" in paths
    assert "src/app/page.tsx" in paths
    assert "src/app/services/page.tsx" in paths
    assert "src/app/sitemap.ts" in paths
    assert "src/app/robots.ts" in paths
    assert "src/lib/seo.ts" in paths


def test_src_app_sitemap_and_robots_are_not_reported_missing(tmp_path):
    create_src_next_fixture(tmp_path)
    scanner = NextJsRepoScanner()

    files = {file.file_path: file for file in scanner.discover_files(tmp_path)}
    assert files["src/app/sitemap.ts"].has_sitemap is True
    assert files["src/app/robots.ts"].has_robots is True

    issue_types = {issue.issue_type for issue in scanner.analyze(list(files.values()))}
    assert SeoCodeIssueType.missing_sitemap not in issue_types
    assert SeoCodeIssueType.missing_robots not in issue_types


def test_src_app_routes_feed_sitemap_route_derivation(tmp_path):
    create_src_next_fixture(tmp_path)
    files = NextJsRepoScanner().discover_files(tmp_path)
    pages = [file for file in files if file.detected_purpose == RepoFilePurpose.page]

    assert static_routes_from_pages(pages) == ["/", "/services"]


def test_metadata_helper_supplies_canonical_open_graph_and_twitter(tmp_path):
    create_src_next_fixture(tmp_path)
    scanner = NextJsRepoScanner()
    files = {file.file_path: file for file in scanner.discover_files(tmp_path)}

    # The page never writes "canonical", "openGraph" or "twitter" itself - the
    # project helper does - so the literal detectors alone reported all three
    # as missing.
    helper_page = files["src/app/services/layout.tsx"]
    assert helper_page.has_metadata is True
    assert helper_page.has_canonical is True
    assert helper_page.has_open_graph is True
    assert helper_page.has_twitter_meta is True

    helper_issues = {
        issue.issue_type
        for issue in scanner.analyze(list(files.values()))
        if issue.file_path == "src/app/services/layout.tsx"
    }
    assert SeoCodeIssueType.missing_canonical not in helper_issues
    assert SeoCodeIssueType.missing_open_graph not in helper_issues
    assert SeoCodeIssueType.missing_twitter_meta not in helper_issues


def test_metadata_helper_does_not_vouch_for_a_file_that_never_calls_it(tmp_path):
    create_src_next_fixture(tmp_path)
    write(
        tmp_path / "src" / "app" / "about" / "layout.tsx",
        'export const metadata = { title: "About", description: "About us." };\n'
        "export default function AboutLayout({ children }) { return <>{children}</>; }\n",
    )
    files = {file.file_path: file for file in NextJsRepoScanner().discover_files(tmp_path)}

    plain = files["src/app/about/layout.tsx"]
    assert plain.has_canonical is False
    assert plain.has_open_graph is False
    assert plain.has_twitter_meta is False


def test_metadata_helper_only_vouches_for_facets_it_actually_sets(tmp_path):
    create_src_next_fixture(tmp_path)
    # A helper that sets a canonical and nothing else must not excuse a missing
    # Open Graph or Twitter block.
    write(
        tmp_path / "src" / "lib" / "seo.ts",
        "export function createMetadata({ title, path }) {\n"
        "  return { title, alternates: { canonical: path } };\n"
        "}\n",
    )
    files = {file.file_path: file for file in NextJsRepoScanner().discover_files(tmp_path)}

    page = files["src/app/services/layout.tsx"]
    assert page.has_canonical is True
    assert page.has_open_graph is False
    assert page.has_twitter_meta is False


def test_metadata_helper_cannot_supply_title_or_description(tmp_path):
    create_src_next_fixture(tmp_path)
    # Title and description are editorial, not structural: a page that passes
    # neither is still weak metadata even though the helper has fallbacks.
    write(
        tmp_path / "src" / "app" / "pricing" / "layout.tsx",
        'import { createMetadata } from "@/lib/seo";\n'
        'export const metadata = createMetadata({ path: "/pricing" });\n'
        "export default function PricingLayout({ children }) { return <>{children}</>; }\n",
    )
    scanner = NextJsRepoScanner()
    issues = [
        issue
        for issue in scanner.analyze(scanner.discover_files(tmp_path))
        if issue.file_path == "src/app/pricing/layout.tsx"
    ]

    assert SeoCodeIssueType.weak_metadata in {issue.issue_type for issue in issues}


def test_repo_relative_maps_app_paths_to_the_layout_in_use(tmp_path):
    create_src_next_fixture(tmp_path)
    assert repo_relative(tmp_path, "app/sitemap.ts") == "src/app/sitemap.ts"
    assert repo_relative(tmp_path, "src/app/robots.ts") == "src/app/robots.ts"
    # Paths outside the app directory are left alone.
    assert repo_relative(tmp_path, "public/robots.txt") == "public/robots.txt"

    root_based = tmp_path / "root-based"
    create_next_fixture(root_based)
    assert repo_relative(root_based, "src/app/sitemap.ts") == "app/sitemap.ts"
    assert repo_relative(root_based, "app/robots.ts") == "app/robots.ts"


def test_root_app_layout_still_resolves_and_scans_unchanged(tmp_path):
    create_next_fixture(tmp_path)
    scanner = NextJsRepoScanner()

    assert scanner.detect_framework(tmp_path) == "nextjs_app_router"
    paths = {file.file_path for file in scanner.discover_files(tmp_path)}
    assert "app/layout.tsx" in paths
    assert "app/sitemap.ts" in paths
    assert not any(path.startswith("src/") for path in paths)


def test_metadata_helper_chain_resolves_through_a_wrapper(tmp_path):
    create_src_next_fixture(tmp_path)
    # The common real-world shape: a small per-section wrapper that sets nothing
    # itself and defers to the project-wide builder.
    write(
        tmp_path / "src" / "components" / "solutions" / "SolutionSeo.tsx",
        'import { createMetadata } from "@/lib/seo";\n'
        "export function createSolutionMetadata(slug: string) {\n"
        "  return createMetadata({\n"
        "    title: slug,\n"
        "    description: `About ${slug}.`,\n"
        "    path: `/solutions/${slug}`,\n"
        "  });\n"
        "}\n",
    )
    write(
        tmp_path / "src" / "app" / "solutions" / "crm" / "layout.tsx",
        'import { createSolutionMetadata } from "@/components/solutions/SolutionSeo";\n'
        'export const metadata = createSolutionMetadata("crm");\n'
        "export default function CrmLayout({ children }) { return <>{children}</>; }\n",
    )
    scanner = NextJsRepoScanner()
    files = {file.file_path: file for file in scanner.discover_files(tmp_path)}

    wrapped = files["src/app/solutions/crm/layout.tsx"]
    assert wrapped.has_canonical is True
    assert wrapped.has_open_graph is True
    assert wrapped.has_twitter_meta is True


def test_helper_chain_stops_at_a_wrapper_that_sets_nothing(tmp_path):
    create_src_next_fixture(tmp_path)
    # A wrapper whose chain never reaches a facet-setting helper must not vouch
    # for anything - propagation is evidence, not a naming convention.
    write(
        tmp_path / "src" / "components" / "Bare.tsx",
        "export function createBareMetadata(title: string) {\n"
        "  return { title };\n"
        "}\n",
    )
    write(
        tmp_path / "src" / "app" / "bare" / "layout.tsx",
        'import { createBareMetadata } from "@/components/Bare";\n'
        'export const metadata = createBareMetadata("Bare");\n'
        "export default function BareLayout({ children }) { return <>{children}</>; }\n",
    )
    files = {file.file_path: file for file in NextJsRepoScanner().discover_files(tmp_path)}

    bare = files["src/app/bare/layout.tsx"]
    assert bare.has_canonical is False
    assert bare.has_open_graph is False
    assert bare.has_twitter_meta is False


def test_page_level_generate_metadata_is_not_treated_as_a_project_helper(tmp_path):
    create_src_next_fixture(tmp_path)
    write(
        tmp_path / "src" / "app" / "dynamic" / "page.tsx",
        'import { createMetadata } from "@/lib/seo";\n'
        "export async function generateMetadata() {\n"
        '  return createMetadata({ title: "Dynamic", description: "d", path: "/dynamic" });\n'
        "}\n"
        "export default function DynamicPage() { return <main><h1>Dynamic</h1></main>; }\n",
    )
    profile = build_metadata_helper_profile(
        tmp_path,
        extra_paths=[file.file_path for file in NextJsRepoScanner().discover_files(tmp_path)],
    )

    assert "generateMetadata" not in profile.facets_by_helper
    assert "createMetadata" in profile.facets_by_helper


def test_helper_that_derives_title_from_a_slug_is_not_weak_metadata(tmp_path):
    """A slug-driven helper looks the real title up, so the page is not weak."""
    create_src_next_fixture(tmp_path)
    write(
        tmp_path / "src" / "components" / "CrmSeo.tsx",
        'import { createMetadata } from "@/lib/seo";\n'
        "const entries = { core: { title: \"CRM Core\", description: \"Leads and deals.\" } };\n"
        "export function createCrmMetadata(slug: string) {\n"
        "  const entry = entries[slug];\n"
        "  return createMetadata({\n"
        "    title: entry.title,\n"
        "    description: entry.description,\n"
        "    path: `/crm/${slug}`,\n"
        "  });\n"
        "}\n",
    )
    write(
        tmp_path / "src" / "app" / "crm" / "core" / "layout.tsx",
        'import { createCrmMetadata } from "@/components/CrmSeo";\n'
        'export const metadata = createCrmMetadata("core");\n'
        "export default function CoreLayout({ children }) { return <>{children}</>; }\n",
    )
    scanner = NextJsRepoScanner()
    files = {file.file_path: file for file in scanner.discover_files(tmp_path)}

    page = files["src/app/crm/core/layout.tsx"]
    assert "title" in page.metadata_facets_from_helper
    assert "description" in page.metadata_facets_from_helper

    issues = {
        issue.issue_type
        for issue in scanner.analyze(list(files.values()))
        if issue.file_path == "src/app/crm/core/layout.tsx"
    }
    assert SeoCodeIssueType.weak_metadata not in issues
    assert SeoCodeIssueType.missing_canonical not in issues


def test_helper_relaying_the_callers_title_still_requires_the_caller_to_pass_one(tmp_path):
    """createMetadata({ title }) relays a title; it does not invent one."""
    create_src_next_fixture(tmp_path)
    profile = build_metadata_helper_profile(
        tmp_path,
        extra_paths=[file.file_path for file in NextJsRepoScanner().discover_files(tmp_path)],
    )

    # The fixture helper destructures `title`, so it never vouches for one.
    assert "title" not in profile.derived_by_helper.get("createMetadata", frozenset())
    assert "canonical" in profile.facets_by_helper["createMetadata"]


def test_no_argument_helper_call_gets_structure_but_not_derived_facets(tmp_path):
    create_src_next_fixture(tmp_path)
    write(
        tmp_path / "src" / "components" / "DefaultSeo.tsx",
        'import { createMetadata } from "@/lib/seo";\n'
        "export function createDefaultMetadata(slug?: string) {\n"
        "  const label = slug ?? \"Site\";\n"
        "  return createMetadata({ title: label, description: `About ${label}.`, path: \"/\" });\n"
        "}\n",
    )
    write(
        tmp_path / "src" / "app" / "defaulted" / "layout.tsx",
        'import { createDefaultMetadata } from "@/components/DefaultSeo";\n'
        "export const metadata = createDefaultMetadata();\n"
        "export default function DefaultedLayout({ children }) { return <>{children}</>; }\n",
    )
    files = {file.file_path: file for file in NextJsRepoScanner().discover_files(tmp_path)}

    page = files["src/app/defaulted/layout.tsx"]
    # Structural blocks still come through; the title does not, because there
    # was no argument to derive it from.
    assert "canonical" in page.metadata_facets_from_helper
    assert "title" not in page.metadata_facets_from_helper
