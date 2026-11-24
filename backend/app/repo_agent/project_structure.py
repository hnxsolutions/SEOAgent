"""Repository-aware project structure detection and patch target resolution.

The framework patch generators in ``app.framework_patches`` are deliberately pure:
they have no filesystem access, so they emit *canonical template* paths such as
``app/sitemap.ts``. That is correct for them, but those strings must never reach
the database unmapped — a project using ``src/app/`` would receive a patch
creating a second, shadowing App Router root at ``app/``, and Next.js resolves
``app/`` first, so the real application would stop being served.

This module is the bridge. It resolves the structure a repository actually uses
and rewrites template targets onto it, reusing the existing helpers in
``app.repo_agent.scanner`` (``app_dir_prefix``, ``repo_relative``,
``safe_child_path``) rather than re-deriving the app/ vs src/app/ decision. The
only thing added here is the Pages Router equivalent, the ambiguity rules, and
the refusal behaviour.

Nothing in this module writes to disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.repo_agent.scanner import (
    APP_DIR_PREFIXES,
    PathSafetyError,
    app_dir_prefixes,
    repo_relative,
    resolve_repo_root,
    safe_child_path,
    split_app_prefix,
)

# The Pages Router equivalent of APP_DIR_PREFIXES. Root-first, matching the
# order Next.js itself resolves them.
PAGES_DIR_PREFIXES = ("pages", "src/pages")

# Resolution outcomes for a single patch target.
RESOLVED = "resolved"
UNRESOLVED = "unresolved"
REJECTED = "rejected"


class StructureError(ValueError):
    """Raised when a repository's structure cannot support patch generation."""


@dataclass
class ResolvedTarget:
    """One framework-template target mapped onto the real repository."""

    original: str
    path: Optional[str] = None
    exists: bool = False
    is_new_file: bool = False
    status: str = UNRESOLVED
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == RESOLVED


@dataclass
class ProjectStructure:
    """What a repository actually looks like on disk."""

    root: Path
    app_prefixes: List[str] = field(default_factory=list)
    pages_prefixes: List[str] = field(default_factory=list)
    typescript: bool = True
    ambiguous: bool = False
    ambiguity_reason: str = ""
    existing: Dict[str, str] = field(default_factory=dict)

    @property
    def app_prefix(self) -> Optional[str]:
        return self.app_prefixes[0] if self.app_prefixes else None

    @property
    def pages_prefix(self) -> Optional[str]:
        return self.pages_prefixes[0] if self.pages_prefixes else None

    @property
    def router(self) -> str:
        if self.app_prefixes:
            return "app"
        if self.pages_prefixes:
            return "pages"
        return "unknown"

    @property
    def code_extension(self) -> str:
        return ".ts" if self.typescript else ".js"

    @property
    def component_extension(self) -> str:
        return ".tsx" if self.typescript else ".jsx"


def _pages_dir_prefixes(root: Path) -> List[str]:
    """Every Pages Router prefix present, root-first."""
    return [prefix for prefix in PAGES_DIR_PREFIXES if (root / prefix).is_dir()]


def _split_pages_prefix(file_path: str) -> tuple[Optional[str], str]:
    """Split a repo-relative path into (pages prefix, path inside it)."""
    path = file_path.replace("\\", "/").lstrip("/")
    for prefix in sorted(PAGES_DIR_PREFIXES, key=len, reverse=True):
        if path == prefix:
            return prefix, ""
        if path.startswith(f"{prefix}/"):
            return prefix, path[len(prefix) + 1 :]
    return None, path


def _uses_typescript(root: Path) -> bool:
    if (root / "tsconfig.json").is_file():
        return True
    for prefix in APP_DIR_PREFIXES + PAGES_DIR_PREFIXES:
        directory = root / prefix
        if not directory.is_dir():
            continue
        for candidate in directory.rglob("*.ts*"):
            if candidate.suffix in {".ts", ".tsx"}:
                return True
    return False


def _find_existing(root: Path, names: List[str]) -> Optional[str]:
    for name in names:
        if (root / name).is_file():
            return name
    return None


