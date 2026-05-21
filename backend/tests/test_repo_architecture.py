from pathlib import Path

from app.models.repo_agent import SeoCodeIssueType, SeoCodePatchType
from app.repo_agent.architecture import RepoArchitectureDetector, html_metadata_patch_content


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_nextjs_app_router_novakos_like_architecture_detection(tmp_path):
    write(tmp_path / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(tmp_path / "app" / "layout.tsx", "export const metadata = { title: 'Site', description: 'Site' };\n")
    write(tmp_path / "app" / "page.tsx", "export default function Page() { return <main />; }\n")
    write(tmp_path / "app" / "blogs" / "page.tsx", "import { blogs } from '@/lib/blogs';\nexport default function Blogs() { return <main />; }\n")
    write(tmp_path / "app" / "blogs" / "[slug]" / "page.tsx", "export default function Blog() { return <article />; }\n")
    write(tmp_path / "lib" / "blogs.ts", "export const blogs = [{ slug: 'pcd-pharma', title: 'PCD Pharma' }];\n")
    write(tmp_path / "components" / "JsonLd.tsx", "export function JsonLd(){ return <script type=\"application/ld+json\" />; }\n")
    write(
        tmp_path / "app" / "sitemap.ts",
        "import { blogs } from '@/lib/blogs';\nexport default function sitemap(){ const staticRoutes = [{ url: '/' }]; const blogRoutes = blogs.map((blog) => ({ url: `/blogs/${blog.slug}` })); return [...staticRoutes, ...blogRoutes]; }\n",
    )
    write(tmp_path / "app" / "robots.ts", "export default function robots(){ return { rules: { userAgent: '*', allow: '/' }, sitemap: 'https://example.com/sitemap.xml' }; }\n")
    write(tmp_path / "app" / "client-page" / "page.tsx", '"use client";\nexport default function Page(){ return <main />; }\n')

    detector = RepoArchitectureDetector()
    profile = detector.detect(tmp_path)

    assert profile.detected_stack == "nextjs_app_router"
    assert profile.blog_system["content_source_file"] == "lib/blogs.ts"
    assert profile.blog_system["insertion_strategy"] == "append_to_static_ts_array"
    assert profile.sitemap_strategy["rich_dynamic"] is True
    assert profile.robots_strategy["exists"] is True
    assert any(zone["zone_type"] == "client_component" for zone in profile.unsafe_patch_zones)
    assert any(zone["zone_type"] == "sitemap_review" for zone in profile.manual_review_zones)
    assert not any(zone["zone_type"] == "blog_insertion_review" for zone in profile.manual_review_zones)

    sitemap_decision = detector.classify_patch(
        profile,
        file_path="app/sitemap.ts",
        patch_type=SeoCodePatchType.sitemap_update,
        issue_type=SeoCodeIssueType.route_not_in_sitemap,
        original_content=(tmp_path / "app" / "sitemap.ts").read_text(encoding="utf-8"),
    )
    assert sitemap_decision.classification == "manual_review"

    robots_decision = detector.classify_patch(
        profile,
        file_path="app/robots.ts",
        patch_type=SeoCodePatchType.robots_update,
        issue_type=SeoCodeIssueType.missing_robots,
        original_content=(tmp_path / "app" / "robots.ts").read_text(encoding="utf-8"),
    )
    assert robots_decision.classification == "manual_review"

    client_decision = detector.classify_patch(
        profile,
        file_path="app/client-page/page.tsx",
        patch_type=SeoCodePatchType.metadata_update,
        issue_type=SeoCodeIssueType.missing_metadata,
        original_content=(tmp_path / "app" / "client-page" / "page.tsx").read_text(encoding="utf-8"),
    )
    assert client_decision.classification == "unsafe_skip"


def test_react_vite_and_plain_html_detection_and_html_patch(tmp_path):
    write(tmp_path / "package.json", '{"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest"}}')
    write(tmp_path / "vite.config.ts", "export default {};\n")
    write(tmp_path / "index.html", "<html><head><title>Old</title></head><body><div id=\"root\"></div></body></html>")
    write(tmp_path / "src" / "main.tsx", "import React from 'react';\n")

    detector = RepoArchitectureDetector()
    profile = detector.detect(tmp_path)
    proposed = html_metadata_patch_content((tmp_path / "index.html").read_text(encoding="utf-8"), "Home", "https://example.com")

    assert profile.detected_stack == "react_vite"
    assert any(zone["zone_type"] == "html_head" for zone in profile.safe_patch_zones)
    assert "<title>Home</title>" in proposed
    assert 'name="description"' in proposed
    assert 'rel="canonical"' in proposed


def test_plain_static_wordpress_shopify_and_unknown_classification(tmp_path):
    detector = RepoArchitectureDetector()

    plain = tmp_path / "plain"
    write(plain / "index.html", "<html><head><title>Plain</title></head><body></body></html>")
    plain_profile = detector.detect(plain)
    assert plain_profile.detected_stack == "plain_static"

    wordpress = tmp_path / "wordpress"
    write(wordpress / "functions.php", "<?php add_action('wp_head', function () {});")
    write(wordpress / "single.php", "<?php get_header(); the_content(); get_footer();")
    wp_profile = detector.detect(wordpress)
    wp_decision = detector.classify_patch(
        wp_profile,
        file_path="single.php",
        patch_type=SeoCodePatchType.metadata_update,
        issue_type=SeoCodeIssueType.weak_metadata,
        original_content=(wordpress / "single.php").read_text(encoding="utf-8"),
    )
    assert wp_profile.detected_stack == "wordpress"
    assert wp_decision.classification == "manual_review"

    shopify = tmp_path / "shopify"
    write(shopify / "layout" / "theme.liquid", "<html><head>{{ page_title }}</head>{{ content_for_layout }}</html>")
    write(shopify / "templates" / "article.liquid", "{{ article.title }}")
    shopify_profile = detector.detect(shopify)
    shopify_decision = detector.classify_patch(
        shopify_profile,
        file_path="templates/article.liquid",
        patch_type=SeoCodePatchType.schema_addition,
        issue_type=SeoCodeIssueType.missing_schema,
        original_content=(shopify / "templates" / "article.liquid").read_text(encoding="utf-8"),
    )
    assert shopify_profile.detected_stack == "shopify"
    assert shopify_decision.classification == "manual_review"

    unknown = tmp_path / "unknown"
    write(unknown / "src" / "widget.custom", "custom generated app")
    unknown_profile = detector.detect(unknown)
    unknown_decision = detector.classify_patch(
        unknown_profile,
        file_path="src/widget.custom",
        patch_type=SeoCodePatchType.metadata_update,
        issue_type=SeoCodeIssueType.missing_metadata,
        original_content="",
    )
    assert unknown_profile.detected_stack == "unknown_custom"
    assert unknown_decision.classification == "unsafe_skip"


def test_markdown_static_blog_strategy(tmp_path):
    write(tmp_path / "content" / "blog" / "first.md", "---\ntitle: First\n---\n")
    write(tmp_path / "content" / "blog" / "second.md", "---\ntitle: Second\n---\n")

    profile = RepoArchitectureDetector().detect(tmp_path)

    assert profile.detected_stack == "markdown_static"
    assert profile.blog_system["insertion_strategy"] == "create_markdown_file"
