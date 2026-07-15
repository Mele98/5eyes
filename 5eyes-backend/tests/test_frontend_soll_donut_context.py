"""Frontend: SOLL-Allokations-Torte — 3eyes-treue Einordnung (Etappe 2).

Produkt-Entscheid 2026-07-15 (Option B): Die SOLL-Torte bleibt auf dem
umschichtbaren Beratungsvermögen (fachlich korrekt nach 3eyes), wird aber
glasklar so beschriftet, und das Reinvermögen (inkl. Eigenheim-Fundament) wird
als Kontext daneben ausgewiesen — gespeist aus dem Engine-Feld total_allocation.
"""
from __future__ import annotations
from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_donut_subline_reframed_positive():
    html = _html()
    # Positive 3eyes-Formulierung statt apologetischem "zeigt nur den Beratungsteil".
    assert "umgeschichtet werden kann" in html
    assert "zeigt aber nur den optimierbaren Beratungsteil" not in html


def test_reinvermoegen_context_element_present():
    html = _html()
    assert 'id="alloc-rein-context"' in html


def test_reinvermoegen_context_populated_from_total_allocation():
    html = _html()
    # Der Sync-Block befüllt Reinvermögen + Eigenheim-Fundament + Beratungsvermögen.
    block = html.split("function syncAllocationDonutFromStrategyState(", 1)[1].split("\nlet charts=", 1)[0]
    assert "alloc-rein-context" in block
    assert "total_allocation" in block
    assert "foundation_rappen" in block
    assert "total_wealth_rappen" in block
    assert "advisory_wealth_rappen" in block
