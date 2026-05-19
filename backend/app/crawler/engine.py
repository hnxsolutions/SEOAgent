"""
SEO Agent SaaS - Core Crawler Engine
Production-grade web crawler using Playwright with async support
"""
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from urllib.parse import urlparse
from contextlib import asynccontextmanager

import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Response
from playwright.async_api import Error as PlaywrightError
import structlog

from app.crawler.extraction import (
    classify_links,
    content_hash,
    count_words,
    normalize_whitespace,
    parse_json_ld_scripts,
)
from app.core.url_utils import URLNormalizer, URLDeduplicator, RobotsTxtParser
from app.core.config import settings

logger = structlog.get_logger(__name__)


class CrawlStats:
    """Statistics tracker for crawl operations"""
    
    def __init__(self):
        self.pages_crawled = 0
        self.pages_failed = 0
        self.pages_skipped = 0
        self.pages_pending = 0
        self.internal_links_found = 0
        self.external_links_found = 0
        self.errors = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
    
    @property
    def elapsed_seconds(self) -> float:
        if not self.start_time:
            return 0.0
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()
    
    @property
    def pages_per_minute(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed == 0:
            return 0.0
        return (self.pages_crawled / elapsed) * 60
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages_crawled": self.pages_crawled,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "pages_pending": self.pages_pending,
            "internal_links_found": self.internal_links_found,
            "external_links_found": self.external_links_found,
            "errors": self.errors,
            "elapsed_seconds": self.elapsed_seconds,
            "pages_per_minute": round(self.pages_per_minute, 2),
        }


class PageData:
    """Data container for extracted page information"""
    
    def __init__(self, url: str):
        self.url = url
        self.final_url: Optional[str] = None
        self.status_code: Optional[int] = None
        self.response_time_ms: Optional[float] = None
        self.content_type: Optional[str] = None
        self.content_length: Optional[int] = None
        
        # Redirect info
        self.redirect_count = 0
        self.redirect_chain: List[str] = []
        
        # Content analysis
        self.title: Optional[str] = None
        self.title_length: Optional[int] = None
        self.meta_description: Optional[str] = None
        self.meta_description_length: Optional[int] = None
        
        # Headings
        self.h1: List[str] = []
        self.h2: List[str] = []
        self.h3: List[str] = []
        self.h4: List[str] = []
        self.h5: List[str] = []
        self.h6: List[str] = []
        
        # Content
        self.word_count: int = 0
        self.text_content: Optional[str] = None
        self.content_hash: Optional[str] = None
        
        # Links
        self.internal_links: List[Dict[str, Any]] = []
        self.external_links: List[Dict[str, Any]] = []
        self.internal_link_urls: List[str] = []
        self.external_link_urls: List[str] = []
        
        # Canonical & Meta
        self.canonical_url: Optional[str] = None
        self.canonical_url_normalized: Optional[str] = None
        self.robots_meta: Optional[str] = None
        self.noindex: bool = False
        self.nofollow: bool = False
        
        # Open Graph
        self.og_title: Optional[str] = None
        self.og_description: Optional[str] = None
        self.og_image: Optional[str] = None
        self.og_type: Optional[str] = None
        self.og_url: Optional[str] = None
        self.has_og_tags: bool = False
        
        # Twitter Card
        self.twitter_card: Optional[str] = None
        self.twitter_title: Optional[str] = None
        self.twitter_description: Optional[str] = None
        self.twitter_image: Optional[str] = None
        self.has_twitter_card: bool = False
        
        # Schema.org
        self.schema_markup: Optional[Dict[str, Any]] = None
        self.schema_types: List[str] = []
        self.has_schema_markup: bool = False
        
        # Images
        self.total_images: int = 0
        self.images_with_alt: int = 0
        self.images_without_alt: int = 0
        self.image_alt_texts: List[str] = []
        
        # Page Speed (placeholders)
        self.load_time_ms: Optional[float] = None
        self.first_contentful_paint_ms: Optional[float] = None
        self.largest_contentful_paint_ms: Optional[float] = None
        self.time_to_interactive_ms: Optional[float] = None
        self.cumulative_layout_shift: Optional[float] = None
        self.first_input_delay_ms: Optional[float] = None
        
        # Mobile
        self.is_mobile_friendly: Optional[bool] = None
        self.viewport_meta: Optional[str] = None
        
        # Language
        self.language: Optional[str] = None
        self.hreflang_tags: List[str] = []
        
        # Issues
        self.issues: List[Dict[str, Any]] = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "redirect_count": self.redirect_count,
            "redirect_chain": self.redirect_chain,
            "title": self.title,
            "title_length": self.title_length,
            "meta_description": self.meta_description,
            "meta_description_length": self.meta_description_length,
            "h1": self.h1,
            "h2": self.h2,
            "h3": self.h3,
            "h4": self.h4,
            "h5": self.h5,
            "h6": self.h6,
            "heading_count": len(self.h1) + len(self.h2) + len(self.h3) + len(self.h4) + len(self.h5) + len(self.h6),
            "word_count": self.word_count,
            "text_content": self.text_content,
            "content_hash": self.content_hash,
            "internal_links": len(self.internal_links),
            "external_links": len(self.external_links),
            "total_links": len(self.internal_links) + len(self.external_links),
            "internal_link_urls": self.internal_link_urls,
            "external_link_urls": self.external_link_urls,
            "canonical_url": self.canonical_url,
            "canonical_url_normalized": self.canonical_url_normalized,
            "robots_meta": self.robots_meta,
            "noindex": self.noindex,
            "nofollow": self.nofollow,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "og_type": self.og_type,
            "og_url": self.og_url,
            "has_og_tags": self.has_og_tags,
            "twitter_card": self.twitter_card,
            "twitter_title": self.twitter_title,
            "twitter_description": self.twitter_description,
            "twitter_image": self.twitter_image,
            "has_twitter_card": self.has_twitter_card,
            "schema_markup": self.schema_markup,
            "schema_types": self.schema_types,
            "has_schema_markup": self.has_schema_markup,
            "total_images": self.total_images,
            "images_with_alt": self.images_with_alt,
            "images_without_alt": self.images_without_alt,
            "image_alt_texts": self.image_alt_texts,
            "load_time_ms": self.load_time_ms,
            "first_contentful_paint_ms": self.first_contentful_paint_ms,
            "largest_contentful_paint_ms": self.largest_contentful_paint_ms,
            "time_to_interactive_ms": self.time_to_interactive_ms,
            "cumulative_layout_shift": self.cumulative_layout_shift,
            "first_input_delay_ms": self.first_input_delay_ms,
            "is_mobile_friendly": self.is_mobile_friendly,
            "viewport_meta": self.viewport_meta,
            "language": self.language,
            "hreflang_tags": self.hreflang_tags,
            "issues": self.issues,
            "issue_count": len(self.issues),
            "critical_issues": sum(1 for i in self.issues if i.get("severity") == "critical"),
            "warning_issues": sum(1 for i in self.issues if i.get("severity") == "warning"),
        }


