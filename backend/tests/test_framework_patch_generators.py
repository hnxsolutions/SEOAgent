"""Per-framework SEO patch generator tests (pure, no I/O).

Verify each framework emits its OWN native code, never another framework's, and
that generated targets are SEO-safe (never UI/business/auth/payments/DB paths)."""
import pytest

from app.framework_patches import PatchContext, SUPPORTED_SURFACES, generate_patch, supported_frameworks
from app.repo_agent.architecture import RepoArchitectureDetector


def _ctx(fw: str) -> PatchContext:
    return PatchContext(framework_key=fw, site_url="https://example.com",
                        page_label="Home", business_name="Example Co", routes=["/", "/about"])


def test_all_frameworks_have_generators():
    fws = supported_frameworks()
    for expected in ("nextjs", "wordpress", "shopify", "laravel", "django", "astro",
                     "nuxt", "react", "vue", "angular", "sveltekit", "gatsby", "custom"):
        assert expected in fws


def test_nextjs_emits_native_code():
    meta = generate_patch("nextjs", "metadata", _ctx("nextjs"))
    robots = generate_patch("nextjs", "robots", _ctx("nextjs"))
    sitemap = generate_patch("nextjs", "sitemap", _ctx("nextjs"))
    assert "generateMetadata" in meta.code or "export const metadata" in meta.code
    assert "MetadataRoute.Robots" in robots.code and robots.target_file == "app/robots.ts"
    assert "MetadataRoute.Sitemap" in sitemap.code and sitemap.target_file == "app/sitemap.ts"
    assert "example.com/about" in sitemap.code  # real routes used


def test_wordpress_emits_php_not_react():
    meta = generate_patch("wordpress", "metadata", _ctx("wordpress"))
    assert "wp_head" in meta.code and "<?php" in meta.code
    assert "generateMetadata" not in meta.code  # never Next.js code


def test_shopify_emits_liquid_not_php():
    schema = generate_patch("shopify", "schema", _ctx("shopify"))
    assert "application/ld+json" in schema.code and "product.title" in schema.code
    assert "<?php" not in schema.code


def test_frameworks_do_not_share_templates():
    # The same surface must produce distinct, framework-specific code per stack.
    codes = {}
    for fw in ("nextjs", "wordpress", "shopify", "laravel", "django", "astro", "nuxt", "custom"):
        c = generate_patch(fw, "metadata", _ctx(fw))
        assert c is not None
        codes[fw] = c.code
    assert len(set(codes.values())) == len(codes)  # all distinct


def test_every_generated_target_is_seo_safe():
    detector = RepoArchitectureDetector()
    for fw in supported_frameworks():
        for surface in SUPPORTED_SURFACES:
            c = generate_patch(fw, surface, _ctx(fw))
            if not c:
                continue
            path = c.target_file.split(" (")[0].strip()
            assert not detector._is_unsafe_path(path), f"{fw}/{surface} -> unsafe target {path}"


def test_schema_is_valid_json_ld_structure():
    for fw in ("nextjs", "django", "custom", "laravel"):
        c = generate_patch(fw, "schema", _ctx(fw))
        assert c and "application/ld+json" in c.code and "schema.org" in c.code


def test_canonical_uses_site_origin():
    c = generate_patch("custom", "metadata", _ctx("custom"))
    assert "https://example.com" in c.code
