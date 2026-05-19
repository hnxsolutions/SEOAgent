"""
Deterministic SEO rules for crawled pages.

This module has no database or LLM dependencies. It accepts crawl-shaped
snapshots and returns repeatable issues plus scores.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from app.core.url_utils import URLNormalizer
from app.models.audit import SEOIssueCategory, SEOIssueSeverity


TITLE_MIN_LENGTH = 30
TITLE_MAX_LENGTH = 60
META_MIN_LENGTH = 50
META_MAX_LENGTH = 160
THIN_CONTENT_WORDS = 300
EXCESSIVE_EXTERNAL_LINKS = 100
WEAK_INTERNAL_DEPTH = 3

SEVERITY_IMPACT = {
    SEOIssueSeverity.critical: 25,
    SEOIssueSeverity.high: 15,
    SEOIssueSeverity.medium: 8,
    SEOIssueSeverity.low: 3,
}


@dataclass(frozen=True)
class AuditPage:
    id: UUID
    url: str
    normalized_url: Optional[str] = None
    title: Optional[str] = None
    title_length: Optional[int] = None
    meta_description: Optional[str] = None
    meta_description_length: Optional[int] = None
    h1: List[str] = field(default_factory=list)
    canonical_url_normalized: Optional[str] = None
    noindex: bool = False
    word_count: int = 0
    total_images: int = 0
    images_without_alt: int = 0
    external_links: int = 0
    has_schema_markup: bool = False
    has_og_tags: bool = False
    depth: int = 0
    status_code: Optional[int] = None

    @property
    def comparable_url(self) -> str:
        return self.normalized_url or URLNormalizer.normalize_url(self.url) or self.url


@dataclass(frozen=True)
class AuditLink:
    source_page_id: UUID
    normalized_url: Optional[str]
    link_type: str = "internal"
    status_code: Optional[int] = None
    is_broken: bool = False


@dataclass(frozen=True)
class DetectedIssue:
    page_id: Optional[UUID]
    url: Optional[str]
    issue_type: str
    title: str
    message: str
    recommendation: str
    severity: SEOIssueSeverity
    category: SEOIssueCategory
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def score_impact(self) -> int:
        return SEVERITY_IMPACT[self.severity]


@dataclass(frozen=True)
class PageScore:
    page_id: UUID
    url: str
    score: int
    issue_count: int
    severity_counts: Dict[str, int]
    score_breakdown: Dict[str, Any]


@dataclass(frozen=True)
class AuditResult:
    issues: List[DetectedIssue]
    page_scores: List[PageScore]
    site_score: int
    issue_counts_by_severity: Dict[str, int]
    issue_counts_by_category: Dict[str, int]


class SEOAuditRulesEngine:
    """Run deterministic SEO rules against crawled page/link snapshots."""

    def analyze(
        self,
        pages: Iterable[AuditPage],
        links: Iterable[AuditLink],
        seed_url: Optional[str] = None,
    ) -> AuditResult:
        page_list = list(pages)
        link_list = list(links)
        issues: List[DetectedIssue] = []

        page_by_url = {page.comparable_url: page for page in page_list}
        incoming_counts = self._incoming_internal_counts(page_list, link_list)
        seed_normalized = URLNormalizer.normalize_url(seed_url or "") if seed_url else None

        for page in page_list:
            issues.extend(self._page_metadata_rules(page))
            issues.extend(self._page_content_rules(page))
            issues.extend(self._page_technical_rules(page))
            issues.extend(self._page_link_rules(page, link_list))
            issues.extend(self._page_schema_rules(page))

            is_seed = bool(seed_normalized and page.comparable_url == seed_normalized) or page.depth == 0
            if not is_seed and incoming_counts[page.id] == 0:
                issues.append(self._issue(
                    page,
                    "orphan_page",
                    "Orphan page",
                    "Page has no internal links pointing to it from crawled pages.",
                    "Add contextual internal links from relevant pages.",
                    SEOIssueSeverity.high,
                    SEOIssueCategory.links,
                    {"incoming_internal_links": 0},
                ))

            if page.depth >= WEAK_INTERNAL_DEPTH:
                issues.append(self._issue(
                    page,
                    "weak_internal_link_depth",
                    "Weak internal link depth",
                    f"Page is at crawl depth {page.depth}.",
                    "Move important pages closer to the homepage with stronger internal linking.",
                    SEOIssueSeverity.medium,
                    SEOIssueCategory.links,
                    {"depth": page.depth, "threshold": WEAK_INTERNAL_DEPTH},
                ))

        issues.extend(self._duplicate_title_rules(page_list))
        issues.extend(self._duplicate_meta_description_rules(page_list))

        page_scores = self._score_pages(page_list, issues)
        site_score = self._site_score(page_scores)
        return AuditResult(
            issues=issues,
            page_scores=page_scores,
            site_score=site_score,
            issue_counts_by_severity=self._count_by(issues, "severity"),
            issue_counts_by_category=self._count_by(issues, "category"),
        )

    def _page_metadata_rules(self, page: AuditPage) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        title = (page.title or "").strip()
        title_length = page.title_length if page.title_length is not None else len(title)
        meta = (page.meta_description or "").strip()
        meta_length = page.meta_description_length if page.meta_description_length is not None else len(meta)

        if not title:
            issues.append(self._issue(
                page,
                "missing_title",
                "Missing title",
                "Page is missing a title tag.",
                "Add a unique, descriptive title tag.",
                SEOIssueSeverity.high,
                SEOIssueCategory.metadata,
            ))
        elif title_length < TITLE_MIN_LENGTH:
            issues.append(self._issue(
                page,
                "title_too_short",
                "Title too short",
                f"Title is {title_length} characters.",
                f"Expand the title to at least {TITLE_MIN_LENGTH} characters.",
                SEOIssueSeverity.medium,
                SEOIssueCategory.metadata,
                {"length": title_length, "minimum": TITLE_MIN_LENGTH},
            ))
        elif title_length > TITLE_MAX_LENGTH:
            issues.append(self._issue(
                page,
                "title_too_long",
                "Title too long",
                f"Title is {title_length} characters.",
                f"Keep the title under {TITLE_MAX_LENGTH} characters.",
                SEOIssueSeverity.low,
                SEOIssueCategory.metadata,
                {"length": title_length, "maximum": TITLE_MAX_LENGTH},
            ))

        if not meta:
            issues.append(self._issue(
                page,
                "missing_meta_description",
                "Missing meta description",
                "Page is missing a meta description.",
                "Add a unique meta description that summarizes the page.",
                SEOIssueSeverity.medium,
                SEOIssueCategory.metadata,
            ))
        elif meta_length < META_MIN_LENGTH:
            issues.append(self._issue(
                page,
                "meta_description_too_short",
                "Meta description too short",
                f"Meta description is {meta_length} characters.",
                f"Expand the meta description to at least {META_MIN_LENGTH} characters.",
                SEOIssueSeverity.low,
                SEOIssueCategory.metadata,
                {"length": meta_length, "minimum": META_MIN_LENGTH},
            ))
        elif meta_length > META_MAX_LENGTH:
            issues.append(self._issue(
                page,
                "meta_description_too_long",
                "Meta description too long",
                f"Meta description is {meta_length} characters.",
                f"Keep the meta description under {META_MAX_LENGTH} characters.",
                SEOIssueSeverity.low,
                SEOIssueCategory.metadata,
                {"length": meta_length, "maximum": META_MAX_LENGTH},
            ))

        if not page.has_og_tags:
            issues.append(self._issue(
                page,
                "missing_open_graph_tags",
                "Missing Open Graph tags",
                "Page does not include Open Graph tags.",
                "Add og:title, og:description, and og:image for social previews.",
                SEOIssueSeverity.low,
                SEOIssueCategory.metadata,
            ))

        return issues

    def _page_content_rules(self, page: AuditPage) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        h1_count = len([value for value in page.h1 if str(value).strip()])

        if h1_count == 0:
            issues.append(self._issue(
                page,
                "missing_h1",
                "Missing H1",
                "Page does not have an H1 heading.",
                "Add exactly one descriptive H1.",
                SEOIssueSeverity.high,
                SEOIssueCategory.content,
            ))
        elif h1_count > 1:
            issues.append(self._issue(
                page,
                "multiple_h1",
                "Multiple H1s",
                f"Page has {h1_count} H1 headings.",
                "Use one primary H1 and demote secondary headings.",
                SEOIssueSeverity.medium,
                SEOIssueCategory.content,
                {"h1_count": h1_count},
            ))

        if page.word_count < THIN_CONTENT_WORDS:
            issues.append(self._issue(
                page,
                "thin_content",
                "Thin content",
                f"Page has {page.word_count} words.",
                f"Add useful, original content to reach at least {THIN_CONTENT_WORDS} words where appropriate.",
                SEOIssueSeverity.medium,
                SEOIssueCategory.content,
                {"word_count": page.word_count, "threshold": THIN_CONTENT_WORDS},
            ))

        if page.images_without_alt > 0:
            issues.append(self._issue(
                page,
                "missing_image_alt_text",
                "Missing image alt text",
                f"{page.images_without_alt} images are missing alt text.",
                "Add meaningful alt text to informative images.",
                SEOIssueSeverity.medium,
                SEOIssueCategory.content,
                {"images_without_alt": page.images_without_alt, "total_images": page.total_images},
            ))

        return issues

    def _page_technical_rules(self, page: AuditPage) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        if not page.canonical_url_normalized:
            issues.append(self._issue(
                page,
                "missing_canonical",
                "Missing canonical",
                "Page is missing a canonical URL.",
                "Add a canonical link that points to the preferred page URL.",
                SEOIssueSeverity.medium,
                SEOIssueCategory.technical,
            ))
        elif URLNormalizer.normalize_url(page.canonical_url_normalized) != page.comparable_url:
            issues.append(self._issue(
                page,
                "canonical_mismatch",
                "Canonical mismatch",
                "Canonical URL does not match the crawled page URL.",
                "Point canonical to the preferred normalized URL for this page.",
                SEOIssueSeverity.high,
                SEOIssueCategory.technical,
                {"canonical": page.canonical_url_normalized, "page_url": page.comparable_url},
            ))

        if page.noindex:
            issues.append(self._issue(
                page,
                "noindex_page",
                "Noindex page",
                "Page has a noindex directive.",
                "Remove noindex if this page should be eligible for search indexing.",
                SEOIssueSeverity.high,
                SEOIssueCategory.technical,
            ))

        return issues

    def _page_link_rules(self, page: AuditPage, links: List[AuditLink]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        broken_links = [
            link for link in links
            if link.source_page_id == page.id
            and link.link_type == "internal"
            and (link.is_broken or (link.status_code is not None and link.status_code >= 400))
        ]
        if broken_links:
            issues.append(self._issue(
                page,
                "broken_internal_links",
                "Broken internal links",
                f"Page has {len(broken_links)} broken internal links.",
                "Fix or remove broken internal links.",
                SEOIssueSeverity.critical,
                SEOIssueCategory.links,
                {"broken_internal_links": len(broken_links)},
            ))

        if page.external_links > EXCESSIVE_EXTERNAL_LINKS:
            issues.append(self._issue(
                page,
                "excessive_external_links",
                "Excessive external links",
                f"Page has {page.external_links} external links.",
                "Review external links and keep only links that support the page goal.",
                SEOIssueSeverity.low,
                SEOIssueCategory.links,
                {"external_links": page.external_links, "threshold": EXCESSIVE_EXTERNAL_LINKS},
            ))
        return issues

    def _page_schema_rules(self, page: AuditPage) -> List[DetectedIssue]:
        if page.has_schema_markup:
            return []
        return [self._issue(
            page,
            "missing_schema",
            "Missing schema",
            "Page does not include structured data.",
            "Add relevant JSON-LD schema for the page type.",
            SEOIssueSeverity.low,
            SEOIssueCategory.schema,
        )]

    def _duplicate_title_rules(self, pages: List[AuditPage]) -> List[DetectedIssue]:
        groups = self._groups_by_text(pages, lambda page: page.title)
        issues: List[DetectedIssue] = []
        for title, group in groups.items():
            if len(group) <= 1:
                continue
            for page in group:
                issues.append(self._issue(
                    page,
                    "duplicate_title",
                    "Duplicate title",
                    f"Title is shared by {len(group)} crawled pages.",
                    "Write a unique title that reflects this page's primary topic.",
                    SEOIssueSeverity.high,
                    SEOIssueCategory.metadata,
                    {"title": title, "duplicate_count": len(group)},
                ))
        return issues

    def _duplicate_meta_description_rules(self, pages: List[AuditPage]) -> List[DetectedIssue]:
        groups = self._groups_by_text(pages, lambda page: page.meta_description)
        issues: List[DetectedIssue] = []
        for meta, group in groups.items():
            if len(group) <= 1:
                continue
            for page in group:
                issues.append(self._issue(
                    page,
                    "duplicate_meta_description",
                    "Duplicate meta description",
                    f"Meta description is shared by {len(group)} crawled pages.",
                    "Write a unique meta description for this page.",
                    SEOIssueSeverity.medium,
                    SEOIssueCategory.metadata,
                    {"duplicate_count": len(group), "meta_description": meta},
                ))
        return issues

    def _score_pages(self, pages: List[AuditPage], issues: List[DetectedIssue]) -> List[PageScore]:
        issues_by_page: Dict[UUID, List[DetectedIssue]] = defaultdict(list)
        for issue in issues:
            if issue.page_id:
                issues_by_page[issue.page_id].append(issue)

        scores = []
        for page in pages:
            page_issues = issues_by_page[page.id]
            score_loss = sum(issue.score_impact for issue in page_issues)
            severity_counts = Counter(issue.severity.value for issue in page_issues)
            score = max(0, 100 - score_loss)
            scores.append(PageScore(
                page_id=page.id,
                url=page.url,
                score=score,
                issue_count=len(page_issues),
                severity_counts={
                    "critical": severity_counts.get("critical", 0),
                    "high": severity_counts.get("high", 0),
                    "medium": severity_counts.get("medium", 0),
                    "low": severity_counts.get("low", 0),
                },
                score_breakdown={
                    "base_score": 100,
                    "score_loss": score_loss,
                    "issues_by_severity": dict(severity_counts),
                },
            ))
        return scores

    def _site_score(self, page_scores: List[PageScore]) -> int:
        if not page_scores:
            return 0
        return round(sum(score.score for score in page_scores) / len(page_scores))

    def _incoming_internal_counts(
        self,
        pages: List[AuditPage],
        links: List[AuditLink],
    ) -> Dict[UUID, int]:
        page_by_url = {page.comparable_url: page for page in pages}
        counts: Dict[UUID, int] = defaultdict(int)
        for page in pages:
            counts[page.id] = 0
        for link in links:
            if link.link_type != "internal" or not link.normalized_url:
                continue
            target = page_by_url.get(URLNormalizer.normalize_url(link.normalized_url) or link.normalized_url)
            if target and target.id != link.source_page_id:
                counts[target.id] += 1
        return counts

    def _groups_by_text(self, pages: List[AuditPage], getter) -> Dict[str, List[AuditPage]]:
        groups: Dict[str, List[AuditPage]] = defaultdict(list)
        for page in pages:
            value = (getter(page) or "").strip().lower()
            if value:
                groups[value].append(page)
        return groups

    def _count_by(self, issues: List[DetectedIssue], attr: str) -> Dict[str, int]:
        counter = Counter(getattr(issue, attr).value for issue in issues)
        return dict(counter)

    def _issue(
        self,
        page: AuditPage,
        issue_type: str,
        title: str,
        message: str,
        recommendation: str,
        severity: SEOIssueSeverity,
        category: SEOIssueCategory,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> DetectedIssue:
        return DetectedIssue(
            page_id=page.id,
            url=page.url,
            issue_type=issue_type,
            title=title,
            message=message,
            recommendation=recommendation,
            severity=severity,
            category=category,
            evidence=evidence or {},
        )
