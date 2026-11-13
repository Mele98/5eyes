"""Live-Test 2026-11 M1 -- Portfolio-Seite zeigte Demo-Werte, Fehler unsichtbar.

Befund: Beim Laden und dauerhaft nach einer fehlgeschlagenen Generierung (409)
zeigte die Portfolio-Maske Werte aus dem statischen HTML ("Beratungsvermoegen
total CHF 2'848'000", "Positionen 14", "Ø TER 0.22 %", "Preisqualitaet Live").
Die 409-Meldung stand nur in der Statuszeile der AA-Maske. Gleiche Bugklasse
wie der frueher behobene Demo-Platzhalter im Cashflow-Tab.

Soll: neutrale Platzhalter ("—"), sichtbare Statusmeldung auf der
Portfolio-Seite, neutraler Fehlerzustand.
"""
from __future__ import annotations

import re

from tests.livetest_monolith_js import html, run_js


def _page_po(src: str) -> str:
    start = src.index('<div id="page-po"')
    return src[start:src.index("<!-- PAGE: REVIEW -->", start)]


def test_portfolio_page_static_html_has_no_demo_figures():
    page = _page_po(html())
    for demo in ("2'848'000", ">14<", ">0.22%<", ">Live<"):
        assert demo not in page, f"Demo-Platzhalter {demo!r} im Portfolio-HTML"
    for el_id in ("po-advisory-wealth", "po-position-count", "po-average-ter", "po-total-footer", "po-price-quality"):
        m = re.search(r'id="' + el_id + r'"[^>]*>([^<]*)<', page)
        assert m and m.group(1) == "—", (el_id, m and m.group(1))


def test_donut_total_has_no_demo_default():
    assert re.search(r"\nlet TOTAL=0;", html()), "TOTAL startet mit Demo-Wert"


def test_status_message_is_visible_on_portfolio_page():
    out = run_js(("updateStrategyStatus",),
                 "updateStrategyStatus('Einzelpositionslimite kann nicht eingehalten werden',true);"
                 "var e=document.getElementById('po-status');return {t:e.textContent,d:e.style.display,c:e.style.color};")
    assert out["t"] == "Einzelpositionslimite kann nicht eingehalten werden"
    assert out["d"] == ""
    assert out["c"] == "var(--neg)"
    assert 'id="po-status"' in _page_po(html())


def test_failed_generation_resets_to_neutral_state():
    out = run_js(("renderPortfolioNeutralState",),
                 "document.getElementById('po-advisory-wealth').textContent='CHF 2\\'848\\'000';"
                 "renderPortfolioNeutralState('Portfolio konnte nicht generiert werden');"
                 "return ['po-advisory-wealth','po-position-count','po-average-ter','po-price-quality','po-price-quality-sub']"
                 ".map(function(i){return document.getElementById(i).textContent;});")
    assert out[:4] == ["—", "—", "—", "—"]
    assert out[4] == "Portfolio konnte nicht generiert werden"
