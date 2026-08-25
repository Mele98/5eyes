"""FE-Contract-Tests fuer B3 Vorsorge-Differenziert (Sprint B Batch 5).

Prueft, dass das Goal-Modal das pension_pillar Feld nur bei Pensionsausgabe
zeigt, korrekt an das Backend wired und in der Goal-Liste anzeigt.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_pension_pillar_select_exists_with_all_options():
    html = _html()
    assert 'id="nz-pension-pillar"' in html
    assert 'id="nz-pension-pillar-wrap"' in html
    for pillar in ("AHV", "BVG", "3a", "1e", "FZG"):
        assert '<option value="' + pillar + '"' in html


def test_pension_pillar_visibility_linked_to_pensionsausgabe():
    html = _html()
    # syncGoalModalState toggled visibility based on type==='Pensionsausgabe'
    assert "type==='Pensionsausgabe'" in html
    assert "pensionPillarWrap" in html


def test_save_goal_payload_includes_pension_pillar_only_for_pension():
    html = _html()
    # Payload enthaelt pension_pillar; clamped auf erlaubte Werte oder null
    assert "pension_pillar:" in html
    assert "['AHV','BVG','3a','1e','FZG']" in html


def test_open_goal_editor_hydrates_pillar():
    html = _html()
    assert "setSelectValue('nz-pension-pillar',goal.pension_pillar||'')" in html


def test_reset_goal_modal_clears_pillar():
    html = _html()
    assert "setSelectValue('nz-pension-pillar','')" in html


def test_goal_badge_renders_pillar_badge_when_set():
    html = _html()
    assert "goal.pension_pillar" in html
    assert "['AHV','BVG','3a','1e','FZG'].indexOf" in html
    assert "AHV: staatliche 1. Säule" in html or "AHV: staatliche 1. Säule" in html


def test_demo_goal_record_carries_pillar():
    html = _html()
    assert "pension_pillar:payload.pension_pillar||null" in html
