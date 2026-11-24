"""Safe local repository scanning and SEO-only patch helpers."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
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

# A Next.js project puts its App Router either at the repository root or under
# src/. Both are first-class in Next itself, so every path in this module is
# built from these prefixes rather than assuming one of them: a repo using src/
# used to scan as "unknown" and have every patch vetoed.
APP_DIR_PREFIXES = ("app", "src/app")
SUPPORT_DIR_PREFIXES = ("", "src")

# SEO files named relative to whichever app directory the repo uses.
APP_SEO_FILENAMES = ("layout.tsx", "page.tsx", "sitemap.ts", "robots.ts")
# SEO files that always sit at the repository root.
ROOT_SEO_FILENAMES = (
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "public/robots.txt",
    "public/sitemap.xml",
)
# Helper files named relative to the repo root or to src/.
SUPPORT_SEO_FILENAMES = ("lib/metadata.ts", "lib/seo.ts", "components/JsonLd.tsx")


def _candidate_seo_paths() -> set[str]:
    paths = set(ROOT_SEO_FILENAMES)
    for prefix in APP_DIR_PREFIXES:
        paths.update(f"{prefix}/{name}" for name in APP_SEO_FILENAMES)
    for prefix in SUPPORT_DIR_PREFIXES:
        paths.update(f"{prefix}/{name}" if prefix else name for name in SUPPORT_SEO_FILENAMES)
    return paths


NEXT_SEO_FILENAMES = _candidate_seo_paths()
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
    # Metadata facets a project helper supplied on this file's behalf, e.g.
    # {"canonical", "open_graph", "twitter", "title"}. Empty when the file
    # writes its own metadata or calls no known helper.
    metadata_facets_from_helper: frozenset = frozenset()


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


def app_dir_prefix(root: Path) -> Optional[str]:
    """The App Router prefix this repository actually uses, or None.

    Returns "app" or "src/app". When both exist the root one wins, because that
    is the directory Next.js itself resolves first.
    """
    for prefix in APP_DIR_PREFIXES:
        if (root / prefix).is_dir():
            return prefix
    return None


def app_dir_prefixes(root: Path) -> List[str]:
    """Every App Router prefix present, root-first."""
    return [prefix for prefix in APP_DIR_PREFIXES if (root / prefix).is_dir()]


def split_app_prefix(file_path: str) -> tuple[Optional[str], str]:
    """Split a repo-relative path into (app prefix, path inside the app dir)."""
    path = file_path.replace("\\", "/").lstrip("/")
    for prefix in sorted(APP_DIR_PREFIXES, key=len, reverse=True):
        if path == prefix:
            return prefix, ""
        if path.startswith(f"{prefix}/"):
            return prefix, path[len(prefix) + 1 :]
    return None, path


def is_app_path(file_path: str) -> bool:
    """True when the path lives under app/ or src/app/."""
    return split_app_prefix(file_path)[0] is not None


def strip_app_prefix(file_path: str) -> str:
    """The part of the path inside the app directory, whichever root it uses."""
    return split_app_prefix(file_path)[1]


def repo_relative(root: Path, file_path: str) -> str:
    """Rewrite an app-relative path to the prefix this repository actually uses.

    "app/sitemap.ts" becomes "src/app/sitemap.ts" in a src/-based repo and is
    returned unchanged in a root-based one. Paths outside the app directory are
    returned untouched. This is the one place the app/ vs src/app/ choice is
    made, so scanner, architecture detector, patch targets and the autonomous
    pipeline all agree on it.
    """
    path = file_path.replace("\\", "/").lstrip("/")
    prefix, inner = split_app_prefix(path)
    if prefix is None:
        # Outside the app directory, only drop a src/ prefix the repo does not
        # have - the behaviour the autonomous pipeline relied on before this
        # mapping moved here.
        if path.startswith("src/") and not (root / "src").is_dir():
            return path[len("src/") :]
        return path
    target = app_dir_prefix(root)
    if target is None or target == prefix:
        return path
    return f"{target}/{inner}" if inner else target


# Facets a project metadata helper can legitimately own on a page's behalf.
#
# Deliberately excludes title and description: those are per-page editorial
# content, and a helper's fallback must not make a page with no title of its own
# look complete. Canonical, Open Graph and Twitter blocks are structural - a
# helper that builds them builds them correctly for every caller.
HELPER_OWNED_FACETS = ("canonical", "open_graph", "twitter")

# Facets a helper may supply only when it derives them from its own arguments -
# a slug it looks up, a data entry it reads. A helper that merely defaults them
# to a site-wide constant supplies nothing: the page really has no title of its
# own, which is what weak_metadata is for.
HELPER_DERIVABLE_FACETS = ("title", "description")

# Where a project keeps its metadata helper, relative to the root or to src/.
METADATA_HELPER_FILENAMES = ("lib/seo.ts", "lib/metadata.ts", "lib/seo.tsx", "lib/metadata.tsx")


@dataclass(frozen=True)
class MetadataHelperProfile:
    """Which metadata facets each in-repo helper function demonstrably sets.

    A page calling `createMetadata({ path: "/about" })` has a canonical, an
    Open Graph block and a Twitter card - but none of those words appear in the
    page file, so the literal detectors below report all three as missing. That
    was the single biggest source of false positives on src/-based repos.

    The fix stays evidence-based rather than trusting a name: the helper has to
    live in this repository and its own body has to set the facet, checked with
    the same detector the page would be checked with. A helper that sets only a
    canonical vouches only for the canonical.
    """

    facets_by_helper: dict = field(default_factory=dict)
    # Facets a helper builds from its arguments rather than from a constant.
    derived_by_helper: dict = field(default_factory=dict)

    def facets_for(self, content: str) -> frozenset:
        """Facets supplied by the helpers this file actually calls."""
        if not (self.facets_by_helper or self.derived_by_helper):
            return frozenset()
        facets: set = set()
        for helper in set(self.facets_by_helper) | set(self.derived_by_helper):
            if not re.search(rf"\b{re.escape(helper)}\s*\(", content):
                continue
            facets.update(self.facets_by_helper.get(helper, frozenset()))
            # A derived facet needs an argument to derive it from, so a bare
            # `helper()` call gets the structural blocks and nothing else.
            if re.search(rf"\b{re.escape(helper)}\s*\(\s*\)", content):
                continue
            facets.update(self.derived_by_helper.get(helper, frozenset()))
        return frozenset(facets)


def _helper_facets(body: str) -> frozenset:
    """Facets a helper body produces, using the page-level detectors."""
    facets = set()
    if has_canonical(body):
        facets.add("canonical")
    if has_open_graph(body):
        facets.add("open_graph")
    if has_twitter_meta(body):
        facets.add("twitter")
    return frozenset(facets & set(HELPER_OWNED_FACETS))


def _derived_facets(param_text: str, body: str) -> frozenset:
    """Facets the helper builds itself rather than taking from its caller.

    Two conditions. The helper must set the key from something other than a
    plain string constant - a parameter, a lookup, a template literal - and it
    must not simply pass the caller's own value through: a helper whose
    parameters destructure `title` is relaying the caller's title, so the page
    still has to provide one.
    """
    destructures = "{" in param_text
    facets = set()
    for facet in HELPER_DERIVABLE_FACETS:
        if destructures and re.search(rf"\b{facet}\b", param_text):
            continue
        shorthand = re.search(rf"[,{{\s]{facet}\s*[,}}]", body)
        dynamic = re.search(rf"\b{facet}\s*:\s*(?![\'\"])", body)
        if shorthand or dynamic:
            facets.add(facet)
    return frozenset(facets)


def _parameter_text(content: str, open_paren_index: int) -> str:
    """Source of a function's parameter list, parentheses included."""
    close = find_matching_delimiter(content, open_paren_index, "(", ")")
    if close is None:
        return ""
    return content[open_paren_index : close + 1]


