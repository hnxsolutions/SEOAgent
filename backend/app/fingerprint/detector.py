"""Deterministic technology detection from live website signals.

`TechnologyFingerprintDetector.detect(SiteSignals)` returns a `FingerprintResult`
with a flat list of detected technologies (category, name, version, confidence,
evidence) plus readiness scores. It performs NO network I/O — the service fetches
the page/headers/robots and passes them in, which keeps detection pure and fully
unit-testable.

Detection is signal-based: every match carries human-readable evidence and a
confidence weight, exactly as the product requires ("confidence % and why it was
detected"). Nothing here modifies a site; it only classifies it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse


# -- inputs -------------------------------------------------------------------


@dataclass
class SiteSignals:
    """Everything the detector needs, gathered by the service (no I/O here)."""

    url: str
    status_code: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)  # lowercased keys
    html: str = ""
    robots_txt: Optional[str] = None
    has_sitemap: bool = False
    final_url: Optional[str] = None  # after redirects (for scheme/host checks)

    def header(self, name: str) -> str:
        return (self.headers or {}).get(name.lower(), "") or ""


# -- outputs ------------------------------------------------------------------


@dataclass
class DetectedTech:
    category: str
    name: str
    confidence: int  # 0-100
    evidence: List[str] = field(default_factory=list)
    version: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "name": self.name,
            "version": self.version,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass
class FingerprintResult:
    technologies: List[DetectedTech]
    scores: Dict[str, int]
    primary_framework: Optional[str]
    primary_cms: Optional[str]
    primary_language: Optional[str]
    rendering: Optional[str]
    hosting: Optional[str]
    cdn: Optional[str]
    content_hash: str

    def technologies_as_dicts(self) -> List[dict]:
        return [t.as_dict() for t in self.technologies]


# Categories used across the product's Technology Overview.
CAT_FRAMEWORK = "framework"
CAT_JS_FRAMEWORK = "js_framework"
CAT_CMS = "cms"
CAT_LANGUAGE = "language"
CAT_RENDERING = "rendering"
CAT_BACKEND = "backend_framework"
CAT_WEB_SERVER = "web_server"
CAT_HOSTING = "hosting"
CAT_CDN = "cdn"
CAT_IMAGE = "image_system"
CAT_ANALYTICS = "analytics"
CAT_SEO = "seo"
CAT_SCHEMA = "schema"
CAT_ROBOTS = "robots"
CAT_SITEMAP = "sitemap"
CAT_CACHING = "caching"
CAT_SECURITY = "security"
CAT_FONTS = "fonts"
CAT_STYLING = "styling"
CAT_BUILD = "build_system"


class TechnologyFingerprintDetector:
    """Classify a website's stack from live signals. Pure + deterministic."""

    def detect(self, signals: SiteSignals) -> FingerprintResult:
        techs: List[DetectedTech] = []
        html = signals.html or ""
        html_lc = html.lower()

        framework = self._detect_framework(signals, html, html_lc, techs)
        cms = self._detect_cms(signals, html, html_lc, techs)
        self._detect_web_server(signals, techs)
        hosting = self._detect_hosting(signals, techs)
        cdn = self._detect_cdn(signals, techs)
        language = self._detect_language(signals, framework, cms, techs)
        self._detect_backend(signals, techs)
        self._detect_image_system(signals, html_lc, techs)
        self._detect_analytics(html_lc, techs)
        self._detect_fonts_styling(html_lc, techs)
        rendering = self._detect_rendering(signals, html_lc, framework, cms, techs)
        self._detect_seo_signals(signals, html, html_lc, techs)
        self._detect_caching_security(signals, techs)

        scores = self._scores(signals, html, html_lc, techs)
        content_hash = self._hash(signals)

        return FingerprintResult(
            technologies=techs,
            scores=scores,
            primary_framework=framework,
            primary_cms=cms,
            primary_language=language,
            rendering=rendering,
            hosting=hosting,
            cdn=cdn,
            content_hash=content_hash,
        )

    # -- framework / js -----------------------------------------------------

    def _detect_framework(self, s: SiteSignals, html: str, html_lc: str, out: List[DetectedTech]) -> Optional[str]:
        xpb = s.header("x-powered-by").lower()
        picks: List[DetectedTech] = []

        if "/_next/" in html_lc or "__next_data__" in html_lc or 'id="__next"' in html_lc:
            ev = []
            if "/_next/" in html_lc:
                ev.append("/_next/ build assets referenced")
            if "__next_data__" in html_lc:
                ev.append("__NEXT_DATA__ hydration payload present")
            if 'id="__next"' in html_lc:
                ev.append('root <div id="__next"> present')
            if "next.js" in xpb or "next" in xpb:
                ev.append(f"X-Powered-By: {s.header('x-powered-by')}")
            picks.append(DetectedTech(CAT_FRAMEWORK, "Next.js", 97, ev, self._version(html, r"next[/@-]?(\d+\.\d+)")))
        if "__nuxt__" in html_lc or "/_nuxt/" in html_lc:
            picks.append(DetectedTech(CAT_FRAMEWORK, "Nuxt", 94, ["Nuxt runtime markers (__NUXT__ / /_nuxt/)"]))
        if "___gatsby" in html_lc or "gatsby" in html_lc and "id=\"___gatsby\"" in html_lc:
            picks.append(DetectedTech(CAT_FRAMEWORK, "Gatsby", 90, ['<div id="___gatsby"> present']))
        if "astro-island" in html_lc or "data-astro" in html_lc:
            picks.append(DetectedTech(CAT_FRAMEWORK, "Astro", 92, ["Astro island hydration markers"]))
        if "__sveltekit" in html_lc or "svelte-" in html_lc:
            picks.append(DetectedTech(CAT_FRAMEWORK, "SvelteKit", 88, ["SvelteKit/Svelte runtime markers"]))
        if "ng-version" in html_lc:
            picks.append(DetectedTech(CAT_FRAMEWORK, "Angular", 93, ["ng-version attribute present"], self._version(html, r'ng-version="(\d+\.\d+)')))

        # Underlying JS libraries (not necessarily the meta-framework).
        if "data-reactroot" in html_lc or "react" in html_lc and "_next" not in html_lc and not picks:
            if "data-reactroot" in html_lc:
                out.append(DetectedTech(CAT_JS_FRAMEWORK, "React", 80, ["data-reactroot attribute present"]))
        elif any(p.name in {"Next.js", "Gatsby"} for p in picks):
            out.append(DetectedTech(CAT_JS_FRAMEWORK, "React", 95, ["Rendered by a React meta-framework"]))
        elif any(p.name in {"Nuxt"} for p in picks):
            out.append(DetectedTech(CAT_JS_FRAMEWORK, "Vue", 95, ["Rendered by Nuxt (Vue)"]))
        if "data-v-" in html_lc and not any(p.name == "Nuxt" for p in picks):
            out.append(DetectedTech(CAT_JS_FRAMEWORK, "Vue", 78, ["Vue scoped-style data-v- attributes present"]))

        if not picks:
            return None
        # Highest-confidence framework wins as primary.
        picks.sort(key=lambda t: t.confidence, reverse=True)
        out.extend(picks)
        return picks[0].name

    # -- cms ----------------------------------------------------------------

    def _detect_cms(self, s: SiteSignals, html: str, html_lc: str, out: List[DetectedTech]) -> Optional[str]:
        generator = self._meta_generator(html)
        gen_lc = (generator or "").lower()
        picks: List[DetectedTech] = []

        if "wp-content" in html_lc or "wp-includes" in html_lc or "/wp-json" in html_lc or "wordpress" in gen_lc:
            ev = [m for m, cond in (
                ("wp-content assets referenced", "wp-content" in html_lc),
                ("wp-includes assets referenced", "wp-includes" in html_lc),
                ("/wp-json REST route present", "/wp-json" in html_lc),
                (f'meta generator "{generator}"', "wordpress" in gen_lc),
            ) if cond]
            picks.append(DetectedTech(CAT_CMS, "WordPress", 96, ev, self._version(generator or "", r"(\d+\.\d+)")))
        if "cdn.shopify.com" in html_lc or "myshopify.com" in html_lc or s.header("x-shopify-stage"):
            ev = [m for m, cond in (
                ("cdn.shopify.com assets", "cdn.shopify.com" in html_lc),
                ("myshopify.com references", "myshopify.com" in html_lc),
                ("X-Shopify-Stage header", bool(s.header("x-shopify-stage"))),
            ) if cond]
            picks.append(DetectedTech(CAT_CMS, "Shopify", 96, ev))
        if "static.squarespace.com" in html_lc or "squarespace" in gen_lc:
            picks.append(DetectedTech(CAT_CMS, "Squarespace", 92, ["Squarespace context/assets present"]))
        if "wix.com" in html_lc or s.header("x-wix-request-id"):
            picks.append(DetectedTech(CAT_CMS, "Wix", 90, ["Wix assets/headers present"]))
        if "webflow" in html_lc or "data-wf-" in html_lc or "webflow" in gen_lc:
            picks.append(DetectedTech(CAT_CMS, "Webflow", 88, ["Webflow markers (data-wf-/generator)"]))
        if "drupal-settings-json" in html_lc or "/sites/default/files" in html_lc or "drupal" in gen_lc or s.header("x-generator").lower().startswith("drupal"):
            picks.append(DetectedTech(CAT_CMS, "Drupal", 90, ["Drupal settings/assets present"]))
        if "/media/jui" in html_lc or "joomla" in gen_lc:
            picks.append(DetectedTech(CAT_CMS, "Joomla", 85, ["Joomla assets/generator present"]))
        if "/static/version" in html_lc and "mage" in html_lc or "magento" in html_lc:
            picks.append(DetectedTech(CAT_CMS, "Magento", 84, ["Magento static/version + mage markers"]))
        if "ghost" in gen_lc or "content=\"ghost" in html_lc:
            picks.append(DetectedTech(CAT_CMS, "Ghost", 82, ['meta generator "Ghost"']))

        if not picks:
            if generator:
                out.append(DetectedTech(CAT_CMS, generator.split()[0], 55, [f'meta generator "{generator}"']))
                return None
            return None
        picks.sort(key=lambda t: t.confidence, reverse=True)
        out.extend(picks)
        return picks[0].name

    # -- infra --------------------------------------------------------------

    def _detect_web_server(self, s: SiteSignals, out: List[DetectedTech]) -> None:
        server = s.header("server")
        sl = server.lower()
        mapping = [
            ("nginx", "Nginx"), ("apache", "Apache"), ("microsoft-iis", "IIS"),
            ("iis", "IIS"), ("litespeed", "LiteSpeed"), ("caddy", "Caddy"),
            ("gunicorn", "Gunicorn"), ("uvicorn", "Uvicorn"), ("kestrel", "Kestrel"),
        ]
        for needle, name in mapping:
            if needle in sl:
                out.append(DetectedTech(CAT_WEB_SERVER, name, 88, [f"Server: {server}"]))
                break

    def _detect_hosting(self, s: SiteSignals, out: List[DetectedTech]) -> Optional[str]:
        checks = [
            (s.header("x-vercel-id") or "vercel" in s.header("server").lower(), "Vercel", "X-Vercel-Id / Server header"),
            (s.header("x-nf-request-id") or "netlify" in s.header("server").lower(), "Netlify", "Netlify request header"),
            (s.header("x-amz-cf-id") or s.header("x-amz-request-id") or "amazons3" in s.header("server").lower(), "AWS", "AWS/S3/CloudFront headers"),
            ("windows-azure" in s.header("server").lower() or s.header("x-azure-ref"), "Azure", "Azure header"),
            (s.header("x-goog-") or "gse" in s.header("server").lower() or s.header("x-cloud-trace-context"), "Google Cloud", "Google Cloud header"),
            ("github.com" in s.header("server").lower() or "github.io" in (s.url or ""), "GitHub Pages", "GitHub Pages host"),
            (s.header("x-render-origin-server"), "Render", "Render origin header"),
            (s.header("fly-request-id"), "Fly.io", "Fly.io request header"),
        ]
        for cond, name, why in checks:
            if cond:
                out.append(DetectedTech(CAT_HOSTING, name, 85, [why]))
                return name
        return None

    def _detect_cdn(self, s: SiteSignals, out: List[DetectedTech]) -> Optional[str]:
        checks = [
            (s.header("cf-ray") or "cloudflare" in s.header("server").lower(), "Cloudflare", "CF-Ray / Server: cloudflare"),
            (s.header("x-served-by") and "fastly" in s.header("x-served-by").lower() or "fastly" in s.header("via").lower(), "Fastly", "Fastly Via/X-Served-By"),
            ("akamai" in s.header("server").lower() or s.header("x-akamai-transformed"), "Akamai", "Akamai header"),
            (s.header("x-amz-cf-id"), "AWS CloudFront", "X-Amz-Cf-Id header"),
            ("bunnycdn" in s.header("server").lower() or s.header("cdn-cache"), "BunnyCDN", "Bunny/CDN cache header"),
        ]
        for cond, name, why in checks:
            if cond:
                out.append(DetectedTech(CAT_CDN, name, 82, [why]))
                return name
        return None

    def _detect_language(self, s: SiteSignals, framework: Optional[str], cms: Optional[str], out: List[DetectedTech]) -> Optional[str]:
        xpb = s.header("x-powered-by").lower()
        if "php" in xpb or cms in {"WordPress", "Drupal", "Joomla", "Magento"}:
            out.append(DetectedTech(CAT_LANGUAGE, "PHP", 82, [f"X-Powered-By: {s.header('x-powered-by')}" if "php" in xpb else f"{cms} runs on PHP"]))
            return "PHP"
        if "asp.net" in xpb or s.header("x-aspnet-version"):
            out.append(DetectedTech(CAT_LANGUAGE, "C# (.NET)", 82, ["ASP.NET headers present"]))
            return "C# (.NET)"
        if framework in {"Next.js", "Nuxt", "Gatsby", "Astro", "SvelteKit", "Angular"} or "express" in xpb or "next" in xpb:
            # JS meta-frameworks: TypeScript is the common default; report JavaScript/TypeScript.
            out.append(DetectedTech(CAT_LANGUAGE, "JavaScript / TypeScript", 72, [f"{framework or 'Node'} runtime"]))
            return "JavaScript / TypeScript"
        if s.header("x-powered-by") and "servlet" in xpb:
            out.append(DetectedTech(CAT_LANGUAGE, "Java", 70, ["Servlet header"]))
            return "Java"
        return None

    def _detect_backend(self, s: SiteSignals, out: List[DetectedTech]) -> None:
        xpb = s.header("x-powered-by").lower()
        mapping = [
            ("express", "Express"), ("nest", "NestJS"), ("laravel", "Laravel"),
            ("symfony", "Symfony"), ("django", "Django"), ("flask", "Flask"),
            ("fastapi", "FastAPI"), ("rails", "Ruby on Rails"), ("spring", "Spring Boot"),
        ]
        for needle, name in mapping:
            if needle in xpb:
                out.append(DetectedTech(CAT_BACKEND, name, 75, [f"X-Powered-By: {s.header('x-powered-by')}"]))
                return
        if s.header("x-drupal-cache") or s.header("x-generator").lower().startswith("drupal"):
            out.append(DetectedTech(CAT_BACKEND, "Drupal", 72, ["Drupal cache header"]))

    def _detect_image_system(self, s: SiteSignals, html_lc: str, out: List[DetectedTech]) -> None:
        if "/_next/image" in html_lc:
            out.append(DetectedTech(CAT_IMAGE, "next/image", 90, ["/_next/image optimizer URLs present"]))
        if "res.cloudinary.com" in html_lc:
            out.append(DetectedTech(CAT_IMAGE, "Cloudinary", 88, ["res.cloudinary.com asset URLs"]))
        if ".imgix.net" in html_lc:
            out.append(DetectedTech(CAT_IMAGE, "imgix", 85, ["imgix asset URLs"]))
        if "cdn.shopify.com" in html_lc:
            out.append(DetectedTech(CAT_IMAGE, "Shopify CDN images", 80, ["cdn.shopify.com image URLs"]))
        if ".webp" in html_lc or ".avif" in html_lc:
            fmts = [f for f in (".webp", ".avif") if f in html_lc]
            out.append(DetectedTech(CAT_IMAGE, "Modern image formats", 70, [f"Serves {', '.join(x.strip('.').upper() for x in fmts)}"]))

    def _detect_analytics(self, html_lc: str, out: List[DetectedTech]) -> None:
        checks = [
            ("googletagmanager.com/gtm" in html_lc or "gtm-" in html_lc, "Google Tag Manager", "GTM container script"),
            ("googletagmanager.com/gtag" in html_lc or "gtag(" in html_lc or "google-analytics.com" in html_lc, "Google Analytics", "gtag/GA script"),
            ("plausible.io" in html_lc, "Plausible", "Plausible script"),
            ("cdn.usefathom.com" in html_lc, "Fathom", "Fathom script"),
            ("static.hotjar.com" in html_lc or "hotjar" in html_lc, "Hotjar", "Hotjar script"),
            ("cdn.segment.com" in html_lc, "Segment", "Segment script"),
            ("connect.facebook.net" in html_lc and "fbq(" in html_lc, "Meta Pixel", "Facebook Pixel script"),
            ("mixpanel" in html_lc, "Mixpanel", "Mixpanel script"),
        ]
        for cond, name, why in checks:
            if cond:
                out.append(DetectedTech(CAT_ANALYTICS, name, 80, [why]))

    def _detect_fonts_styling(self, html_lc: str, out: List[DetectedTech]) -> None:
        if "fonts.googleapis.com" in html_lc or "fonts.gstatic.com" in html_lc:
            out.append(DetectedTech(CAT_FONTS, "Google Fonts", 82, ["Google Fonts stylesheet/preconnect"]))
        if "use.typekit" in html_lc or "typekit.net" in html_lc:
            out.append(DetectedTech(CAT_FONTS, "Adobe Fonts (Typekit)", 78, ["Typekit stylesheet"]))
        # Tailwind's atomic classes commonly co-occur; low-confidence heuristic.
        if re.search(r'class="[^"]*\b(flex|grid|text-\w+|bg-\w+|px-\d|py-\d)\b', html_lc):
            out.append(DetectedTech(CAT_STYLING, "Tailwind CSS", 60, ["Atomic utility class patterns in markup"]))

    def _detect_rendering(self, s: SiteSignals, html_lc: str, framework: Optional[str], cms: Optional[str], out: List[DetectedTech]) -> Optional[str]:
        body_text = re.sub(r"<[^>]+>", " ", html_lc)
        has_content = len(body_text.split()) > 60
        if "__next_data__" in html_lc or "__nuxt__" in html_lc:
            label = "Server-Side Rendering / Static Generation"
            out.append(DetectedTech(CAT_RENDERING, label, 80, ["Hydration payload with server-rendered HTML"]))
            return "SSR/SSG"
        if cms in {"WordPress", "Drupal", "Joomla", "Magento", "Shopify", "Squarespace", "Wix", "Webflow"}:
            out.append(DetectedTech(CAT_RENDERING, "Server-rendered (CMS)", 78, [f"{cms} renders HTML server-side"]))
            return "Server-rendered"
        if framework and not has_content and ('id="__next"' in html_lc or "data-reactroot" in html_lc):
            out.append(DetectedTech(CAT_RENDERING, "Client-Side Rendering", 65, ["Framework app shell with little server HTML"]))
            return "CSR"
        if has_content:
            out.append(DetectedTech(CAT_RENDERING, "Server-rendered HTML", 60, ["Substantive server-rendered content present"]))
            return "Server-rendered"
        return None

    def _detect_seo_signals(self, s: SiteSignals, html: str, html_lc: str, out: List[DetectedTech]) -> None:
        if "<title" in html_lc:
            out.append(DetectedTech(CAT_SEO, "Title tag", 90, ["<title> present"]))
        if 'name="description"' in html_lc:
            out.append(DetectedTech(CAT_SEO, "Meta description", 88, ['<meta name="description"> present']))
        if 'rel="canonical"' in html_lc:
            out.append(DetectedTech(CAT_SEO, "Canonical tag", 86, ['<link rel="canonical"> present']))
        if 'property="og:' in html_lc:
            out.append(DetectedTech(CAT_SEO, "Open Graph", 84, ["og: meta tags present"]))
        if 'name="twitter:' in html_lc:
            out.append(DetectedTech(CAT_SEO, "Twitter Cards", 80, ["twitter: meta tags present"]))
        if 'name="robots"' in html_lc:
            out.append(DetectedTech(CAT_SEO, "Meta robots", 78, ['<meta name="robots"> present']))
        if 'hreflang=' in html_lc:
            out.append(DetectedTech(CAT_SEO, "hreflang", 76, ["hreflang alternate links present"]))
        if "application/ld+json" in html_lc:
            types = self._jsonld_types(html)
            ev = ["JSON-LD structured data present"]
            if types:
                ev.append("Types: " + ", ".join(sorted(types)[:6]))
            out.append(DetectedTech(CAT_SCHEMA, "JSON-LD Schema.org", 85, ev))
        if s.robots_txt is not None:
            out.append(DetectedTech(CAT_ROBOTS, "robots.txt", 90, ["robots.txt served"]))
        if s.has_sitemap:
            out.append(DetectedTech(CAT_SITEMAP, "XML sitemap", 88, ["sitemap.xml reachable or declared in robots.txt"]))

    def _detect_caching_security(self, s: SiteSignals, out: List[DetectedTech]) -> None:
        cache = s.header("cache-control")
        if cache:
            out.append(DetectedTech(CAT_CACHING, "Cache-Control", 70, [f"Cache-Control: {cache[:60]}"]))
        enc = s.header("content-encoding")
        if enc:
            out.append(DetectedTech(CAT_CACHING, f"{enc.upper()} compression", 72, [f"Content-Encoding: {enc}"]))
        scheme = urlparse(s.final_url or s.url).scheme
        if scheme == "https":
            out.append(DetectedTech(CAT_SECURITY, "HTTPS", 95, ["Served over HTTPS"]))
        if s.header("strict-transport-security"):
            out.append(DetectedTech(CAT_SECURITY, "HSTS", 80, ["Strict-Transport-Security header"]))
        if s.header("content-security-policy"):
            out.append(DetectedTech(CAT_SECURITY, "Content Security Policy", 78, ["CSP header present"]))

    # -- scores -------------------------------------------------------------

    def _scores(self, s: SiteSignals, html: str, html_lc: str, techs: List[DetectedTech]) -> Dict[str, int]:
        names = {t.name for t in techs}

        def pct(points: int, total: int) -> int:
            return int(round(100 * points / total)) if total else 0

        # SEO readiness.
        seo_have = sum(1 for n in ("Title tag", "Meta description", "Canonical tag",
                                   "Open Graph", "Meta robots", "JSON-LD Schema.org",
                                   "XML sitemap", "robots.txt") if n in names)
        seo = pct(seo_have, 8)

        # Performance readiness.
        perf_points = 0
        if any(t.category == CAT_CDN for t in techs):
            perf_points += 1
        if s.header("content-encoding"):
            perf_points += 1
        if s.header("cache-control"):
            perf_points += 1
        if any(t.category == CAT_IMAGE for t in techs):
            perf_points += 1
        if "rel=\"preconnect\"" in html_lc or "rel=\"preload\"" in html_lc:
            perf_points += 1
        performance = pct(perf_points, 5)

        # Accessibility (limited to what static HTML reveals).
        acc_points = 0
        if re.search(r"<html[^>]*\blang=", html_lc):
            acc_points += 1
        if 'name="viewport"' in html_lc:
            acc_points += 1
        imgs = re.findall(r"<img\b[^>]*>", html_lc)
        if imgs:
            with_alt = sum(1 for i in imgs if "alt=" in i)
            if with_alt / max(len(imgs), 1) >= 0.8:
                acc_points += 1
        else:
            acc_points += 1  # no images -> not penalized
        if any(tag in html_lc for tag in ("<main", "<nav", "<header", "role=")):
            acc_points += 1
        accessibility = pct(acc_points, 4)

        # Security.
        sec_points = 0
        if urlparse(s.final_url or s.url).scheme == "https":
            sec_points += 1
        if s.header("strict-transport-security"):
            sec_points += 1
        if s.header("content-security-policy"):
            sec_points += 1
        if s.header("x-content-type-options"):
            sec_points += 1
        if s.header("x-frame-options") or "frame-ancestors" in s.header("content-security-policy").lower():
            sec_points += 1
        security = pct(sec_points, 5)

        # Indexability.
        robots_txt = (s.robots_txt or "")
        blocked = bool(re.search(r"(?im)^\s*disallow:\s*/\s*$", robots_txt)) and "user-agent: *" in robots_txt.lower()
        meta_noindex = 'name="robots"' in html_lc and "noindex" in html_lc
        indexability = 100
        if blocked:
            indexability -= 60
        if meta_noindex:
            indexability -= 40
        if not s.has_sitemap:
            indexability -= 10
        indexability = max(0, indexability)

        # Framework health = confidence of the strongest framework/cms signal.
        fw = [t.confidence for t in techs if t.category in (CAT_FRAMEWORK, CAT_CMS)]
        framework_health = max(fw) if fw else (60 if s.status_code == 200 else 30)

        return {
            "framework_health": framework_health,
            "seo_readiness": seo,
            "performance_readiness": performance,
            "accessibility": accessibility,
            "security": security,
            "indexability": indexability,
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _meta_generator(html: str) -> Optional[str]:
        m = re.search(r'<meta[^>]+name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*name=["\']generator["\']', html, re.I)
        return m.group(1).strip() if m else None

    @staticmethod
    def _version(text: str, pattern: str) -> Optional[str]:
        m = re.search(pattern, text or "", re.I)
        return m.group(1) if m else None

    @staticmethod
    def _jsonld_types(html: str) -> set:
        types = set()
        for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S):
            for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', block):
                types.add(t)
        return types

    @staticmethod
    def _hash(s: SiteSignals) -> str:
        h = hashlib.sha256()
        h.update((s.header("server") + "|" + s.header("x-powered-by") + "|").encode("utf-8", "ignore"))
        # Only structural markers, not full HTML, so trivial content edits don't
        # invalidate an otherwise-identical stack (Learning: never relearn same).
        markers = []
        for needle in ("/_next/", "__next_data__", "wp-content", "cdn.shopify.com",
                       "__nuxt__", "ng-version", "astro-island", "application/ld+json",
                       "res.cloudinary.com", "googletagmanager.com"):
            if needle in (s.html or "").lower():
                markers.append(needle)
        h.update("|".join(markers).encode("utf-8", "ignore"))
        return h.hexdigest()
