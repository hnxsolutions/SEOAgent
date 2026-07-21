"""Pure growth analysis (no I/O, fully testable)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Intent signal words.
_QUESTION = ("how", "what", "why", "when", "where", "who", "which", "can", "does", "is", "are")
_COMMERCIAL = ("best", "top", "review", "compare", "comparison", "vs", "alternative", "cheap", "affordable")
_TRANSACTIONAL = ("buy", "price", "pricing", "cost", "order", "book", "hire", "quote", "deal", "discount", "near me", "for sale")
_LOCAL = ("near me", "in ", "nearby", "local")


def classify_intent(keyword: str, brand_terms: Optional[List[str]] = None) -> str:
    """Return one of: brand / question / transactional / commercial / local /
    navigational / informational / long_tail (long_tail is length-based)."""
    kw = (keyword or "").strip().lower()
    if not kw:
        return "informational"
    brand_terms = [b.lower() for b in (brand_terms or []) if b]
    if any(b and b in kw for b in brand_terms):
        return "brand"
    words = kw.split()
    if words[0] in _QUESTION or kw.endswith("?"):
        return "question"
    if any(t in kw for t in _TRANSACTIONAL):
        return "transactional"
    if any(kw.startswith(c + " ") or f" {c} " in f" {kw} " for c in _COMMERCIAL):
        return "commercial"
    if any(t in kw for t in _LOCAL):
        return "local"
    if len(words) >= 4:
        return "long_tail"
    return "informational"


def keyword_difficulty(position: Optional[int], search_volume: Optional[int]) -> str:
    """Heuristic difficulty from current position + volume (no external API).
    Ranking already (pos<=20) or low volume => easier to win."""
    if position is not None and position <= 10:
        return "low"
    if position is not None and position <= 20:
        return "medium"
    if search_volume is not None and search_volume >= 5000:
        return "high"
    if search_volume is not None and search_volume >= 500:
        return "medium"
    return "medium"


def priority_score(*, intent: str, difficulty: str, impressions: Optional[int] = None,
                   position: Optional[int] = None, ctr: Optional[float] = None) -> int:
    """0-100 priority. Commercial/transactional intent, high impressions with low
    CTR, and near-page-1 positions score highest (fastest wins)."""
    score = 40
    score += {"transactional": 25, "commercial": 20, "local": 15, "question": 10,
              "long_tail": 12, "brand": 8, "informational": 5, "navigational": 3}.get(intent, 5)
    score += {"low": 20, "medium": 10, "high": 0}.get(difficulty, 5)
    if impressions:
        score += 15 if impressions >= 1000 else 8 if impressions >= 100 else 3
    if position is not None and 4 <= position <= 20:
        score += 12  # striking distance
    if ctr is not None and impressions and impressions >= 100 and ctr < 0.02:
        score += 10  # high impressions, low CTR = quick metadata win
    return max(0, min(100, score))


def estimate_traffic(impressions: Optional[int], position: Optional[float],
                     current_ctr: Optional[float] = None) -> Dict[str, Any]:
    """ESTIMATED monthly click uplift if the keyword reaches page 1. Uses a
    standard position->CTR curve. Clearly labelled as an estimate — never a
    measured value."""
    # Rough organic CTR by position (industry-standard curve).
    target_ctr = 0.28  # ~position 1-3 average
    if impressions is None:
        return {"is_estimate": True, "estimated_monthly_clicks": None,
                "note": "No impression data yet — connect Search Console for a real estimate."}
    current = current_ctr if current_ctr is not None else 0.0
    uplift = max(0.0, target_ctr - current)
    est_clicks = int(round(impressions * uplift))
    return {
        "is_estimate": True,
        "estimated_monthly_clicks": est_clicks,
        "assumption": f"Assumes reaching page 1 (~{int(target_ctr*100)}% CTR) from current {round(current*100,1)}% CTR.",
        "note": "Estimate only. Real results depend on ranking, competition and content quality.",
    }


def _framework_schema(framework_key: Optional[str]) -> str:
    fw = (framework_key or "").lower()
    if fw in ("nextjs", "nuxt", "astro", "sveltekit", "gatsby", "react", "vue"):
        return "Article JSON-LD in a server component / head (framework metadata API)"
    if fw == "wordpress":
        return "Article schema via Yoast / Rank Math"
    if fw == "shopify":
        return "Article JSON-LD in the blog Liquid template"
    if fw == "laravel":
        return "Article JSON-LD partial in the Blade layout"
    if fw == "django":
        return "Article JSON-LD block in the base template"
    return "Article JSON-LD <script> in the page head"


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "post"


def suggest_blog_post(topic: str, target_keyword: str, *, framework_key: Optional[str],
                      domain: str, secondary: Optional[List[str]] = None,
                      internal_targets: Optional[List[str]] = None) -> Dict[str, Any]:
    """Framework-aware, SEO-safe blog suggestion (a plan, not code that ships)."""
    origin = domain if domain.startswith("http") else "https://" + (domain or "")
    origin = origin.rstrip("/")
    slug = _slugify(target_keyword or topic)
    intent = classify_intent(target_keyword or topic)
    title = topic if len(topic) <= 60 else topic[:57] + "…"
    return {
        "topic": topic,
        "target_keyword": target_keyword,
        "secondary_keywords": (secondary or [])[:5],
        "search_intent": intent,
        "suggested_url": f"{origin}/blog/{slug}",
        "suggested_title": f"{title}".strip(),
        "suggested_h1": topic,
        "suggested_meta": f"{topic} — a clear, practical guide covering {target_keyword} with actionable steps.",
        "suggested_schema": _framework_schema(framework_key),
        "suggested_internal_links": (internal_targets or [])[:5],
    }


def cluster_topics(keywords: List[str], max_clusters: int = 8) -> List[Dict[str, Any]]:
    """Group keywords into topic clusters by their most significant shared word
    (a pillar), with supporting keywords. Deterministic, no ML."""
    stop = {"the", "a", "an", "for", "and", "to", "in", "of", "best", "how", "what",
            "near", "me", "with", "your", "you", "is", "are", "on", "my"}
    buckets: Dict[str, List[str]] = {}
    for kw in keywords:
        words = [w for w in re.split(r"[^a-z0-9]+", (kw or "").lower()) if w and w not in stop]
        if not words:
            continue
        # pillar = longest significant word
        pillar = max(words, key=len)
        buckets.setdefault(pillar, []).append(kw)
    clusters = []
    for pillar, kws in sorted(buckets.items(), key=lambda x: len(x[1]), reverse=True)[:max_clusters]:
        clusters.append({
            "pillar": pillar,
            "pillar_title": pillar.title(),
            "supporting_keywords": sorted(set(kws))[:12],
            "article_count": len(set(kws)),
        })
    return clusters


def growth_score(dimensions: Dict[str, Optional[int]]) -> Dict[str, Any]:
    """Composite 0-100 growth score from measured/estimated growth dimensions."""
    measured = {k: v for k, v in dimensions.items() if v is not None}
    overall = int(round(sum(measured.values()) / len(measured))) if measured else None
    return {
        "overall": overall,
        "dimensions": dimensions,
        "measured_dimensions": len(measured),
    }
