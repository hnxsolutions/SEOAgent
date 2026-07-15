"""Deterministic robots.txt parser and issue detectors.

Pure functions only: no network, no database. The service layer fetches the
live robots.txt and feeds the raw text here. Every finding is high-confidence
and traceable to the exact offending line(s) so it can safely become a
human-approved repository patch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.models.robots import RobotsIssueSeverity, RobotsIssueType


# Fields robots.txt legitimately supports (case-insensitive). Anything else is
# almost always a typo that Google silently ignores (e.g. "Dissallow").
KNOWN_FIELDS = {
    "user-agent",
    "disallow",
    "allow",
    "sitemap",
    "crawl-delay",
    "host",
    "clean-param",
    "noindex",  # unofficial/deprecated but seen in the wild; not flagged as invalid
    "request-rate",
    "visit-time",
}

CSS_HINTS = (".css",)
JS_HINTS = (".js",)
IMAGE_HINTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".avif")
# Framework asset directories that must stay crawlable for rendering/CWV.
CRITICAL_ASSET_PATHS = ("/_next/static", "/static/", "/assets/", "/_nuxt/", "/wp-includes/", "/wp-content/themes/")


@dataclass
class RobotsRule:
    field: str          # normalized lower-case field name
    value: str
    line_no: int
    raw: str


@dataclass
class RobotsGroup:
    agents: List[str] = field(default_factory=list)
    rules: List[RobotsRule] = field(default_factory=list)


@dataclass
class ParsedRobots:
    groups: List[RobotsGroup] = field(default_factory=list)
    sitemaps: List[Tuple[str, int]] = field(default_factory=list)   # (url, line_no)
    unknown_fields: List[RobotsRule] = field(default_factory=list)


@dataclass
class RobotsFinding:
    issue_type: RobotsIssueType
    severity: RobotsIssueSeverity
    title: str
    description: str
    recommended_action: str
    evidence: dict


def parse_robots(text: str) -> ParsedRobots:
    """Parse robots.txt into user-agent groups, global sitemaps and unknowns."""
    parsed = ParsedRobots()
    current: Optional[RobotsGroup] = None
    # A run of consecutive User-agent lines shares one group; the first rule
    # after them closes the agent list.
    expecting_agents = False

    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            # Malformed line with no field separator.
            parsed.unknown_fields.append(RobotsRule("", line, idx, raw_line))
            continue
        field_name, value = line.split(":", 1)
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "sitemap":
            parsed.sitemaps.append((value, idx))
            continue

        if field_name == "user-agent":
            if current is None or not expecting_agents:
                current = RobotsGroup()
                parsed.groups.append(current)
            current.agents.append(value)
            expecting_agents = True
            continue

        if field_name in KNOWN_FIELDS:
            if current is None:
                # Rule before any user-agent: attach to an implicit "*" group.
                current = RobotsGroup(agents=["*"])
                parsed.groups.append(current)
            current.rules.append(RobotsRule(field_name, value, idx, raw_line))
            expecting_agents = False
        else:
            parsed.unknown_fields.append(RobotsRule(field_name, value, idx, raw_line))
            expecting_agents = False

    return parsed


def _group_targets_all(group: RobotsGroup) -> bool:
    return any(agent.strip() == "*" for agent in group.agents)


def _disallow_rules(group: RobotsGroup):
    return [r for r in group.rules if r.field == "disallow" and r.value]


def _path_blocks(value: str, hints: Tuple[str, ...]) -> bool:
    low = value.lower()
    return any(h in low for h in hints)


def analyze_robots(text: str) -> List[RobotsFinding]:
    """Run every deterministic detector over robots.txt content."""
    parsed = parse_robots(text)
    findings: List[RobotsFinding] = []

    findings.extend(_detect_missing_sitemap(parsed))
    findings.extend(_detect_sitemap_not_https(parsed))
    findings.extend(_detect_disallow_all(parsed))
    findings.extend(_detect_blocked_assets(parsed))
    findings.extend(_detect_broken_wildcards(parsed))
    findings.extend(_detect_conflicts(parsed))
    findings.extend(_detect_duplicates(parsed))
    findings.extend(_detect_invalid_fields(parsed))
    return findings


def _detect_missing_sitemap(parsed: ParsedRobots) -> List[RobotsFinding]:
    if parsed.sitemaps:
        return []
    return [
        RobotsFinding(
            RobotsIssueType.missing_sitemap_directive,
            RobotsIssueSeverity.medium,
            "robots.txt does not declare a Sitemap",
            "No `Sitemap:` directive was found. Declaring the sitemap in robots.txt "
            "helps every search engine discover your URLs.",
            "Add a `Sitemap: https://<domain>/sitemap.xml` line to robots.txt.",
            {"sitemaps_found": 0},
        )
    ]


def _detect_sitemap_not_https(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for url, line_no in parsed.sitemaps:
        if url.lower().startswith("http://"):
            findings.append(
                RobotsFinding(
                    RobotsIssueType.sitemap_not_https,
                    RobotsIssueSeverity.low,
                    "Sitemap declared over HTTP",
                    f"The sitemap `{url}` is declared with an insecure http:// URL.",
                    "Update the Sitemap directive to use https://.",
                    {"line": line_no, "url": url},
                )
            )
    return findings


def _detect_disallow_all(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for group in parsed.groups:
        if not _group_targets_all(group):
            continue
        for rule in _disallow_rules(group):
            if rule.value.strip() == "/":
                findings.append(
                    RobotsFinding(
                        RobotsIssueType.disallow_all,
                        RobotsIssueSeverity.critical,
                        "robots.txt blocks the entire site",
                        "A `Disallow: /` rule for `User-agent: *` blocks all crawlers "
                        "from the whole site, which will remove it from search results.",
                        "Remove or scope the `Disallow: /` rule unless the site must stay "
                        "fully de-indexed.",
                        {"line": rule.line_no, "rule": rule.raw.strip()},
                    )
                )
    return findings


def _detect_blocked_assets(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for group in parsed.groups:
        # Only user-agent * and Googlebot groups matter for rendering.
        agents = " ".join(group.agents).lower()
        if "*" not in agents and "googlebot" not in agents:
            continue
        for rule in _disallow_rules(group):
            v = rule.value
            checks = [
                (CSS_HINTS, RobotsIssueType.blocked_css, RobotsIssueSeverity.high, "CSS"),
                (JS_HINTS, RobotsIssueType.blocked_js, RobotsIssueSeverity.high, "JavaScript"),
                (IMAGE_HINTS, RobotsIssueType.blocked_images, RobotsIssueSeverity.medium, "image"),
            ]
            matched = False
            for hints, itype, sev, label in checks:
                if _path_blocks(v, hints):
                    findings.append(
                        RobotsFinding(
                            itype, sev,
                            f"robots.txt blocks {label} resources",
                            f"The rule `{rule.raw.strip()}` prevents Google from fetching "
                            f"{label} files, which harms rendering and Core Web Vitals.",
                            f"Allow Google to crawl {label} assets by removing or narrowing this rule.",
                            {"line": rule.line_no, "rule": rule.raw.strip()},
                        )
                    )
                    matched = True
            # Framework asset directory blocks (e.g. /_next/static) block css+js.
            if not matched and _path_blocks(v, CRITICAL_ASSET_PATHS):
                findings.append(
                    RobotsFinding(
                        RobotsIssueType.blocked_js, RobotsIssueSeverity.high,
                        "robots.txt blocks a critical asset directory",
                        f"The rule `{rule.raw.strip()}` blocks a build/asset directory that "
                        f"typically serves CSS and JavaScript needed to render pages.",
                        "Remove or narrow this Disallow so rendering assets stay crawlable.",
                        {"line": rule.line_no, "rule": rule.raw.strip()},
                    )
                )
    return findings


def _detect_broken_wildcards(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for group in parsed.groups:
        for rule in group.rules:
            if rule.field not in {"disallow", "allow"}:
                continue
            v = rule.value
            problem = None
            if "**" in v:
                problem = "uses `**` which is not valid; robots.txt supports a single `*` wildcard"
            elif "$" in v and not v.rstrip().endswith("$"):
                problem = "places `$` (end-of-URL anchor) somewhere other than the end of the pattern"
            if problem:
                findings.append(
                    RobotsFinding(
                        RobotsIssueType.broken_wildcard,
                        RobotsIssueSeverity.medium,
                        "Malformed wildcard pattern in robots.txt",
                        f"The rule `{rule.raw.strip()}` {problem}. Google may interpret it "
                        f"differently than intended.",
                        "Rewrite the pattern using a single `*` wildcard and a trailing `$` anchor.",
                        {"line": rule.line_no, "rule": rule.raw.strip()},
                    )
                )
    return findings


def _detect_conflicts(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for group in parsed.groups:
        disallowed = {r.value: r for r in group.rules if r.field == "disallow" and r.value}
        for rule in group.rules:
            if rule.field == "allow" and rule.value and rule.value in disallowed:
                findings.append(
                    RobotsFinding(
                        RobotsIssueType.conflicting_directives,
                        RobotsIssueSeverity.medium,
                        "Conflicting Allow and Disallow for the same path",
                        f"The path `{rule.value}` is both Allowed and Disallowed in the same "
                        f"group (`User-agent: {', '.join(group.agents)}`). Behaviour depends on "
                        f"rule-length precedence and is easy to get wrong.",
                        "Keep a single, unambiguous rule for this path.",
                        {"path": rule.value, "agents": group.agents},
                    )
                )
    return findings


def _detect_duplicates(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for group in parsed.groups:
        seen = {}
        for rule in group.rules:
            key = (rule.field, rule.value)
            if key in seen:
                findings.append(
                    RobotsFinding(
                        RobotsIssueType.duplicate_directive,
                        RobotsIssueSeverity.low,
                        "Duplicate directive in robots.txt",
                        f"`{rule.field.title()}: {rule.value}` is repeated within the same group.",
                        "Remove the duplicate line to keep robots.txt clean.",
                        {"first_line": seen[key], "duplicate_line": rule.line_no, "rule": rule.raw.strip()},
                    )
                )
            else:
                seen[key] = rule.line_no
    return findings


def _detect_invalid_fields(parsed: ParsedRobots) -> List[RobotsFinding]:
    findings = []
    for rule in parsed.unknown_fields:
        label = rule.field or rule.value
        findings.append(
            RobotsFinding(
                RobotsIssueType.invalid_directive,
                RobotsIssueSeverity.low,
                "Unrecognized directive in robots.txt",
                f"Line {rule.line_no} (`{rule.raw.strip()}`) is not a recognized robots.txt "
                f"field. Search engines silently ignore it, so a typo (e.g. 'Dissallow') can "
                f"leave URLs unexpectedly crawlable.",
                "Fix the field name or remove the line.",
                {"line": rule.line_no, "field": label, "rule": rule.raw.strip()},
            )
        )
    return findings