def metadata_helper_paths(root: Path) -> List[str]:
    """Candidate metadata-helper files, under the root or under src/."""
    paths = []
    for prefix in SUPPORT_DIR_PREFIXES:
        for name in METADATA_HELPER_FILENAMES:
            rel = f"{prefix}/{name}" if prefix else name
            if (root / rel).is_file():
                paths.append(rel)
    return paths


# How many times to propagate facets along helper-calls-helper chains. A chain
# deeper than this is unusual and would make the evidence too indirect to trust.
MAX_HELPER_RESOLUTION_ROUNDS = 4

# Next.js reserved metadata exports. They are a page's own metadata, not a
# reusable project helper, so they never vouch for another file.
RESERVED_METADATA_EXPORTS = frozenset({"metadata", "generateMetadata", "generateViewport"})

_EXPORTED_FUNCTION = re.compile(
    r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
)
_EXPORTED_ARROW = re.compile(
    r"export\s+const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?\("
)


def build_metadata_helper_profile(
    root: Path,
    extra_paths: Optional[Iterable[str]] = None,
) -> MetadataHelperProfile:
    """Read this repo's metadata helpers and record what each one provides.

    Two passes. First every exported function in the candidate files is read and
    credited with the facets its own body literally sets. Then facets propagate
    along helper-calls-helper chains, because the common shape is a small
    per-section wrapper that defers to one project-wide builder:

        createCrmSolutionMetadata(slug)  ->  createMetadata({...canonical...})

    The wrapper sets nothing itself, so without propagation it vouches for
    nothing and every page using it is still reported as missing a canonical.
    Propagation is bounded and always terminates at a helper that does set the
    facet in its own source, so nothing is trusted on the strength of its name.

    A repo with no such helper gets an empty profile, which leaves the literal
    detection exactly as it was.
    """
    bodies: dict = {}
    facets_by_helper: dict = {}
    derived_by_helper: dict = {}
    for rel in _helper_candidate_paths(root, extra_paths):
        try:
            path = safe_child_path(root, rel)
        except PathSafetyError:
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                continue
        except OSError:
            continue
        content = read_repo_text(path)
        for pattern in (_EXPORTED_FUNCTION, _EXPORTED_ARROW):
            for match in pattern.finditer(content):
                name = match.group(1)
                if name in RESERVED_METADATA_EXPORTS:
                    continue
                body = _function_body(content, match.end() - 1)
                if not body:
                    continue
                bodies[name] = bodies.get(name, "") + body
                facets = _helper_facets(body)
                if facets:
                    facets_by_helper[name] = facets_by_helper.get(name, frozenset()) | facets
                derived = _derived_facets(_parameter_text(content, match.end() - 1), body)
                if derived:
                    derived_by_helper[name] = derived_by_helper.get(name, frozenset()) | derived

    for _ in range(MAX_HELPER_RESOLUTION_ROUNDS):
        changed = False
        for name, body in bodies.items():
            inherited = set(facets_by_helper.get(name, frozenset()))
            for other, other_facets in facets_by_helper.items():
                if other == name or not other_facets:
                    continue
                if re.search(rf"\b{re.escape(other)}\s*\(", body):
                    inherited.update(other_facets)
            merged = frozenset(inherited)
            if merged and merged != facets_by_helper.get(name, frozenset()):
                facets_by_helper[name] = merged
                changed = True
        if not changed:
            break

    return MetadataHelperProfile(
        facets_by_helper=facets_by_helper,
        derived_by_helper=derived_by_helper,
    )


