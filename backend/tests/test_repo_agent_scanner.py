from pathlib import Path

import pytest

from app.models.repo_agent import SeoCodeIssueType
from app.repo_agent.scanner import (
    NextJsRepoScanner,
    PathSafetyError,
    has_metadata_export,
    has_jsonld,
    read_repo_text,
    resolve_repo_root,
    safe_child_path,
    schema_patch_content,
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
