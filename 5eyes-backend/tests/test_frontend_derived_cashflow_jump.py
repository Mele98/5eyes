"""Regressions-Sperre #53: Klick auf eine abgeleitete (AUTO) Cashflow-Zeile
springt zur auslösenden Vermögensposition (Seite «Vermögen») und hebt sie hervor.
Voraussetzung: das derived-Payload trägt origin_position_id (DerivedCashflow.to_dict).
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_jump_function_exists():
    html = _html()
    assert "function jumpToWealthPosition(posId)" in html
    # navigiert zur Vermögensseite + sucht die Position per data-posid.
    assert "go('vg')" in html
    assert '.wr[data-posid="' in html
    assert "scrollIntoView" in html


def test_derived_row_is_clickable_when_origin_known():
    html = _html()
    assert "c.origin_position_id" in html
    assert "onclick=\"jumpToWealthPosition(" in html


def test_derived_cashflow_payload_carries_origin_position_id():
    # Backend-Vertrag: to_dict() = asdict() -> origin_position_id ist enthalten.
    wc = (Path(__file__).resolve().parents[1] / "services" / "wealth_cashflows.py").read_text(encoding="utf-8")
    assert "origin_position_id" in wc
    assert "def to_dict" in wc
