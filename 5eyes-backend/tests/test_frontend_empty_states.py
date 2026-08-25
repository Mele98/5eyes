"""Regressions-Sperre #100: führende Leer-Zustände — sagen nicht nur «leer»,
sondern was zu erfassen ist und warum es für die holistische Planung zählt.
Greift für Ziele und beide Cashflow-Seiten über einen gemeinsamen Helper.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_journey_empty_hint_helper_exists():
    html = _html()
    assert "function journeyEmptyHint(text)" in html


def test_guiding_empty_states_use_helper():
    html = _html()
    # Ziele + Cashflow-Ein-/Ausgaben nutzen den führenden Helper.
    assert "journeyEmptyHint('Noch keine Ziele." in html
    assert "journeyEmptyHint('Noch keine Einnahmen." in html
    assert "journeyEmptyHint('Noch keine Ausgaben." in html


def test_empty_states_are_actionable():
    html = _html()
    # Holistischer Bezug: Hinweise nennen die Wirkung auf die Planung.
    assert "zielbasierte Asset Allocation" in html
    assert "Vermögensverzehr" in html
