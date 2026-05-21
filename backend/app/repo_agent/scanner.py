"""Safe local repository scanning and SEO-only patch helpers."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from app.models.repo_agent import (
    RepoFilePurpose,
    SeoCodeIssueSeverity,
    SeoCodeIssueSource,
    SeoCodeIssueType,
    SeoCodePatchRisk,
    SeoCodePatchType,
)

IGNORE_DIRS = {"node_modules", ".next", "dist", "build", ".git", "coverage"}
MAX_FILE_SIZE_BYTES = 256 * 1024
NEXT_SEO_FILENAMES = {
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "public/robots.txt",
    "public/sitemap.xml",
    "app/layout.tsx",
    "app/page.tsx",
    "app/sitemap.ts",
    "app/robots.ts",
    "lib/metadata.ts",
    "lib/seo.ts",
    "components/JsonLd.tsx",
}
SEO_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js", ".mjs", ".txt", ".xml"}


@dataclass
class ScannedRepoFile:
    file_path: str
    file_type: str
    content_hash: str
    detected_purpose: RepoFilePurpose
    has_metadata: bool
    has_jsonld: bool
    has_canonical: bool
    has_open_graph: bool
    has_twitter_meta: bool
    has_sitemap: bool
    has_robots: bool
    content: str


@dataclass
class RepoIssueCandidate:
    file_path: Optional[str]
    file_content_hash: str
    issue_type: SeoCodeIssueType
    severity: SeoCodeIssueSeverity
    title: str
    description: str
    recommended_fix: str
    source_reference_type: SeoCodeIssueSource
    source_reference_id: Optional[object] = None


@dataclass
class PatchCandidate:
    issue_type: SeoCodeIssueType
    file_path: str
    patch_type: SeoCodePatchType
    original_content_hash: str
    diff_text: str
    proposed_content: str
    explanation: str
    risk_level: SeoCodePatchRisk


class PathSafetyError(ValueError):
    """Raised when a repository path would escape its root."""


def resolve_repo_root(local_path: str) -> Path:
    """Resolve and validate a local repository root."""
    if not local_path:
        raise PathSafetyError("local_path is required for local repository scanning")
    root = Path(local_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise PathSafetyError("local_path must point to an existing directory")
    return root


def safe_child_path(root: Path, relative_path: str) -> Path:
    """Resolve a relative path inside a repository root."""
    clean = relative_path.replace("\\", "/").lstrip("/")
    if not clean or ".." in Path(clean).parts:
        raise PathSafetyError("Repository file path is not safe")
    candidate = (root / clean).resolve()
    if not candidate.is_relative_to(root):
        raise PathSafetyError("Repository file path escapes the repository root")
    return candidate


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_repo_text(content: str) -> str:
    """Normalize source text before storing/hashing it in the database."""
    return content.lstrip("\ufeff")


def read_repo_text(path: Path) -> str:
    return normalize_repo_text(path.read_text(encoding="utf-8", errors="ignore"))


class NextJsRepoScanner:
    """Scanner for Next.js App Router SEO files."""

    def detect_framework(self, root: Path) -> str:
        package_json = root / "package.json"
        app_dir = root / "app"
        has_next_dependency = False
        if package_json.exists():
            try:
                data = json.loads(read_repo_text(package_json))
                dependencies = {}
                dependencies.update(data.get("dependencies") or {})
                dependencies.update(data.get("devDependencies") or {})
                has_next_dependency = "next" in dependencies
            except (json.JSONDecodeError, OSError):
                has_next_dependency = False
        if app_dir.exists() and ((app_dir / "layout.tsx").exists() or (app_dir / "page.tsx").exists()):
            return "nextjs_app_router"
        if has_next_dependency and app_dir.exists():
            return "nextjs_app_router"
        return "unknown"

    def discover_files(self, root: Path) -> List[ScannedRepoFile]:
        files: List[Path] = []
        for rel_path in NEXT_SEO_FILENAMES:
            candidate = safe_child_path(root, rel_path)
            if candidate.exists() and candidate.is_file():
                files.append(candidate)
        app_dir = root / "app"
        if app_dir.exists():
            files.extend(self._walk_for_pages(app_dir, root))
        for folder in [root / "components", root / "lib"]:
            if folder.exists():
                files.extend(self._walk_for_seo_helpers(folder, root))
        unique = []
        seen = set()
        for path in files:
            if path in seen or not self._is_scannable_file(path, root):
                continue
            seen.add(path)
            unique.append(path)
        return [self._scan_file(path, root) for path in sorted(unique, key=lambda value: value.as_posix())]

    def analyze(self, files: List[ScannedRepoFile]) -> List[RepoIssueCandidate]:
        issues: List[RepoIssueCandidate] = []
        by_path = {file.file_path: file for file in files}
        app_files = [file for file in files if file.file_path.startswith("app/")]
        page_files = [file for file in files if file.detected_purpose == RepoFilePurpose.page]
        layout_files = [file for file in files if file.detected_purpose == RepoFilePurpose.layout]
        sitemap_file = by_path.get("app/sitemap.ts") or by_path.get("public/sitemap.xml")
        robots_file = by_path.get("app/robots.ts") or by_path.get("public/robots.txt")

        if not sitemap_file:
            issues.append(
                self._global_issue(
                    SeoCodeIssueType.missing_sitemap,
                    SeoCodeIssueSeverity.high,
                    "Missing sitemap implementation",
                    "No app/sitemap.ts or public/sitemap.xml file was found.",
                    "Add a Next.js app/sitemap.ts route so important routes can be discovered by search engines.",
                )
            )
        if not robots_file:
            issues.append(
                self._global_issue(
                    SeoCodeIssueType.missing_robots,
                    SeoCodeIssueSeverity.medium,
                    "Missing robots implementation",
                    "No app/robots.ts or public/robots.txt file was found.",
                    "Add a robots file or app/robots.ts route with crawl directives and sitemap location.",
                )
            )
        for file in layout_files + page_files:
            if is_internal_app_path(file.file_path):
                continue
            if not file.has_metadata and not self._is_client_component(file.content):
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.missing_metadata,
                        SeoCodeIssueSeverity.high if file.detected_purpose == RepoFilePurpose.layout else SeoCodeIssueSeverity.medium,
                        "Missing metadata export",
                        f"{file.file_path} does not export metadata or generateMetadata.",
                        "Add a safe App Router metadata export with title and description.",
                    )
                )
            elif file.has_metadata and not self._metadata_has_title_and_description(file.content):
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.weak_metadata,
                        SeoCodeIssueSeverity.medium,
                        "Weak metadata export",
                        f"{file.file_path} has metadata but appears to miss a title or description.",
                        "Complete the metadata object with a title and description.",
                    )
                )
            if file.has_metadata and not file.has_canonical:
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.missing_canonical,
                        SeoCodeIssueSeverity.medium,
                        "Missing canonical metadata",
                        f"{file.file_path} metadata does not define alternates.canonical.",
                        "Add a canonical URL in the metadata alternates object.",
                    )
                )
            if file.has_metadata and not file.has_open_graph:
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.missing_open_graph,
                        SeoCodeIssueSeverity.medium,
                        "Missing Open Graph metadata",
                        f"{file.file_path} metadata does not include openGraph fields.",
                        "Add Open Graph title, description, and URL metadata.",
                    )
                )
            if file.has_metadata and not file.has_twitter_meta:
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.missing_twitter_meta,
                        SeoCodeIssueSeverity.low,
                        "Missing Twitter card metadata",
                        f"{file.file_path} metadata does not include twitter card fields.",
                        "Add Twitter card title and description metadata.",
                    )
                )
            if file.detected_purpose == RepoFilePurpose.page and not file.has_jsonld:
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.missing_schema,
                        SeoCodeIssueSeverity.medium,
                        "Missing JSON-LD schema",
                        f"{file.file_path} does not include JSON-LD structured data.",
                        "Add a hidden JSON-LD WebPage schema script without changing visible UI.",
                    )
                )
            if self._has_image_without_alt(file.content):
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.missing_alt_pattern,
                        SeoCodeIssueSeverity.medium,
                        "Image alt text risk",
                        f"{file.file_path} contains image tags that may not include alt text.",
                        "Add descriptive alt attributes without changing layout or styling.",
                    )
                )
            h1_count = len(re.findall(r"<h1[\s>]", file.content, flags=re.IGNORECASE))
            if file.detected_purpose == RepoFilePurpose.page and h1_count != 1:
                issues.append(
                    self._file_issue(
                        file,
                        SeoCodeIssueType.heading_semantics_risk,
                        SeoCodeIssueSeverity.high,
                        "Heading semantics risk",
                        f"{file.file_path} has {h1_count} h1 elements; heading changes can affect visible structure.",
                        "Review heading semantics manually. Any patch should be high risk and require careful review.",
                    )
                )
        if sitemap_file:
            routes = [route for route in static_routes_from_pages(page_files) if route != "/"]
            for route in routes:
                if route not in sitemap_file.content:
                    issues.append(
                        self._file_issue(
                            sitemap_file,
                            SeoCodeIssueType.route_not_in_sitemap,
                            SeoCodeIssueSeverity.medium,
                            "Route missing from sitemap",
                            f"The static route {route} does not appear in {sitemap_file.file_path}.",
                            "Add the route to the sitemap output.",
                        )
                    )
        duplicate_titles = self._duplicate_metadata_titles(app_files)
        for file in duplicate_titles:
            issues.append(
                self._file_issue(
                    file,
                    SeoCodeIssueType.duplicate_metadata,
                    SeoCodeIssueSeverity.medium,
                    "Duplicate metadata title risk",
                    f"{file.file_path} appears to share a metadata title with another route.",
                    "Make the metadata title unique for this page.",
                )
            )
        return issues

    def _walk_for_pages(self, app_dir: Path, root: Path) -> List[Path]:
        paths = []
        for path in app_dir.rglob("*.tsx"):
            if self._ignored(path, root):
                continue
            rel = path.relative_to(root).as_posix()
            if rel.endswith("/page.tsx") or rel == "app/page.tsx" or rel.endswith("/layout.tsx"):
                paths.append(path)
        return paths

    def _walk_for_seo_helpers(self, folder: Path, root: Path) -> List[Path]:
        paths = []
        for path in folder.rglob("*"):
            if self._ignored(path, root) or not path.is_file():
                continue
            name = path.name.lower()
            if name in {"jsonld.tsx", "metadata.ts", "seo.ts"} or "seo" in name or "jsonld" in name:
                paths.append(path)
        return paths

    def _is_scannable_file(self, path: Path, root: Path) -> bool:
        if self._ignored(path, root) or path.is_symlink() or not path.is_file():
            return False
        if path.suffix.lower() not in SEO_EXTENSIONS:
            return False
        try:
            return path.stat().st_size <= MAX_FILE_SIZE_BYTES
        except OSError:
            return False

    def _ignored(self, path: Path, root: Path) -> bool:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return True
        return any(part in IGNORE_DIRS for part in parts)

    def _scan_file(self, path: Path, root: Path) -> ScannedRepoFile:
        content = read_repo_text(path)
        rel_path = path.relative_to(root).as_posix()
        purpose = detect_file_purpose(rel_path, content)
        return ScannedRepoFile(
            file_path=rel_path,
            file_type=path.suffix.lstrip(".") or "text",
            content_hash=content_hash(content),
            detected_purpose=purpose,
            has_metadata=has_metadata_export(content),
            has_jsonld=has_jsonld(content),
            has_canonical=has_canonical(content),
            has_open_graph=has_open_graph(content),
            has_twitter_meta=has_twitter_meta(content),
            has_sitemap=purpose == RepoFilePurpose.sitemap,
            has_robots=purpose == RepoFilePurpose.robots,
            content=content,
        )

    def _file_issue(
        self,
        file: ScannedRepoFile,
        issue_type: SeoCodeIssueType,
        severity: SeoCodeIssueSeverity,
        title: str,
        description: str,
        recommended_fix: str,
    ) -> RepoIssueCandidate:
        return RepoIssueCandidate(
            file_path=file.file_path,
            file_content_hash=file.content_hash,
            issue_type=issue_type,
            severity=severity,
            title=title,
            description=description,
            recommended_fix=recommended_fix,
            source_reference_type=SeoCodeIssueSource.repo_scan,
        )

    def _global_issue(
        self,
        issue_type: SeoCodeIssueType,
        severity: SeoCodeIssueSeverity,
        title: str,
        description: str,
        recommended_fix: str,
    ) -> RepoIssueCandidate:
        return RepoIssueCandidate(
            file_path=None,
            file_content_hash="0" * 64,
            issue_type=issue_type,
            severity=severity,
            title=title,
            description=description,
            recommended_fix=recommended_fix,
            source_reference_type=SeoCodeIssueSource.repo_scan,
        )

    def _metadata_has_title_and_description(self, content: str) -> bool:
        return bool(re.search(r"\btitle\s*:", content) and re.search(r"\bdescription\s*:", content))

    def _has_image_without_alt(self, content: str) -> bool:
        for match in re.finditer(r"<(?:Image|img)\b[^>]*>", content):
            if not re.search(r"\balt\s*=", match.group(0)):
                return True
        return False

    def _is_client_component(self, content: str) -> bool:
        first = content.strip().splitlines()[:3]
        return any(line.strip().strip(";").strip("'\"") == "use client" for line in first)

    def _duplicate_metadata_titles(self, files: Iterable[ScannedRepoFile]) -> List[ScannedRepoFile]:
        seen: dict[str, ScannedRepoFile] = {}
        duplicates: List[ScannedRepoFile] = []
        for file in files:
            title = extract_metadata_title(file.content)
            if not title:
                continue
            key = title.lower()
            if key in seen:
                duplicates.extend([seen[key], file])
            else:
                seen[key] = file
        unique = []
        paths = set()
        for file in duplicates:
            if file.file_path not in paths:
                unique.append(file)
                paths.add(file.file_path)
        return unique


def detect_file_purpose(file_path: str, content: str = "") -> RepoFilePurpose:
    path = file_path.replace("\\", "/")
    name = Path(path).name.lower()
    if path == "app/layout.tsx" or path.endswith("/layout.tsx"):
        return RepoFilePurpose.layout
    if path == "app/page.tsx" or path.endswith("/page.tsx"):
        return RepoFilePurpose.page
    if path == "app/sitemap.ts" or path == "public/sitemap.xml":
        return RepoFilePurpose.sitemap
    if path == "app/robots.ts" or path == "public/robots.txt":
        return RepoFilePurpose.robots
    if path in {"lib/metadata.ts", "lib/seo.ts"} or "metadata" in name or name == "seo.ts":
        return RepoFilePurpose.metadata
    if "jsonld" in name or "json-ld" in name or has_jsonld(content):
        return RepoFilePurpose.jsonld
    if name.startswith("next.config"):
        return RepoFilePurpose.config
    if path.startswith("components/"):
        return RepoFilePurpose.component
    return RepoFilePurpose.unknown


def has_metadata_export(content: str) -> bool:
    return bool(
        re.search(r"export\s+const\s+metadata\b", content)
        or re.search(r"export\s+(?:async\s+)?function\s+generateMetadata\b", content)
    )


def is_client_component(content: str) -> bool:
    first = content.strip().splitlines()[:3]
    return any(line.strip().strip(";").strip("'\"") == "use client" for line in first)


def has_jsonld(content: str) -> bool:
    return bool(
        "application/ld+json" in content
        or "JSON.stringify(jsonLd" in content
        or "JsonLd" in content
        or "@context" in content and "schema.org" in content
    )


def has_canonical(content: str) -> bool:
    return bool("canonical" in content or "alternates" in content)


def has_open_graph(content: str) -> bool:
    return bool("openGraph" in content or "og:" in content)


def has_twitter_meta(content: str) -> bool:
    return bool(re.search(r"\btwitter\s*:", content) or "twitter:" in content)


def extract_metadata_title(content: str) -> Optional[str]:
    match = re.search(r"\btitle\s*:\s*['\"]([^'\"]+)['\"]", content)
    return match.group(1).strip() if match else None


def static_routes_from_pages(files: Iterable[ScannedRepoFile]) -> List[str]:
    routes = []
    for file in files:
        path = file.file_path
        if is_internal_app_path(path):
            continue
        if not path.startswith("app/") or not path.endswith("/page.tsx") and path != "app/page.tsx":
            continue
        if "[" in path or "]" in path:
            continue
        route = path.removeprefix("app/").removesuffix("/page.tsx").removesuffix("page.tsx")
        route = "/" + route.strip("/")
        routes.append(route if route != "/" else "/")
    return sorted(set(routes), key=lambda value: (value.count("/"), value))


def is_internal_app_path(file_path: str) -> bool:
    route = file_path.replace("\\", "/").removeprefix("app/").strip("/")
    first = route.split("/", 1)[0]
    return first in {"admin", "api", "_components", "dashboard"}


def build_unified_diff(file_path: str, original: str, proposed: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
    )


def metadata_patch_content(original: str, route_label: str, site_url: str) -> str:
    metadata = (
        "export const metadata = {\n"
        f"  title: \"{route_label}\",\n"
        f"  description: \"Learn about {route_label.lower()} with clear service details and next steps.\",\n"
        "  alternates: {\n"
        f"    canonical: \"{site_url}\",\n"
        "  },\n"
        "  openGraph: {\n"
        f"    title: \"{route_label}\",\n"
        f"    description: \"Learn about {route_label.lower()} with clear service details and next steps.\",\n"
        f"    url: \"{site_url}\",\n"
        "    type: \"website\",\n"
        "  },\n"
        "  twitter: {\n"
        "    card: \"summary_large_image\",\n"
        f"    title: \"{route_label}\",\n"
        f"    description: \"Learn about {route_label.lower()} with clear service details and next steps.\",\n"
        "  },\n"
        "};\n\n"
    )
    if is_client_component(original) or re.search(r"export\s+(?:async\s+)?function\s+generateMetadata\b", original):
        return original
    if has_metadata_export(original):
        return complete_metadata_object(original, route_label, site_url)
    lines = original.splitlines(keepends=True)
    insert_at = find_import_block_end(lines)
    return "".join(lines[:insert_at]) + ("\n" if insert_at and lines[insert_at - 1].strip() else "") + metadata + "".join(lines[insert_at:])


def complete_metadata_object(original: str, route_label: str, site_url: str) -> str:
    bounds = find_exported_const_object_bounds(original, "metadata")
    if not bounds:
        return original
    _open_at, close_at = bounds
    object_text = original[bounds[0] : close_at + 1]
    additions = []
    description = f"Learn about {route_label.lower()} with clear service details and next steps."
    if not re.search(r"\bdescription\s*:", object_text):
        additions.append(f"  description: \"{description}\",")
    if not re.search(r"\balternates\s*:", object_text):
        additions.append("  alternates: {")
        additions.append(f"    canonical: \"{site_url}\",")
        additions.append("  },")
    if not re.search(r"\bopenGraph\s*:", object_text):
        additions.append("  openGraph: {")
        additions.append(f"    title: \"{route_label}\",")
        additions.append(f"    description: \"{description}\",")
        additions.append(f"    url: \"{site_url}\",")
        additions.append("    type: \"website\",")
        additions.append("  },")
    if not re.search(r"\btwitter\s*:", object_text):
        additions.append("  twitter: {")
        additions.append("    card: \"summary_large_image\",")
        additions.append(f"    title: \"{route_label}\",")
        additions.append(f"    description: \"{description}\",")
        additions.append("  },")
    if not additions:
        return original
    insertion = "\n" + "\n".join(additions) + "\n"
    return original[:close_at] + insertion + original[close_at:]


def find_import_block_end(lines: List[str]) -> int:
    insert_at = 0
    in_import = False
    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if not stripped:
            insert_at += 1
            continue
        if stripped.startswith("import "):
            in_import = not stripped.endswith(";")
            insert_at += 1
            continue
        if in_import:
            in_import = not stripped.endswith(";")
            insert_at += 1
            continue
        break
    return insert_at


def find_exported_const_object_bounds(content: str, name: str) -> Optional[tuple[int, int]]:
    match = re.search(rf"export\s+const\s+{re.escape(name)}\s*(?::[^=]+)?=\s*\{{", content)
    if not match:
        return None
    open_at = content.find("{", match.start())
    if open_at < 0:
        return None
    close_at = find_matching_delimiter(content, open_at, "{", "}")
    if close_at is None:
        return None
    return open_at, close_at


def find_matching_delimiter(content: str, start: int, open_char: str, close_char: str) -> Optional[int]:
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return None


def schema_patch_content(original: str, route_label: str, site_url: str) -> str:
    if is_client_component(original) or has_jsonld(original):
        return original
    jsonld_block = (
        "  const jsonLd = {\n"
        "    \"@context\": \"https://schema.org\",\n"
        "    \"@type\": \"WebPage\",\n"
        f"    name: \"{route_label}\",\n"
        f"    url: \"{site_url}\",\n"
        "  };\n\n"
    )
    script = (
        "      <script\n"
        "        type=\"application/ld+json\"\n"
        "        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}\n"
        "      />\n"
    )
    function_match = re.search(r"(export\s+default\s+function\s+\w+\s*\([^)]*\)\s*\{)", original)
    proposed = original
    if function_match and "const jsonLd" not in original:
        insert_at = function_match.end()
        proposed = original[:insert_at] + "\n" + jsonld_block + original[insert_at:]
    return_fragment_match = re.search(r"return\s*\(\s*\n\s*<>\s*\n", proposed)
    if return_fragment_match:
        insert_at = return_fragment_match.end()
        return proposed[:insert_at] + script + proposed[insert_at:]
    return_match = re.search(r"return\s*\(\s*\n", proposed)
    close_match = re.search(r"\n\s*\);\s*\n?\s*\}", proposed)
    if return_match and close_match:
        insert_at = return_match.end()
        close_at = close_match.start()
        return proposed[:insert_at] + "    <>\n" + script + proposed[insert_at:close_at] + "\n    </>" + proposed[close_at:]
    return proposed


def robots_patch_content(site_url: str) -> str:
    sitemap = site_url.rstrip("/") + "/sitemap.xml"
    return (
        "import type { MetadataRoute } from \"next\";\n\n"
        "export default function robots(): MetadataRoute.Robots {\n"
        "  return {\n"
        "    rules: {\n"
        "      userAgent: \"*\",\n"
        "      allow: \"/\",\n"
        "    },\n"
        f"    sitemap: \"{sitemap}\",\n"
        "  };\n"
        "}\n"
    )


def sitemap_patch_content(routes: Iterable[str], site_url: str, original: str = "") -> str:
    route_list = sorted(set(routes or ["/"]))
    if original.strip():
        return extend_existing_sitemap(original, route_list, site_url)
    lines = "\n".join(f"    \"{route}\"," for route in route_list)
    return (
        "import type { MetadataRoute } from \"next\";\n\n"
        "export default function sitemap(): MetadataRoute.Sitemap {\n"
        f"  const baseUrl = \"{site_url.rstrip('/')}\";\n"
        f"  const routes = [\n{lines}\n  ];\n\n"
        "  return routes.map((route) => ({\n"
        "    url: `${baseUrl}${route}`,\n"
        "    lastModified: new Date(),\n"
        "    changeFrequency: \"weekly\",\n"
        "    priority: route === \"/\" ? 1 : 0.8,\n"
        "  }));\n"
        "}\n"
    )


def extend_existing_sitemap(original: str, routes: Iterable[str], site_url: str) -> str:
    missing = [route for route in sorted(set(routes)) if route != "/" and route not in original]
    if not missing:
        return original
    match = re.search(r"const\s+staticRoutes\s*:[^=]+=\s*\[", original)
    if not match:
        return original
    array_open = original.rfind("[", 0, match.end())
    array_close = find_matching_delimiter(original, array_open, "[", "]") if array_open >= 0 else None
    if array_close is None:
        return original
    entries = []
    for route in missing:
        entries.append(
            "    {\n"
            f"      url: `${{baseUrl}}{route}`,\n"
            "      lastModified: now,\n"
            "      changeFrequency: \"monthly\",\n"
            "      priority: 0.7,\n"
            "    },\n"
        )
    return original[:array_close] + "".join(entries) + original[array_close:]


def label_from_route(file_path: str, fallback: str = "Website Page") -> str:
    path = file_path.replace("\\", "/")
    if path == "app/layout.tsx":
        return fallback
    route = path.removeprefix("app/").removesuffix("/page.tsx").removesuffix("page.tsx")
    words = [part for part in re.split(r"[-_/]+", route) if part and not part.startswith("[")]
    return " ".join(word.capitalize() for word in words) or fallback
