"""Universal repository architecture detection and patch safety rules."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from app.models.repo_agent import SeoCodeIssueType, SeoCodePatchType
from app.repo_agent.scanner import (
    IGNORE_DIRS,
    MAX_FILE_SIZE_BYTES,
    has_jsonld,
    has_metadata_export,
    is_client_component,
    read_repo_text,
)


ARCHITECTURE_EXTENSIONS = {
    ".astro",
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".liquid",
    ".md",
    ".mdx",
    ".mjs",
    ".php",
    ".svelte",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

# Files/areas the SEO engine must NEVER modify. These enforce the product rule
# that the agent only makes SEO-safe changes and never touches UI, business
# logic, authentication, payments, CRM, or the database. A patch whose path
# matches any of these is hard-rejected as unsafe_skip before any generation.
PROTECTED_TOKENS = (
    "checkout", "payment", "billing", "invoice", "subscription", "pricing/checkout",
    "cart", "auth", "login", "signin", "sign-in", "signup", "sign-up", "logout",
    "oauth", "password", "session", "crm", "admin", "dashboard", "account",
    "middleware", "migration", "migrations", "schema.prisma", "database", "prisma",
    ".generated.", "__generated__",
)
# Path *segments* (exact directory/file names) that are protected. Segment
# matching avoids false positives from substrings inside benign SEO filenames.
PROTECTED_SEGMENTS = {
    "api", "db", "auth", "admin", "crm", "payments", "checkout", "migrations",
    "webhooks", "hooks", "middleware",
}

CONFIG_NAMES = {
    "astro.config.mjs",
    "astro.config.ts",
    "composer.json",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "nuxt.config.js",
    "nuxt.config.ts",
    "package.json",
    "svelte.config.js",
    "theme.liquid",
    "vite.config.js",
    "vite.config.ts",
}

LANGUAGE_BY_EXTENSION = {
    ".astro": "Astro",
    ".css": "CSS",
    ".html": "HTML",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".json": "JSON",
    ".liquid": "Liquid",
    ".md": "Markdown",
    ".mdx": "MDX",
    ".mjs": "JavaScript",
    ".php": "PHP",
    ".svelte": "Svelte",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".txt": "Text",
    ".vue": "Vue",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
}


@dataclass
class ArchitectureProfileData:
    detected_stack: str
    framework: str
    router_type: Optional[str]
    package_manager: Optional[str]
    languages: dict
    route_map: list[dict]
    content_sources: list[dict]
    blog_system: dict
    metadata_strategy: dict
    schema_strategy: dict
    sitemap_strategy: dict
    robots_strategy: dict
    cms_strategy: dict
    client_server_boundaries: dict
    safe_patch_zones: list[dict]
    manual_review_zones: list[dict]
    unsafe_patch_zones: list[dict]
    confidence_score: float
    detection_notes: list[dict]

    def as_record(self) -> dict:
        return {
            "detected_stack": self.detected_stack,
            "framework": self.framework,
            "router_type": self.router_type,
            "package_manager": self.package_manager,
            "languages": self.languages,
            "route_map": self.route_map,
            "content_sources": self.content_sources,
            "blog_system": self.blog_system,
            "metadata_strategy": self.metadata_strategy,
            "schema_strategy": self.schema_strategy,
            "sitemap_strategy": self.sitemap_strategy,
            "robots_strategy": self.robots_strategy,
            "cms_strategy": self.cms_strategy,
            "client_server_boundaries": self.client_server_boundaries,
            "safe_patch_zones": self.safe_patch_zones,
            "manual_review_zones": self.manual_review_zones,
            "unsafe_patch_zones": self.unsafe_patch_zones,
            "confidence_score": self.confidence_score,
            "detection_notes": self.detection_notes,
        }


@dataclass
class PatchSafetyDecision:
    classification: str
    reason: str
    confidence: float
    zone: Optional[dict] = None

    @property
    def is_safe(self) -> bool:
        return self.classification == "safe_patch"


class RepoArchitectureDetector:
    """Detect broad website repo architecture and safe SEO patch zones."""

    def detect(self, root: Path) -> ArchitectureProfileData:
        files = self._collect_files(root)
        rel_paths = {path.relative_to(root).as_posix() for path in files}
        package = self._read_package(root)
        deps = self._package_dependencies(package)
        detected_stack, framework, router_type, confidence, notes = self._detect_stack(root, rel_paths, deps)
        route_map = self._route_map(root, files, detected_stack)
        content_sources = self._content_sources(root, files, detected_stack)
        blog_system = self._blog_system(route_map, content_sources, detected_stack)
        metadata_strategy = self._metadata_strategy(root, files, detected_stack)
        schema_strategy = self._schema_strategy(root, files, detected_stack)
        sitemap_strategy = self._sitemap_strategy(root, rel_paths, detected_stack)
        robots_strategy = self._robots_strategy(root, rel_paths, detected_stack)
        cms_strategy = self._cms_strategy(root, files, detected_stack)
        boundaries = self._client_server_boundaries(root, files)
        safe_zones, manual_zones, unsafe_zones = self._patch_zones(
            root=root,
            files=files,
            detected_stack=detected_stack,
            route_map=route_map,
            blog_system=blog_system,
            metadata_strategy=metadata_strategy,
            schema_strategy=schema_strategy,
            sitemap_strategy=sitemap_strategy,
            robots_strategy=robots_strategy,
            boundaries=boundaries,
            confidence=confidence,
        )
        return ArchitectureProfileData(
            detected_stack=detected_stack,
            framework=framework,
            router_type=router_type,
            package_manager=self._package_manager(root),
            languages=self._languages(files),
            route_map=route_map,
            content_sources=content_sources,
            blog_system=blog_system,
            metadata_strategy=metadata_strategy,
            schema_strategy=schema_strategy,
            sitemap_strategy=sitemap_strategy,
            robots_strategy=robots_strategy,
            cms_strategy=cms_strategy,
            client_server_boundaries=boundaries,
            safe_patch_zones=safe_zones,
            manual_review_zones=manual_zones,
            unsafe_patch_zones=unsafe_zones,
            confidence_score=confidence,
            detection_notes=notes,
        )

    def classify_patch(
        self,
        profile: ArchitectureProfileData | object | dict,
        *,
        file_path: str,
        patch_type: SeoCodePatchType,
        issue_type: SeoCodeIssueType,
        original_content: str = "",
    ) -> PatchSafetyDecision:
        data = _profile_dict(profile)
        normalized = file_path.replace("\\", "/")
        if self._is_unsafe_path(normalized):
            return PatchSafetyDecision(
                "unsafe_skip",
                "Patch target is generated, minified, payment/checkout, or otherwise outside safe SEO zones.",
                0.95,
            )
        if data.get("confidence_score", 0) < 0.5 or data.get("detected_stack") == "unknown_custom":
            return PatchSafetyDecision(
                "unsafe_skip",
                "Repository architecture confidence is too low for automated patch generation.",
                float(data.get("confidence_score") or 0),
            )
        if patch_type in {SeoCodePatchType.metadata_update, SeoCodePatchType.og_twitter_addition} and is_client_component(original_content):
            return PatchSafetyDecision("unsafe_skip", "Next.js metadata cannot be exported from a client component.", 0.98)
        if patch_type == SeoCodePatchType.schema_addition and (is_client_component(original_content) or has_jsonld(original_content)):
            return PatchSafetyDecision(
                "manual_review",
                "Schema patch is blocked because the target is a client component or already has JSON-LD.",
                0.86,
            )
        if patch_type == SeoCodePatchType.sitemap_update and data.get("sitemap_strategy", {}).get("rich_dynamic"):
            return PatchSafetyDecision(
                "manual_review",
                "Existing sitemap appears rich or dynamic; replacing it is not safe.",
                0.9,
            )
        if patch_type == SeoCodePatchType.robots_update and data.get("robots_strategy", {}).get("exists"):
            return PatchSafetyDecision("manual_review", "Existing robots implementation should not be overwritten.", 0.9)
        stack = data.get("detected_stack")
        if stack in {"wordpress", "shopify"}:
            return PatchSafetyDecision(
                "manual_review",
                f"{stack} template edits can affect live theme behavior and require manual review.",
                0.82,
            )

        for zone in data.get("safe_patch_zones") or []:
            if self._zone_matches(zone, normalized, patch_type):
                return PatchSafetyDecision("safe_patch", zone.get("reason", "Patch matches a safe SEO zone."), zone.get("confidence", 0.8), zone)
        for zone in data.get("manual_review_zones") or []:
            if self._zone_matches(zone, normalized, patch_type):
                return PatchSafetyDecision(
                    "manual_review",
                    zone.get("reason", "Patch target requires manual review."),
                    zone.get("confidence", 0.7),
                    zone,
                )
        for zone in data.get("unsafe_patch_zones") or []:
            if self._zone_matches(zone, normalized, patch_type):
                return PatchSafetyDecision(
                    "unsafe_skip",
                    zone.get("reason", "Patch target is unsafe."),
                    zone.get("confidence", 0.8),
                    zone,
                )

        if normalized.endswith(".html") and patch_type in {SeoCodePatchType.metadata_update, SeoCodePatchType.og_twitter_addition}:
            return PatchSafetyDecision("safe_patch", "Plain HTML head metadata can be updated without layout changes.", 0.82)
        return PatchSafetyDecision("manual_review", "No high-confidence safe patch zone matched this change.", 0.55)

    def patch_safety_summary(self, profile: ArchitectureProfileData | object | dict) -> dict:
        data = _profile_dict(profile)
        reasons = []
        for zone in (data.get("manual_review_zones") or []) + (data.get("unsafe_patch_zones") or []):
            reason = zone.get("reason")
            if reason and reason not in reasons:
                reasons.append(reason)
        return {
            "detected_stack": data.get("detected_stack"),
            "framework": data.get("framework"),
            "confidence_score": data.get("confidence_score", 0),
            "blog_system": data.get("blog_system") or {},
            "metadata_strategy": data.get("metadata_strategy") or {},
            "schema_strategy": data.get("schema_strategy") or {},
            "sitemap_strategy": data.get("sitemap_strategy") or {},
            "robots_strategy": data.get("robots_strategy") or {},
            "safe_patch_count": len(data.get("safe_patch_zones") or []),
            "manual_review_count": len(data.get("manual_review_zones") or []),
            "unsafe_skipped_count": len(data.get("unsafe_patch_zones") or []),
            "top_safety_reasons": reasons[:8],
        }

    def architecture_file_paths(self, profile: ArchitectureProfileData | object | dict) -> list[str]:
        data = _profile_dict(profile)
        paths = set()
        for route in data.get("route_map") or []:
            if route.get("file_path"):
                paths.add(route["file_path"])
            if route.get("seo_control_location"):
                paths.add(route["seo_control_location"])
        for source in data.get("content_sources") or []:
            if source.get("file_path"):
                paths.add(source["file_path"])
        for strategy_key in ["metadata_strategy", "schema_strategy", "sitemap_strategy", "robots_strategy"]:
            strategy = data.get(strategy_key) or {}
            for item in strategy.get("files") or []:
                paths.add(item)
            if strategy.get("file_path"):
                paths.add(strategy["file_path"])
        for zone_key in ["safe_patch_zones", "manual_review_zones", "unsafe_patch_zones"]:
            for zone in data.get(zone_key) or []:
                if zone.get("file_path"):
                    paths.add(zone["file_path"])
        return sorted(path for path in paths if path)

    def _collect_files(self, root: Path) -> list[Path]:
        files = []
        for path in root.rglob("*"):
            if self._ignored(path, root) or path.is_symlink() or not path.is_file():
                continue
            if path.name not in CONFIG_NAMES and path.suffix.lower() not in ARCHITECTURE_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue
            files.append(path)
        return sorted(files, key=lambda value: value.relative_to(root).as_posix())

    def _ignored(self, path: Path, root: Path) -> bool:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return True
        return any(part in IGNORE_DIRS for part in parts)

    def _read_package(self, root: Path) -> dict:
        package_path = root / "package.json"
        if not package_path.exists():
            return {}
        try:
            return json.loads(read_repo_text(package_path))
        except (json.JSONDecodeError, OSError):
            return {}

    def _package_dependencies(self, package: dict) -> set[str]:
        deps = {}
        deps.update(package.get("dependencies") or {})
        deps.update(package.get("devDependencies") or {})
        return set(deps)

    def _detect_stack(self, root: Path, rel_paths: set[str], deps: set[str]) -> tuple[str, str, Optional[str], float, list[dict]]:
        notes = []
        def note(kind: str, value: str):
            notes.append({"kind": kind, "value": value})

        has_next = "next" in deps or any(path.startswith("next.config.") for path in rel_paths)
        has_app = any(path == "app/page.tsx" or path == "app/layout.tsx" or re.match(r"app/.+/page\.(tsx|jsx|ts|js|mdx)$", path) for path in rel_paths)
        has_pages = any(path.startswith("pages/") and path.split("/")[-1].startswith("_") is False for path in rel_paths)
        if "layout/theme.liquid" in rel_paths or "templates/index.liquid" in rel_paths or "config/settings_schema.json" in rel_paths:
            note("stack", "Shopify Liquid theme markers found.")
            return "shopify", "shopify", "theme", 0.92, notes
        if "functions.php" in rel_paths or any(path.startswith("wp-content/themes/") for path in rel_paths):
            note("stack", "WordPress theme/plugin markers found.")
            return "wordpress", "wordpress", "theme", 0.9, notes
        if "composer.json" in rel_paths and (root / "routes" / "web.php").exists() and (root / "resources" / "views").exists():
            note("stack", "Laravel routes and Blade views found.")
            return "laravel", "laravel", "php_routes", 0.88, notes
        if has_next and has_app:
            note("stack", "Next.js App Router markers found.")
            return "nextjs_app_router", "nextjs", "app_router", 0.94, notes
        if has_next and has_pages:
            note("stack", "Next.js Pages Router markers found.")
            return "nextjs_pages_router", "nextjs", "pages_router", 0.9, notes
        if "astro" in deps or any(path.startswith("astro.config.") for path in rel_paths):
            note("stack", "Astro config or dependency found.")
            return "astro", "astro", "file_routes", 0.88, notes
        if "nuxt" in deps or any(path.startswith("nuxt.config.") for path in rel_paths):
            note("stack", "Nuxt config or dependency found.")
            return "nuxt", "nuxt", "pages_router", 0.88, notes
        if "@sveltejs/kit" in deps or "svelte.config.js" in rel_paths:
            note("stack", "SvelteKit config or dependency found.")
            return "sveltekit", "sveltekit", "file_routes", 0.88, notes
        if "vite" in deps or any(path.startswith("vite.config.") for path in rel_paths):
            note("stack", "Vite config or dependency found.")
            return "react_vite", "react", "client_router", 0.78, notes
        markdown_count = len([path for path in rel_paths if path.endswith((".md", ".mdx"))])
        if markdown_count >= 2 and any(path.startswith(("content/", "posts/", "blog/", "blogs/")) for path in rel_paths):
            note("stack", "Markdown static content folders found.")
            return "markdown_static", "static_markdown", "content_routes", 0.78, notes
        html_count = len([path for path in rel_paths if path.endswith(".html")])
        if html_count and not deps:
            note("stack", "Plain HTML files found without framework dependencies.")
            return "plain_static", "plain_static", "html_files", 0.75, notes
        if has_app or has_pages or deps:
            note("stack", "Repository has web app markers but no high-confidence supported framework match.")
            return "unknown_custom", "unknown", None, 0.42, notes
        note("stack", "No known website architecture markers found.")
        return "unknown_custom", "unknown", None, 0.25, notes

    def _route_map(self, root: Path, files: Iterable[Path], detected_stack: str) -> list[dict]:
        routes = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            route = None
            route_type = "page"
            if detected_stack == "nextjs_app_router" and re.match(r"app/(?:.+/)?page\.(tsx|jsx|ts|js|mdx)$", rel):
                route = self._next_app_route(rel)
            elif detected_stack == "nextjs_pages_router" and rel.startswith("pages/") and path.suffix.lower() in {".tsx", ".jsx", ".ts", ".js", ".mdx"}:
                route = self._pages_route(rel, prefix="pages")
                if route and route.startswith("/api/"):
                    route = None
            elif detected_stack == "astro" and rel.startswith("src/pages/"):
                route = self._pages_route(rel, prefix="src/pages")
            elif detected_stack == "nuxt" and rel.startswith("pages/"):
                route = self._pages_route(rel, prefix="pages")
            elif detected_stack == "sveltekit" and rel.startswith("src/routes/") and "/+page." in rel:
                route = "/" + rel.removeprefix("src/routes/").split("/+page.", 1)[0].strip("/")
            elif detected_stack in {"plain_static", "react_vite"} and rel.endswith(".html"):
                route = self._html_route(rel)
            elif detected_stack == "wordpress" and path.suffix.lower() == ".php":
                route = self._wordpress_template_route(rel)
                route_type = "template"
            elif detected_stack == "shopify" and rel.startswith("templates/"):
                route = "/" + Path(rel).stem.replace(".", "/")
                route_type = "template"
            if route:
                routes.append(
                    {
                        "route_path": route if route.startswith("/") else f"/{route}",
                        "file_path": rel,
                        "route_type": route_type,
                        "dynamic": "[" in route or ":" in route or "$" in route,
                        "confidence": 0.88 if detected_stack.startswith("nextjs") else 0.72,
                        "seo_control_location": self._seo_control_location(root, rel, detected_stack),
                    }
                )
        return sorted(routes, key=lambda item: (item["route_path"].count("/"), item["route_path"], item["file_path"]))

    def _next_app_route(self, rel: str) -> str:
        route = rel.removeprefix("app/").rsplit("/page.", 1)[0]
        route = "" if route.startswith("page.") else route
        return "/" if not route else "/" + route.strip("/")

    def _pages_route(self, rel: str, prefix: str) -> Optional[str]:
        clean = rel.removeprefix(prefix + "/")
        stem = re.sub(r"\.(tsx|jsx|ts|js|mdx|astro|vue)$", "", clean)
        if stem in {"_app", "_document", "_error"} or stem.split("/")[0] in {"_app", "_document"}:
            return None
        if stem.endswith("/index"):
            stem = stem.removesuffix("/index")
        if stem == "index":
            return "/"
        return "/" + stem.strip("/")

    def _html_route(self, rel: str) -> str:
        clean = rel.removeprefix("public/")
        if clean == "index.html":
            return "/"
        return "/" + clean.removesuffix(".html").removesuffix("/index").strip("/")

    def _wordpress_template_route(self, rel: str) -> str:
        name = Path(rel).stem
        if name in {"front-page", "home", "index"}:
            return "/"
        if name == "single":
            return "/{post}"
        if name == "archive":
            return "/archive"
        return f"/template/{name}"

    def _seo_control_location(self, root: Path, rel: str, detected_stack: str) -> Optional[str]:
        if detected_stack == "nextjs_app_router":
            content = _safe_read(root / rel)
            if has_metadata_export(content) and not is_client_component(content):
                return rel
            if rel.endswith("/page.tsx"):
                layout = rel.removesuffix("/page.tsx") + "/layout.tsx"
                if (root / layout).exists():
                    return layout
            if (root / "app/layout.tsx").exists():
                return "app/layout.tsx"
        if detected_stack in {"plain_static", "react_vite"} and rel.endswith(".html"):
            return rel
        return rel

    def _content_sources(self, root: Path, files: Iterable[Path], detected_stack: str) -> list[dict]:
        sources = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            lower = rel.lower()
            content = _safe_read(path)
            if path.suffix.lower() in {".md", ".mdx"} and re.search(r"(^|/)(content|posts|blog|blogs)(/|$)", lower):
                sources.append(
                    {
                        "source_type": "mdx" if path.suffix.lower() == ".mdx" else "markdown",
                        "file_path": rel,
                        "purpose": "blog_content" if "blog" in lower or "post" in lower else "static_content",
                        "confidence": 0.84,
                    }
                )
            elif path.suffix.lower() in {".ts", ".tsx", ".js", ".jsx"} and "blog" in lower:
                is_data_file = rel.startswith(("lib/", "src/lib/", "data/", "src/data/", "content/", "src/content/"))
                if re.search(r"export\s+const\s+(blogs|blogPosts|posts)\b", content) or (
                    is_data_file and "slug" in content and "title" in content
                ):
                    sources.append(
                        {
                            "source_type": "static_ts_array",
                            "file_path": rel,
                            "purpose": "blog_content",
                            "export_name": self._blog_export_name(content),
                            "confidence": 0.9,
                        }
                    )
            elif detected_stack == "wordpress" and path.suffix.lower() == ".php" and any(token in lower for token in ["single", "archive", "content"]):
                sources.append({"source_type": "wordpress_template", "file_path": rel, "purpose": "cms_template", "confidence": 0.75})
            elif detected_stack == "shopify" and path.suffix.lower() == ".liquid" and ("article" in lower or "blog" in lower):
                sources.append({"source_type": "shopify_liquid", "file_path": rel, "purpose": "cms_template", "confidence": 0.75})
            elif "fetch(" in content and re.search(r"(cms|contentful|sanity|strapi|wordpress|wp-json)", content, flags=re.I):
                sources.append({"source_type": "cms_fetcher", "file_path": rel, "purpose": "external_cms", "confidence": 0.65})
        return sources

    def _blog_export_name(self, content: str) -> Optional[str]:
        match = re.search(r"export\s+const\s+(blogs|blogPosts|posts)\b", content)
        return match.group(1) if match else None

    def _blog_system(self, route_map: list[dict], content_sources: list[dict], detected_stack: str) -> dict:
        blog_routes = [route for route in route_map if re.match(r"^/blogs?(?:/|$)", route["route_path"])]
        static_source = next((source for source in content_sources if source["source_type"] == "static_ts_array"), None)
        mdx_source = next((source for source in content_sources if source["source_type"] == "mdx"), None)
        md_source = next((source for source in content_sources if source["source_type"] == "markdown"), None)
        cms_source = next((source for source in content_sources if source["source_type"] in {"cms_fetcher", "wordpress_template", "shopify_liquid"}), None)
        if static_source:
            return {
                "exists": bool(blog_routes),
                "route_path": self._first_blog_index(blog_routes),
                "detail_route": self._first_blog_detail(blog_routes),
                "content_source_type": "static_ts_array",
                "content_source_file": static_source["file_path"],
                "insertion_strategy": "append_to_static_ts_array",
                "confidence": 0.92,
            }
        if mdx_source or md_source:
            source = mdx_source or md_source
            return {
                "exists": True,
                "route_path": self._first_blog_index(blog_routes),
                "detail_route": self._first_blog_detail(blog_routes),
                "content_source_type": source["source_type"],
                "content_source_file": source["file_path"],
                "insertion_strategy": "create_mdx_file" if source["source_type"] == "mdx" else "create_markdown_file",
                "confidence": 0.86,
            }
        if detected_stack == "wordpress":
            return {"exists": True, "content_source_type": "wordpress", "insertion_strategy": "wordpress_draft", "confidence": 0.82}
        if detected_stack == "shopify":
            return {
                "exists": bool(cms_source),
                "content_source_type": "shopify",
                "insertion_strategy": "shopify_article_draft_manual_review",
                "confidence": 0.72,
            }
        if cms_source:
            return {
                "exists": bool(blog_routes),
                "content_source_type": "cms_fetcher",
                "content_source_file": cms_source["file_path"],
                "insertion_strategy": "cms_only_manual_review",
                "confidence": 0.62,
            }
        if detected_stack == "plain_static" and blog_routes:
            return {
                "exists": True,
                "route_path": self._first_blog_index(blog_routes),
                "content_source_type": "html",
                "insertion_strategy": "html_file_create",
                "confidence": 0.7,
            }
        return {"exists": bool(blog_routes), "insertion_strategy": "unknown_manual_review", "confidence": 0.4}

    def _first_blog_index(self, blog_routes: list[dict]) -> Optional[str]:
        for route in blog_routes:
            if route["route_path"] in {"/blog", "/blogs"}:
                return route["route_path"]
        return blog_routes[0]["route_path"] if blog_routes else None

    def _first_blog_detail(self, blog_routes: list[dict]) -> Optional[str]:
        for route in blog_routes:
            if route.get("dynamic"):
                return route["route_path"]
        return None

    def _metadata_strategy(self, root: Path, files: Iterable[Path], detected_stack: str) -> dict:
        strategy = "unknown"
        strategy_files = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            content = _safe_read(path)
            if has_metadata_export(content):
                strategy = "next_metadata_export" if "generateMetadata" not in content else "next_generate_metadata"
                strategy_files.append(rel)
            elif "next/head" in content or re.search(r"<Head[\s>]", content):
                strategy = "next_head_component"
                strategy_files.append(rel)
            elif "react-helmet" in content or "Helmet" in content:
                strategy = "react_helmet"
                strategy_files.append(rel)
            elif path.suffix.lower() == ".html" and re.search(r"<title>|<meta\s+name=[\"']description", content, flags=re.I):
                if strategy == "unknown" or detected_stack in {"plain_static", "react_vite"}:
                    strategy = "plain_html_head"
                    strategy_files.append(rel)
            elif detected_stack == "wordpress" and "wp_head" in content:
                strategy = "wordpress_wp_head"
                strategy_files.append(rel)
            elif detected_stack == "shopify" and ("{{ page_title" in content or "og:" in content):
                strategy = "shopify_theme_meta"
                strategy_files.append(rel)
            elif detected_stack == "astro" and path.suffix.lower() == ".astro" and "<title>" in content:
                strategy = "astro_head"
                strategy_files.append(rel)
            elif detected_stack == "nuxt" and ("useHead(" in content or "head()" in content):
                strategy = "nuxt_use_head"
                strategy_files.append(rel)
            elif detected_stack == "sveltekit" and "<svelte:head>" in content:
                strategy = "svelte_head"
                strategy_files.append(rel)
        return {"strategy": strategy, "files": sorted(set(strategy_files)), "confidence": 0.88 if strategy != "unknown" else 0.35}

    def _schema_strategy(self, root: Path, files: Iterable[Path], detected_stack: str) -> dict:
        schema_files = []
        helper_files = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            content = _safe_read(path)
            if has_jsonld(content):
                schema_files.append(rel)
            if "jsonld" in rel.lower() or "schema" in rel.lower():
                helper_files.append(rel)
        if detected_stack == "wordpress" and any("schema" in path.lower() for path in schema_files + helper_files):
            strategy = "wordpress_schema_plugin_or_theme"
        elif detected_stack == "shopify" and schema_files:
            strategy = "shopify_structured_data_snippet"
        elif helper_files:
            strategy = "jsonld_helper_component"
        elif schema_files:
            strategy = "inline_jsonld"
        else:
            strategy = "unknown"
        return {
            "strategy": strategy,
            "files": sorted(set(schema_files + helper_files)),
            "duplicate_risk": len(schema_files) > 1,
            "confidence": 0.86 if strategy != "unknown" else 0.35,
        }

    def _sitemap_strategy(self, root: Path, rel_paths: set[str], detected_stack: str) -> dict:
        candidates = ["app/sitemap.ts", "public/sitemap.xml", "sitemap.xml"]
        found = next((path for path in candidates if path in rel_paths), None)
        if detected_stack == "wordpress":
            return {"exists": True, "strategy": "wordpress_platform_or_plugin", "file_path": found, "rich_dynamic": True, "confidence": 0.75}
        if detected_stack == "shopify":
            return {"exists": True, "strategy": "shopify_platform_generated", "file_path": None, "rich_dynamic": True, "confidence": 0.78}
        if not found:
            return {"exists": False, "strategy": "missing", "file_path": None, "rich_dynamic": False, "confidence": 0.7}
        content = _safe_read(root / found)
        rich = bool(re.search(r"(map|flatMap|fetch|import\s+\{|\.\.\.|Promise|async|products|blogs|posts|categories)", content))
        strategy = "next_app_dynamic" if found == "app/sitemap.ts" else "static_xml"
        return {"exists": True, "strategy": strategy, "file_path": found, "rich_dynamic": rich, "confidence": 0.88}

    def _robots_strategy(self, root: Path, rel_paths: set[str], detected_stack: str) -> dict:
        candidates = ["app/robots.ts", "public/robots.txt", "robots.txt"]
        found = next((path for path in candidates if path in rel_paths), None)
        if detected_stack == "shopify":
            return {"exists": True, "strategy": "shopify_platform_generated", "file_path": None, "rich_dynamic": True, "confidence": 0.78}
        if not found:
            return {"exists": False, "strategy": "missing", "file_path": None, "rich_dynamic": False, "confidence": 0.7}
        content = _safe_read(root / found)
        rich = bool(re.search(r"(process\.env|sitemap|host|rules|async|fetch|\.\.\.)", content, flags=re.I))
        strategy = "next_app_dynamic" if found == "app/robots.ts" else "static_txt"
        return {"exists": True, "strategy": strategy, "file_path": found, "rich_dynamic": rich, "confidence": 0.88}

    def _cms_strategy(self, root: Path, files: Iterable[Path], detected_stack: str) -> dict:
        if detected_stack == "wordpress":
            return {"strategy": "wordpress", "editable_mode": "draft_api_or_manual_theme_review", "confidence": 0.86}
        if detected_stack == "shopify":
            return {"strategy": "shopify", "editable_mode": "manual_theme_review", "confidence": 0.82}
        cms_files = []
        for path in files:
            content = _safe_read(path)
            if re.search(r"(contentful|sanity|strapi|wp-json|graphql)", content, flags=re.I):
                cms_files.append(path.relative_to(root).as_posix())
        if cms_files:
            return {"strategy": "custom_cms_fetcher", "files": cms_files, "editable_mode": "manual_review", "confidence": 0.62}
        return {"strategy": "none_detected", "confidence": 0.5}

    def _client_server_boundaries(self, root: Path, files: Iterable[Path]) -> dict:
        client = []
        server = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            if path.suffix.lower() not in {".tsx", ".jsx", ".ts", ".js", ".mjs", ".vue", ".svelte", ".astro"}:
                continue
            content = _safe_read(path)
            if is_client_component(content):
                client.append(rel)
            elif rel.startswith(("app/", "pages/", "src/")):
                server.append(rel)
        return {"client_components": client, "server_or_static_files": server[:250]}

    def _patch_zones(
        self,
        *,
        root: Path,
        files: Iterable[Path],
        detected_stack: str,
        route_map: list[dict],
        blog_system: dict,
        metadata_strategy: dict,
        schema_strategy: dict,
        sitemap_strategy: dict,
        robots_strategy: dict,
        boundaries: dict,
        confidence: float,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        safe = []
        manual = []
        unsafe = []
        client_files = set(boundaries.get("client_components") or [])
        for route in route_map:
            file_path = route["file_path"]
            if self._is_unsafe_path(file_path):
                unsafe.append(self._zone("unsafe_path", file_path, "Route is in generated, minified, checkout, cart, payment, or ignored code.", ["metadata_update"], 0.95))
                continue
            if file_path in client_files:
                unsafe.append(self._zone("client_component", file_path, "Client components cannot receive Next.js metadata or schema patches.", ["metadata_update", "schema_addition"], 0.98))
                continue
            if detected_stack in {"nextjs_app_router", "nextjs_pages_router"}:
                safe.append(
                    self._zone(
                        "metadata",
                        route.get("seo_control_location") or file_path,
                        "Next route has a server-side metadata control location.",
                        ["metadata_update", "og_twitter_addition", "canonical_addition"],
                        0.88,
                    )
                )
                if not schema_strategy.get("duplicate_risk"):
                    safe.append(self._zone("schema", file_path, "Server route can accept hidden JSON-LD if no schema already exists.", ["schema_addition"], 0.76))
            elif detected_stack in {"plain_static", "react_vite"} and file_path.endswith(".html"):
                safe.append(self._zone("html_head", file_path, "Plain HTML head metadata can be updated safely.", ["metadata_update", "og_twitter_addition"], 0.84))
            elif detected_stack in {"wordpress", "shopify", "laravel"}:
                manual.append(self._zone("template_review", file_path, f"{detected_stack} template edits require manual review.", ["metadata_update", "schema_addition"], 0.76))
        strategy = blog_system.get("insertion_strategy")
        if strategy in {"append_to_static_ts_array", "create_markdown_file", "create_mdx_file", "html_file_create"}:
            safe.append(
                self._zone(
                    "blog_insertion",
                    blog_system.get("content_source_file") or blog_system.get("route_path") or "",
                    "Blog insertion strategy is file-based and reviewable.",
                    ["semantic_html_safe_suggestion"],
                    float(blog_system.get("confidence") or 0.75),
                )
            )
        elif strategy and strategy != "unknown_manual_review":
            manual.append(self._zone("blog_insertion_review", blog_system.get("content_source_file") or "", "Blog publishing should use provider/CMS workflow or manual review.", ["semantic_html_safe_suggestion"], 0.7))
        if sitemap_strategy.get("exists"):
            if sitemap_strategy.get("rich_dynamic") or detected_stack in {"wordpress", "shopify"}:
                manual.append(self._zone("sitemap_review", sitemap_strategy.get("file_path") or "", "Existing sitemap is rich, dynamic, or platform-generated; do not replace it.", ["sitemap_update"], 0.9))
            else:
                safe.append(self._zone("sitemap_additive", sitemap_strategy.get("file_path") or "", "Static sitemap may be extended additively.", ["sitemap_update"], 0.78))
        elif detected_stack.startswith("nextjs"):
            safe.append(self._zone("sitemap_create", "app/sitemap.ts", "Missing Next.js sitemap can be created as a new file.", ["sitemap_update"], 0.82))
        if robots_strategy.get("exists"):
            manual.append(self._zone("robots_review", robots_strategy.get("file_path") or "", "Existing robots implementation should not be overwritten.", ["robots_update"], 0.86))
        elif detected_stack.startswith("nextjs"):
            safe.append(self._zone("robots_create", "app/robots.ts", "Missing Next.js robots route can be created as a new file.", ["robots_update"], 0.82))
        if detected_stack in {"wordpress", "shopify"}:
            manual.append(self._zone("platform_templates", "", f"{detected_stack} SEO edits are live-theme sensitive.", ["metadata_update", "schema_addition", "sitemap_update", "robots_update"], 0.82))
        if detected_stack == "unknown_custom" or confidence < 0.5:
            unsafe.append(self._zone("unknown_architecture", "", "Unknown/custom architecture confidence is too low for automated patches.", ["metadata_update", "schema_addition", "sitemap_update", "robots_update"], confidence))
        if schema_strategy.get("duplicate_risk"):
            manual.append(self._zone("schema_duplicate_risk", "", "Multiple schema implementations detected; avoid duplicate JSON-LD without review.", ["schema_addition"], 0.84))
        return _dedupe_zones(safe), _dedupe_zones(manual), _dedupe_zones(unsafe)

    def _zone(self, zone_type: str, file_path: str, reason: str, patch_types: list[str], confidence: float) -> dict:
        return {
            "zone_type": zone_type,
            "file_path": file_path,
            "reason": reason,
            "patch_types": patch_types,
            "confidence": confidence,
        }

    def _zone_matches(self, zone: dict, file_path: str, patch_type: SeoCodePatchType) -> bool:
        zone_path = (zone.get("file_path") or "").replace("\\", "/")
        if zone_path and zone_path != file_path:
            return False
        patch_types = set(zone.get("patch_types") or [])
        return patch_type.value in patch_types or not patch_types

    def _is_unsafe_path(self, file_path: str) -> bool:
        parts = set(file_path.replace("\\", "/").split("/"))
        lower = file_path.lower()
        return (
            any(part in IGNORE_DIRS for part in parts)
            or lower.endswith(".min.js")
            or lower.endswith(".min.css")
            or lower.endswith(".sql")
            or any(part in PROTECTED_SEGMENTS for part in parts)
            or any(token in lower for token in PROTECTED_TOKENS)
        )

    def _languages(self, files: Iterable[Path]) -> dict:
        counts: dict[str, int] = {}
        for path in files:
            language = LANGUAGE_BY_EXTENSION.get(path.suffix.lower())
            if language:
                counts[language] = counts.get(language, 0) + 1
        primary = max(counts.items(), key=lambda item: item[1])[0] if counts else None
        return {"primary": primary, "counts": counts}

    def _package_manager(self, root: Path) -> Optional[str]:
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (root / "yarn.lock").exists():
            return "yarn"
        if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            return "bun"
        if (root / "package-lock.json").exists():
            return "npm"
        if (root / "composer.lock").exists():
            return "composer"
        return None


def html_metadata_patch_content(original: str, route_label: str, site_url: str) -> str:
    """Update safe non-visible title/meta/canonical fields in a plain HTML head."""
    if not re.search(r"<head[\s>]", original, flags=re.I):
        return original
    description = f"Learn about {route_label.lower()} with clear service details and next steps."
    proposed = re.sub(
        r"<title>.*?</title>",
        f"<title>{route_label}</title>",
        original,
        count=1,
        flags=re.I | re.S,
    )
    if proposed == original:
        proposed = re.sub(r"(<head[^>]*>)", r"\1\n  " + f"<title>{route_label}</title>", proposed, count=1, flags=re.I)
    if re.search(r"<meta\s+name=[\"']description[\"']", proposed, flags=re.I):
        proposed = re.sub(
            r"<meta\s+name=[\"']description[\"'][^>]*>",
            f'<meta name="description" content="{description}">',
            proposed,
            count=1,
            flags=re.I,
        )
    else:
        proposed = re.sub(
            r"(<title>.*?</title>)",
            r"\1\n  " + f'<meta name="description" content="{description}">',
            proposed,
            count=1,
            flags=re.I | re.S,
        )
    if not re.search(r"<link\s+rel=[\"']canonical[\"']", proposed, flags=re.I):
        proposed = re.sub(
            r"(<meta\s+name=[\"']description[\"'][^>]*>)",
            r"\1\n  " + f'<link rel="canonical" href="{site_url}">',
            proposed,
            count=1,
            flags=re.I,
        )
    return proposed


def _safe_read(path: Path) -> str:
    try:
        return read_repo_text(path)
    except OSError:
        return ""


def _profile_dict(profile: ArchitectureProfileData | object | dict) -> dict:
    if isinstance(profile, ArchitectureProfileData):
        return profile.as_record()
    if isinstance(profile, dict):
        return profile
    return {
        "detected_stack": getattr(profile, "detected_stack", None),
        "framework": getattr(profile, "framework", None),
        "router_type": getattr(profile, "router_type", None),
        "package_manager": getattr(profile, "package_manager", None),
        "languages": getattr(profile, "languages", None) or {},
        "route_map": getattr(profile, "route_map", None) or [],
        "content_sources": getattr(profile, "content_sources", None) or [],
        "blog_system": getattr(profile, "blog_system", None) or {},
        "metadata_strategy": getattr(profile, "metadata_strategy", None) or {},
        "schema_strategy": getattr(profile, "schema_strategy", None) or {},
        "sitemap_strategy": getattr(profile, "sitemap_strategy", None) or {},
        "robots_strategy": getattr(profile, "robots_strategy", None) or {},
        "cms_strategy": getattr(profile, "cms_strategy", None) or {},
        "client_server_boundaries": getattr(profile, "client_server_boundaries", None) or {},
        "safe_patch_zones": getattr(profile, "safe_patch_zones", None) or [],
        "manual_review_zones": getattr(profile, "manual_review_zones", None) or [],
        "unsafe_patch_zones": getattr(profile, "unsafe_patch_zones", None) or [],
        "confidence_score": getattr(profile, "confidence_score", 0) or 0,
        "detection_notes": getattr(profile, "detection_notes", None) or [],
    }


def _dedupe_zones(zones: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for zone in zones:
        key = (zone.get("zone_type"), zone.get("file_path"), tuple(zone.get("patch_types") or []), zone.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(zone)
    return unique
