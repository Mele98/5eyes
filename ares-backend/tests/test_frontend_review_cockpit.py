from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_review_cockpit_dom_anchors_exist():
    html = _html()
    for element_id in [
        "rv-main-goal-label",
        "rv-main-goal-prob",
        "rv-main-goal-prob-icon",
        "rv-limiting-factor-badge",
        "rv-allocation-story",
        "rv-message-banner",
        "rv-goal-achievability-list",
        "rv-details-accordion",
    ]:
        assert f'id="{element_id}"' in html


def test_review_cockpit_renderer_is_hooked_into_review_state():
    html = _html()
    assert "function renderReviewCockpit(state)" in html
    assert "renderReviewCockpit(state||{})" in html
    assert "mainGoalAchievability(result)" in html
    assert "rvBuildAllocationStory(result,risk)" in html
    assert "renderReviewGoalAchievability(result)" in html


def test_limiting_factor_mapping_and_story_builder_exist():
    html = _html()
    assert "function limitingFactorMeta(factor)" in html
    for factor in [
        "risikoprofil",
        "liquiditaetsreserve",
        "bandbreite",
        "zielkonflikt",
        "solver_konvergenz",
    ]:
        assert factor in html
    assert "function rvBuildAllocationStory(result,riskAssessment)" in html
    assert "risk_budget_bps_at_generation" in html
    assert "risky_fraction_bps_at_generation" in html


def test_review_goal_probability_badge_logic_exists():
    html = _html()
    assert "function rvGoalProbBadge(prob)" in html
    # UX-1 (CIO-Entscheid): Ampel einheitlich 70/45 wie die Legende.
    assert "p>=0.70" in html
    assert "p>=0.45" in html
    assert "p>=0.80" not in html
    # Der tau-basierte Optimizer-Status behaelt seine eigene Sprache.
    assert "nicht plausibel" in html