def detect_structure(local_path: str) -> ProjectStructure:
    """Inspect a checkout and describe the structure it actually uses.

    Raises ``PathSafetyError`` when the path is missing — the caller should treat
    that as "repository unavailable" and refuse to guess paths.
    """
    root = resolve_repo_root(local_path)
    app_prefixes = app_dir_prefixes(root)
    pages_prefixes = _pages_dir_prefixes(root)

    ambiguous = False
    reason = ""
    # Two roots of the SAME router kind is the dangerous case: Next.js resolves
    # one and silently ignores the other, so any patch we write may land in the
    # dead one. An app/ + pages/ hybrid is legal Next.js and is NOT ambiguous.
    if len(app_prefixes) > 1:
        ambiguous = True
        reason = (
            "Both "
            + " and ".join(app_prefixes)
            + " exist. Next.js serves only the first, so a patch target cannot be chosen safely."
        )
    elif len(pages_prefixes) > 1:
        ambiguous = True
        reason = (
            "Both "
            + " and ".join(pages_prefixes)
            + " exist. Next.js serves only the first, so a patch target cannot be chosen safely."
        )
    elif not app_prefixes and not pages_prefixes:
        ambiguous = True
        reason = (
            "No Next.js application root was found (looked for "
            + ", ".join(APP_DIR_PREFIXES + PAGES_DIR_PREFIXES)
            + ")."
        )

    structure = ProjectStructure(
        root=root,
        app_prefixes=app_prefixes,
        pages_prefixes=pages_prefixes,
        typescript=_uses_typescript(root),
        ambiguous=ambiguous,
        ambiguity_reason=reason,
    )

    active_app = structure.app_prefix
    active_pages = structure.pages_prefix
    sitemap_names = [f"{active_app}/sitemap.ts", f"{active_app}/sitemap.js"] if active_app else []
    robots_names = [f"{active_app}/robots.ts", f"{active_app}/robots.js"] if active_app else []
    structure.existing = {
        key: value
        for key, value in {
            "sitemap": _find_existing(root, sitemap_names + ["public/sitemap.xml"]),
            "robots": _find_existing(root, robots_names + ["public/robots.txt"]),
            "layout": _find_existing(
                root, [f"{active_app}/layout.tsx", f"{active_app}/layout.jsx"] if active_app else []
            ),
            "app_document": _find_existing(
                root,
                [f"{active_pages}/_document.tsx", f"{active_pages}/_document.jsx"]
                if active_pages
                else [],
            ),
            "seo_helper": _find_existing(
                root, ["src/lib/seo.ts", "lib/seo.ts", "src/lib/metadata.ts", "lib/metadata.ts"]
            ),
            "jsonld": _find_existing(
                root, ["src/components/JsonLd.tsx", "components/JsonLd.tsx"]
            ),
        }.items()
        if value
    }
    return structure


def _adapt_extension(path: str, structure: ProjectStructure) -> str:
    """Match the project's own language. A JS project gets .js / .jsx."""
    if structure.typescript:
        return path
    if path.endswith(".tsx"):
        return path[: -len(".tsx")] + ".jsx"
    if path.endswith(".ts"):
        return path[: -len(".ts")] + ".js"
    return path


def strip_target_hint(target_file: str) -> str:
    """Drop the human hint generators append, e.g. "app/page.tsx (metadata export)"."""
    return (target_file or "").split(" (")[0].strip()


def resolve_target(target_file: str, structure: ProjectStructure) -> ResolvedTarget:
    """Map one framework-template target onto this repository.

    Returns a ``ResolvedTarget`` whose ``status`` is ``resolved``, ``unresolved``
    or ``rejected``. A rejected target must never be stored as a safe patch.
    """
    original = target_file or ""
    cleaned = strip_target_hint(original)
    if not cleaned:
        return ResolvedTarget(original, status=REJECTED, reason="Patch has no target path.")

    if structure.ambiguous:
        return ResolvedTarget(
            original,
            status=REJECTED,
            reason=f"Repository architecture is ambiguous: {structure.ambiguity_reason}",
        )

    app_prefix, app_inner = split_app_prefix(cleaned)
    pages_prefix, pages_inner = _split_pages_prefix(cleaned)

    if app_prefix is not None:
        active = structure.app_prefix
        if not active:
            return ResolvedTarget(
                original,
                status=REJECTED,
                reason=(
                    f"Target is App Router ({cleaned}) but this repository has no App Router "
                    f"directory. Creating {app_prefix}/ would add a second application root."
                ),
            )
        # repo_relative is the single source of truth for app/ vs src/app/.
        mapped = repo_relative(structure.root, cleaned)
    elif pages_prefix is not None:
        active = structure.pages_prefix
        if not active:
            return ResolvedTarget(
                original,
                status=REJECTED,
                reason=(
                    f"Target is Pages Router ({cleaned}) but this repository has no Pages Router "
                    f"directory. Creating {pages_prefix}/ would add a second application root."
                ),
            )
        mapped = f"{active}/{pages_inner}" if pages_inner else active
    else:
        # Outside any router directory (public/robots.txt, next.config.js, a
        # support component). repo_relative still normalises a src/ prefix the
        # repository does not have.
        mapped = repo_relative(structure.root, cleaned)

    mapped = _adapt_extension(mapped, structure)

    try:
        absolute = safe_child_path(structure.root, mapped)
    except PathSafetyError as exc:
        return ResolvedTarget(original, status=REJECTED, reason=str(exc))

    return ResolvedTarget(
        original=original,
        path=mapped,
        exists=absolute.is_file(),
        is_new_file=not absolute.is_file(),
        status=RESOLVED,
        reason=f"Mapped onto the repository's own structure ({structure.router} router).",
    )


def shadow_root_risk(target_path: str, structure: ProjectStructure) -> Optional[str]:
    """Explain why writing ``target_path`` would create a competing app root.

    Returns None when there is no such risk.
    """
    path = (target_path or "").replace("\\", "/").lstrip("/")
    app_prefix, _ = split_app_prefix(path)
    if app_prefix and structure.app_prefix and app_prefix != structure.app_prefix:
        return (
            f"Writing {path} would create a second App Router root at {app_prefix}/ "
            f"while this project serves from {structure.app_prefix}/. Next.js resolves "
            f"{APP_DIR_PREFIXES[0]}/ first, so the existing application would stop being served."
        )
    pages_prefix, _ = _split_pages_prefix(path)
    if pages_prefix and structure.pages_prefix and pages_prefix != structure.pages_prefix:
        return (
            f"Writing {path} would create a second Pages Router root at {pages_prefix}/ "
            f"while this project serves from {structure.pages_prefix}/."
        )
    return None
