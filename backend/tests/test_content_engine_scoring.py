"""Opportunity scoring, cannibalisation and performance classification.

These are the rules that decide what gets written and what gets judged a
failure, so they are tested directly rather than through the service. The
no-fabrication guarantees are asserted, not assumed: a regression that starts
inventing search volume should fail here first.
"""
import pytest

from app.content_engine.scoring import (
    CANNIBAL_THRESHOLD,
    SCORE_WEIGHTS,
    OpportunitySignals,
    business_relevance,
    classify_performance,
    expected_ctr,
    find_cannibalisation,
    normalise_phrase,
    score_opportunity,
    similarity,
)


# --------------------------------------------------------------------------
# The promise that no number is invented
# --------------------------------------------------------------------------

def test_search_volume_is_never_fabricated():
    """Whatever the signals, volume comes back None."""
    result = score_opportunity(
        OpportunitySignals(query="emergency dentist", impressions=50_000, clicks=900, position=3.0)
    )
    assert result.search_volume is None


def test_score_is_bounded_and_explained():
    result = score_opportunity(
        OpportunitySignals(
            query="emergency dentist chandigarh",
            impressions=100_000,
            clicks=0,
            ctr=0.0,
            position=8.0,
            has_covering_page=False,
            business_relevance=1.0,
        )
    )
    assert 0 <= result.score <= 100
    # Every weighted signal reports its own contribution, so the UI can show
    # the formula rather than a bare number.
    assert set(result.breakdown) == set(SCORE_WEIGHTS)
    assert result.reasons, "a score with no stated reason is not reviewable"


# --------------------------------------------------------------------------
# Ranking behaviour
# --------------------------------------------------------------------------

def test_page_two_beats_already_winning():
    """Position 4-20 is the opportunity; position 1-3 has little left to gain."""
    winnable = score_opportunity(
        OpportunitySignals(query="seo audit service", impressions=1000, clicks=5, ctr=0.005, position=12.0)
    )
    already_won = score_opportunity(
        OpportunitySignals(query="seo audit service", impressions=1000, clicks=280, ctr=0.28, position=1.5)
    )
    assert winnable.score > already_won.score


def test_existing_coverage_removes_the_coverage_points():
    kwargs = dict(query="local seo guide", impressions=500, clicks=10, ctr=0.02, position=9.0)
    uncovered = score_opportunity(OpportunitySignals(**kwargs, has_covering_page=False))
    covered = score_opportunity(OpportunitySignals(**kwargs, has_covering_page=True))

    assert covered.breakdown["coverage"] == 0
    assert uncovered.breakdown["coverage"] == SCORE_WEIGHTS["coverage"]
    assert covered.score < uncovered.score
    assert any("update it" in reason for reason in covered.reasons)


def test_no_demand_data_scores_low_but_not_negative():
    """A content gap with no measured impressions is a weak signal, not a lie."""
    result = score_opportunity(OpportunitySignals(query="a topic nobody has searched"))
    assert result.breakdown["demand"] == 0
    assert result.score >= 0


def test_ctr_gap_rewards_underperforming_positions():
    poor = score_opportunity(
        OpportunitySignals(query="x", impressions=2000, clicks=4, ctr=0.002, position=5.0)
    )
    healthy = score_opportunity(
        OpportunitySignals(query="x", impressions=2000, clicks=120, ctr=0.06, position=5.0)
    )
    assert poor.breakdown["ctr_gap"] > healthy.breakdown["ctr_gap"]
    assert healthy.breakdown["ctr_gap"] == 0


def test_expected_ctr_decays_with_position():
    assert expected_ctr(1) > expected_ctr(5) > expected_ctr(10) > expected_ctr(30)
    assert expected_ctr(None) == 0.0
    assert expected_ctr(0) == 0.0


# --------------------------------------------------------------------------
# Cannibalisation
# --------------------------------------------------------------------------

def test_similarity_ignores_stopwords_and_order():
    assert similarity("the best SEO guide", "SEO guide") == pytest.approx(1.0)
    assert similarity("seo guide", "pricing page") == 0.0


def test_finds_the_closest_duplicate_not_the_first():
    match = find_cannibalisation(
        "local seo guide for small businesses",
        [
            ("seo guide small business local", None),   # near-identical
            ("local seo guide", None),                  # also similar
            ("contact us", None),
        ],
    )
    assert match is not None
    assert match.overlap >= CANNIBAL_THRESHOLD
    assert match.existing == "seo guide small business local"


def test_unrelated_topics_are_not_cannibalisation():
    assert find_cannibalisation("dental implants cost", [("office opening hours", None)]) is None


def test_empty_candidate_never_matches():
    assert find_cannibalisation("", [("anything at all", None)]) is None


# --------------------------------------------------------------------------
# Published performance — refusing to judge too early
# --------------------------------------------------------------------------

def test_recent_article_is_never_called_underperforming():
    label, why = classify_performance(
        impressions=3, clicks=0, position=None, days_since_published=5
    )
    assert label == "NO_DATA_YET"
    assert "recently" in why.lower()


def test_thin_data_is_no_data_not_failure():
    label, _ = classify_performance(
        impressions=4, clicks=0, position=55.0, days_since_published=400
    )
    assert label == "NO_DATA_YET"


def test_real_decline_is_flagged_for_update():
    label, why = classify_performance(
        impressions=300, clicks=2, position=14.0,
        previous_impressions=900, days_since_published=200,
    )
    assert label == "NEEDS_UPDATE"
    assert "67%" in why


def test_growth_is_recognised():
    label, _ = classify_performance(
        impressions=1200, clicks=40, position=7.0,
        previous_impressions=800, days_since_published=200,
    )
    assert label == "GROWING"


def test_impressions_without_clicks_is_underperforming():
    label, why = classify_performance(
        impressions=500, clicks=0, position=12.0,
        previous_impressions=490, days_since_published=200,
    )
    assert label == "UNDERPERFORMING"
    assert "clicked" in why


def test_healthy_article_is_performing():
    label, _ = classify_performance(
        impressions=900, clicks=70, position=4.2,
        previous_impressions=880, days_since_published=200,
    )
    assert label == "PERFORMING"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def test_business_relevance_matches_services():
    terms = ["dental implants", "teeth whitening"]
    assert business_relevance("dental implants cost", terms) > 0.4
    assert business_relevance("weather forecast", terms) == 0.0
    assert business_relevance("anything", []) == 0.0


def test_normalise_phrase_strips_punctuation_and_case():
    assert normalise_phrase("  Best SEO, Guide! ") == "best seo guide"