def _helper_candidate_paths(
    root: Path,
    extra_paths: Optional[Iterable[str]] = None,
) -> List[str]:
    """Files that may define a metadata helper, conventional ones first."""
    candidates = list(metadata_helper_paths(root))
    seen = set(candidates)
    for rel in extra_paths or []:
        clean = rel.replace("\\", "/").lstrip("/")
        if clean in seen:
            continue
        if Path(clean).suffix.lower() not in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            continue
        if not (root / clean).is_file():
            continue
        seen.add(clean)
        candidates.append(clean)
    return candidates


def _function_body(content: str, open_paren_index: int) -> str:
    """Source of one function, from its parameter list to its closing brace."""
    close_paren = find_matching_delimiter(content, open_paren_index, "(", ")")
    if close_paren is None:
        return ""
    open_brace = content.find("{", close_paren)
    if open_brace == -1:
        return ""
    close_brace = find_matching_delimiter(content, open_brace, "{", "}")
    if close_brace is None:
        return content[open_brace:]
    return content[open_brace : close_brace + 1]


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_repo_text(content: str) -> str:
    """Normalize source text before storing/hashing it in the database."""
    return content.lstrip("\ufeff")


def read_repo_text(path: Path) -> str:
    return normalize_repo_text(path.read_text(encoding="utf-8", errors="ignore"))


