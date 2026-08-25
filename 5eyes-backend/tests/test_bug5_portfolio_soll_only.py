"""Bug-#5 (2026-06-07): Portfolio-Tab zeigt nur SOLL, keine IST-Vergleichs-UI.

Customer-Journey 3eyes-Stil:
  Standortanalyse -> Cashflow/Goals -> Risikoprofil -> SAA -> Portfolio

Portfolio = Ableitung der SAA in konkrete Produkte (ISIN-Liste). KEIN
Bestand-vs-Empfehlung-Vergleich; Drift gehoert in den Depot-Check.
Anlagephilosophie: Strategietreue, keine automatischen Markt-Trigger
(ADR-003 Anti-Market-Timing).

Vorher zeigte page-po:
- 'Massnahme'-Spalte mit ANPASSEN/IN-SOLL/PRUEFEN-Status-Badges
- Rebalance-Summary-Banner 'Handlungsbedarf: N Position(en) ausserhalb
  Bandbreite'
- Detail-Allokation mit Ist+Soll-Balken nebeneinander
- Detail-'Abweichung' mit Drift + Buchgewinn/-verlust

Drift-Tests verhindern Regression auf die alte SOLL/IST-Vergleichs-UI.
"""
from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html_text() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _page_po(text: str) -> str:
    start = text.find('<div id="page-po"')
    assert start > 0, "page-po Container fehlt"
    end = text.find("<!-- PAGE: REVIEW -->", start)
    assert end > start, "PAGE: REVIEW-Marker fehlt"
    return text[start:end]


def test_bug5_marker_vorhanden():
    assert "Bug-#5 (2026-06-07)" in _html_text()


def test_page_po_hat_keine_massnahme_spalte():
    """Header-Zeile darf keine 'Massnahme'-Spalte mehr enthalten."""
    page = _page_po(_html_text())
    assert "<div class=\"pch\">Massnahme</div>" not in page
    assert "Soll-Gewicht" in page  # neue Spalten-Header
    assert "Zielbetrag" in page


def test_page_po_hat_kein_rebalance_summary_div():
    """po-rebalance-summary-Container entfaellt."""
    page = _page_po(_html_text())
    assert "id=\"po-rebalance-summary\"" not in page


def test_renderportfoliosections_hat_kein_pstatus_badge():
    """Render-Zweig der prow-main darf keine pstatus-Badges mehr erzeugen."""
    text = _html_text()
    fn_start = text.find("function renderPortfolioSections(")
    fn_end = text.find("\nfunction renderRecommendationWarnings(", fn_start)
    assert fn_start > 0 and fn_end > fn_start
    fn_body = text[fn_start:fn_end]
    # Keine pstatus-Badge mehr ausgegeben.
    assert "pstatus-badge" not in fn_body
    # Kein Ist-Balken mehr im Detail.
    assert "<span>Ist</span>" not in fn_body
    # Kein 'Abweichung' Detail-Tile mehr (Drift / Buchgewinn).
    assert ">Abweichung<" not in fn_body
    # Kein Status-Banner-Banner-Text fuer 'Handlungsbedarf'.
    assert "Handlungsbedarf" not in fn_body


def test_renderPortfolioRebalancingSummary_ist_noop():
    """Funktion darf nur noch das Banner verstecken, keine Items erzeugen."""
    text = _html_text()
    fn_start = text.find("function renderPortfolioRebalancingSummary(")
    fn_end = text.find("\nfunction ", fn_start + 1)
    assert fn_start > 0 and fn_end > fn_start
    body = text[fn_start:fn_end]
    # Markiert als Bug-#5-No-op.
    assert "Bug-#5 (2026-06-07)" in body
    # Erzeugt keine Banner-Items mehr.
    assert "Handlungsbedarf" not in body
    assert "openDecisionTemplateModal" not in body


def test_alte_kpi_spaltentitel_marktwert_gewicht_weg():
    """Markwert/Gewicht waren IST-Konzepte; jetzt heissen die Spalten
    Zielbetrag/Soll-Gewicht."""
    page = _page_po(_html_text())
    header_start = page.find("<div class=\"pcols\">")
    header_end = page.find("</div></div>", header_start) + len("</div></div>")
    header = page[header_start:header_end]
    assert ">Marktwert<" not in header
    assert ">Gewicht<" not in header
    assert ">Zielbetrag<" in header
    assert ">Soll-Gewicht<" in header