class SEOAnalyzer:
    """Analyzes pages for SEO issues"""
    
    # Title length recommendations
    TITLE_MIN_LENGTH = 30
    TITLE_MAX_LENGTH = 60
    TITLE_IDEAL_MAX = 55
    
    # Meta description recommendations
    META_MIN_LENGTH = 50
    META_MAX_LENGTH = 160
    
    @staticmethod
    def analyze_page(page_data: PageData) -> List[Dict[str, Any]]:
        """Analyze a page for SEO issues and return list of issues found"""
        issues = []
        
        # Title analysis
        if not page_data.title:
            issues.append({
                "type": "missing_title",
                "severity": "critical",
                "message": "Page is missing a title tag",
                "recommendation": "Add a descriptive title tag (30-60 characters)",
            })
        else:
            if page_data.title_length < SEOAnalyzer.TITLE_MIN_LENGTH:
                issues.append({
                    "type": "title_too_short",
                    "severity": "warning",
                    "message": f"Title is too short ({page_data.title_length} characters)",
                    "recommendation": f"Expand title to at least {SEOAnalyzer.TITLE_MIN_LENGTH} characters",
                })
            elif page_data.title_length > SEOAnalyzer.TITLE_MAX_LENGTH:
                issues.append({
                    "type": "title_too_long",
                    "severity": "warning",
                    "message": f"Title is too long ({page_data.title_length} characters)",
                    "recommendation": f"Shorten title to under {SEOAnalyzer.TITLE_MAX_LENGTH} characters",
                })
        
        # Meta description analysis
        if not page_data.meta_description:
            issues.append({
                "type": "missing_meta_description",
                "severity": "critical",
                "message": "Page is missing a meta description",
                "recommendation": "Add a compelling meta description (50-160 characters)",
            })
        else:
            if page_data.meta_description_length < SEOAnalyzer.META_MIN_LENGTH:
                issues.append({
                    "type": "meta_description_too_short",
                    "severity": "warning",
                    "message": f"Meta description is too short ({page_data.meta_description_length} characters)",
                    "recommendation": f"Expand to at least {SEOAnalyzer.META_MIN_LENGTH} characters",
                })
            elif page_data.meta_description_length > SEOAnalyzer.META_MAX_LENGTH:
                issues.append({
                    "type": "meta_description_too_long",
                    "severity": "warning",
                    "message": f"Meta description is too long ({page_data.meta_description_length} characters)",
                    "recommendation": f"Shorten to under {SEOAnalyzer.META_MAX_LENGTH} characters",
                })
        
        # H1 analysis
        if not page_data.h1:
            issues.append({
                "type": "missing_h1",
                "severity": "critical",
                "message": "Page is missing an H1 heading",
                "recommendation": "Add a clear H1 heading that describes the page content",
            })
        elif len(page_data.h1) > 1:
            issues.append({
                "type": "multiple_h1",
                "severity": "warning",
                "message": f"Page has {len(page_data.h1)} H1 tags",
                "recommendation": "Use only one H1 tag per page",
            })
        
        # Canonical URL analysis
        if not page_data.canonical_url:
            issues.append({
                "type": "missing_canonical",
                "severity": "warning",
                "message": "Page is missing a canonical URL",
                "recommendation": "Add a canonical tag to prevent duplicate content issues",
            })
        
        # Noindex analysis
        if page_data.noindex:
            issues.append({
                "type": "noindex_page",
                "severity": "warning",
                "message": "Page has noindex meta tag",
                "recommendation": "Remove noindex if page should appear in search results",
            })
        
        # Image alt analysis
        if page_data.images_without_alt > 0:
            issues.append({
                "type": "missing_alt_tags",
                "severity": "warning",
                "message": f"{page_data.images_without_alt} images missing alt text",
                "recommendation": "Add descriptive alt text to all images",
            })
        
        # Schema markup analysis
        if not page_data.has_schema_markup:
            issues.append({
                "type": "missing_schema_markup",
                "severity": "info",
                "message": "Page is missing schema.org markup",
                "recommendation": "Add structured data to enhance search results",
            })
        
        # Open Graph analysis
        if not page_data.has_og_tags:
            issues.append({
                "type": "missing_og_tags",
                "severity": "info",
                "message": "Page is missing Open Graph tags",
                "recommendation": "Add OG tags for better social media sharing",
            })
        
        # Twitter Card analysis
        if not page_data.has_twitter_card:
            issues.append({
                "type": "missing_twitter_card",
                "severity": "info",
                "message": "Page is missing Twitter Card tags",
                "recommendation": "Add Twitter Card tags for better Twitter sharing",
            })
        
        # Word count analysis
        if page_data.word_count < 300:
            issues.append({
                "type": "low_word_count",
                "severity": "warning",
                "message": f"Page has low word count ({page_data.word_count} words)",
                "recommendation": "Aim for at least 300 words of quality content",
            })
        
        # HTTP status analysis
        if page_data.status_code == 404:
            issues.append({
                "type": "broken_page",
                "severity": "critical",
                "message": "Page returns 404 status code",
                "recommendation": "Fix or redirect this broken page",
            })
        elif page_data.status_code and page_data.status_code >= 500:
            issues.append({
                "type": "server_error",
                "severity": "critical",
                "message": f"Page returns {page_data.status_code} status code",
                "recommendation": "Fix server error",
            })
        elif page_data.status_code in [301, 302, 303, 307, 308]:
            issues.append({
                "type": "redirect_page",
                "severity": "info",
                "message": f"Page returns {page_data.status_code} redirect",
                "recommendation": "Consider updating internal links to point to final URL",
            })
        
        return issues