# Reading a file with `read_text` translates every newline to a line feed,
# which is what the hashes and the patch builders want: they compare logical
# content, not line endings. Writing that text back with `write_text` then uses
# the host's convention, so a CRLF checkout edited from a Linux container
# silently became LF.
#
# That is invisible in `git diff`, because git's clean filter normalises line
# endings too - and still wrong. The file stops matching its neighbours, and
# the bytes on disk are no longer the bytes the owner of the checkout had.
CRLF = "\r\n"
LF = "\n"


def detect_newline_style(data) -> str:
    """The newline convention a file uses, from a path, raw bytes or text.

    CRLF wins when any CRLF is present: a file with mixed endings is already
    inconsistent, and CRLF is the convention worth preserving because it is the
    one a plain text-mode write would destroy.
    """
    if isinstance(data, Path):
        try:
            data = data.read_bytes()
        except OSError:
            return LF
    if isinstance(data, bytes):
        return CRLF if b"\r\n" in data else LF
    return CRLF if "\r\n" in (data or "") else LF


def write_repo_text(path: Path, content: str, newline: str = LF) -> None:
    """Write text using an explicit newline convention.

    `newline` goes straight to the file object, so each "\\n" in `content`
    becomes exactly that sequence and nothing else is translated.
    """
    path.write_text(content, encoding="utf-8", newline=newline)


