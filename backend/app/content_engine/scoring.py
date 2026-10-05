"""Opportunity scoring and cannibalisation detection — pure functions, no I/O.

Kept free of the database and of every network call so the scoring rules can be
read, reasoned about and tested on their own. The service layer fetches; this
module decides.

**Why there is no search volume here.** Volume, keyword difficulty and
competitor rankings are not obtainable for free at any useful accuracy, and the
project's rule is that a number nobody measured is never shown as if somebody
had. So nothing in this file estimates how many people search for a phrase.

What it computes instead is an **Opportunity Score**: a transparent 0-100
ranking built only from signals this deployment genuinely holds — the site's
own Search Console impressions, clicks, CTR and average position, whether a
page already covers the topic, and how close the phrase sits to what the
business actually sells. It answers "which of the things we already appear for
is most worth working on", which is the question that matters, and it answers it
from measurements rather than from a vendor's model.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "OpportunitySignals",
    "score_opportunity",
    "expected_ctr",
    "normalise_phrase",
    "phrase_tokens",
    "similarity",
    "find_cannibalisation",
    "classify_performance",
    "SCORE_WEIGHTS",
]


# ---------------------------------------------------------------------------
# Position → expected CTR
# ---------------------------------------------------------------------------

#: Rough click-through rate by Google position, used only to judge whether a page
#: under-performs *relative to where it already ranks*. These are public,
#: widely-replicated industry averages, not a measurement of this site, and
#: they are used for ranking opportunities against each other — never shown to
#: anyone as this site's predicted traffic.
_CTR_BY_POSITION = {
    1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.06,
    6: 0.05, 7: 0.04, 8: 0.03, 9: 0.028, 10: 0.025,
}


def expected_ctr(position: Optional[float]) -> float:
    """The CTR a page at this position would typically see."""
    if position is None or position <= 0:
        return 0.0
    rounded = int(round(position))
    if rounded in _CTR_BY_POSITION:
        return _CTR_BY_POSITION[rounded]
    if rounded < 1:
        return _CTR_BY_POSITION[1]
    # Beyond the first page CTR decays slowly towards nothing.
    return max(0.001, 0.025 * math.exp(-0.12 * (rounded - 10)))


# ---------------------------------------------------------------------------
# Phrase handling
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")

#: Words that carry no topical meaning when comparing two phrases.
_STOPWORDS = frozenset(
    """a an the and or but of for to in on at by with from as is are was were be been
    how what why when where which who whom this that these those it its your you we our
    us i me my best top good great vs versus near""".split()
)


def normalise_phrase(value: str) -> str:
    return " ".join(_WORD.findall((value or "").lower()))


def phrase_tokens(value: str) -> frozenset:
    """Meaning-bearing tokens of a phrase."""
    return frozenset(t for t in _WORD.findall((value or "").lower()) if t not in _STOPWORDS)


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of two phrases' meaningful tokens, 0.0-1.0.

    Deliberately not an embedding. Cannibalisation is about two pages chasing
    the *same words*, the comparison has to be explainable to whoever is told
    their article is a duplicate, and this runs on thousands of pairs without
    touching a model.
    """
    a, b = phrase_tokens(left), phrase_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Opportunity score
# ---------------------------------------------------------------------------

#: What each signal is worth. Exposed so the dashboard can show the formula
#: rather than presenting the score as a black box.
SCORE_WEIGHTS: Dict[str, int] = {
    "demand": 30,        # measured impressions — real interest, already observed
    "position": 25,      # how winnable the current ranking is
    "ctr_gap": 20,       # clicks being left on the table at the current position
    "coverage": 15,      # whether a page already addresses this
    "business_value": 10,  # closeness to what the business actually sells
}


@dataclass
class OpportunitySignals:
    """Everything known about one candidate topic. All of it measured."""

    query: str
    impressions: int = 0
    clicks: int = 0
    ctr: Optional[float] = None
    position: Optional[float] = None
    #: True when an existing page already targets this intent.
    has_covering_page: bool = False
    #: Overlap with the project's stated services/keywords, 0.0-1.0.
    business_relevance: float = 0.0
    #: Only ever None. Reserved for a future provider; never invented.
    search_volume: Optional[int] = None


@dataclass
class ScoredOpportunity:
    query: str
    score: int
    #: Per-signal contribution, so the UI can explain the number.
    breakdown: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    #: Always None without a paid provider. Present so nothing downstream has
    #: to special-case its absence — and so it is never silently filled in.
    search_volume: Optional[int] = None
    estimated: bool = True


def _demand_points(impressions: int) -> int:
    """Impressions on a log curve: 10 → some, 100 → most, 10,000 → all.

    Linear scaling would let one huge query flatten every other candidate to
    zero, which is how a content plan ends up with twelve articles about the
    same thing.
    """
    if impressions <= 0:
        return 0
    return int(min(SCORE_WEIGHTS["demand"], SCORE_WEIGHTS["demand"] * math.log10(1 + impressions) / 4))


def _position_points(position: Optional[float]) -> Tuple[int, str]:
    """Positions 4-20 score highest — close enough to move, far enough to gain."""
    weight = SCORE_WEIGHTS["position"]
    if position is None or position <= 0:
        return 0, ""
    if position < 4:
        # Already winning; little headroom left.
        return int(weight * 0.25), f"already ranks {position:.1f}"
    if position <= 10:
        return weight, f"ranks {position:.1f} — page one, within reach of the top"
    if position <= 20:
        return int(weight * 0.8), f"ranks {position:.1f} — page two, a realistic target"
    if position <= 40:
        return int(weight * 0.4), f"ranks {position:.1f} — needs real work"
    return int(weight * 0.15), f"ranks {position:.1f} — a long way back"


