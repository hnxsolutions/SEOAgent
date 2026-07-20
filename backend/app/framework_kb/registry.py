"""The framework registry: declarative SEO profiles per framework/CMS.

Each `FrameworkProfile` captures, in plain language, how a framework handles the
SEO surfaces the engine cares about, its impact ratings, known limitations, and —
crucially — the framework-specific *action* for each generic task type (so
"Improve Metadata" becomes "use generateMetadata()" on Next.js and "configure
Yoast/Rank Math" on WordPress). Consumers query this module; they never hardcode
framework logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TaskAction:
    """The framework-specific way to accomplish a generic SEO task."""

    action: str            # short imperative, e.g. "Use generateMetadata()"
    detail: str            # one sentence of how, business-readable
    safe_files: List[str] = field(default_factory=list)  # example SEO-safe targets
    code_fixable: bool = True  # can the repo agent auto-patch this on this stack?


@dataclass(frozen=True)
class FrameworkProfile:
    key: str
    display_name: str
    category: str          # "framework" | "cms" | "site_builder" | "custom"
    rendering: str         # typical rendering mode
    language: str
    # Business-language purpose + impact ratings (1-5 stars).
    purpose: str
    seo_impact: int        # 1-5
    performance_impact: int  # 1-5
    seo_impact_reason: str
    performance_impact_reason: str
    # SEO capability systems (what the framework offers).
    metadata_system: str
    robots_system: str
    sitemap_system: str
    image_system: str
    schema_strategy: str
    internal_linking: str
    caching: str
    performance: str
    limitations: List[str] = field(default_factory=list)
    # Capability flags used to generate "already supports / available but unused"
    # style recommendations.
    supports_ssr: bool = False
    supports_auto_metadata: bool = False
    supports_image_optimization: bool = False
    supports_structured_data: bool = False
    supports_auto_sitemap: bool = False
    # Generic-task -> framework-specific action.
    task_actions: Dict[str, TaskAction] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "category": self.category,
            "rendering": self.rendering,
            "language": self.language,
            "purpose": self.purpose,
            "seo_impact": self.seo_impact,
            "performance_impact": self.performance_impact,
            "seo_impact_reason": self.seo_impact_reason,
            "performance_impact_reason": self.performance_impact_reason,
            "capabilities": {
                "metadata_system": self.metadata_system,
                "robots_system": self.robots_system,
                "sitemap_system": self.sitemap_system,
                "image_system": self.image_system,
                "schema_strategy": self.schema_strategy,
                "internal_linking": self.internal_linking,
                "caching": self.caching,
                "performance": self.performance,
            },
            "limitations": self.limitations,
            "flags": {
                "supports_ssr": self.supports_ssr,
                "supports_auto_metadata": self.supports_auto_metadata,
                "supports_image_optimization": self.supports_image_optimization,
                "supports_structured_data": self.supports_structured_data,
                "supports_auto_sitemap": self.supports_auto_sitemap,
            },
        }


# -- profiles -----------------------------------------------------------------

_NEXTJS = FrameworkProfile(
    key="nextjs",
    display_name="Next.js",
    category="framework",
    rendering="Server-Side Rendering / Static Generation",
    language="JavaScript / TypeScript",
    purpose="A React framework that renders pages on the server so search engines get complete HTML.",
    seo_impact=5,
    performance_impact=5,
    seo_impact_reason="Server rendering delivers fully-formed HTML, so Google can crawl and index pages immediately.",
    performance_impact_reason="Static generation and automatic code-splitting make pages load fast, which Google rewards.",
    metadata_system="Metadata API — generateMetadata() / the metadata export in the App Router.",
    robots_system="app/robots.ts (or public/robots.txt).",
    sitemap_system="app/sitemap.ts generates an XML sitemap automatically.",
    image_system="next/image with automatic WebP/AVIF, sizing and lazy-loading.",
    schema_strategy="Inject JSON-LD via a server component in the page/layout.",
    internal_linking="next/link for crawlable, prefetching internal links.",
    caching="Automatic full-route cache + ISR revalidation.",
    performance="Automatic code-splitting, streaming, and image/font optimization.",
    limitations=[
        "Metadata cannot be exported from a Client Component ('use client').",
        "Dynamic routes need generateStaticParams or dynamic rendering to be indexable.",
    ],
    supports_ssr=True,
    supports_auto_metadata=True,
    supports_image_optimization=True,
    supports_structured_data=True,
    supports_auto_sitemap=True,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Use generateMetadata()",
            "Set title/description/canonical in the route's server-side generateMetadata() or metadata export.",
            ["app/**/page.tsx", "app/**/layout.tsx"],
        ),
        "schema_addition": TaskAction(
            "Add JSON-LD in a server component",
            "Render an application/ld+json <script> from the server component (never a client component).",
            ["app/**/page.tsx", "app/**/layout.tsx"],
        ),
        "sitemap_robots_fix": TaskAction(
            "Use app/sitemap.ts and app/robots.ts",
            "Generate the sitemap and robots rules with Next's file conventions instead of static files.",
            ["app/sitemap.ts", "app/robots.ts"],
        ),
        "technical_seo_fix": TaskAction(
            "Apply the fix in server config/components",
            "Use next.config.js or server components for headers, redirects, and canonicalization — never touch UI.",
            ["next.config.js", "app/**/layout.tsx"],
        ),
    },
)

_WORDPRESS = FrameworkProfile(
    key="wordpress",
    display_name="WordPress",
    category="cms",
    rendering="Server-rendered (PHP)",
    language="PHP",
    purpose="The most popular CMS; SEO is handled by plugins and the active theme's head.",
    seo_impact=4,
    performance_impact=3,
    seo_impact_reason="Mature SEO plugins (Yoast, Rank Math) give full control of metadata, schema and sitemaps.",
    performance_impact_reason="Performance depends on hosting, theme and plugins; caching plugins help but bloat is common.",
    metadata_system="Yoast SEO / Rank Math, or wp_head hooks in functions.php.",
    robots_system="Plugin-managed virtual robots.txt (Yoast/Rank Math).",
    sitemap_system="Yoast/Rank Math generate XML sitemaps automatically.",
    image_system="Theme/plugin driven (e.g. Smush, ShortPixel, WebP Express).",
    schema_strategy="Yoast/Rank Math output schema graph; custom via functions.php filters.",
    internal_linking="Editor links + plugins (Link Whisper); menus via nav.",
    caching="Page-cache plugins (WP Rocket, W3 Total Cache) + host cache.",
    performance="Depends on theme/plugins; needs caching + image optimization.",
    limitations=[
        "Theme/template edits can change live design — must stay in SEO plugin/config only.",
        "Plugin conflicts can duplicate metadata or schema.",
    ],
    supports_ssr=True,
    supports_auto_metadata=True,
    supports_image_optimization=False,
    supports_structured_data=True,
    supports_auto_sitemap=True,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Configure Yoast / Rank Math title & meta",
            "Set the SEO title and meta description in the Yoast/Rank Math fields (or a wp_head filter) — not the theme.",
            ["functions.php (wp_head filter)"],
            code_fixable=False,
        ),
        "schema_addition": TaskAction(
            "Enable schema in Yoast / Rank Math",
            "Turn on the relevant schema type in the SEO plugin; add custom graph via a functions.php filter.",
            ["functions.php"],
            code_fixable=False,
        ),
        "sitemap_robots_fix": TaskAction(
            "Use the SEO plugin's sitemap & robots",
            "Enable the Yoast/Rank Math XML sitemap and edit robots rules in the plugin, not a static file.",
            [],
            code_fixable=False,
        ),
    },
)

_SHOPIFY = FrameworkProfile(
    key="shopify",
    display_name="Shopify",
    category="cms",
    rendering="Server-rendered (Liquid)",
    language="Liquid",
    purpose="Hosted e-commerce platform; SEO is controlled through Liquid theme templates and admin settings.",
    seo_impact=4,
    performance_impact=4,
    seo_impact_reason="Built-in canonical URLs, auto sitemap, and per-product meta fields cover core SEO.",
    performance_impact_reason="Shopify's global CDN and image serving keep storefronts fast by default.",
    metadata_system="theme.liquid <head> + page/product meta fields; SEO apps.",
    robots_system="robots.txt.liquid (editable) + platform defaults.",
    sitemap_system="Automatic /sitemap.xml maintained by Shopify.",
    image_system="Shopify CDN with img_url filters and responsive sizes.",
    schema_strategy="JSON-LD in product/collection Liquid templates.",
    internal_linking="Liquid navigation + collection links.",
    caching="Shopify-managed edge caching/CDN.",
    performance="CDN-backed; theme/app bloat is the main risk.",
    limitations=[
        "Liquid template edits can affect live storefront behavior — review carefully.",
        "robots.txt.liquid changes apply store-wide.",
    ],
    supports_ssr=True,
    supports_auto_metadata=True,
    supports_image_optimization=True,
    supports_structured_data=True,
    supports_auto_sitemap=True,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Edit title/meta in theme.liquid & product fields",
            "Set the <title>/meta in theme.liquid head and per-product SEO fields (SEO-safe head only).",
            ["layout/theme.liquid", "templates/product.liquid"],
            code_fixable=False,
        ),
        "schema_addition": TaskAction(
            "Add JSON-LD to product/collection Liquid",
            "Inject Product/BreadcrumbList JSON-LD in the relevant Liquid template head.",
            ["templates/product.liquid", "snippets/*.liquid"],
            code_fixable=False,
        ),
        "sitemap_robots_fix": TaskAction(
            "Use Shopify's auto sitemap / robots.txt.liquid",
            "Shopify maintains /sitemap.xml automatically; adjust rules in robots.txt.liquid only if required.",
            ["templates/robots.txt.liquid"],
            code_fixable=False,
        ),
    },
)

_LARAVEL = FrameworkProfile(
    key="laravel",
    display_name="Laravel",
    category="framework",
    rendering="Server-rendered (Blade)",
    language="PHP",
    purpose="A PHP framework; SEO is rendered through Blade templates and middleware.",
    seo_impact=4,
    performance_impact=4,
    seo_impact_reason="Server-rendered Blade views give full, crawlable HTML and total control of the head.",
    performance_impact_reason="Route/response caching and CDN make Laravel apps fast when configured.",
    metadata_system="Blade layout @yield('meta') + a shared SEO view/composer.",
    robots_system="public/robots.txt or a route returning robots rules.",
    sitemap_system="A sitemap route/controller or spatie/laravel-sitemap.",
    image_system="Intervention Image / CDN; responsive images in Blade.",
    schema_strategy="JSON-LD partial included in the Blade layout head.",
    internal_linking="Blade route() links; navigation partials.",
    caching="Route, view and response caching + CDN.",
    performance="Good with caching; N+1 queries are the usual risk.",
    limitations=[
        "SEO must live in layout/partials, never in controllers' business logic.",
        "Middleware changes can affect auth/session — out of bounds.",
    ],
    supports_ssr=True,
    supports_auto_metadata=False,
    supports_image_optimization=False,
    supports_structured_data=True,
    supports_auto_sitemap=False,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Set meta in the Blade layout head",
            "Use a shared SEO partial / @section('meta') in the Blade layout — not controllers.",
            ["resources/views/layouts/*.blade.php"],
        ),
        "schema_addition": TaskAction(
            "Include a JSON-LD Blade partial",
            "Add a structured-data partial to the layout head.",
            ["resources/views/partials/schema.blade.php"],
        ),
        "sitemap_robots_fix": TaskAction(
            "Add a sitemap route + public/robots.txt",
            "Serve a sitemap via a dedicated route/controller and edit public/robots.txt.",
            ["routes/web.php", "public/robots.txt"],
        ),
    },
)

_DJANGO = FrameworkProfile(
    key="django",
    display_name="Django",
    category="framework",
    rendering="Server-rendered (templates)",
    language="Python",
    purpose="A Python framework; SEO is rendered via templates, context processors and the sitemap framework.",
    seo_impact=4,
    performance_impact=4,
    seo_impact_reason="Server templates emit complete HTML and Django ships a built-in sitemap framework.",
    performance_impact_reason="Template fragment and per-view caching keep responses quick.",
    metadata_system="Base template blocks + a context processor for shared meta.",
    robots_system="A static/served robots.txt or a simple view.",
    sitemap_system="django.contrib.sitemaps generates sitemaps.",
    image_system="Storage/CDN + template tags; sorl-thumbnail/imagekit.",
    schema_strategy="JSON-LD block in the base template head.",
    internal_linking="{% url %} template tags; navigation includes.",
    caching="Per-view / template-fragment caching + CDN.",
    performance="Strong with caching; ORM query tuning matters.",
    limitations=[
        "Keep SEO in templates/context processors, never in views' business logic.",
        "Settings/middleware changes are out of scope for SEO.",
    ],
    supports_ssr=True,
    supports_auto_metadata=False,
    supports_image_optimization=False,
    supports_structured_data=True,
    supports_auto_sitemap=True,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Set meta in base template blocks",
            "Use {% block meta %} in the base template + a context processor for shared values.",
            ["templates/base.html"],
        ),
        "schema_addition": TaskAction(
            "Add a JSON-LD block to the base template",
            "Render structured data from a template block in the head.",
            ["templates/base.html"],
        ),
        "sitemap_robots_fix": TaskAction(
            "Use django.contrib.sitemaps",
            "Wire the sitemap framework and serve robots.txt via a static file or view.",
            ["sitemaps.py", "urls.py"],
        ),
    },
)


def _react_like(key: str, name: str, rendering: str, note: str) -> FrameworkProfile:
    """Client-rendered SPA libraries share the same SEO shape/limitations."""
    return FrameworkProfile(
        key=key,
        display_name=name,
        category="framework",
        rendering=rendering,
        language="JavaScript / TypeScript",
        purpose=f"{name} — {note}",
        seo_impact=3,
        performance_impact=3,
        seo_impact_reason="Client-side rendering can hide content from crawlers until JavaScript runs; SSR/prerender is recommended.",
        performance_impact_reason="Large JS bundles can slow first paint; code-splitting helps.",
        metadata_system="react-helmet / head manager, or a meta-framework for SSR.",
        robots_system="Static public/robots.txt.",
        sitemap_system="Build-time sitemap plugin or a static sitemap.xml.",
        image_system="Manual responsive images / a CDN; no built-in optimizer.",
        schema_strategy="Inject JSON-LD via the head manager (ensure it renders server-side).",
        internal_linking="Router <Link> components.",
        caching="Static hosting/CDN cache headers.",
        performance="Depends on bundle size and hydration cost.",
        limitations=[
            "Pure client rendering hurts indexability — prefer SSR/SSG or prerendering.",
            "Metadata set only on the client may be missed by some crawlers.",
        ],
        supports_ssr=False,
        supports_auto_metadata=False,
        supports_image_optimization=False,
        supports_structured_data=True,
        supports_auto_sitemap=False,
        task_actions={
            "metadata_rewrite": TaskAction(
                "Set meta via the head manager (prefer SSR)",
                "Use react-helmet/head manager and ensure it renders server-side for crawlers.",
                ["src/**/*.tsx"],
            ),
            "sitemap_robots_fix": TaskAction(
                "Generate a build-time sitemap + static robots.txt",
                "Add a sitemap build step and a static public/robots.txt.",
                ["public/robots.txt"],
            ),
        },
    )


_NUXT = FrameworkProfile(
    key="nuxt",
    display_name="Nuxt",
    category="framework",
    rendering="Server-Side Rendering / Static Generation",
    language="JavaScript / TypeScript",
    purpose="A Vue framework that renders on the server so crawlers receive full HTML.",
    seo_impact=5,
    performance_impact=4,
    seo_impact_reason="SSR + useHead/useSeoMeta deliver complete, crawlable HTML and easy meta control.",
    performance_impact_reason="Automatic code-splitting and payload optimization keep pages fast.",
    metadata_system="useSeoMeta / useHead composables (or definePageMeta).",
    robots_system="@nuxtjs/robots module or public/robots.txt.",
    sitemap_system="@nuxtjs/sitemap module generates sitemaps.",
    image_system="@nuxt/image with modern formats and resizing.",
    schema_strategy="nuxt-schema-org or JSON-LD via useHead.",
    internal_linking="<NuxtLink> for crawlable links.",
    caching="Nitro route rules / ISR + CDN.",
    performance="Strong with Nitro; watch bundle size.",
    limitations=["Ensure pages aren't forced to client-only rendering for SEO."],
    supports_ssr=True,
    supports_auto_metadata=True,
    supports_image_optimization=True,
    supports_structured_data=True,
    supports_auto_sitemap=True,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Use useSeoMeta() / useHead()",
            "Set title/description/canonical with the Nuxt SEO composables in the page setup.",
            ["pages/**/*.vue"],
        ),
        "schema_addition": TaskAction(
            "Add JSON-LD via useHead / nuxt-schema-org",
            "Render structured data server-side through useHead or the schema.org module.",
            ["pages/**/*.vue"],
        ),
        "sitemap_robots_fix": TaskAction(
            "Use @nuxtjs/sitemap & @nuxtjs/robots",
            "Configure the sitemap and robots modules instead of static files.",
            ["nuxt.config.ts"],
        ),
    },
)

_ASTRO = FrameworkProfile(
    key="astro",
    display_name="Astro",
    category="framework",
    rendering="Static Generation (islands)",
    language="JavaScript / TypeScript",
    purpose="A content-focused framework that ships mostly static HTML — excellent for SEO.",
    seo_impact=5,
    performance_impact=5,
    seo_impact_reason="Ships static, fully-rendered HTML with minimal JS, so crawlers see everything instantly.",
    performance_impact_reason="Near-zero JavaScript by default gives outstanding Core Web Vitals.",
    metadata_system="Meta tags in the layout .astro head (or an SEO component).",
    robots_system="Static public/robots.txt.",
    sitemap_system="@astrojs/sitemap integration.",
    image_system="astro:assets <Image> with modern formats.",
    schema_strategy="JSON-LD in the layout head.",
    internal_linking="Standard <a> links in static HTML.",
    caching="Static hosting/CDN.",
    performance="Excellent — minimal client JS.",
    limitations=["SSR endpoints need adapters; mostly static by design."],
    supports_ssr=True,
    supports_auto_metadata=False,
    supports_image_optimization=True,
    supports_structured_data=True,
    supports_auto_sitemap=True,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Set meta in the layout .astro head",
            "Add title/description/canonical to the shared layout head or an SEO component.",
            ["src/layouts/*.astro"],
        ),
        "sitemap_robots_fix": TaskAction(
            "Use @astrojs/sitemap + static robots.txt",
            "Add the sitemap integration and a static public/robots.txt.",
            ["astro.config.mjs", "public/robots.txt"],
        ),
    },
)

_CUSTOM = FrameworkProfile(
    key="custom",
    display_name="Custom HTML",
    category="custom",
    rendering="Static / server-rendered HTML",
    language="HTML",
    purpose="A hand-built site; SEO tags live directly in each page's <head>.",
    seo_impact=3,
    performance_impact=3,
    seo_impact_reason="Full control of the head, but everything is manual with no framework automation.",
    performance_impact_reason="Performance depends entirely on how assets are authored and served.",
    metadata_system="Meta tags written directly in each page's <head>.",
    robots_system="A static robots.txt file.",
    sitemap_system="A hand-maintained or generated sitemap.xml.",
    image_system="Manual <img> with width/height, srcset and modern formats.",
    schema_strategy="JSON-LD <script> in the head.",
    internal_linking="Standard <a> links.",
    caching="Web-server / CDN cache headers.",
    performance="Manual; depends on asset discipline.",
    limitations=["No framework automation — every SEO change is manual head-only editing."],
    supports_ssr=True,
    supports_auto_metadata=False,
    supports_image_optimization=False,
    supports_structured_data=True,
    supports_auto_sitemap=False,
    task_actions={
        "metadata_rewrite": TaskAction(
            "Edit the page <head> metadata",
            "Update title/description/canonical directly in the page head (head-only, no layout changes).",
            ["*.html"],
        ),
        "schema_addition": TaskAction(
            "Add a JSON-LD <script> to the head",
            "Insert structured data as an application/ld+json script in the head.",
            ["*.html"],
        ),
        "sitemap_robots_fix": TaskAction(
            "Maintain sitemap.xml & robots.txt",
            "Update the static sitemap.xml and robots.txt files.",
            ["sitemap.xml", "robots.txt"],
        ),
    },
)


_REGISTRY: Dict[str, FrameworkProfile] = {
    "nextjs": _NEXTJS,
    "wordpress": _WORDPRESS,
    "shopify": _SHOPIFY,
    "laravel": _LARAVEL,
    "django": _DJANGO,
    "nuxt": _NUXT,
    "astro": _ASTRO,
    "react": _react_like("react", "React", "Client-Side Rendering", "a client-rendered UI library (SSR recommended for SEO)."),
    "vue": _react_like("vue", "Vue", "Client-Side Rendering", "a client-rendered UI framework (SSR recommended for SEO)."),
    "angular": _react_like("angular", "Angular", "Client-Side Rendering", "a client-rendered framework (use Angular Universal for SSR)."),
    "sveltekit": _react_like("sveltekit", "SvelteKit", "Server-Side Rendering", "a Svelte meta-framework with SSR support."),
    "gatsby": _react_like("gatsby", "Gatsby", "Static Generation", "a React static-site generator (good for SEO)."),
    "custom": _CUSTOM,
}

# Aliases from detector/repo names to registry keys.
_ALIASES = {
    "next.js": "nextjs",
    "next": "nextjs",
    "nextjs_app_router": "nextjs",
    "nextjs_pages_router": "nextjs",
    "word press": "wordpress",
    "wp": "wordpress",
    "ruby on rails": "custom",  # no dedicated profile yet -> safe generic
    "squarespace": "custom",
    "wix": "custom",
    "webflow": "custom",
    "magento": "custom",
    "drupal": "custom",
    "joomla": "custom",
    "custom html": "custom",
    "unknown_custom": "custom",
    "svelte": "sveltekit",
}


def normalize_framework_key(name: Optional[str]) -> Optional[str]:
    """Map a detector/repo framework name to a registry key (or None)."""
    if not name:
        return None
    raw = str(name).strip().lower()
    if raw in _REGISTRY:
        return raw
    if raw in _ALIASES:
        return _ALIASES[raw]
    # tolerate spacing/underscores/dots
    compact = raw.replace(" ", "").replace("_", "").replace(".", "")
    for key in _REGISTRY:
        if key.replace(" ", "") == compact:
            return key
    for alias, key in _ALIASES.items():
        if alias.replace(" ", "").replace(".", "") == compact:
            return key
    return None


def get_framework_profile(name: Optional[str]) -> Optional[FrameworkProfile]:
    key = normalize_framework_key(name)
    return _REGISTRY.get(key) if key else None


def known_frameworks() -> List[str]:
    return sorted(_REGISTRY.keys())


def task_action_for(framework: Optional[str], task_type: str) -> Optional[TaskAction]:
    """The framework-specific action for a generic task type, or None if the
    framework has no special handling (caller keeps the generic task)."""
    profile = get_framework_profile(framework)
    if not profile:
        return None
    return profile.task_actions.get(task_type)
