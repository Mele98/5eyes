"""Regressions-Sperre #99: Cashflow-Liste nach Lebensbereich gruppiert
(Erwerb / Vorsorge / Wohnen / Kapital & Vermögen / Lebenshaltung / Sonstiges),
inkl. Zwischentotal je Gruppe; abgeleitete Posten landen anhand der Herkunft
(Hypothek/Immobilie → Wohnen, Liquidität → Kapital) in der richtigen Gruppe.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_life_area_groups_defined():
    html = _html()
    assert "var CASHFLOW_LIFE_AREAS=" in html
    for label in ("Erwerb", "Vorsorge", "Wohnen", "Kapital & Vermögen", "Lebenshaltung"):
        assert f"label:'{label}'" in html


def test_categorizer_and_grouper_exist():
    html = _html()
    assert "function cashflowLifeArea(c)" in html
    assert "function renderCashflowGroups(" in html


def test_derived_origin_maps_to_group():
    html = _html()
    # Hypothek/Immobilie -> Wohnen, Liquidität -> Kapital (Herkunft hat Vorrang).
    assert "origin_position_type" in html
    assert "indexOf('hypothek')" in html
    assert "indexOf('liquid')" in html


def test_both_sides_use_grouped_renderer():
    html = _html()
    assert "renderCashflowGroups(inc,derInc,true,renderRow,renderDerivedRow,fmt)" in html
    assert "renderCashflowGroups(exp,derExp,false,renderRow,renderDerivedRow,fmt)" in html


def test_group_shows_subtotal():
    html = _html()
    # Zwischentotal je Gruppe (Summe amount_rappen) im Header.
    assert "class=\"cf-grp\"" in html
    assert "amount_rappen" in html