class CrawlerEngine:
    """
    Production-grade web crawler engine using Playwright.
    Supports distributed crawling with Redis-based queue.
    """
    
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    def __init__(
        self,
        max_concurrent_pages: int = 5,
        request_timeout: int = 30,
        crawl_delay: float = 1.0,
        render_javascript: bool = True,
        user_agent: Optional[str] = None,
        respect_robots_txt: bool = True,
    ):
        self.max_concurrent_pages = max_concurrent_pages
        self.request_timeout = request_timeout
        self.crawl_delay = crawl_delay
        self.render_javascript = render_javascript
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.respect_robots_txt = respect_robots_txt
        
        # URL tracking
        self.deduplicator = URLDeduplicator()
        self.robots_cache: Dict[str, RobotsTxtParser] = {}
        
        # Browser management
        self._browser: Optional[Browser] = None
        self._playwright = None
        
        # Statistics
        self.stats = CrawlStats()
        
        # Semaphore for concurrency control
        self._semaphore: Optional[asyncio.Semaphore] = None
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def start(self):
        """Initialize the browser and playwright instance"""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
            ]
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent_pages)
        self.stats.start_time = datetime.utcnow()
        logger.info("Crawler engine started")
    
    async def close(self):
        """Close the browser and cleanup"""
        self.stats.end_time = datetime.utcnow()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info(f"Crawler engine closed. Stats: {self.stats.to_dict()}")
    
    def _get_robots_parser(self, url: str) -> Optional[RobotsTxtParser]:
        """Get or create robots.txt parser for a domain"""
        domain = URLNormalizer.get_domain(url)
        if not domain:
            return None
        
        if domain in self.robots_cache:
            return self.robots_cache[domain]
        
        return None
    
    async def _fetch_robots_txt(self, url: str) -> Optional[RobotsTxtParser]:
        """Fetch and cache robots.txt for a domain"""
        domain = URLNormalizer.get_domain(url)
        if not domain:
            return None
        
        if domain in self.robots_cache:
            return self.robots_cache[domain]
        
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
                timeout=10.0,
                verify=False,
            ) as client:
                response = await client.get(robots_url)

            if response.status_code == 200:
                parser = RobotsTxtParser(response.text)
                self.robots_cache[domain] = parser
                logger.debug("Fetched robots.txt", domain=domain, sitemap_count=len(parser.get_sitemaps()))
                return parser

            logger.debug("robots.txt not found", domain=domain, status_code=response.status_code)
            self.robots_cache[domain] = RobotsTxtParser("")
            return self.robots_cache[domain]
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt for {domain}: {e}")
            self.robots_cache[domain] = RobotsTxtParser("")
            return self.robots_cache[domain]
    
    def _should_crawl_url(
        self,
        url: str,
        base_domain: str,
        allowed_domains: Optional[List[str]] = None,
        excluded_paths: Optional[List[str]] = None,
        follow_subdomains: bool = False,
    ) -> Tuple[bool, str]:
        """
        Determine if a URL should be crawled based on various rules.
        
        Returns:
            Tuple of (should_crawl: bool, reason: str)
        """
        # Check if URL is valid
        if not URLNormalizer.is_valid_url(url):
            return False, "Invalid URL"
        
        # Check robots.txt
        if self.respect_robots_txt:
            robots_parser = self._get_robots_parser(url)
            if robots_parser and not robots_parser.can_crawl(url):
                return False, "Blocked by robots.txt"
        
        # Check domain restrictions
        url_domain = URLNormalizer.get_domain(url)
        if allowed_domains:
            if url_domain not in allowed_domains:
                return False, "Domain not in allowed list"
        else:
            if follow_subdomains:
                if URLNormalizer.get_base_domain(url) != URLNormalizer.get_base_domain(base_domain):
                    return False, "Different base domain"
            else:
                if url_domain != base_domain:
                    return False, "Different domain"
        
        # Check excluded paths
        if excluded_paths and URLNormalizer.matches_path_pattern(url, excluded_paths):
            return False, "Path excluded by pattern"
        
        return True, "OK"
    
    async def _get_attribute(self, page: Page, selector: str, attribute: str) -> Optional[str]:
        """Safely read an attribute from the first matching element."""
        try:
            locator = page.locator(selector)
            if await locator.count() == 0:
                return None
            value = await locator.first.get_attribute(attribute)
            return normalize_whitespace(value) if value else None
        except Exception:
            return None

    async def _evaluate_or_none(self, page: Page, expression: str) -> Any:
        """Safely evaluate browser JavaScript and return None on DOM errors."""
        try:
            return await page.evaluate(expression)
        except Exception:
            return None

    def _redirect_chain_from_response(self, response: Optional[Response]) -> List[str]:
        """Build a redirect chain from Playwright's request redirect links."""
        if not response:
            return []

        chain: List[str] = []
        request = response.request
        while request.redirected_from:
            request = request.redirected_from
            chain.insert(0, request.url)

        if chain:
            chain.append(response.url)
        return chain

    async def _extract_page_data(
        self,
        page: Page,
        url: str,
        response: Optional[Response] = None,
        allowed_domains: Optional[List[str]] = None,
        follow_subdomains: bool = False,
    ) -> PageData:
        """Extract all SEO data from a rendered page."""
        page_data = PageData(url)

        if response:
            page_data.status_code = response.status
            page_data.content_type = response.headers.get("content-type", "")
            page_data.final_url = page.url or response.url
            try:
                page_data.content_length = int(response.headers.get("content-length", 0))
            except (ValueError, TypeError):
                pass
        else:
            page_data.final_url = page.url
        
        # Extract title
        page_data.title = normalize_whitespace(await page.title())
        page_data.title_length = len(page_data.title) if page_data.title else 0

        page_data.meta_description = await self._get_attribute(
            page,
            'meta[name="description" i]',
            "content",
        )
        if page_data.meta_description:
            page_data.meta_description_length = len(page_data.meta_description)
        
        # Extract headings
        for i in range(1, 7):
            heading_texts = await page.locator(f"h{i}").all_text_contents()
            heading_texts = [normalize_whitespace(text) for text in heading_texts]
            heading_texts = [text for text in heading_texts if text]
            setattr(page_data, f'h{i}', heading_texts)
        
        page_data.canonical_url = await self._get_attribute(
            page,
            'link[rel="canonical" i]',
            "href",
        )
        if page_data.canonical_url:
            canonical_absolute = URLNormalizer.resolve_relative_url(page.url or url, page_data.canonical_url)
            page_data.canonical_url = canonical_absolute
            page_data.canonical_url_normalized = URLNormalizer.normalize_url(canonical_absolute)

        robots_meta = await self._get_attribute(page, 'meta[name="robots" i]', "content")
        if robots_meta:
            page_data.robots_meta = robots_meta
            robots_lower = robots_meta.lower()
            page_data.noindex = "noindex" in robots_lower
            page_data.nofollow = "nofollow" in robots_lower
        
        # Extract Open Graph tags
        og_extractors = {
            'og:title': 'og_title',
            'og:description': 'og_description',
            'og:image': 'og_image',
            'og:type': 'og_type',
            'og:url': 'og_url',
        }
        for prop, attr in og_extractors.items():
            value = await self._get_attribute(
                page,
                f'meta[property="{prop}"]',
                "content",
            )
            if value:
                setattr(page_data, attr, value)
                page_data.has_og_tags = True
        
        # Extract Twitter Card tags
        twitter_extractors = {
            'twitter:card': 'twitter_card',
            'twitter:title': 'twitter_title',
            'twitter:description': 'twitter_description',
            'twitter:image': 'twitter_image',
        }
        for name, attr in twitter_extractors.items():
            value = await self._get_attribute(
                page,
                f'meta[name="{name}"]',
                "content",
            )
            if value:
                setattr(page_data, attr, value)
                page_data.has_twitter_card = True
        
        # Extract schema.org markup
        schema_texts = await page.locator('script[type="application/ld+json"]').all_text_contents()
        schema_markup, schema_types = parse_json_ld_scripts(schema_texts)
        if schema_markup:
            page_data.schema_markup = schema_markup
            page_data.schema_types = schema_types
            page_data.has_schema_markup = True
        
        # Extract links
        raw_links = await page.locator("a[href]").evaluate_all(
            """elements => elements.slice(0, 500).map((element) => ({
                href: element.getAttribute("href"),
                text: element.textContent || "",
                rel: element.getAttribute("rel") || "",
                target: element.getAttribute("target") || ""
            }))"""
        )
        (
            page_data.internal_links,
            page_data.external_links,
            page_data.internal_link_urls,
            page_data.external_link_urls,
        ) = classify_links(
            url,
            raw_links,
            allowed_domains=allowed_domains,
            follow_subdomains=follow_subdomains,
        )
        
        # Extract images
        raw_images = await page.locator("img").evaluate_all(
            """elements => elements.slice(0, 100).map((element) => ({
                alt: element.getAttribute("alt")
            }))"""
        )
        page_data.total_images = len(raw_images)
        for image in raw_images:
            alt_text = normalize_whitespace(image.get("alt"))
            if alt_text:
                page_data.images_with_alt += 1
                page_data.image_alt_texts.append(alt_text)
            else:
                page_data.images_without_alt += 1
        
        html_lang = await self._get_attribute(page, "html", "lang")
        if html_lang:
            page_data.language = html_lang
        
        # Extract hreflang tags
        hreflang_tags = await page.locator('link[rel="alternate" i][hreflang]').evaluate_all(
            """elements => elements.map((element) => element.getAttribute("hreflang")).filter(Boolean)"""
        )
        page_data.hreflang_tags = [normalize_whitespace(tag) for tag in hreflang_tags]
        
        viewport = await self._get_attribute(page, 'meta[name="viewport" i]', "content")
        if viewport:
            page_data.viewport_meta = viewport
            page_data.is_mobile_friendly = 'width=device-width' in viewport.lower()
        
        # Calculate word count
        text_content = await self._evaluate_or_none(page, "() => document.body ? document.body.innerText : ''")
        page_data.text_content = normalize_whitespace(text_content)
        if text_content:
            page_data.word_count = count_words(text_content)
        
        # Generate content hash
        page_data.content_hash = content_hash(text_content)
        
        # Page speed metrics (placeholders - would need real performance API)
        try:
            performance_timing = await page.evaluate('''() => {
                const timing = performance.timing;
                const navigation = performance.getEntriesByType('navigation')[0];
                return {
                    loadTime: navigation ? navigation.loadEventEnd - navigation.fetchStart : null,
                    domContentLoaded: navigation ? navigation.domContentLoadedEventEnd - navigation.fetchStart : null,
                    firstByte: timing.responseStart - timing.navigationStart,
                };
            }''')
            if performance_timing:
                page_data.load_time_ms = performance_timing.get('loadTime')
                page_data.first_contentful_paint_ms = performance_timing.get('domContentLoaded')
        except Exception:
            pass
        
        # Run SEO analysis
        page_data.issues = SEOAnalyzer.analyze_page(page_data)
        
        return page_data
    
    async def crawl_page(
        self,
        url: str,
        depth: int = 0,
        max_depth: int = 2,
        crawl_job_id: Optional[str] = None,
        allowed_domains: Optional[List[str]] = None,
        excluded_paths: Optional[List[str]] = None,
        follow_subdomains: bool = False,
        max_retries: Optional[int] = None,
    ) -> Tuple[PageData, List[str]]:
        """
        Crawl a single page and extract SEO data.
        
        Returns:
            Tuple of (PageData, list of new URLs to crawl)
        """
        if not self._browser:
            await self.start()

        async with self._semaphore:
            page_data = None
            new_urls = []
            retry_limit = 3 if max_retries is None else max_retries
            
            normalized_url = URLNormalizer.normalize_url(url)
            if not normalized_url:
                logger.warning("Invalid URL", url=url)
                self.stats.pages_skipped += 1
                return None, []

            if self.respect_robots_txt:
                robots_parser = await self._fetch_robots_txt(normalized_url)
                if robots_parser and not robots_parser.can_crawl(normalized_url, self.user_agent):
                    self.stats.pages_skipped += 1
                    page_data = PageData(normalized_url)
                    page_data.issues.append({
                        "type": "blocked_by_robots",
                        "severity": "info",
                        "message": "URL blocked by robots.txt",
                    })
                    return page_data, []

            last_error: Optional[Exception] = None
            for attempt in range((retry_limit or 0) + 1):
                context = await self._browser.new_context(
                    user_agent=self.user_agent,
                    ignore_https_errors=True,
                    java_script_enabled=self.render_javascript,
                )
                start_time = time.time()

                try:
                    page = await context.new_page()
                    response = await page.goto(
                        normalized_url,
                        wait_until="domcontentloaded",
                        timeout=self.request_timeout * 1000,
                    )

                    if self.render_javascript:
                        try:
                            await page.wait_for_load_state("networkidle", timeout=self.request_timeout * 1000)
                        except PlaywrightError:
                            logger.debug("networkidle wait timed out; continuing extraction", url=normalized_url)

                    elapsed = (time.time() - start_time) * 1000
                    page_data = await self._extract_page_data(
                        page,
                        normalized_url,
                        response=response,
                        allowed_domains=allowed_domains,
                        follow_subdomains=follow_subdomains,
                    )
                    page_data.response_time_ms = elapsed
                    page_data.redirect_chain = self._redirect_chain_from_response(response)
                    page_data.redirect_count = max(len(page_data.redirect_chain) - 1, 0)

                    self.stats.pages_crawled += 1

                    if depth < max_depth:
                        seen_urls: Set[str] = set()
                        base_domain = URLNormalizer.get_domain(normalized_url) or ""
                        for candidate in page_data.internal_link_urls:
                            should_crawl, _ = self._should_crawl_url(
                                candidate,
                                base_domain,
                                allowed_domains,
                                excluded_paths,
                                follow_subdomains,
                            )
                            if should_crawl and candidate not in seen_urls:
                                seen_urls.add(candidate)
                                new_urls.append(candidate)

                    logger.info(
                        "Crawled page",
                        url=normalized_url,
                        status=page_data.status_code,
                        depth=depth,
                        links=len(new_urls),
                        word_count=page_data.word_count,
                    )
                    break

                except (PlaywrightError, asyncio.TimeoutError) as e:
                    last_error = e
                    if attempt < (retry_limit or 0):
                        await asyncio.sleep(min(2 ** attempt, 10))
                        continue
                    logger.warning("Crawler failed after retries", url=normalized_url, error=str(e))

                except Exception as e:
                    last_error = e
                    logger.error("Unexpected crawler error", url=normalized_url, error=str(e), exc_info=True)
                    break

                finally:
                    try:
                        await context.close()
                    except PlaywrightError as close_error:
                        logger.debug(
                            "Browser context already closed",
                            url=normalized_url,
                            error=str(close_error).encode("ascii", errors="backslashreplace").decode("ascii"),
                        )

            if page_data is None:
                self.stats.pages_failed += 1
                self.stats.errors += 1
                page_data = PageData(normalized_url)
                page_data.issues.append({
                    "type": "crawl_error",
                    "severity": "critical",
                    "message": f"Failed to crawl page: {last_error}",
                })

            if self.crawl_delay > 0:
                await asyncio.sleep(self.crawl_delay)
            
            return page_data, new_urls
    
    async def crawl_site(
        self,
        start_url: str,
        max_pages: int = 100,
        max_depth: int = 2,
        allowed_domains: Optional[List[str]] = None,
        excluded_paths: Optional[List[str]] = None,
        follow_subdomains: bool = False,
        sitemap_urls: Optional[List[str]] = None,
        progress_callback=None,
    ) -> List[PageData]:
        """
        Crawl an entire site starting from a given URL.
        
        Args:
            start_url: The URL to start crawling from
            max_pages: Maximum number of pages to crawl
            max_depth: Maximum depth to crawl
            allowed_domains: List of allowed domains (if None, uses start URL's domain)
            excluded_paths: List of path patterns to exclude
            follow_subdomains: Whether to follow subdomains
            sitemap_urls: Additional sitemap URLs to extract URLs from
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of PageData objects for all crawled pages
        """
        if not self._browser:
            await self.start()
        
        results = []
        url_queue: asyncio.Queue = asyncio.Queue()
        base_domain = URLNormalizer.get_domain(start_url)
        
        if not base_domain:
            logger.error(f"Invalid start URL: {start_url}")
            return results
        
        discovered_sitemaps = list(sitemap_urls or [])

        # Fetch robots.txt
        if self.respect_robots_txt:
            robots_parser = await self._fetch_robots_txt(start_url)
            if robots_parser:
                for sitemap_url in robots_parser.get_sitemaps():
                    if sitemap_url not in discovered_sitemaps:
                        discovered_sitemaps.append(sitemap_url)

        default_sitemap = f"{urlparse(start_url).scheme}://{base_domain}/sitemap.xml"
        if default_sitemap not in discovered_sitemaps:
            discovered_sitemaps.append(default_sitemap)
        
        # Add start URL to queue
        await url_queue.put((start_url, 0))  # (url, depth)
        self.deduplicator.add(start_url)
        
        # Process sitemap URLs if provided
        if discovered_sitemaps:
            for sitemap_url in discovered_sitemaps:
                try:
                    sitemap_urls_from_file = await self._parse_sitemap(sitemap_url)
                    for sitemap_url_item in sitemap_urls_from_file:
                        should_crawl, reason = self._should_crawl_url(
                            sitemap_url_item,
                            base_domain,
                            allowed_domains,
                            excluded_paths,
                            follow_subdomains,
                        )
                        if should_crawl and self.deduplicator.add(sitemap_url_item):
                            await url_queue.put((sitemap_url_item, 0))
                            logger.debug(f"Added URL from sitemap: {sitemap_url_item}")
                except Exception as e:
                    logger.warning(f"Failed to parse sitemap {sitemap_url}: {e}")
        
        # Process queue
        while not url_queue.empty() and self.stats.pages_crawled < max_pages:
            try:
                url, depth = await asyncio.wait_for(url_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            
            # Check if we should crawl this URL
            should_crawl, reason = self._should_crawl_url(
                url,
                base_domain,
                allowed_domains,
                excluded_paths,
                follow_subdomains,
            )
            
            if not should_crawl:
                logger.debug(f"Skipping {url}: {reason}")
                self.stats.pages_skipped += 1
                continue
            
            # Crawl the page
            page_data, new_urls = await self.crawl_page(
                url,
                depth=depth,
                max_depth=max_depth,
                allowed_domains=allowed_domains,
                excluded_paths=excluded_paths,
                follow_subdomains=follow_subdomains,
            )
            
            if page_data:
                results.append(page_data)
                
                # Update stats
                self.stats.internal_links_found += len(page_data.internal_links)
                self.stats.external_links_found += len(page_data.external_links)
                
                # Add new URLs to queue
                for new_url in new_urls:
                    should_add, _ = self._should_crawl_url(
                        new_url,
                        base_domain,
                        allowed_domains,
                        excluded_paths,
                        follow_subdomains,
                    )
                    if should_add and self.deduplicator.add(new_url):
                        await url_queue.put((new_url, depth + 1))
            
            # Progress callback
            if progress_callback:
                await progress_callback(self.stats)
        
        return results

    async def discover_sitemap_urls(
        self,
        start_url: str,
        additional_sitemaps: Optional[List[str]] = None,
    ) -> List[str]:
        """Discover sitemap URLs from robots.txt, request config, and /sitemap.xml."""
        sitemap_urls: List[str] = []

        if self.respect_robots_txt:
            robots_parser = await self._fetch_robots_txt(start_url)
            if robots_parser:
                sitemap_urls.extend(robots_parser.get_sitemaps())

        sitemap_urls.extend(additional_sitemaps or [])

        parsed = urlparse(start_url)
        domain = URLNormalizer.get_domain(start_url)
        if parsed.scheme and domain:
            sitemap_urls.append(f"{parsed.scheme}://{domain}/sitemap.xml")

        unique_urls: List[str] = []
        for sitemap_url in sitemap_urls:
            normalized = URLNormalizer.normalize_url(sitemap_url)
            if normalized and normalized not in unique_urls:
                unique_urls.append(normalized)
        return unique_urls

    async def discover_sitemap_pages(
        self,
        start_url: str,
        additional_sitemaps: Optional[List[str]] = None,
        max_urls: int = 1000,
    ) -> List[str]:
        """Discover page URLs from sitemaps, following sitemap indexes recursively."""
        sitemap_stack = await self.discover_sitemap_urls(start_url, additional_sitemaps)
        seen_sitemaps: Set[str] = set()
        page_urls: List[str] = []

        while sitemap_stack and len(page_urls) < max_urls:
            sitemap_url = sitemap_stack.pop(0)
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)

            for loc in await self._parse_sitemap(sitemap_url):
                normalized = URLNormalizer.normalize_url(loc)
                if not normalized:
                    continue
                parsed_path = urlparse(normalized).path.lower()
                if parsed_path.endswith(".xml") or "sitemap" in parsed_path:
                    if normalized not in seen_sitemaps and normalized not in sitemap_stack:
                        sitemap_stack.append(normalized)
                elif normalized not in page_urls:
                    page_urls.append(normalized)
                    if len(page_urls) >= max_urls:
                        break

        return page_urls
    
    async def _parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Parse a sitemap XML file and extract URLs"""
        urls = []
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
                timeout=15.0,
                verify=False,
            ) as client:
                response = await client.get(sitemap_url)

            if response.status_code == 200:
                urls = self._extract_urls_from_sitemap(response.text)
                logger.info("Parsed sitemap", sitemap_url=sitemap_url, url_count=len(urls))
            else:
                logger.debug("Sitemap unavailable", sitemap_url=sitemap_url, status_code=response.status_code)

        except Exception as e:
            logger.warning(f"Failed to parse sitemap {sitemap_url}: {e}")
        
        return urls
    
    def _extract_urls_from_sitemap(self, content: str) -> List[str]:
        """Extract URLs from sitemap XML content"""
        import xml.etree.ElementTree as ET
        
        urls = []
        try:
            root = ET.fromstring(content)
            
            # Handle sitemap index
            if 'sitemapindex' in root.tag:
                for sitemap in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                    loc = sitemap.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                    if loc is not None and loc.text:
                        urls.append(loc.text)
            
            # Handle URL set
            elif 'urlset' in root.tag:
                for url_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
                    loc = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                    if loc is not None and loc.text:
                        urls.append(loc.text)
            
            # Fallback: regex extraction
            if not urls:
                url_pattern = r'<loc>(.*?)</loc>'
                urls = re.findall(url_pattern, content)
                
        except ET.ParseError:
            # Fallback to regex
            url_pattern = r'<loc>(.*?)</loc>'
            urls = re.findall(url_pattern, content)
        
        return urls
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current crawl statistics"""
        return self.stats.to_dict()
