"""FE-Contract-Tests fuer B6 Conditional Goals (Sprint B Batch 4).

Prueft, dass das Goal-Editor-Modal das probability_pct Feld korrekt
an das Backend wired und in der Goal-Liste anzeigt.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_goal_modal_has_probability_input():
    html = _html()
    assert 'id="nz-probability"' in html
    assert 'min="0"' in html and 'max="100"' in html
    assert 'Eintrittswahrscheinlichkeit' in html


def test_save_goal_payload_includes_probability_pct():
    html = _html()
    # Payload enthaelt das Feld und clamped 0-100
    assert 'probability_pct:' in html
    assert "getInputValue('nz-probability')" in html
    assert "Math.max(0,Math.min(100" in html


def test_open_goal_editor_hydrates_probability():
    html = _html()
    # openGoalEditor liest goal.probability_pct (default 100 wenn null)
    assert "goal.probability_pct==null?'100'" in html


def test_reset_goal_modal_defaults_to_100():
    html = _html()
    assert "setInputValue('nz-probability','100')" in html


def test_goal_badge_renders_bedingt_when_below_100():
    html = _html()
    # Badge-Logik: Number(prob)<100 -> BEDINGT X% Badge
    assert "BEDINGT '+probClamped+'%" in html
    assert "goal.probability_pct" in html


def test_demo_goal_record_carries_probability():
    html = _html()
    # buildDemoGoalRecord propagiert payload.probability_pct
    assert "probability_pct:payload.probability_pct==null?100:payload.probability_pct" in html
