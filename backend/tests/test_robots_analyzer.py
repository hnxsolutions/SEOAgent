"""Unit tests for the deterministic robots.txt analyzer."""
from app.models.robots import RobotsIssueSeverity, RobotsIssueType
from app.robots.analyzer import analyze_robots, parse_robots


def _types(text):
    return {f.issue_type for f in analyze_robots(text)}


def test_clean_robots_has_no_issues():
    clean = (
        "User-agent: *\n"
        "Disallow: /admin/\n"
        "Allow: /admin/public/\n"
        "\n"
        "Sitemap: https://example.com/sitemap.xml\n"
    )
    assert analyze_robots(clean) == []


def test_missing_sitemap_directive():
    assert RobotsIssueType.missing_sitemap_directive in _types("User-agent: *\nDisallow: /admin/\n")
    assert RobotsIssueType.missing_sitemap_directive not in _types(
        "User-agent: *\nDisallow: /admin/\nSitemap: https://example.com/sitemap.xml\n"
    )


def test_disallow_all_is_critical():
    findings = analyze_robots("User-agent: *\nDisallow: /\nSitemap: https://e.com/s.xml\n")
    disallow = [f for f in findings if f.issue_type == RobotsIssueType.disallow_all]
    assert len(disallow) == 1
    assert disallow[0].severity == RobotsIssueSeverity.critical


def test_disallow_all_only_for_star_agent():
    # Disallow: / for a specific bot (not *) is intentional, not a site-wide block.
    findings = _types("User-agent: BadBot\nDisallow: /\nSitemap: https://e.com/s.xml\n")
    assert RobotsIssueType.disallow_all not in findings


def test_blocked_css_and_js_are_high_severity():
    text = (
        "User-agent: *\n"
        "Disallow: /styles/main.css\n"
        "Disallow: /scripts/app.js\n"
        "Sitemap: https://e.com/s.xml\n"
    )
    findings = {f.issue_type: f for f in analyze_robots(text)}
    assert findings[RobotsIssueType.blocked_css].severity == RobotsIssueSeverity.high
    assert findings[RobotsIssueType.blocked_js].severity == RobotsIssueSeverity.high


def test_blocked_framework_asset_dir_flagged():
    text = "User-agent: *\nDisallow: /_next/static\nSitemap: https://e.com/s.xml\n"
    assert RobotsIssueType.blocked_js in _types(text)


def test_blocked_images_flagged_for_googlebot_group():
    text = (
        "User-agent: Googlebot\n"
        "Disallow: /media/hero.png\n"
        "Sitemap: https://e.com/s.xml\n"
    )
    assert RobotsIssueType.blocked_images in _types(text)


def test_asset_block_ignored_for_unrelated_bot():
    text = "User-agent: AhrefsBot\nDisallow: /app.js\nSitemap: https://e.com/s.xml\n"
    assert RobotsIssueType.blocked_js not in _types(text)


def test_broken_wildcard_double_star_and_misplaced_anchor():
    text = (
        "User-agent: *\n"
        "Disallow: /a/**/b\n"
        "Disallow: /x$y\n"
        "Sitemap: https://e.com/s.xml\n"
    )
    assert RobotsIssueType.broken_wildcard in _types(text)
    # A correctly anchored pattern must NOT be flagged.
    ok = "User-agent: *\nDisallow: /*.pdf$\nSitemap: https://e.com/s.xml\n"
    assert RobotsIssueType.broken_wildcard not in _types(ok)


def test_conflicting_allow_and_disallow_same_path():
    text = (
        "User-agent: *\n"
        "Disallow: /cart\n"
        "Allow: /cart\n"
        "Sitemap: https://e.com/s.xml\n"
    )
    assert RobotsIssueType.conflicting_directives in _types(text)


def test_duplicate_directive():
    text = (
        "User-agent: *\n"
        "Disallow: /admin/\n"
        "Disallow: /admin/\n"
        "Sitemap: https://e.com/s.xml\n"
    )
    assert RobotsIssueType.duplicate_directive in _types(text)


def test_invalid_directive_typo():
    text = "User-agent: *\nDissallow: /secret\nSitemap: https://e.com/s.xml\n"
    findings = _types(text)
    assert RobotsIssueType.invalid_directive in findings
    # The typo'd line must not be silently treated as a real Disallow.
    parsed = parse_robots(text)
    assert all(r.field != "disallow" for g in parsed.groups for r in g.rules)


def test_sitemap_not_https():
    text = "User-agent: *\nDisallow: /admin/\nSitemap: http://e.com/s.xml\n"
    assert RobotsIssueType.sitemap_not_https in _types(text)


def test_comments_and_blank_lines_are_ignored():
    text = (
        "# global rules\n"
        "User-agent: *\n"
        "Disallow: /admin/   # keep admin private\n"
        "\n"
        "Sitemap: https://e.com/s.xml\n"
    )
    assert analyze_robots(text) == []


def test_rule_before_user_agent_attaches_to_star_group():
    # Some sites put Disallow before any User-agent; treat as '*'.
    text = "Disallow: /\nSitemap: https://e.com/s.xml\n"
    assert RobotsIssueType.disallow_all in _types(text)
