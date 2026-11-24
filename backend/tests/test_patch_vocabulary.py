"""Rules for the structural patch types.

Each new type is a narrow licence, not a general one: it names the paths it may
touch and the single operation it may perform, and the validator must reject a
change that strayed outside either. These tests pin that boundary — especially
for `internal_link_fix`, which is allowed into component files (links live
there) and so must be provably unable to do anything but swap a route literal.

Pure unit tests: no database, no git, no real repository.
"""
from pathlib import Path

import pytest

from app.repo_agent.patch_vocabulary import (
    ALLOWED_CONFIG_KEYS,
    ALLOWED_METADATA_FIELDS,
    NEW_PATCH_TYPES,
    SPECS,
    path_permitted,
    validate_patch,
)
from app.repo_agent.project_structure import detect_structure


def write(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def structure(tmp_path):
    write(tmp_path / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(tmp_path / "tsconfig.json", "{}")
    write(tmp_path / "src" / "app" / "layout.tsx", "export default function L(){return null}")
    write(tmp_path / "src" / "app" / "page.tsx", "export default function P(){return null}")
    return detect_structure(str(tmp_path))


LAYOUT_WITH_CANONICAL = """\
export const metadata = {
  title: "HNX",
  description: "d",
  alternates: {
    canonical: "https://example.test",
  },
};
"""

LAYOUT_WITHOUT_CANONICAL = """\
export const metadata = {
  title: "HNX",
  description: "d",
};
"""


# -- the vocabulary itself ----------------------------------------------------

def test_all_five_types_are_defined():
    assert set(NEW_PATCH_TYPES) == {
        "canonical_removal", "internal_link_fix", "metadata_replace",
        "config_update", "multi_file_patch",
    }


def test_every_vocabulary_type_exists_in_the_patch_type_enum():
    """Guards against the enum and the rule set drifting apart.

    A vocabulary type with no enum member cannot be persisted; an enum member
    with no rules would be an unbounded licence. Both are bugs.
    """
    from app.models.repo_agent import SeoCodePatchType

    enum_values = {e.value for e in SeoCodePatchType}
    for name in NEW_PATCH_TYPES:
        assert name in enum_values, f"{name} has rules but no SeoCodePatchType member"


def test_every_spec_names_one_operation_and_its_limits():
    for name, spec in SPECS.items():
        assert spec.operation, f"{name} has no operation"
        assert spec.required_fields, f"{name} declares no required fields"
        assert spec.forbidden_segments, f"{name} declares no forbidden areas"


def test_unknown_patch_type_is_refused(structure):
    r = validate_patch("rewrite_everything", {"target_file": "src/app/page.tsx"},
                       before="x", after="y", structure=structure)
    assert not r.ok and "not a known structural patch type" in r.reasons[0]


# -- canonical_removal --------------------------------------------------------

def test_canonical_removal_accepts_a_real_removal(structure):
    r = validate_patch("canonical_removal", {"target_file": "src/app/layout.tsx"},
                       before=LAYOUT_WITH_CANONICAL, after=LAYOUT_WITHOUT_CANONICAL,
                       structure=structure)
    assert r.ok, r.reasons


def test_canonical_removal_refuses_when_nothing_to_remove(structure):
    r = validate_patch("canonical_removal", {"target_file": "src/app/layout.tsx"},
                       before=LAYOUT_WITHOUT_CANONICAL, after=LAYOUT_WITHOUT_CANONICAL,
                       structure=structure)
    assert not r.ok and any("nothing to remove" in x for x in r.reasons)


def test_canonical_removal_refuses_if_canonical_survives(structure):
    r = validate_patch("canonical_removal", {"target_file": "src/app/layout.tsx"},
                       before=LAYOUT_WITH_CANONICAL,
                       after=LAYOUT_WITH_CANONICAL.replace("HNX", "HNX2"),
                       structure=structure)
    assert not r.ok and any("still declares a canonical" in x for x in r.reasons)


def test_canonical_removal_refuses_to_add_lines(structure):
    sneaky = LAYOUT_WITHOUT_CANONICAL + "\nexport const EXTRA = fetch('/x');\n"
    r = validate_patch("canonical_removal", {"target_file": "src/app/layout.tsx"},
                       before=LAYOUT_WITH_CANONICAL, after=sneaky, structure=structure)
    assert not r.ok and any("must not add lines" in x for x in r.reasons)


def test_canonical_removal_refuses_collateral_damage(structure):
    """A removal that also deletes unrelated declarations must be rejected.

    This is the real hazard: a line-based edit on an inline
    `metadata = { alternates: { canonical: "x", languages: {} } }` deletes the
    whole export, yet still looks clean — shorter, canonical gone, nothing added.
    """
    before = 'export const metadata = { alternates: { canonical: "x", languages: {} } };\n'
    r = validate_patch("canonical_removal", {"target_file": "src/app/layout.tsx"},
                       before=before, after="", structure=structure)
    assert not r.ok
    assert any("must not delete anything but the canonical" in x for x in r.reasons)


def test_canonical_removal_allows_dropping_an_emptied_alternates_wrapper(structure):
    before = 'export const metadata = {\n  alternates: {\n    canonical: "x",\n  },\n};\n'
    after = "export const metadata = {\n};\n"
    r = validate_patch("canonical_removal", {"target_file": "src/app/layout.tsx"},
                       before=before, after=after, structure=structure)
    assert r.ok, r.reasons


def test_canonical_removal_refuses_a_component_target(structure):
    r = validate_patch("canonical_removal", {"target_file": "src/components/Navbar.tsx"},
                       before=LAYOUT_WITH_CANONICAL, after=LAYOUT_WITHOUT_CANONICAL,
                       structure=structure)
    assert not r.ok and "path not permitted" in r.reasons[0]


# -- internal_link_fix --------------------------------------------------------

BEFORE_LINK = '<Link href="/solutions/workflow-engine">Explore</Link>\n'
AFTER_LINK = '<Link href="/solutions/crm/workflow-engine">Explore</Link>\n'


def test_internal_link_fix_accepts_a_pure_substitution(structure):
    r = validate_patch(
        "internal_link_fix",
        {"target_file": "src/components/CrmGrid.tsx",
         "old_href": "/solutions/workflow-engine",
         "new_href": "/solutions/crm/workflow-engine"},
        before=BEFORE_LINK, after=AFTER_LINK, structure=structure)
    assert r.ok, r.reasons


def test_internal_link_fix_refuses_any_other_edit(structure):
    """The whole reason components are allowed for this type."""
    sneaky = AFTER_LINK + "\nexport const token = process.env.SECRET;\n"
    r = validate_patch(
        "internal_link_fix",
        {"target_file": "src/components/CrmGrid.tsx",
         "old_href": "/solutions/workflow-engine",
         "new_href": "/solutions/crm/workflow-engine"},
        before=BEFORE_LINK, after=sneaky, structure=structure)
    assert not r.ok
    assert any("not a pure substitution" in x for x in r.reasons)


def test_internal_link_fix_refuses_when_old_href_absent(structure):
    r = validate_patch(
        "internal_link_fix",
        {"target_file": "src/components/CrmGrid.tsx",
         "old_href": "/nope", "new_href": "/solutions"},
        before=BEFORE_LINK, after=BEFORE_LINK, structure=structure)
    assert not r.ok and any("does not appear" in x for x in r.reasons)


def test_internal_link_fix_refuses_external_urls(structure):
    r = validate_patch(
        "internal_link_fix",
        {"target_file": "src/components/CrmGrid.tsx",
         "old_href": "https://evil.test", "new_href": "https://other.test"},
        before='a href="https://evil.test"', after='a href="https://other.test"',
        structure=structure)
    assert not r.ok and any("root-relative" in x for x in r.reasons)


def test_internal_link_fix_refuses_api_and_auth_areas(structure):
    for bad in ("src/app/api/users/route.ts", "src/auth/login.tsx"):
        r = validate_patch(
            "internal_link_fix",
            {"target_file": bad, "old_href": "/a", "new_href": "/b"},
            before='href="/a"', after='href="/b"', structure=structure)
        assert not r.ok, bad


def test_internal_link_fix_requires_both_hrefs(structure):
    r = validate_patch("internal_link_fix",
                       {"target_file": "src/components/X.tsx", "old_href": "/a"},
                       before="x", after="y", structure=structure)
    assert not r.ok and any("new_href" in x for x in r.reasons)


# -- metadata_replace ---------------------------------------------------------

def test_metadata_replace_accepts_one_field(structure):
    before = 'export const metadata = { title: "A", description: "d" };\n'
    after = 'export const metadata = { title: "B", description: "d" };\n'
    r = validate_patch("metadata_replace",
                       {"target_file": "src/app/page.tsx", "field": "title"},
                       before=before, after=after, structure=structure)
    assert r.ok, r.reasons


def test_metadata_replace_refuses_an_unlisted_field(structure):
    r = validate_patch("metadata_replace",
                       {"target_file": "src/app/page.tsx", "field": "generateViewport"},
                       before="x", after="y", structure=structure)
    assert not r.ok and any("not a replaceable metadata field" in x for x in r.reasons)


def test_metadata_replace_refuses_touching_another_field(structure):
    before = 'export const metadata = { title: "A", description: "d" };\n'
    after = 'export const metadata = { title: "B" };\n'
    r = validate_patch("metadata_replace",
                       {"target_file": "src/app/page.tsx", "field": "title"},
                       before=before, after=after, structure=structure)
    assert not r.ok and any("description was added or removed" in x for x in r.reasons)


def test_allowed_metadata_fields_are_seo_only():
    assert "scripts" not in ALLOWED_METADATA_FIELDS
    assert {"title", "description", "alternates"} <= ALLOWED_METADATA_FIELDS


# -- config_update ------------------------------------------------------------

def test_config_update_accepts_an_allow_listed_key(structure):
    r = validate_patch("config_update",
                       {"target_file": "next.config.js", "config_key": "trailingSlash"},
                       before="module.exports = {};\n",
                       after="module.exports = { trailingSlash: false };\n",
                       structure=structure)
    assert r.ok, r.reasons


def test_config_update_refuses_an_unlisted_key(structure):
    r = validate_patch("config_update",
                       {"target_file": "next.config.js", "config_key": "webpack"},
                       before="module.exports = {};\n",
                       after="module.exports = { webpack: (c)=>c };\n",
                       structure=structure)
    assert not r.ok and any("not an allow-listed config key" in x for x in r.reasons)


def test_config_update_refuses_new_imports(structure):
    r = validate_patch("config_update",
                       {"target_file": "next.config.js", "config_key": "headers"},
                       before="module.exports = {};\n",
                       after="const fs = require('fs');\nmodule.exports = { headers: [] };\n",
                       structure=structure)
    assert not r.ok and any("new imports" in x for x in r.reasons)


def test_config_update_refuses_a_nested_config_path(structure):
    r = validate_patch("config_update",
                       {"target_file": "src/app/next.config.js", "config_key": "headers"},
                       before="module.exports = {};\n", after="module.exports = {headers: []};\n",
                       structure=structure)
    assert not r.ok and "path not permitted" in r.reasons[0]


def test_allowed_config_keys_exclude_build_and_security_escapes():
    for dangerous in ("webpack", "env", "serverRuntimeConfig", "rewrites"):
        assert dangerous not in ALLOWED_CONFIG_KEYS


# -- multi_file_patch ---------------------------------------------------------

def _member(path, old, new):
    return {"patch_type": "internal_link_fix", "target_file": path,
            "old_href": old, "new_href": new,
            "before": f'href="{old}"', "after": f'href="{new}"'}


def test_multi_file_patch_accepts_valid_members(structure):
    r = validate_patch("multi_file_patch", {"members": [
        _member("src/components/A.tsx", "/a", "/b"),
        _member("src/components/B.tsx", "/a", "/b"),
    ]}, structure=structure)
    assert r.ok, r.reasons
    assert r.notes["members"] == 2


def test_multi_file_patch_fails_if_any_member_fails(structure):
    r = validate_patch("multi_file_patch", {"members": [
        _member("src/components/A.tsx", "/a", "/b"),
        _member("src/app/api/x/route.ts", "/a", "/b"),   # forbidden area
    ]}, structure=structure)
    assert not r.ok and any("member" in x for x in r.reasons)


def test_multi_file_patch_refuses_nesting(structure):
    r = validate_patch("multi_file_patch", {"members": [
        {"patch_type": "multi_file_patch", "target_file": "x", "members": []},
        _member("src/components/B.tsx", "/a", "/b"),
    ]}, structure=structure)
    assert not r.ok and any("may not contain another multi_file_patch" in x for x in r.reasons)


def test_multi_file_patch_refuses_duplicate_targets(structure):
    r = validate_patch("multi_file_patch", {"members": [
        _member("src/components/A.tsx", "/a", "/b"),
        _member("src/components/A.tsx", "/c", "/d"),
    ]}, structure=structure)
    assert not r.ok and any("duplicate member target" in x for x in r.reasons)


def test_multi_file_patch_needs_at_least_two_members(structure):
    r = validate_patch("multi_file_patch",
                       {"members": [_member("src/components/A.tsx", "/a", "/b")]},
                       structure=structure)
    assert not r.ok and any("at least two members" in x for x in r.reasons)


# -- path permission ----------------------------------------------------------

def test_no_type_may_touch_node_modules_or_prisma(structure):
    for spec in SPECS.values():
        if spec.operation == "group":
            continue
        for bad in ("node_modules/pkg/index.ts", "prisma/schema.prisma"):
            ok, _ = path_permitted(bad, spec, structure)
            assert not ok, f"{spec.name} must not touch {bad}"


def test_component_access_is_limited_to_link_fixes(structure):
    component = "src/components/Navbar.tsx"
    assert path_permitted(component, SPECS["internal_link_fix"], structure)[0]
    for other in ("canonical_removal", "metadata_replace", "config_update"):
        assert not path_permitted(component, SPECS[other], structure)[0], other


def test_unknown_structure_cannot_authorise_a_route_file():
    ok, why = path_permitted("src/app/layout.tsx", SPECS["canonical_removal"], None)
    assert not ok and "structure unknown" in why
