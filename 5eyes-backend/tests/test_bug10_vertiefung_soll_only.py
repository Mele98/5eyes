"""Bug-#10 (2026-06-07): 'Vertiefung & Dokumentation' zeigt nur SOLL.

User-Bug: 'Vertiefung & Dokumentation (nur SOLL)'. Konsistent mit
Bug-#5 (Portfolio-IST/SOLL raus), Bug-#9 (Review-Rebalancing raus)
und Bug-#11 (Strategie-Spiegel raus).

Vorher haetten Heading und Disclosure-Title noch IST/SOLL- und
Strategie-Spiegel-Begriffe enthalten, obwohl die zugehoerigen Cards
weg sind. Drift-Test wacht ueber den Wording-Fix.
"""
from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_bug10_marker_vorhanden():
    assert "Bug-#10 (2026-06-07)" in _html()


def test_secondary_heading_wording_ist_soll_only():
    """secondaryHeading.copy darf nicht mehr 'Portfolio-Vergleich'
    versprechen (das war die IST/SOLL-Sicht)."""
    text = _html()
    idx = text.find("rvSectionHeader('rv-secondary-heading'")
    assert idx > 0, "secondaryHeading nicht gefunden"
    line_end = text.find(";", idx) + 1
    line = text[idx:line_end]
    assert "Portfolio-Vergleich" not in line
    assert "SOLL-Methodik" in line or "SOLL" in line


def test_analysis_disclosure_wording_ist_soll_only():
    """Disclosure-Titel + Copy duerfen nicht mehr nach IST/SOLL oder
    Strategie-Spiegel klingen."""
    text = _html()
    idx = text.find("rvDisclosure('rv-analysis-disclosure'")
    assert idx > 0, "analysisDisclosure nicht gefunden"
    line_end = text.find(";", idx) + 1
    line = text[idx:line_end]
    assert "IST/SOLL" not in line
    assert "Strategie-Spiegel" not in line
    assert "Solver-Trace" in line


def test_analysis_body_haengt_nicht_mehr_strategyCard_oder_strategySpiegel_an():
    """Code-Block, der die Vertiefung mit Inhalt befuellt, darf
    strategyCard und strategySpiegel nicht mehr in einem appendChild
    referenzieren — diese Cards sind in Bug-#9 und Bug-#11 entfernt
    worden. Erklaerende Kommentare duerfen die Begriffe nennen."""
    text = _html()
    idx = text.find("var analysisDisclosure=rvDisclosure('rv-analysis-disclosure'")
    assert idx > 0
    block = text[idx:idx + 800]
    # Kein appendChild(strategyCard) / appendChild(strategySpiegel).
    assert "appendChild(strategyCard)" not in block
    assert "appendChild(strategySpiegel)" not in block
    # Kein gemeinsamer Array-forEach mit den alten Namen mehr.
    assert "[strategyCard,strategySpiegel" not in block
