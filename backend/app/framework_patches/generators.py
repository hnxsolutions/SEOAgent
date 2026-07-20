"""Per-framework SEO patch generators.

Every framework gets its own generator class producing framework-native, SEO-safe
code. Surfaces: metadata, robots, sitemap, schema, og_twitter. Generators are
pure (no I/O) and only ever emit SEO markup/config — never UI, layout, business
logic, auth, payments, CRM, or database code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

SUPPORTED_SURFACES = ["metadata", "robots", "sitemap", "schema", "og_twitter"]

# surface -> existing SeoCodePatchType value (for the shared safety classifier).
SURFACE_PATCH_TYPE = {
    "metadata": "metadata_update",
    "robots": "robots_update",
    "sitemap": "sitemap_update",
    "schema": "schema_addition",
    "og_twitter": "og_twitter_addition",
}


@dataclass
class PatchContext:
    framework_key: str
    site_url: str
    page_label: str = "Home"
    page_path: str = "/"
    business_name: str = ""
    description: str = ""
    routes: List[str] = field(default_factory=lambda: ["/"])

    @property
    def origin(self) -> str:
        p = urlparse(self.site_url if "://" in self.site_url else "https://" + self.site_url)
        return f"{p.scheme or 'https'}://{p.netloc or p.path}".rstrip("/")

    @property
    def canonical(self) -> str:
        path = self.page_path if self.page_path.startswith("/") else "/" + self.page_path
        return (self.origin + (path if path != "/" else "")).rstrip("/") or self.origin

    @property
    def desc(self) -> str:
        return self.description or f"Learn about {self.page_label.lower()} — clear details and next steps."

    @property
    def brand(self) -> str:
        return self.business_name or (urlparse(self.origin).netloc or "Website")


@dataclass
class GeneratedPatchContent:
    framework: str
    surface: str
    patch_type: str
    target_file: str
    language: str
    code: str
    is_new_file: bool = True
    notes: str = ""
    code_fixable: bool = True

    def as_dict(self) -> dict:
        return {
            "framework": self.framework,
            "surface": self.surface,
            "patch_type": self.patch_type,
            "target_file": self.target_file,
            "language": self.language,
            "code": self.code,
            "is_new_file": self.is_new_file,
            "notes": self.notes,
            "code_fixable": self.code_fixable,
        }


def _org_jsonld(ctx: PatchContext) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": ctx.brand,
        "url": ctx.origin,
        "description": ctx.desc,
    }


class BaseGenerator:
    framework = "base"
    display = "Base"

    def generate(self, surface: str, ctx: PatchContext) -> Optional[GeneratedPatchContent]:
        fn = getattr(self, f"_{surface}", None)
        return fn(ctx) if fn else None

    # each subclass overrides the surfaces it supports with its OWN templates.


# -- Next.js ------------------------------------------------------------------

class NextjsGenerator(BaseGenerator):
    framework = "nextjs"
    display = "Next.js"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "import type { Metadata } from 'next';\n\n"
            "export const metadata: Metadata = {\n"
            f"  title: {json.dumps(ctx.page_label)},\n"
            f"  description: {json.dumps(ctx.desc)},\n"
            f"  alternates: {{ canonical: {json.dumps(ctx.canonical)} }},\n"
            "  openGraph: {\n"
            f"    title: {json.dumps(ctx.page_label)},\n"
            f"    description: {json.dumps(ctx.desc)},\n"
            f"    url: {json.dumps(ctx.canonical)},\n"
            "    type: 'website',\n"
            "  },\n"
            "  twitter: { card: 'summary_large_image', "
            f"title: {json.dumps(ctx.page_label)}, description: {json.dumps(ctx.desc)} }},\n"
            "};\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "app/page.tsx (metadata export)", "typescript", code,
                                     is_new_file=False,
                                     notes="Add to a Server Component only (not 'use client'). App Router metadata export.")

    _og_twitter = _metadata  # Next.js metadata export already carries OG/Twitter.

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "import type { MetadataRoute } from 'next';\n\n"
            "export default function robots(): MetadataRoute.Robots {\n"
            "  return {\n"
            "    rules: { userAgent: '*', allow: '/' },\n"
            f"    sitemap: '{ctx.origin}/sitemap.xml',\n"
            "  };\n"
            "}\n"
        )
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "app/robots.ts", "typescript", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        entries = ",\n".join(
            f"    {{ url: '{ctx.origin}{r if r != '/' else ''}', lastModified: new Date() }}"
            for r in (ctx.routes or ["/"])
        )
        code = (
            "import type { MetadataRoute } from 'next';\n\n"
            "export default function sitemap(): MetadataRoute.Sitemap {\n"
            "  return [\n"
            f"{entries}\n"
            "  ];\n"
            "}\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "app/sitemap.ts", "typescript", code)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx), indent=2)
        code = (
            "export default function JsonLd() {\n"
            f"  const data = {data};\n"
            "  return (\n"
            "    <script\n"
            "      type=\"application/ld+json\"\n"
            "      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}\n"
            "    />\n"
            "  );\n"
            "}\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "app/components/JsonLd.tsx", "tsx", code,
                                     notes="Render <JsonLd /> from a Server Component in the page/layout head.")


# -- WordPress ----------------------------------------------------------------

class WordpressGenerator(BaseGenerator):
    framework = "wordpress"
    display = "WordPress"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<?php\n"
            "// Add to your theme's functions.php (child theme recommended).\n"
            "// SEO-only: outputs meta tags in <head>; does not alter templates or design.\n"
            "add_action('wp_head', function () {\n"
            "    if (function_exists('wpseo_init') || class_exists('RankMath')) { return; } // let Yoast/Rank Math own it\n"
            f"    echo '<meta name=\"description\" content=\"' . esc_attr('{ctx.desc}') . '\">' . \"\\n\";\n"
            f"    echo '<link rel=\"canonical\" href=\"' . esc_url('{ctx.canonical}') . '\">' . \"\\n\";\n"
            "}, 1);\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "functions.php (wp_head)", "php", code, is_new_file=False,
                                     notes="Prefer configuring Yoast/Rank Math fields; this hook is the safe fallback.",
                                     code_fixable=False)

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<?php\n"
            "add_action('wp_head', function () {\n"
            f"    $title = esc_attr('{ctx.page_label}'); $desc = esc_attr('{ctx.desc}'); $url = esc_url('{ctx.canonical}');\n"
            "    echo \"<meta property=\\\"og:title\\\" content=\\\"$title\\\">\\n\";\n"
            "    echo \"<meta property=\\\"og:description\\\" content=\\\"$desc\\\">\\n\";\n"
            "    echo \"<meta property=\\\"og:url\\\" content=\\\"$url\\\">\\n\";\n"
            "    echo \"<meta name=\\\"twitter:card\\\" content=\\\"summary_large_image\\\">\\n\";\n"
            "}, 2);\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "functions.php (wp_head)", "php", code, is_new_file=False, code_fixable=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<?php\n"
            "// Adds the sitemap directive via the core robots.txt filter (virtual robots.txt).\n"
            "add_filter('robots_txt', function ($output) {\n"
            f"    $output .= \"\\nSitemap: {ctx.origin}/sitemap_index.xml\\n\";\n"
            "    return $output;\n"
            "}, 10, 1);\n"
        )
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "functions.php (robots_txt filter)", "php", code, is_new_file=False, code_fixable=False)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "WordPress generates XML sitemaps automatically:\n"
            "  - Yoast SEO: /sitemap_index.xml (Settings > enable XML sitemaps)\n"
            "  - Rank Math: /sitemap_index.xml (Sitemap Settings)\n"
            "  - WordPress core (5.5+): /wp-sitemap.xml\n"
            "No code change required — enable the sitemap in your active SEO plugin."
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "(SEO plugin setting)", "text", code, is_new_file=False, code_fixable=False,
                                     notes="Guided setting, not a code patch.")

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "<?php\n"
            "add_action('wp_head', function () {\n"
            f"    $schema = '{data}';\n"
            "    echo '<script type=\"application/ld+json\">' . $schema . '</script>' . \"\\n\";\n"
            "}, 20);\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "functions.php (wp_head)", "php", code, is_new_file=False, code_fixable=False)


# -- Shopify (Liquid) ---------------------------------------------------------

class ShopifyGenerator(BaseGenerator):
    framework = "shopify"
    display = "Shopify"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{%- comment -%} Add inside <head> in layout/theme.liquid (SEO-only, head only) {%- endcomment -%}\n"
            "<title>{{ page_title }}</title>\n"
            "<meta name=\"description\" content=\"{{ page_description | default: shop.description | escape }}\">\n"
            "<link rel=\"canonical\" href=\"{{ canonical_url }}\">\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "layout/theme.liquid (head)", "liquid", code, is_new_file=False, code_fixable=False,
                                     notes="Shopify sets canonical_url automatically; edit only the head.")

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{%- comment -%} Open Graph / Twitter in layout/theme.liquid head {%- endcomment -%}\n"
            "<meta property=\"og:title\" content=\"{{ page_title }}\">\n"
            "<meta property=\"og:type\" content=\"website\">\n"
            "<meta property=\"og:url\" content=\"{{ canonical_url }}\">\n"
            "<meta property=\"og:description\" content=\"{{ page_description | default: shop.description | escape }}\">\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\">\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "layout/theme.liquid (head)", "liquid", code, is_new_file=False, code_fixable=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{%- comment -%} templates/robots.txt.liquid — extend defaults; store-wide {%- endcomment -%}\n"
            "{% for group in robots.default_groups %}\n"
            "  {{- group.user_agent }}\n"
            "  {% for rule in group.rules %}{{ rule }}\n  {% endfor %}\n"
            "  {%- if group.sitemap != blank %}{{ group.sitemap }}{% endif %}\n"
            "{% endfor %}\n"
        )
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "templates/robots.txt.liquid", "liquid", code, is_new_file=False, code_fixable=False)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = "Shopify maintains /sitemap.xml automatically for all published products, collections and pages. No code change required."
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "(platform-managed /sitemap.xml)", "text", code, is_new_file=False, code_fixable=False,
                                     notes="Guided note, not a code patch.")

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{%- comment -%} Product JSON-LD in templates/product.liquid (or a snippet) {%- endcomment -%}\n"
            "<script type=\"application/ld+json\">\n"
            "{\n"
            "  \"@context\": \"https://schema.org/\",\n"
            "  \"@type\": \"Product\",\n"
            "  \"name\": {{ product.title | json }},\n"
            "  \"description\": {{ product.description | strip_html | json }},\n"
            "  \"url\": {{ canonical_url | json }},\n"
            "  \"offers\": { \"@type\": \"Offer\", \"price\": {{ product.price | divided_by: 100.0 | json }}, \"priceCurrency\": {{ shop.currency | json }} }\n"
            "}\n"
            "</script>\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "templates/product.liquid", "liquid", code, is_new_file=False, code_fixable=False)


# -- Laravel (Blade) ----------------------------------------------------------

class LaravelGenerator(BaseGenerator):
    framework = "laravel"
    display = "Laravel"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{{-- resources/views/layouts/app.blade.php <head> (SEO-only) --}}\n"
            "<title>@yield('title', '" + ctx.page_label + "')</title>\n"
            "<meta name=\"description\" content=\"@yield('description', '" + ctx.desc + "')\">\n"
            "<link rel=\"canonical\" href=\"@yield('canonical', '" + ctx.canonical + "')\">\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "resources/views/layouts/app.blade.php", "blade", code, is_new_file=False,
                                     notes="Set values per page via @section('title')/@section('description').")

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{{-- Open Graph / Twitter in the layout <head> --}}\n"
            f"<meta property=\"og:title\" content=\"@yield('title', '{ctx.page_label}')\">\n"
            f"<meta property=\"og:description\" content=\"@yield('description', '{ctx.desc}')\">\n"
            f"<meta property=\"og:url\" content=\"{ctx.canonical}\">\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\">\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "resources/views/layouts/app.blade.php", "blade", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "public/robots.txt", "text", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// routes/web.php — serve a sitemap (or use spatie/laravel-sitemap).\n"
            "use Illuminate\\Support\\Facades\\Response;\n\n"
            "Route::get('/sitemap.xml', function () {\n"
            "    $urls = " + json.dumps([ctx.origin + (r if r != "/" else "") for r in (ctx.routes or ["/"])]) + ";\n"
            "    $xml = '<?xml version=\"1.0\" encoding=\"UTF-8\"?>';\n"
            "    $xml .= '<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">';\n"
            "    foreach ($urls as $u) { $xml .= '<url><loc>'.$u.'</loc></url>'; }\n"
            "    $xml .= '</urlset>';\n"
            "    return Response::make($xml, 200, ['Content-Type' => 'application/xml']);\n"
            "});\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "routes/web.php", "php", code, is_new_file=False)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx), indent=2)
        code = (
            "{{-- resources/views/partials/schema.blade.php ; @include in layout head --}}\n"
            "<script type=\"application/ld+json\">\n" + data + "\n</script>\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "resources/views/partials/schema.blade.php", "blade", code)


# -- Django (templates) -------------------------------------------------------

class DjangoGenerator(BaseGenerator):
    framework = "django"
    display = "Django"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{# templates/base.html <head> (SEO-only) #}\n"
            "<title>{% block title %}" + ctx.page_label + "{% endblock %}</title>\n"
            "<meta name=\"description\" content=\"{% block description %}" + ctx.desc + "{% endblock %}\">\n"
            "<link rel=\"canonical\" href=\"{% block canonical %}" + ctx.canonical + "{% endblock %}\">\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "templates/base.html", "html", code, is_new_file=False)

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "{# Open Graph / Twitter in base.html head #}\n"
            "<meta property=\"og:title\" content=\"{% block og_title %}" + ctx.page_label + "{% endblock %}\">\n"
            "<meta property=\"og:description\" content=\"" + ctx.desc + "\">\n"
            "<meta property=\"og:url\" content=\"" + ctx.canonical + "\">\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\">\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "templates/base.html", "html", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "static/robots.txt", "text", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "# sitemaps.py — Django's built-in sitemap framework\n"
            "from django.contrib.sitemaps import Sitemap\n"
            "from django.urls import reverse\n\n"
            "class StaticViewSitemap(Sitemap):\n"
            "    priority = 0.7\n"
            "    changefreq = 'weekly'\n"
            "    def items(self):\n"
            "        return " + json.dumps([r for r in (ctx.routes or ["/"])]) + "\n"
            "    def location(self, item):\n"
            "        return item\n\n"
            "# urls.py: from django.contrib.sitemaps.views import sitemap\n"
            "#   path('sitemap.xml', sitemap, {'sitemaps': {'static': StaticViewSitemap}})\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "sitemaps.py", "python", code)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx), indent=2)
        code = (
            "{# base.html head — structured data #}\n"
            "{% block jsonld %}<script type=\"application/ld+json\">\n" + data + "\n</script>{% endblock %}\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "templates/base.html", "html", code, is_new_file=False)


# -- Nuxt ---------------------------------------------------------------------

class NuxtGenerator(BaseGenerator):
    framework = "nuxt"
    display = "Nuxt"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<script setup lang=\"ts\">\n"
            "useSeoMeta({\n"
            f"  title: {json.dumps(ctx.page_label)},\n"
            f"  description: {json.dumps(ctx.desc)},\n"
            f"  ogTitle: {json.dumps(ctx.page_label)},\n"
            f"  ogDescription: {json.dumps(ctx.desc)},\n"
            f"  ogUrl: {json.dumps(ctx.canonical)},\n"
            "  twitterCard: 'summary_large_image',\n"
            "});\n"
            f"useHead({{ link: [{{ rel: 'canonical', href: {json.dumps(ctx.canonical)} }}] }});\n"
            "</script>\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "pages/index.vue (script setup)", "vue", code, is_new_file=False)

    _og_twitter = _metadata

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "public/robots.txt", "text", code,
                                     notes="Or configure @nuxtjs/robots in nuxt.config.ts.")

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// nuxt.config.ts — @nuxtjs/sitemap\n"
            "export default defineNuxtConfig({\n"
            "  modules: ['@nuxtjs/sitemap'],\n"
            f"  site: {{ url: {json.dumps(ctx.origin)} }},\n"
            "});\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "nuxt.config.ts", "typescript", code, is_new_file=False)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "<script setup lang=\"ts\">\n"
            "useHead({\n"
            f"  script: [{{ type: 'application/ld+json', innerHTML: {json.dumps(data)} }}],\n"
            "});\n"
            "</script>\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "pages/index.vue (script setup)", "vue", code, is_new_file=False)


# -- Astro --------------------------------------------------------------------

class AstroGenerator(BaseGenerator):
    framework = "astro"
    display = "Astro"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "---\n"
            f"const title = {json.dumps(ctx.page_label)};\n"
            f"const description = {json.dumps(ctx.desc)};\n"
            f"const canonical = {json.dumps(ctx.canonical)};\n"
            "---\n"
            "<title>{title}</title>\n"
            "<meta name=\"description\" content={description} />\n"
            "<link rel=\"canonical\" href={canonical} />\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "src/layouts/Layout.astro (head)", "astro", code, is_new_file=False)

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<meta property=\"og:title\" content={title} />\n"
            "<meta property=\"og:description\" content={description} />\n"
            "<meta property=\"og:url\" content={canonical} />\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\" />\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "src/layouts/Layout.astro (head)", "astro", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap-index.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "public/robots.txt", "text", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// astro.config.mjs — @astrojs/sitemap\n"
            "import sitemap from '@astrojs/sitemap';\n"
            "export default defineConfig({\n"
            f"  site: {json.dumps(ctx.origin)},\n"
            "  integrations: [sitemap()],\n"
            "});\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "astro.config.mjs", "javascript", code, is_new_file=False)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx), indent=2)
        code = "<script type=\"application/ld+json\" set:html={JSON.stringify(" + data + ")} />\n"
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "src/layouts/Layout.astro (head)", "astro", code, is_new_file=False)


# -- SvelteKit ----------------------------------------------------------------

class SvelteKitGenerator(BaseGenerator):
    framework = "sveltekit"
    display = "SvelteKit"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<svelte:head>\n"
            f"  <title>{ctx.page_label}</title>\n"
            f"  <meta name=\"description\" content=\"{ctx.desc}\" />\n"
            f"  <link rel=\"canonical\" href=\"{ctx.canonical}\" />\n"
            "</svelte:head>\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "src/routes/+page.svelte", "svelte", code, is_new_file=False)

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<svelte:head>\n"
            f"  <meta property=\"og:title\" content=\"{ctx.page_label}\" />\n"
            f"  <meta property=\"og:description\" content=\"{ctx.desc}\" />\n"
            f"  <meta property=\"og:url\" content=\"{ctx.canonical}\" />\n"
            "  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n"
            "</svelte:head>\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "src/routes/+page.svelte", "svelte", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "static/robots.txt", "text", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        urls = "".join(f"<url><loc>{ctx.origin}{r if r != '/' else ''}</loc></url>" for r in (ctx.routes or ["/"]))
        code = (
            "// src/routes/sitemap.xml/+server.ts\n"
            "export const GET = async () => {\n"
            "  const body = `<?xml version=\"1.0\" encoding=\"UTF-8\"?>` +\n"
            "    `<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">` +\n"
            f"    `{urls}` +\n"
            "    `</urlset>`;\n"
            "  return new Response(body, { headers: { 'Content-Type': 'application/xml' } });\n"
            "};\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "src/routes/sitemap.xml/+server.ts", "typescript", code)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "<svelte:head>\n"
            "  {@html `<script type=\"application/ld+json\">" + data + "</script>`}\n"
            "</svelte:head>\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "src/routes/+page.svelte", "svelte", code, is_new_file=False)


# -- Gatsby -------------------------------------------------------------------

class GatsbyGenerator(BaseGenerator):
    framework = "gatsby"
    display = "Gatsby"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// Gatsby Head API — export from the page component (SEO-only).\n"
            "export function Head() {\n"
            "  return (\n"
            "    <>\n"
            f"      <title>{ctx.page_label}</title>\n"
            f"      <meta name=\"description\" content={json.dumps(ctx.desc)} />\n"
            f"      <link rel=\"canonical\" href={json.dumps(ctx.canonical)} />\n"
            "    </>\n"
            "  );\n"
            "}\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "src/pages/index.tsx (Head export)", "tsx", code, is_new_file=False)

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// Add to the page's Head() export\n"
            f"<meta property=\"og:title\" content={json.dumps(ctx.page_label)} />\n"
            f"<meta property=\"og:description\" content={json.dumps(ctx.desc)} />\n"
            f"<meta property=\"og:url\" content={json.dumps(ctx.canonical)} />\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\" />\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "src/pages/index.tsx (Head export)", "tsx", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap-index.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "static/robots.txt", "text", code,
                                     notes="Or use gatsby-plugin-robots-txt in gatsby-config.")

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// gatsby-config.js — gatsby-plugin-sitemap\n"
            "module.exports = {\n"
            f"  siteMetadata: {{ siteUrl: {json.dumps(ctx.origin)} }},\n"
            "  plugins: ['gatsby-plugin-sitemap'],\n"
            "};\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "gatsby-config.js", "javascript", code, is_new_file=False)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "// In the page's Head() export\n"
            "<script type=\"application/ld+json\" "
            f"dangerouslySetInnerHTML={{{{ __html: JSON.stringify({data}) }}}} />\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "src/pages/index.tsx (Head export)", "tsx", code, is_new_file=False)


# -- React / Vue / Angular (client SPAs) --------------------------------------

class ReactGenerator(BaseGenerator):
    framework = "react"
    display = "React"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// react-helmet-async — ensure it renders server-side for crawlers.\n"
            "import { Helmet } from 'react-helmet-async';\n\n"
            "export function Seo() {\n"
            "  return (\n"
            "    <Helmet>\n"
            f"      <title>{ctx.page_label}</title>\n"
            f"      <meta name=\"description\" content={json.dumps(ctx.desc)} />\n"
            f"      <link rel=\"canonical\" href={json.dumps(ctx.canonical)} />\n"
            "    </Helmet>\n"
            "  );\n"
            "}\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "src/components/Seo.tsx", "tsx", code,
                                     notes="Client rendering: prefer SSR/prerender so crawlers see these tags.")

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// Inside the <Helmet> block\n"
            f"<meta property=\"og:title\" content={json.dumps(ctx.page_label)} />\n"
            f"<meta property=\"og:description\" content={json.dumps(ctx.desc)} />\n"
            f"<meta property=\"og:url\" content={json.dumps(ctx.canonical)} />\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\" />\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "src/components/Seo.tsx", "tsx", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "public/robots.txt", "text", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        urls = "\n".join(f"  <url><loc>{ctx.origin}{r if r != '/' else ''}</loc></url>" for r in (ctx.routes or ["/"]))
        code = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
            f"{urls}\n"
            "</urlset>\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "public/sitemap.xml", "xml", code,
                                     notes="Static sitemap; regenerate at build time for larger sites.")

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "// Inside <Helmet>\n"
            f"<script type=\"application/ld+json\">{{`{data}`}}</script>\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "src/components/Seo.tsx", "tsx", code, is_new_file=False)


class VueGenerator(ReactGenerator):
    framework = "vue"
    display = "Vue"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<script setup lang=\"ts\">\n"
            "// @vueuse/head or Nuxt's useHead. Ensure SSR for crawlers.\n"
            "import { useHead } from '@vueuse/head';\n"
            "useHead({\n"
            f"  title: {json.dumps(ctx.page_label)},\n"
            f"  meta: [{{ name: 'description', content: {json.dumps(ctx.desc)} }}],\n"
            f"  link: [{{ rel: 'canonical', href: {json.dumps(ctx.canonical)} }}],\n"
            "});\n"
            "</script>\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "src/App.vue (script setup)", "vue", code, is_new_file=False,
                                     notes="Client rendering: prefer SSR so crawlers see these tags.")

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "<script setup lang=\"ts\">\n"
            "import { useHead } from '@vueuse/head';\n"
            f"useHead({{ script: [{{ type: 'application/ld+json', children: {json.dumps(data)} }}] }});\n"
            "</script>\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "src/App.vue (script setup)", "vue", code, is_new_file=False)

    _og_twitter = _metadata


class AngularGenerator(ReactGenerator):
    framework = "angular"
    display = "Angular"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "// Use Angular's Title + Meta services in the component (SEO-only).\n"
            "import { Title, Meta } from '@angular/platform-browser';\n\n"
            "constructor(private title: Title, private meta: Meta) {}\n"
            "ngOnInit() {\n"
            f"  this.title.setTitle({json.dumps(ctx.page_label)});\n"
            f"  this.meta.updateTag({{ name: 'description', content: {json.dumps(ctx.desc)} }});\n"
            f"  this.meta.updateTag({{ rel: 'canonical', href: {json.dumps(ctx.canonical)} }} as any);\n"
            "}\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "src/app/app.component.ts", "typescript", code, is_new_file=False,
                                     notes="Use Angular Universal (SSR) so crawlers receive these tags.")

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx))
        code = (
            "// Inject JSON-LD via a script element in ngOnInit (SEO-only).\n"
            "const s = document.createElement('script');\n"
            "s.type = 'application/ld+json';\n"
            f"s.text = {json.dumps(data)};\n"
            "document.head.appendChild(s);\n"
        )
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "src/app/app.component.ts", "typescript", code, is_new_file=False)

    _og_twitter = ReactGenerator._og_twitter


# -- Custom HTML --------------------------------------------------------------

class CustomHtmlGenerator(BaseGenerator):
    framework = "custom"
    display = "Custom HTML"

    def _metadata(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<!-- Add inside <head> (SEO-only; no layout/body changes) -->\n"
            f"<title>{ctx.page_label}</title>\n"
            f"<meta name=\"description\" content=\"{ctx.desc}\">\n"
            f"<link rel=\"canonical\" href=\"{ctx.canonical}\">\n"
        )
        return GeneratedPatchContent(self.framework, "metadata", "metadata_update",
                                     "index.html (head)", "html", code, is_new_file=False)

    def _og_twitter(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = (
            "<!-- Open Graph / Twitter in <head> -->\n"
            f"<meta property=\"og:title\" content=\"{ctx.page_label}\">\n"
            f"<meta property=\"og:description\" content=\"{ctx.desc}\">\n"
            f"<meta property=\"og:url\" content=\"{ctx.canonical}\">\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\">\n"
        )
        return GeneratedPatchContent(self.framework, "og_twitter", "og_twitter_addition",
                                     "index.html (head)", "html", code, is_new_file=False)

    def _robots(self, ctx: PatchContext) -> GeneratedPatchContent:
        code = f"User-agent: *\nAllow: /\nSitemap: {ctx.origin}/sitemap.xml\n"
        return GeneratedPatchContent(self.framework, "robots", "robots_update",
                                     "robots.txt", "text", code)

    def _sitemap(self, ctx: PatchContext) -> GeneratedPatchContent:
        urls = "\n".join(f"  <url><loc>{ctx.origin}{r if r != '/' else ''}</loc></url>" for r in (ctx.routes or ["/"]))
        code = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
            f"{urls}\n"
            "</urlset>\n"
        )
        return GeneratedPatchContent(self.framework, "sitemap", "sitemap_update",
                                     "sitemap.xml", "xml", code)

    def _schema(self, ctx: PatchContext) -> GeneratedPatchContent:
        data = json.dumps(_org_jsonld(ctx), indent=2)
        code = "<script type=\"application/ld+json\">\n" + data + "\n</script>\n"
        return GeneratedPatchContent(self.framework, "schema", "schema_addition",
                                     "index.html (head)", "html", code, is_new_file=False)


_GENERATORS: Dict[str, BaseGenerator] = {
    g.framework: g for g in (
        NextjsGenerator(), WordpressGenerator(), ShopifyGenerator(), LaravelGenerator(),
        DjangoGenerator(), NuxtGenerator(), AstroGenerator(), SvelteKitGenerator(),
        GatsbyGenerator(), ReactGenerator(), VueGenerator(), AngularGenerator(),
        CustomHtmlGenerator(),
    )
}


def supported_frameworks() -> List[str]:
    return sorted(_GENERATORS.keys())


def generator_for(framework_key: Optional[str]) -> Optional[BaseGenerator]:
    if not framework_key:
        return None
    return _GENERATORS.get(framework_key)


def generate_patch(framework_key: str, surface: str, ctx: PatchContext) -> Optional[GeneratedPatchContent]:
    gen = generator_for(framework_key)
    if not gen:
        return None
    return gen.generate(surface, ctx)
