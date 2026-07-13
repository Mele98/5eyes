"""Frontend: Dedizierter Editor fuer Vermoegenszufluesse (Roadmap #54).

Praesenz-Test — stellt sicher, dass Modal, JS-Funktionen, Endpoint und die
source_type-Werte im Monolithen vorhanden bleiben (Drift-Schutz).
"""
from __future__ import annotations

from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_inflow_modal_present():
    html = _html()
    assert 'id="m-awi"' in html
    assert 'id="awi-label"' in html
    assert 'id="awi-source-type"' in html
    assert 'id="awi-amount"' in html
    assert 'id="awi-year"' in html
    assert 'id="btn-awi-save"' in html
    assert 'id="inflow-rows"' in html


def test_inflow_js_functions_present():
    html = _html()
    assert "function openNewInflow(" in html
    assert "function saveInflow(" in html
    assert "function refreshInflowsUI(" in html
    assert "function openInflowEditor(" in html
    assert "function buildWealthInflowMarkers(" in html


def test_inflow_endpoint_present():
    html = _html()
    assert "/wealth-inflows" in html


def test_inflow_source_type_values_present():
    html = _html()
    for value in ("Erbschaft", "Bonus", "Saeule3b", "Verkaufserloes", "Andere"):
        assert value in html
