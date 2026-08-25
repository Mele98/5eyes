"""Regressions-Sperre #36 / PAR-3: Zielerreichung je Ziel SOLL vs IST im Frontend.
Liest result.goal_analysis (SOLL) + result.current_goal_analysis (IST, Backend).
Graceful: bleibt versteckt, solange das IST-Payload fehlt (kein Regress).
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_goal_soll_ist_container_and_renderer_exist():
    html = _html()
    assert 'id="aa-goal-sollist"' in html
    assert "function renderGoalAchievementSollIst(result)" in html
    assert "renderGoalAchievementSollIst(result)" in html  # Aufruf in applyAllocationEngineResult


def test_goal_soll_ist_reads_both_paths_and_fields():
    html = _html()
    assert "result.goal_analysis" in html
    assert "result.current_goal_analysis" in html
    assert "median_achievement_pct" in html
    assert "pessimistic_shortfall_rappen" in html


def test_goal_soll_ist_is_graceful_when_ist_missing():
    html = _html()
    # Ohne IST-Daten -> Container versteckt (kein Regress fuer Alt-Berechnungen).
    assert "if(!soll.length||!ist.length){ el.style.display='none'" in html


def test_backend_exposes_current_goal_analysis():
    # Codex-Backend-Vertrag: das Payload fuehrt current_goal_analysis.
    # ADR-014 (Engine-God-Modul-Split): median_achievement_pct/
    # pessimistic_shortfall_rappen leben seit Schritt 7 (Payload-Bau Phase B)
    # in services/portfolio_engine_payload.py (_merge_goal_analysis_with_
    # monte_carlo), nicht mehr in portfolio_engine.py -- Scan analog zu
    # test_liquidity_zero_engine_lock.py auf alle portfolio_engine*.py
    # Submodule ausgeweitet.
    services_dir = Path(__file__).resolve().parents[1] / "services"
    pe = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(services_dir.glob("portfolio_engine*.py"))
    )
    assert '"current_goal_analysis"' in pe
    assert "median_achievement_pct" in pe
    assert "pessimistic_shortfall_rappen" in pe