class NextJsRepoScanner:
    """Scanner for Next.js App Router SEO files."""

    def detect_framework(self, root: Path) -> str:
        package_json = root / "package.json"
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
        # Either app/ or src/app/ identifies an App Router project.
        for app_dir in (root / prefix for prefix in app_dir_prefixes(root)):
            if (app_dir / "layout.tsx").exists() or (app_dir / "page.tsx").exists():
                return "nextjs_app_router"
            if has_next_dependency:
                return "nextjs_app_router"
        return "unknown"

    def discover_files(self, root: Path) -> List[ScannedRepoFile]:
        files: List[Path] = []
        for rel_path in NEXT_SEO_FILENAMES:
            candidate = safe_child_path(root, rel_path)
            if candidate.exists() and candidate.is_file():
                files.append(candidate)
        for prefix in app_dir_prefixes(root):
            files.extend(self._walk_for_pages(root / prefix, root))
        for prefix in SUPPORT_DIR_PREFIXES:
            base = root / prefix if prefix else root
            for name in ("components", "lib"):
                folder = base / name
                if folder.exists():
                    files.extend(self._walk_for_seo_helpers(folder, root))
        unique = []
        seen = set()
        for path in files:
            if path in seen or not self._is_scannable_file(path, root):
                continue
            seen.add(path)
            unique.append(path)
        ordered = sorted(unique, key=lambda value: value.as_posix())
        # Build the helper profile from the files just discovered, so a page
        # that delegates its canonical/OG/Twitter to a project helper is not
        # reported as missing them.
        helpers = build_metadata_helper_profile(
            root, extra_paths=[path.relative_to(root).as_posix() for path in ordered]
        )
        return [self._scan_file(path, root, helpers=helpers) for path in ordered]

    def analyze(
        self, files: List[ScannedRepoFile], structure=None
    ) -> List[RepoIssueCandidate]:
        """Find SEO defects in a scanned repository.

        ``structure`` is a `ProjectStructure` from
        `app.repo_agent.project_structure.detect_structure`. It is optional so
        existing callers keep working, but without it the structural detectors
        (inherited canonical, broken internal link) cannot run: both need to know
        which application root this repository actually serves from, and guessing
        is what caused patches to be written into a parallel `app/` tree before.
        """
        issues: List[RepoIssueCandidate] = []
        by_path = {file.file_path: file for file in files}
        app_files = [file for file in files if is_app_path(file.file_path)]
        page_files = [file for file in files if file.detected_purpose == RepoFilePurpose.page]
        layout_files = [file for file in files if file.detected_purpose == RepoFilePurpose.layout]
        # The sitemap/robots route lives under whichever app directory the repo
        # uses, so look for both before falling back to the static public/ file.
        sitemap_file = self._first_by_path(by_path, APP_DIR_PREFIXES, "sitemap.ts") or by_path.get(
            "public/sitemap.xml"
        )
        robots_file = self._first_by_path(by_path, APP_DIR_PREFIXES, "robots.ts") or by_path.get(
            "public/robots.txt"
        )

        if not sitemap_file:
            issues.append(
                self._global_issue(
                    SeoCodeIssueType.missing_sitemap,
                    SeoCodeIssueSeverity.high,
                    "Missing sitemap implementation",
                    "No app/sitemap.ts, src/app/sitemap.ts or public/sitemap.xml file was found.",
                    "Add a Next.js app/sitemap.ts route so important routes can be discovered by search engines.",
                )
            )
        if not robots_file:
            issues.append(
                self._global_issue(
                    SeoCodeIssueType.missing_robots,
                    SeoCodeIssueSeverity.medium,
                    "Missing robots implementation",
                    "No app/robots.ts, src/app/robots.ts or public/robots.txt file was found.",
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
            elif file.has_metadata and not self._metadata_has_title_and_description(
                file.content, file.metadata_facets_from_helper
            ):
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
        issues.extend(self._structural_issues(files, by_path, structure))
        return issues

    def _structural_issues(
        self, files: List[ScannedRepoFile], by_path: dict, structure
    ) -> List[RepoIssueCandidate]:
        """Defects that are fixed by removing or rewriting code, not adding it.

        Imported lazily: `structural_detectors` reaches back into this module
        through `project_structure`, so a module-level import would be circular.
        """
        if structure is None:
            return []
        from app.repo_agent.structural_detectors import (
            find_broken_internal_links,
            find_inherited_canonicals,
            routes_without_own_canonical,
        )

        issues: List[RepoIssueCandidate] = []

        for finding in find_inherited_canonicals(files, structure):
            file = by_path.get(finding.file_path)
            if not file:
                continue
            affected = routes_without_own_canonical(files, structure)
            issues.append(
                self._file_issue(
                    file,
                    SeoCodeIssueType.inherited_canonical,
                    # High, not critical: it only bites the routes that have no
                    # canonical of their own, and the count tells the reviewer
                    # how much is actually at stake.
                    SeoCodeIssueSeverity.high,
                    "Canonical declared in the root layout",
                    finding.detail
                    + f" {len(affected)} route file(s) currently inherit it.",
                    "Remove the canonical from the root layout and give each route its own.",
                )
            )

        routes = static_routes_from_pages(files)
        link_files = self._discover_link_files(structure.root, files)
        link_by_path = {file.file_path: file for file in link_files}
        for finding in find_broken_internal_links(link_files, routes):
            file = link_by_path.get(finding.file_path)
            if not file:
                continue
            suggestion = finding.payload.get("new_href")
            issues.append(
                self._file_issue(
                    file,
                    SeoCodeIssueType.broken_internal_link,
                    SeoCodeIssueSeverity.high,
                    "Internal link points at a route that does not exist",
                    finding.detail,
                    (f"Repoint the link to {suggestion}." if suggestion
                     else "Decide the correct destination; no single replacement was obvious."),
                )
            )
        return issues

    # Links live in ordinary components, which the SEO-helper walk deliberately
    # skips (it only wants files named like seo.ts / JsonLd.tsx). Link checking
    # therefore needs its own, wider pass — bounded so a large repository cannot
    # turn a scan into a full-tree read.
    LINK_SCAN_DIRS = ("components", "src/components", "data", "src/data")
    LINK_SCAN_FILE_LIMIT = 400

    def _discover_link_files(
        self, root: Path, already: List[ScannedRepoFile]
    ) -> List[ScannedRepoFile]:
        """The already-scanned files plus the component/data files links live in."""
        collected = list(already)
        seen = {file.file_path for file in already}
        budget = self.LINK_SCAN_FILE_LIMIT
        folders = [root / prefix for prefix in app_dir_prefixes(root)]
        folders += [root / name for name in self.LINK_SCAN_DIRS]
        for folder in folders:
            if budget <= 0:
                break
            if not folder.exists() or not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if budget <= 0:
                    break
                if not self._is_scannable_file(path, root):
                    continue
                rel = path.relative_to(root).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                budget -= 1
                try:
                    collected.append(self._scan_file(path, root))
                except OSError:
                    continue
        return collected

    @staticmethod
    def _first_by_path(
        by_path: dict,
        prefixes: Iterable[str],
        name: str,
    ) -> Optional[ScannedRepoFile]:
        """First scanned file matching <prefix>/<name> over the given prefixes."""
        for prefix in prefixes:
            found = by_path.get(f"{prefix}/{name}")
            if found:
                return found
        return None

    def _walk_for_pages(self, app_dir: Path, root: Path) -> List[Path]:
        paths = []
        for path in app_dir.rglob("*.tsx"):
            if self._ignored(path, root):
                continue
            rel = path.relative_to(root).as_posix()
            inner = strip_app_prefix(rel)
            if rel.endswith("/page.tsx") or inner == "page.tsx" or rel.endswith("/layout.tsx"):
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

    def _scan_file(
        self,
        path: Path,
        root: Path,
        helpers: Optional[MetadataHelperProfile] = None,
    ) -> ScannedRepoFile:
        content = read_repo_text(path)
        rel_path = path.relative_to(root).as_posix()
        purpose = detect_file_purpose(rel_path, content)
        has_metadata = has_metadata_export(content)
        # A helper only vouches for a file that exports metadata and calls it.
        supplied = (
            helpers.facets_for(content) if (helpers and has_metadata) else frozenset()
        )
        return ScannedRepoFile(
            file_path=rel_path,
            file_type=path.suffix.lstrip(".") or "text",
            content_hash=content_hash(content),
            detected_purpose=purpose,
            has_metadata=has_metadata,
            has_jsonld=has_jsonld(content),
            has_canonical=has_canonical(content) or "canonical" in supplied,
            has_open_graph=has_open_graph(content) or "open_graph" in supplied,
            has_twitter_meta=has_twitter_meta(content) or "twitter" in supplied,
            has_sitemap=purpose == RepoFilePurpose.sitemap,
            has_robots=purpose == RepoFilePurpose.robots,
            content=content,
            metadata_facets_from_helper=supplied,
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

    def _metadata_has_title_and_description(
        self,
        content: str,
        helper_facets: frozenset = frozenset(),
    ) -> bool:
        """Whether the page ends up with both a title and a description.

        Either the file writes them, or a project helper derives them from the
        arguments the file passes - `createSolutionMetadata({ activeSlug })`
        looks the real title up by slug, so the page is not weak just because
        the string is not in this file.
        """
        has_title = bool(re.search(r"\btitle\s*:", content)) or "title" in helper_facets
        has_description = (
            bool(re.search(r"\bdescription\s*:", content)) or "description" in helper_facets
        )
        return has_title and has_description

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
    inner = strip_app_prefix(path)
    if inner == "layout.tsx" or path.endswith("/layout.tsx"):
        return RepoFilePurpose.layout
    if inner == "page.tsx" or path.endswith("/page.tsx"):
        return RepoFilePurpose.page
    if inner == "sitemap.ts" or path == "public/sitemap.xml":
        return RepoFilePurpose.sitemap
    if inner == "robots.ts" or path == "public/robots.txt":
        return RepoFilePurpose.robots
    if path in _support_paths("lib/metadata.ts", "lib/seo.ts") or "metadata" in name or name == "seo.ts":
        return RepoFilePurpose.metadata
    if "jsonld" in name or "json-ld" in name or has_jsonld(content):
        return RepoFilePurpose.jsonld
    if name.startswith("next.config"):
        return RepoFilePurpose.config
    if path.startswith(tuple(f"{p}/" for p in _support_paths("components"))):
        return RepoFilePurpose.component
    return RepoFilePurpose.unknown


def _support_paths(*names: str) -> set[str]:
    """The given helper paths under the repository root and under src/."""
    return {
        f"{prefix}/{name}" if prefix else name
        for prefix in SUPPORT_DIR_PREFIXES
        for name in names
    }


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
        prefix, inner = split_app_prefix(path)
        if prefix is None or not (inner.endswith("/page.tsx") or inner == "page.tsx"):
            continue
        if "[" in path or "]" in path:
            continue
        route = inner.removesuffix("/page.tsx").removesuffix("page.tsx")
        route = "/" + route.strip("/")
        routes.append(route if route != "/" else "/")
    return sorted(set(routes), key=lambda value: (value.count("/"), value))


def is_internal_app_path(file_path: str) -> bool:
    route = strip_app_prefix(file_path).strip("/")
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
    # Strip whichever app directory the repo uses, so a src/-based project does
    # not produce labels like "Src App Company".
    inner = strip_app_prefix(path)
    if inner == "layout.tsx":
        return fallback
    route = inner.removesuffix("/page.tsx").removesuffix("page.tsx")
    words = [part for part in re.split(r"[-_/]+", route) if part and not part.startswith("[")]
    return " ".join(word.capitalize() for word in words) or fallback
