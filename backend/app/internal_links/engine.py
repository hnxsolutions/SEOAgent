"""Pure deterministic internal link recommendation rules."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from uuid import UUID
from urllib.parse import urlparse, unquote

from app.core.url_utils import URLNormalizer
from app.models.internal_linking import InternalLinkRecommendationType


WEAK_INBOUND_LINKS = 2
TOO_FEW_INTERNAL_LINKS = 3
EXCESSIVE_INTERNAL_LINKS = 150
MIN_SEMANTIC_SIMILARITY = 0.62
MAX_RECOMMENDATIONS_PER_SOURCE = 5


@dataclass(frozen=True)
class LinkPage:
    id: UUID
    url: str
    normalized_url: Optional[str] = None
    title: Optional[str] = None
    h1: List[str] = field(default_factory=list)
    word_count: int = 0
    internal_links: int = 0
    depth: int = 0
    text_content: Optional[str] = None

    @property
    def comparable_url(self) -> str:
        return self.normalized_url or URLNormalizer.normalize_url(self.url) or self.url


@dataclass(frozen=True)
class LinkEdge:
    source_page_id: UUID
    normalized_url: Optional[str]
    link_text: Optional[str] = None
    link_type: str = "internal"


@dataclass(frozen=True)
class AuditSignal:
    page_id: UUID
    issue_type: str


@dataclass(frozen=True)
class SemanticPair:
    source_page_id: UUID
    target_page_id: UUID
    similarity: float
    context_snippet: Optional[str] = None


@dataclass(frozen=True)
class LinkRecommendationCandidate:
    source_page_id: UUID
    source_url: str
    target_page_id: UUID
    target_url: str
    suggested_anchor_text: str
    suggested_context_snippet: Optional[str]
    reason: str
    confidence_score: float
    priority_score: float
    recommendation_type: InternalLinkRecommendationType
    semantic_similarity: Optional[float]
    evidence: Dict[str, object]


RecommendationKey = Tuple[UUID, UUID, InternalLinkRecommendationType]


class InternalLinkRulesEngine:
    """Generate deterministic internal link recommendations from graph signals."""

    def generate(
        self,
        pages: Iterable[LinkPage],
        links: Iterable[LinkEdge],
        audit_signals: Iterable[AuditSignal],
        semantic_pairs: Iterable[SemanticPair],
        existing_recommendation_keys: Optional[Set[RecommendationKey]] = None,
        limit: int = 100,
    ) -> List[LinkRecommendationCandidate]:
        page_list = list(pages)
        link_list = [link for link in links if (link.link_type or "internal") == "internal"]
        audit_list = list(audit_signals)
        page_by_id = {page.id: page for page in page_list}
        page_by_url = {page.comparable_url: page for page in page_list}
        incoming_counts, outgoing_counts = self._link_counts(page_list, link_list, page_by_url)
        existing_pairs = self._existing_link_pairs(link_list, page_by_url)
        anchor_counts = Counter((link.link_text or "").strip().lower() for link in link_list if (link.link_text or "").strip())
        audit_by_page = self._audit_by_page(audit_list)
        existing_recommendation_keys = existing_recommendation_keys or set()

        candidates: List[LinkRecommendationCandidate] = []
        seen_keys: Set[RecommendationKey] = set()

        for pair in sorted(semantic_pairs, key=lambda item: item.similarity, reverse=True):
            if pair.similarity < MIN_SEMANTIC_SIMILARITY:
                continue
            source = page_by_id.get(pair.source_page_id)
            target = page_by_id.get(pair.target_page_id)
            if not source or not target:
                continue
            candidate = self._build_candidate(
                source=source,
                target=target,
                similarity=pair.similarity,
                context_snippet=pair.context_snippet,
                incoming_counts=incoming_counts,
                outgoing_counts=outgoing_counts,
                existing_pairs=existing_pairs,
                anchor_counts=anchor_counts,
                audit_issue_types=audit_by_page.get(target.id, set()),
                seen_keys=seen_keys,
                existing_recommendation_keys=existing_recommendation_keys,
            )
            if candidate:
                candidates.append(candidate)

        candidates.extend(self._fallback_support_candidates(
            page_list,
            incoming_counts,
            outgoing_counts,
            existing_pairs,
            anchor_counts,
            audit_by_page,
            seen_keys,
            existing_recommendation_keys,
        ))

        candidates = self._limit_per_source(candidates)
        candidates.sort(key=lambda item: (item.priority_score, item.confidence_score), reverse=True)
        return candidates[:limit]

    def summary(
        self,
        pages: Iterable[LinkPage],
        links: Iterable[LinkEdge],
        recommendations: Iterable[object],
    ) -> Dict[str, object]:
        page_list = list(pages)
        link_list = [link for link in links if (link.link_type or "internal") == "internal"]
        page_by_url = {page.comparable_url: page for page in page_list}
        incoming_counts, outgoing_counts = self._link_counts(page_list, link_list, page_by_url)
        anchor_counts = Counter((link.link_text or "").strip().lower() for link in link_list if (link.link_text or "").strip())
        rec_list = list(recommendations)

        return {
            "total_pages": len(page_list),
            "orphan_pages": sum(1 for page in page_list if page.depth != 0 and incoming_counts[page.id] == 0),
            "weakly_linked_pages": sum(1 for page in page_list if 0 < incoming_counts[page.id] < WEAK_INBOUND_LINKS),
            "pages_with_too_few_internal_links": sum(1 for page in page_list if outgoing_counts[page.id] < TOO_FEW_INTERNAL_LINKS),
            "pages_with_excessive_internal_links": sum(1 for page in page_list if outgoing_counts[page.id] > EXCESSIVE_INTERNAL_LINKS),
            "duplicate_anchor_text_risks": sum(1 for count in anchor_counts.values() if count >= 5),
            "total_recommendations": len(rec_list),
            "average_priority_score": self._average([float(getattr(rec, "priority_score", 0) or 0) for rec in rec_list]),
        }

    def _build_candidate(
        self,
        source: LinkPage,
        target: LinkPage,
        similarity: Optional[float],
        context_snippet: Optional[str],
        incoming_counts: Dict[UUID, int],
        outgoing_counts: Dict[UUID, int],
        existing_pairs: Set[Tuple[UUID, UUID]],
        anchor_counts: Counter,
        audit_issue_types: Set[str],
        seen_keys: Set[RecommendationKey],
        existing_recommendation_keys: Set[RecommendationKey],
    ) -> Optional[LinkRecommendationCandidate]:
        if source.id == target.id or source.comparable_url == target.comparable_url:
            return None
        if (source.id, target.id) in existing_pairs:
            return None
        if outgoing_counts[source.id] > EXCESSIVE_INTERNAL_LINKS:
            return None

        recommendation_type = self._recommendation_type(source, target, incoming_counts, outgoing_counts, audit_issue_types)
        key = (source.id, target.id, recommendation_type)
        if key in seen_keys or key in existing_recommendation_keys:
            return None

        anchor = self.suggest_anchor_text(target)
        anchor_count = anchor_counts.get(anchor.lower(), 0)
        confidence_score = self._confidence_score(source, similarity, anchor_count)
        priority_score = self._priority_score(source, target, incoming_counts, outgoing_counts, audit_issue_types, similarity, anchor_count)
        if priority_score <= 0:
            return None

        seen_keys.add(key)
        reason_parts = self._reason_parts(
            recommendation_type,
            target,
            incoming_counts[target.id],
            similarity,
            audit_issue_types,
            anchor_count,
        )

        return LinkRecommendationCandidate(
            source_page_id=source.id,
            source_url=source.url,
            target_page_id=target.id,
            target_url=target.url,
            suggested_anchor_text=anchor,
            suggested_context_snippet=context_snippet or self._context_snippet(source),
            reason=" ".join(reason_parts),
            confidence_score=round(confidence_score, 2),
            priority_score=round(priority_score, 2),
            recommendation_type=recommendation_type,
            semantic_similarity=round(similarity, 4) if similarity is not None else None,
            evidence={
                "incoming_internal_links": incoming_counts[target.id],
                "source_internal_links": outgoing_counts[source.id],
                "source_word_count": source.word_count,
                "target_depth": target.depth,
                "audit_issue_types": sorted(audit_issue_types),
                "anchor_existing_count": anchor_count,
            },
        )

    def _fallback_support_candidates(
        self,
        pages: List[LinkPage],
        incoming_counts: Dict[UUID, int],
        outgoing_counts: Dict[UUID, int],
        existing_pairs: Set[Tuple[UUID, UUID]],
        anchor_counts: Counter,
        audit_by_page: Dict[UUID, Set[str]],
        seen_keys: Set[RecommendationKey],
        existing_recommendation_keys: Set[RecommendationKey],
    ) -> List[LinkRecommendationCandidate]:
        targets = [
            page for page in pages
            if page.depth != 0 and incoming_counts[page.id] < WEAK_INBOUND_LINKS
        ]
        sources = sorted(
            pages,
            key=lambda page: (page.word_count, -page.depth, -outgoing_counts[page.id]),
            reverse=True,
        )
        candidates: List[LinkRecommendationCandidate] = []
        for target in targets:
            for source in sources:
                if source.id == target.id:
                    continue
                candidate = self._build_candidate(
                    source=source,
                    target=target,
                    similarity=None,
                    context_snippet=None,
                    incoming_counts=incoming_counts,
                    outgoing_counts=outgoing_counts,
                    existing_pairs=existing_pairs,
                    anchor_counts=anchor_counts,
                    audit_issue_types=audit_by_page.get(target.id, set()),
                    seen_keys=seen_keys,
                    existing_recommendation_keys=existing_recommendation_keys,
                )
                if candidate:
                    candidates.append(candidate)
                    break
        return candidates

    def _recommendation_type(
        self,
        source: LinkPage,
        target: LinkPage,
        incoming_counts: Dict[UUID, int],
        outgoing_counts: Dict[UUID, int],
        audit_issue_types: Set[str],
    ) -> InternalLinkRecommendationType:
        if audit_issue_types.intersection({"orphan_page", "weak_internal_link_depth", "thin_content"}):
            return InternalLinkRecommendationType.audit_issue_support
        if target.depth != 0 and incoming_counts[target.id] == 0:
            return InternalLinkRecommendationType.orphan_support
        if incoming_counts[target.id] < WEAK_INBOUND_LINKS:
            return InternalLinkRecommendationType.weak_page_support
        if source.depth <= 1 and outgoing_counts[source.id] >= TOO_FEW_INTERNAL_LINKS and target.depth >= source.depth:
            return InternalLinkRecommendationType.hub_spoke
        return InternalLinkRecommendationType.semantic_related

    def _priority_score(
        self,
        source: LinkPage,
        target: LinkPage,
        incoming_counts: Dict[UUID, int],
        outgoing_counts: Dict[UUID, int],
        audit_issue_types: Set[str],
        similarity: Optional[float],
        anchor_count: int,
    ) -> float:
        score = 0.0
        inbound = incoming_counts[target.id]
        if target.depth != 0 and inbound == 0:
            score += 35
        elif inbound < WEAK_INBOUND_LINKS:
            score += 25
        elif inbound < 4:
            score += 10

        if audit_issue_types:
            score += 15
        if target.depth >= 3:
            score += 10
        if target.word_count >= 300:
            score += 8
        if similarity is not None:
            score += similarity * 30
        if source.word_count >= 300:
            score += 10
        elif source.word_count < 80:
            score -= 8
        if outgoing_counts[source.id] < TOO_FEW_INTERNAL_LINKS:
            score += 5
        if outgoing_counts[source.id] > 75:
            score -= 10
        if anchor_count >= 5:
            score -= 10
        return max(0, min(100, score))

    def _confidence_score(self, source: LinkPage, similarity: Optional[float], anchor_count: int) -> float:
        score = 45.0
        if similarity is not None:
            score = similarity * 75
        if source.word_count >= 150:
            score += 12
        elif source.word_count < 50:
            score -= 12
        if anchor_count == 0:
            score += 8
        elif anchor_count >= 5:
            score -= 12
        return max(0, min(100, score))

    def suggest_anchor_text(self, target: LinkPage) -> str:
        generic = {"home", "homepage", "quotes to scrape", "untitled", "login"}
        heading = next((value.strip() for value in target.h1 if str(value).strip()), "")
        if heading and heading.lower() not in generic:
            return self._clean_anchor(heading)

        title = (target.title or "").strip()
        if title and title.lower() not in generic:
            return self._clean_anchor(title)

        parsed = urlparse(target.url)
        generic_slug_parts = {"page", "pages", "tag", "tags", "category", "categories", "author", "authors"}
        slug_parts = [
            part for part in parsed.path.split("/")
            if part and not part.isdigit() and part.lower() not in generic_slug_parts
        ]
        if slug_parts:
            slug = unquote(slug_parts[-1]).replace("-", " ").replace("_", " ")
            return self._clean_anchor(slug.title())
        return "this page"

    def _clean_anchor(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned[:255] or "this page"

    def _link_counts(
        self,
        pages: List[LinkPage],
        links: List[LinkEdge],
        page_by_url: Dict[str, LinkPage],
    ) -> Tuple[Dict[UUID, int], Dict[UUID, int]]:
        incoming: Dict[UUID, int] = defaultdict(int)
        outgoing: Dict[UUID, int] = defaultdict(int)
        for page in pages:
            incoming[page.id] = 0
            outgoing[page.id] = 0

        for link in links:
            outgoing[link.source_page_id] += 1
            target = self._target_page(link, page_by_url)
            if target and target.id != link.source_page_id:
                incoming[target.id] += 1
        return incoming, outgoing

    def _existing_link_pairs(
        self,
        links: List[LinkEdge],
        page_by_url: Dict[str, LinkPage],
    ) -> Set[Tuple[UUID, UUID]]:
        pairs: Set[Tuple[UUID, UUID]] = set()
        for link in links:
            target = self._target_page(link, page_by_url)
            if target:
                pairs.add((link.source_page_id, target.id))
        return pairs

    def _target_page(self, link: LinkEdge, page_by_url: Dict[str, LinkPage]) -> Optional[LinkPage]:
        if not link.normalized_url:
            return None
        normalized = URLNormalizer.normalize_url(link.normalized_url) or link.normalized_url
        return page_by_url.get(normalized)

    def _audit_by_page(self, signals: List[AuditSignal]) -> Dict[UUID, Set[str]]:
        values: Dict[UUID, Set[str]] = defaultdict(set)
        for signal in signals:
            values[signal.page_id].add(signal.issue_type)
        return values

    def _reason_parts(
        self,
        recommendation_type: InternalLinkRecommendationType,
        target: LinkPage,
        inbound_links: int,
        similarity: Optional[float],
        audit_issue_types: Set[str],
        anchor_count: int,
    ) -> List[str]:
        parts = []
        if recommendation_type == InternalLinkRecommendationType.orphan_support:
            parts.append("Target page is orphaned and needs an internal path.")
        elif recommendation_type == InternalLinkRecommendationType.weak_page_support:
            parts.append(f"Target page has only {inbound_links} internal inbound links.")
        elif recommendation_type == InternalLinkRecommendationType.hub_spoke:
            parts.append("Source can act as a hub for this related target.")
        elif recommendation_type == InternalLinkRecommendationType.audit_issue_support:
            parts.append("Target has internal-linking related SEO audit signals.")
        else:
            parts.append("Pages are semantically related and do not already link.")

        if similarity is not None:
            parts.append(f"Semantic similarity is {similarity:.2f}.")
        if target.depth >= 3:
            parts.append(f"Target is deep in the crawl at depth {target.depth}.")
        if audit_issue_types:
            parts.append(f"Audit signals: {', '.join(sorted(audit_issue_types))}.")
        if anchor_count >= 5:
            parts.append("Suggested anchor text is already used often, so priority was reduced.")
        return parts

    def _context_snippet(self, source: LinkPage) -> Optional[str]:
        text = re.sub(r"\s+", " ", (source.text_content or "").strip())
        if not text:
            return None
        return text[:300]

    def _limit_per_source(self, candidates: List[LinkRecommendationCandidate]) -> List[LinkRecommendationCandidate]:
        kept: List[LinkRecommendationCandidate] = []
        source_counts: Counter = Counter()
        for candidate in sorted(candidates, key=lambda item: (item.priority_score, item.confidence_score), reverse=True):
            if source_counts[candidate.source_page_id] >= MAX_RECOMMENDATIONS_PER_SOURCE:
                continue
            source_counts[candidate.source_page_id] += 1
            kept.append(candidate)
        return kept

    def _average(self, values: List[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)
