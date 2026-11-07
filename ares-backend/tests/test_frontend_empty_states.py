"""Regressions-Sperre #100: führende Leer-Zustände — sagen nicht nur «leer»,
sondern was zu erfassen ist und warum es für die holistische Planung zählt.
Greift für Ziele und beide Cashflow-Seiten über einen gemeinsamen Helper.
"""
from pathlib import Path
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile


HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"


def _html() -> str:
    return read_monolith_bundle()


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