def _ctr_gap_points(signals: OpportunitySignals) -> Tuple[int, str]:
    """Clicks being lost at the position the page already holds."""
    weight = SCORE_WEIGHTS["ctr_gap"]
    if not signals.impressions or signals.position is None:
        return 0, ""
    expected = expected_ctr(signals.position)
    actual = signals.ctr if signals.ctr is not None else (
        signals.clicks / signals.impressions if signals.impressions else 0.0
    )
    if expected <= 0 or actual >= expected:
        return 0, ""
    shortfall = (expected - actual) / expected
    points = int(weight * min(1.0, shortfall))
    if points <= 0:
        return 0, ""
    missed = int(signals.impressions * (expected - actual))
    return points, (
        f"CTR {actual:.1%} against about {expected:.1%} typical at this position"
        + (f" — roughly {missed} clicks a period unrealised" if missed > 0 else "")
    )


def score_opportunity(signals: OpportunitySignals) -> ScoredOpportunity:
    """Rank one candidate topic. Never invents a number it was not given."""
    breakdown: Dict[str, int] = {}
    reasons: List[str] = []

    breakdown["demand"] = _demand_points(signals.impressions)
    if signals.impressions > 0:
        reasons.append(f"{signals.impressions:,} impressions already measured in Search Console")

    position_points, position_reason = _position_points(signals.position)
    breakdown["position"] = position_points
    if position_reason:
        reasons.append(position_reason)

    ctr_points, ctr_reason = _ctr_gap_points(signals)
    breakdown["ctr_gap"] = ctr_points
    if ctr_reason:
        reasons.append(ctr_reason)

    if signals.has_covering_page:
        breakdown["coverage"] = 0
        reasons.append("a page already covers this — update it rather than writing another")
    else:
        breakdown["coverage"] = SCORE_WEIGHTS["coverage"]
        reasons.append("no existing page targets this")

    breakdown["business_value"] = int(
        SCORE_WEIGHTS["business_value"] * max(0.0, min(1.0, signals.business_relevance))
    )
    if signals.business_relevance >= 0.5:
        reasons.append("close to what the business sells")

    return ScoredOpportunity(
        query=signals.query,
        score=int(min(100, sum(breakdown.values()))),
        breakdown=breakdown,
        reasons=reasons,
        search_volume=None,  # never fabricated
        estimated=True,
    )


# ---------------------------------------------------------------------------
# Cannibalisation
# ---------------------------------------------------------------------------

#: Above this overlap two topics are competing for the same search.
CANNIBAL_THRESHOLD = 0.6


@dataclass
class CannibalMatch:
    existing: str
    overlap: float
    reference: Optional[str] = None


def find_cannibalisation(
    candidate: str,
    existing: Iterable[Tuple[str, Optional[str]]],
    *,
    threshold: float = CANNIBAL_THRESHOLD,
) -> Optional[CannibalMatch]:
    """The closest existing topic that already targets this intent.

    Returning the *closest* match rather than the first lets the caller say
    which article to update, which is the only useful form of this answer.
    """
    best: Optional[CannibalMatch] = None
    for title, reference in existing:
        overlap = similarity(candidate, title)
        if overlap >= threshold and (best is None or overlap > best.overlap):
            best = CannibalMatch(existing=title, overlap=round(overlap, 3), reference=reference)
    return best


# ---------------------------------------------------------------------------
# Published-article performance
# ---------------------------------------------------------------------------

def classify_performance(
    *,
    impressions: int,
    clicks: int,
    position: Optional[float],
    previous_impressions: Optional[int] = None,
    days_since_published: Optional[int] = None,
) -> Tuple[str, str]:
    """Label a published article from measurements, or decline to.

    The first branch matters most: an article with almost no data is
    `NO_DATA_YET`, never `UNDERPERFORMING`. Judging a two-week-old post as a
    failure is how a content programme deletes the things that were about to
    work.
    """
    if days_since_published is not None and days_since_published < 21:
        return "NO_DATA_YET", "Published too recently to judge — Google needs a few weeks."
    if impressions < 20:
        return "NO_DATA_YET", "Not enough impressions yet to say anything honest."

    if previous_impressions and previous_impressions >= 20:
        change = (impressions - previous_impressions) / previous_impressions
        if change <= -0.3:
            return "NEEDS_UPDATE", (
                f"Impressions fell {abs(change):.0%} against the previous period."
            )
        if change >= 0.2:
            return "GROWING", f"Impressions up {change:.0%} against the previous period."

    if position is not None and position <= 10 and clicks > 0:
        return "PERFORMING", f"Ranking {position:.1f} and earning clicks."
    if position is not None and position > 30:
        return "UNDERPERFORMING", f"Ranking {position:.1f} — outside the first three pages."
    if impressions >= 100 and clicks == 0:
        return "UNDERPERFORMING", "Seen in search but never clicked — the title and description are not earning the visit."
    return "PERFORMING", "Holding steady."


def business_relevance(query: str, terms: Sequence[str]) -> float:
    """How close a phrase sits to what the business says it sells, 0.0-1.0."""
    if not terms:
        return 0.0
    return max((similarity(query, term) for term in terms if term), default=0.0)
