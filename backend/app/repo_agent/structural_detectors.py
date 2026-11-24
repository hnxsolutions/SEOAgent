"""Detect the structural SEO defects the additive vocabulary could never express.

Two detectors, both drawn from defects found on a real site:

* **inherited canonical** — a canonical declared in a root layout. In the App
  Router `alternates` is inherited by every segment that does not set its own, so
  one line in `layout.tsx` can make dozens of pages declare the homepage as their
  canonical and be folded into it. The additive vocabulary had only
  `canonical_addition`; the fix is a removal.

* **broken internal link** — an `href` pointing at a route the repository does
  not build. The additive vocabulary had no way to rewrite a link at all.

Both produce *findings*, not patches. Turning a finding into a patch is a
separate, explicit step that runs the candidate through
`patch_vocabulary.validate_patch`, so nothing bypasses the per-type rules.

Pure: no database, no git, no writes. The only input is scanned file content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from app.repo_agent.patch_vocabulary import validate_patch
from app.repo_agent.project_structure import ProjectStructure

# `href="/x"`, `href={"/x"}`, `href: "/x"` — root-relative only. External URLs,
# template literals and variables are deliberately not matched: this detector
# only reports links it can reason about with certainty.
_HREF_RE = re.compile(r"""href\s*[:=]\s*\{?\s*["'](?P<href>/[^"'{}\s]*)["']""")

# A canonical inside a metadata object.
_CANONICAL_RE = re.compile(r"canonical\s*:\s*[\"'`]")
# A line holding a canonical entry AND NOTHING ELSE — the only shape it is safe
# to delete wholesale.
_CANONICAL_ONLY_RE = re.compile(r"^\s*canonical\s*:\s*[\"'`][^\"'`]*[\"'`]\s*,?\s*$")

_ROOT_LAYOUT_NAMES = ("layout.tsx", "layout.jsx")


@dataclass
class Finding:
    """One detected defect, with the patch it suggests (when it is certain)."""

    kind: str
    file_path: str
    detail: str
    suggested_patch_type: Optional[str] = None
    payload: Dict[str, str] = field(default_factory=dict)
    confident: bool = False

    @property
    def actionable(self) -> bool:
        return self.confident and self.suggested_patch_type is not None


def _is_root_layout(file_path: str, structure: Optional[ProjectStructure]) -> bool:
    """Is this THE layout every route inherits from?"""
    if structure is None or not structure.app_prefix:
        return False
    path = file_path.replace("\\", "/").strip("/")
    for name in _ROOT_LAYOUT_NAMES:
        if path == f"{structure.app_prefix}/{name}":
            return True
    return False


# -- inherited canonical ------------------------------------------------------

def find_inherited_canonicals(
    files: Iterable, structure: Optional[ProjectStructure]
) -> List[Finding]:
    """Flag a canonical declared in the root layout.

    Only the root layout is reported. A canonical in a nested layout applies to a
    bounded subtree and is often deliberate; the root one applies to everything
    and is almost never what the author meant.
    """
    findings: List[Finding] = []
    for file in files:
        path = getattr(file, "file_path", "")
        content = getattr(file, "content", "") or ""
        if not _is_root_layout(path, structure):
            continue
        if not _CANONICAL_RE.search(content):
            continue
        findings.append(
            Finding(
                kind="inherited_canonical",
                file_path=path,
                detail=(
                    f"{path} declares a canonical in the root layout. Every route that does "
                    "not set its own canonical inherits it, so those pages all claim the same "
                    "canonical URL and search engines will fold them together."
                ),
                suggested_patch_type="canonical_removal",
                payload={"target_file": path},
                confident=True,
            )
        )
    return findings


def routes_without_own_canonical(
    files: Iterable, structure: Optional[ProjectStructure]
) -> List[str]:
    """Which route files would actually be harmed by an inherited canonical."""
    affected = []
    for file in files:
        path = getattr(file, "file_path", "")
        if _is_root_layout(path, structure):
            continue
        if not path.endswith(("page.tsx", "page.jsx")):
            continue
        if getattr(file, "has_canonical", False):
            continue
        if getattr(file, "metadata_facets_from_helper", None) and "canonical" in file.metadata_facets_from_helper:
            continue
        affected.append(path)
    return affected


# -- broken internal links ----------------------------------------------------

def _normalise(route: str) -> str:
    route = (route or "").split("#", 1)[0].split("?", 1)[0]
    route = "/" + route.strip("/")
    return route if route != "/" else "/"


def dynamic_route_patterns(files: Iterable) -> List[List[str]]:
    """Segment patterns for the App Router's dynamic routes.

    `static_routes_from_pages` deliberately skips any path containing `[`, so a
    link served by `app/industries/[slug]/[solutionSlug]/page.tsx` has no entry
    in the static table and would otherwise be reported as broken. This returns
    those routes as segment lists — `["industries", "[slug]", "[solutionSlug]"]`
    — so they can be matched against.
    """
    patterns: List[List[str]] = []
    for file in files:
        path = (getattr(file, "file_path", "") or "").replace("\\", "/")
        if "[" not in path:
            continue
        if not path.endswith(("/page.tsx", "/page.jsx", "/page.ts", "/page.js")):
            continue
        from app.repo_agent.scanner import is_internal_app_path, split_app_prefix

        if is_internal_app_path(path):
            continue
        prefix, inner = split_app_prefix(path)
        if prefix is None:
            continue
        inner = re.sub(r"/page\.[tj]sx?$", "", inner)
        segments = [s for s in inner.split("/") if s]
        # Route groups like (marketing) do not appear in the URL.
        segments = [s for s in segments if not (s.startswith("(") and s.endswith(")"))]
        if segments:
            patterns.append(segments)
    return patterns


def _matches_dynamic(route: str, patterns: Iterable[List[str]]) -> bool:
    parts = [s for s in _normalise(route).split("/") if s]
    for pattern in patterns:
        if _segments_match(parts, pattern):
            return True
    return False


def _segments_match(parts: List[str], pattern: List[str]) -> bool:
    index = 0
    for position, segment in enumerate(pattern):
        if segment.startswith("[...") or segment.startswith("[[..."):
            # A catch-all consumes the rest; an optional one may consume nothing.
            optional = segment.startswith("[[")
            remaining = len(parts) - index
            return remaining > 0 or optional
        if index >= len(parts):
            return False
        if segment.startswith("[") and segment.endswith("]"):
            index += 1
            continue
        if segment != parts[index]:
            return False
        index += 1
    return index == len(parts)


def suggest_route(dead: str, routes: Set[str]) -> Optional[str]:
    """The one live route a dead one almost certainly meant, or None.

    Conservative on purpose: a suggestion is only returned when exactly one live
    route ends with the dead route's last segment. Where several could match, the
    link is still reported — it just does not become an automatic patch.
    """
    tail = _normalise(dead).rsplit("/", 1)[-1]
    if not tail:
        return None
    candidates = sorted({r for r in routes if r.rsplit("/", 1)[-1] == tail})
    if len(candidates) == 1:
        return candidates[0]
    return None


def find_broken_internal_links(
    files: Iterable,
    routes: Sequence[str],
    *,
    ignore: Sequence[str] = (),
    dynamic_patterns: Optional[Sequence[List[str]]] = None,
) -> List[Finding]:
    """Flag root-relative hrefs that no built route serves.

    ``dynamic_patterns`` comes from `dynamic_route_patterns()`. Without it, a
    link served by a dynamic route is reported as broken — the static route table
    has no entry for it — so callers that have the file list should always pass
    it. ``files`` is used to derive it when the caller does not.
    """
    files = list(files)
    live = {_normalise(r) for r in routes}
    skip = {_normalise(r) for r in ignore}
    patterns = list(dynamic_patterns) if dynamic_patterns is not None else dynamic_route_patterns(files)
    findings: List[Finding] = []
    for file in files:
        path = getattr(file, "file_path", "")
        content = getattr(file, "content", "") or ""
        seen: Set[str] = set()
        for match in _HREF_RE.finditer(content):
            href = match.group("href")
            target = _normalise(href)
            if target in live or target in skip or target in seen:
                continue
            seen.add(target)
            # A path with a dynamic segment cannot be checked against a static
            # route table, so it is left alone.
            if "[" in target or "]" in target:
                continue
            # A dynamic route may well serve it even though the static table
            # has no entry.
            if _matches_dynamic(target, patterns):
                continue
            suggestion = suggest_route(target, live)
            findings.append(
                Finding(
                    kind="broken_internal_link",
                    file_path=path,
                    detail=(
                        f"{path} links to {href}, which no route in this repository builds."
                        + (f" The only matching live route is {suggestion}." if suggestion
                           else " No single obvious replacement was found, so this needs a human decision.")
                    ),
                    suggested_patch_type="internal_link_fix" if suggestion else None,
                    payload=({"target_file": path, "old_href": href, "new_href": suggestion}
                             if suggestion else {"target_file": path, "old_href": href}),
                    confident=bool(suggestion),
                )
            )
    return findings


# -- finding -> validated patch ----------------------------------------------

@dataclass
class PatchCandidate:
    patch_type: str
    target_file: str
    payload: Dict[str, str]
    before: str
    after: str
    reasons: List[str] = field(default_factory=list)
    ok: bool = False


def _strip_canonical_block(content: str) -> str:
    """Remove a `canonical: "..."` entry, and an `alternates` wrapper left empty.

    Deliberately line-based and conservative: it removes the canonical line, then
    an `alternates: {` / `},` pair only when nothing else remained inside it. A
    shape it does not recognise is left alone, and the vocabulary's removal check
    then rejects the patch rather than letting a half-edit through.
    """
    lines = content.splitlines(keepends=True)
    # Only drop a line that is NOTHING BUT a canonical entry. When the canonical
    # shares its line with other declarations — an inline `metadata = { alternates:
    # { canonical: "x", languages: {} } }` — removing the line would take them with
    # it, so the line is left alone and the vocabulary's collateral-damage check
    # then rejects the unchanged patch instead of applying a destructive one.
    kept = [
        line for line in lines
        if not (_CANONICAL_RE.search(line) and _CANONICAL_ONLY_RE.match(line))
    ]
    out: List[str] = []
    index = 0
    while index < len(kept):
        line = kept[index]
        if re.search(r"alternates\s*:\s*\{\s*$", line):
            closing = index + 1
            if closing < len(kept) and re.match(r"^\s*\},?\s*$", kept[closing]):
                index = closing + 1
                continue
        out.append(line)
        index += 1
    return "".join(out)


def build_patch(
    finding: Finding, before: str, structure: Optional[ProjectStructure]
) -> PatchCandidate:
    """Turn an actionable finding into a patch, validated by the vocabulary."""
    candidate = PatchCandidate(
        patch_type=finding.suggested_patch_type or "",
        target_file=finding.file_path,
        payload=dict(finding.payload),
        before=before,
        after=before,
    )
    if not finding.actionable:
        candidate.reasons.append("finding is not actionable; it is reported for review only")
        return candidate

    if finding.suggested_patch_type == "canonical_removal":
        candidate.after = _strip_canonical_block(before)
    elif finding.suggested_patch_type == "internal_link_fix":
        old = finding.payload.get("old_href", "")
        new = finding.payload.get("new_href", "")
        candidate.after = before.replace(old, new) if old and new else before
    else:
        candidate.reasons.append(f"no builder for {finding.suggested_patch_type}")
        return candidate

    result = validate_patch(
        candidate.patch_type,
        candidate.payload,
        before=candidate.before,
        after=candidate.after,
        structure=structure,
    )
    candidate.ok = result.ok
    candidate.reasons = list(result.reasons)
    return candidate
