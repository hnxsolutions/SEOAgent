"""Declarative rules for the structural patch types.

The original vocabulary was additive only — `metadata_update`, `schema_addition`,
`sitemap_update`, `robots_update`, `canonical_addition`, `og_twitter_addition`,
`semantic_html_safe_suggestion`. Nothing could express "delete this canonical" or
"this href points at a 404", so whole classes of real SEO defects were outside
the agent's reach.

This module adds the structural types, and does it declaratively: each type
names the paths it may touch, the single operation it may perform, and the
checks that must pass. A patch type is never a licence to edit arbitrary code —
`internal_link_fix`, for instance, may touch a component file (that is where
links live) but may only swap one literal route string for another, and the
validator rejects a diff that changed anything else.

Pure: no I/O beyond reading the file it is asked to judge, no database, no git.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from app.repo_agent.project_structure import ProjectStructure, strip_target_hint

# -- operations ---------------------------------------------------------------

REMOVE = "remove"
REPLACE_LITERAL = "replace_literal"
REPLACE_FIELD = "replace_field"
SET_CONFIG_KEY = "set_config_key"
GROUP = "group"

# Config keys a config_update patch may touch. Anything else is refused: a
# config file is the one place a "small SEO change" can alter routing, security
# headers or the build.
ALLOWED_CONFIG_KEYS = frozenset({
    "trailingSlash",
    "redirects",
    "headers",
    "images",
    "generateBuildId",
})

# Metadata fields a metadata_replace patch may rewrite.
ALLOWED_METADATA_FIELDS = frozenset({
    "title",
    "description",
    "keywords",
    "alternates",
    "openGraph",
    "twitter",
    "robots",
})


@dataclass
class PatchTypeSpec:
    """What one patch type is allowed to be."""

    name: str
    operation: str
    summary: str
    # Path predicates. A target must satisfy at least one to be permitted.
    allows_app_routes: bool = False
    allows_pages_routes: bool = False
    allows_seo_helpers: bool = False
    allows_components: bool = False
    allows_data_modules: bool = False
    allowed_filenames: Sequence[str] = ()
    # Hard refusals regardless of anything else.
    forbidden_segments: Sequence[str] = ("node_modules", ".next", "api", "auth", "payments", "prisma")
    requires_existing_file: bool = True
    may_create_file: bool = False
    # Extra keys the patch payload must carry.
    required_fields: Sequence[str] = ()


SPECS: Dict[str, PatchTypeSpec] = {
    "canonical_removal": PatchTypeSpec(
        name="canonical_removal",
        operation=REMOVE,
        summary="Delete a canonical declaration that should not be there.",
        allows_app_routes=True,
        allows_pages_routes=True,
        allows_seo_helpers=True,
        allowed_filenames=("layout.tsx", "layout.jsx", "page.tsx", "page.jsx",
                           "_document.tsx", "_document.jsx", "seo.ts", "metadata.ts"),
        required_fields=("target_file",),
    ),
    "metadata_replace": PatchTypeSpec(
        name="metadata_replace",
        operation=REPLACE_FIELD,
        summary="Replace the value of one existing metadata field.",
        allows_app_routes=True,
        allows_pages_routes=True,
        allows_seo_helpers=True,
        allowed_filenames=("layout.tsx", "layout.jsx", "page.tsx", "page.jsx",
                           "_document.tsx", "_document.jsx", "seo.ts", "metadata.ts"),
        required_fields=("target_file", "field"),
    ),
    "internal_link_fix": PatchTypeSpec(
        name="internal_link_fix",
        operation=REPLACE_LITERAL,
        summary="Repoint an internal link from a dead route to a live one.",
        allows_app_routes=True,
        allows_pages_routes=True,
        # Links live in components and in data modules; this type is the one
        # exception to the component guard, and it is bounded to swapping a
        # route literal.
        allows_components=True,
        allows_data_modules=True,
        required_fields=("target_file", "old_href", "new_href"),
    ),
    "config_update": PatchTypeSpec(
        name="config_update",
        operation=SET_CONFIG_KEY,
        summary="Change one allow-listed key in the framework config.",
        allowed_filenames=("next.config.js", "next.config.mjs", "next.config.ts", "vercel.json"),
        required_fields=("target_file", "config_key"),
    ),
    "multi_file_patch": PatchTypeSpec(
        name="multi_file_patch",
        operation=GROUP,
        summary="A set of single-file patches applied all-or-nothing.",
        requires_existing_file=False,
        required_fields=("members",),
    ),
}

NEW_PATCH_TYPES = tuple(SPECS)


@dataclass
class VocabularyResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    notes: Dict[str, object] = field(default_factory=dict)

    def fail(self, reason: str) -> "VocabularyResult":
        self.ok = False
        self.reasons.append(reason)
        return self


# -- path permission ----------------------------------------------------------

_SEO_HELPER_RE = re.compile(r"(^|/)(lib|utils)/(seo|metadata)\.(ts|js)$")
_COMPONENT_RE = re.compile(r"(^|/)components?/")
_DATA_RE = re.compile(r"(^|/)data/")


def _within_router(path: str, structure: Optional[ProjectStructure], kind: str) -> bool:
    if structure is None:
        return False
    prefix = structure.app_prefix if kind == "app" else structure.pages_prefix
    return bool(prefix) and path.startswith(f"{prefix}/")


def path_permitted(
    path: str, spec: PatchTypeSpec, structure: Optional[ProjectStructure]
) -> tuple[bool, str]:
    """Is this patch type allowed to touch this path at all?"""
    clean = (path or "").replace("\\", "/").strip("/")
    if not clean:
        return False, "empty target path"
    segments = clean.split("/")
    for segment in segments[:-1]:
        if segment in spec.forbidden_segments:
            return False, f"target is inside a forbidden area ({segment}/)"
    filename = segments[-1]

    if spec.allowed_filenames and filename in spec.allowed_filenames:
        # A filename allowance still has to sit somewhere sensible for route files.
        if spec.name == "config_update":
            if len(segments) != 1:
                return False, "config files are only permitted at the repository root"
            return True, "allow-listed config file at the repository root"
        if _within_router(clean, structure, "app") or _within_router(clean, structure, "pages"):
            return True, "route file inside the project's application root"
        if spec.allows_seo_helpers and _SEO_HELPER_RE.search(clean):
            return True, "project SEO helper module"
        if structure is None:
            return False, "repository structure unknown; cannot confirm the target is a route file"
        return False, f"{filename} is not inside {structure.app_prefix or structure.pages_prefix}/"

    if spec.allows_seo_helpers and _SEO_HELPER_RE.search(clean):
        return True, "project SEO helper module"
    if spec.allows_components and _COMPONENT_RE.search(clean):
        return True, "component file (permitted for this type, operation is bounded)"
    if spec.allows_data_modules and _DATA_RE.search(clean):
        return True, "data module (permitted for this type, operation is bounded)"
    if spec.allows_app_routes and _within_router(clean, structure, "app"):
        return True, "file inside the App Router root"
    if spec.allows_pages_routes and _within_router(clean, structure, "pages"):
        return True, "file inside the Pages Router root"
    return False, f"{spec.name} is not permitted to modify {clean}"


# -- per-operation content checks ---------------------------------------------

_CANONICAL_RE = re.compile(r"canonical\s*:|rel=[\"']canonical[\"']")


def _check_removal(before: str, after: str, payload: Dict) -> List[str]:
    problems = []
    if not _CANONICAL_RE.search(before):
        problems.append("the file declares no canonical, so there is nothing to remove")
    if _CANONICAL_RE.search(after):
        problems.append("the result still declares a canonical")
    if len(after) >= len(before):
        problems.append("a removal must make the file shorter")
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    added = [l for l in after_lines if l.strip() and l not in before_lines]
    if added:
        problems.append(f"a removal must not add lines (added {len(added)})")

    # The collateral-damage guard. Removing the canonical must not take anything
    # else with it. A line-based edit can swallow a whole inline declaration —
    # `metadata = { alternates: { canonical: "x", languages: {} } }` lives on one
    # line — and still look like a clean removal: shorter, canonical gone, nothing
    # added. Comparing lines cannot catch that, because the offending line is the
    # canonical's own line. So compare *tokens* instead: take `before`, delete just
    # the canonical declaration from it, and require every identifier that remains
    # to still be present afterwards.
    lost = _lost_identifiers(before, after)
    if lost:
        problems.append(
            "a removal must not delete anything but the canonical; it would also remove: "
            + ", ".join(sorted(lost)[:5])
        )
    return problems


# Identifiers worth protecting: anything word-like that is not punctuation or a
# bare number. Structural tokens (braces, commas) are ignored because an emptied
# `alternates` wrapper may legitimately disappear with its canonical.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CANONICAL_DECL_RE = re.compile(r"canonical\s*:\s*[\"'`][^\"'`]*[\"'`]\s*,?")


def _lost_identifiers(before: str, after: str) -> set:
    """Identifiers present in `before` (minus the canonical) but gone from `after`.

    `alternates` is excluded: when the canonical was the only thing it held, the
    wrapper is expected to go too.
    """
    stripped = _CANONICAL_DECL_RE.sub("", before)
    before_tokens = set(_IDENT_RE.findall(stripped))
    after_tokens = set(_IDENT_RE.findall(after))
    return {
        token for token in before_tokens - after_tokens
        if token not in {"alternates", "canonical"}
    }


def _check_replace_literal(before: str, after: str, payload: Dict) -> List[str]:
    old = payload.get("old_href") or ""
    new = payload.get("new_href") or ""
    problems = []
    if not old or not new:
        problems.append("old_href and new_href are both required")
        return problems
    if not old.startswith("/") or not new.startswith("/"):
        problems.append("internal_link_fix only rewrites root-relative routes")
    occurrences = before.count(old)
    if occurrences == 0:
        problems.append(f"{old} does not appear in the file")
    if old in after:
        problems.append(f"{old} still appears after the change")
    expected = before.replace(old, new)
    if after != expected:
        problems.append("the change is not a pure substitution of old_href with new_href")
    return problems


def _check_replace_field(before: str, after: str, payload: Dict) -> List[str]:
    field_name = payload.get("field") or ""
    problems = []
    if field_name not in ALLOWED_METADATA_FIELDS:
        problems.append(f"{field_name or '<missing>'} is not a replaceable metadata field")
        return problems
    if not re.search(rf"\b{re.escape(field_name)}\s*:", before):
        problems.append(f"the file has no existing {field_name} field to replace")
    if not re.search(rf"\b{re.escape(field_name)}\s*:", after):
        problems.append(f"the result no longer declares {field_name}")
    for other in ALLOWED_METADATA_FIELDS - {field_name}:
        if (f"{other}:" in before) != (f"{other}:" in after):
            problems.append(f"{other} was added or removed; only {field_name} may change")
    return problems


def _check_config_key(before: str, after: str, payload: Dict) -> List[str]:
    key = payload.get("config_key") or ""
    problems = []
    if key not in ALLOWED_CONFIG_KEYS:
        problems.append(f"{key or '<missing>'} is not an allow-listed config key")
    if re.search(r"\brequire\s*\(|\bimport\s+", after) and not re.search(
        r"\brequire\s*\(|\bimport\s+", before
    ):
        problems.append("a config_update may not introduce new imports")
    return problems


_CHECKS: Dict[str, Callable[[str, str, Dict], List[str]]] = {
    REMOVE: _check_removal,
    REPLACE_LITERAL: _check_replace_literal,
    REPLACE_FIELD: _check_replace_field,
    SET_CONFIG_KEY: _check_config_key,
}


# -- public entry point -------------------------------------------------------

def validate_patch(
    patch_type: str,
    payload: Dict,
    *,
    before: Optional[str] = None,
    after: Optional[str] = None,
    structure: Optional[ProjectStructure] = None,
) -> VocabularyResult:
    """Judge one structural patch against its type's rules.

    ``payload`` carries the type's required fields. ``before`` / ``after`` are the
    file's content now and the content the patch proposes.
    """
    result = VocabularyResult(ok=True)
    spec = SPECS.get(patch_type)
    if spec is None:
        return result.fail(f"{patch_type} is not a known structural patch type")
    result.notes["operation"] = spec.operation
    result.notes["summary"] = spec.summary

    for required in spec.required_fields:
        if not payload.get(required):
            result.fail(f"{patch_type} requires {required}")
    if not result.ok:
        return result

    if spec.operation == GROUP:
        members = payload.get("members") or []
        if len(members) < 2:
            result.fail("a multi_file_patch needs at least two members")
        seen = set()
        for member in members:
            member_type = member.get("patch_type")
            member_path = strip_target_hint(member.get("target_file", ""))
            if member_type == "multi_file_patch":
                result.fail("a multi_file_patch may not contain another multi_file_patch")
                continue
            if member_path in seen:
                result.fail(f"duplicate member target {member_path}")
            seen.add(member_path)
            inner = validate_patch(
                member_type, member,
                before=member.get("before"), after=member.get("after"),
                structure=structure,
            )
            if not inner.ok:
                result.fail(f"member {member_path}: {inner.reasons[0]}")
        result.notes["members"] = len(members)
        return result

    path = strip_target_hint(payload.get("target_file", ""))
    permitted, why = path_permitted(path, spec, structure)
    result.notes["path_permission"] = why
    if not permitted:
        return result.fail(f"path not permitted: {why}")

    if spec.requires_existing_file and before is None:
        return result.fail(f"{patch_type} requires the current file content to validate against")

    checker = _CHECKS.get(spec.operation)
    if checker is not None:
        if after is None:
            return result.fail(f"{patch_type} requires the proposed content")
        for problem in checker(before or "", after, payload):
            result.fail(problem)

    if result.ok:
        result.notes["verdict"] = f"{patch_type} is within its permitted operation and path"
    return result
