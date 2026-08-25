"""Bug-#9 (2026-06-07): Review-Tab ohne Rebalancing-/IST-vs-SOLL-Vergleich.

User-Bug: 'Review ueberarbeiten (Rebalancing entfernen, Protokoll
behalten).' Im Review-Tab gab es bisher:

- 'Portfolio-Check'-Card mit IST vs. SOLL-Tabelle + Status-Badges +
  'Massnahme'-Spalte + 'Handelsliste oeffnen'-Button
- 'Umsetzungsschwerpunkte'-Hotspots auf Drift-Basis

Beides widerspricht ADR-003 (Anti-Market-Timing) und der Anlage-
philosophie (Strategietreue). Rebalancing-Aktionen gehoeren in den
Depot-Check, nicht in den Beratungsabschluss.

Erhalten bleibt:
- Cockpit (Hauptziel, Limitierender Faktor, Zielerreichung)
- Hero / Portfolio-Status-Ampel
- Strategie-Spiegel-Card (Bug-#11 separat)
- Entscheid & Advisory-Log
- Dokumente & Ausgabe (inkl. Beratungsprotokoll)
- Zusammenfassung
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


def _page_rv(text: str) -> str:
    start = text.find('<div id="page-rv"')
    assert start > 0, "page-rv Container fehlt"
    # page-rv ist die letzte Page; HTML-Section endet beim ersten
    # </main> nach dem Page-Start.
    end = text.find("</main>", start + 1)
    assert end > start, "</main> nach page-rv nicht gefunden"
    return text[start:end]


def test_bug9_marker_vorhanden():
    assert "Bug-#9 (2026-06-07)" in _html()


def test_review_hat_keinen_portfolio_check_card_mehr():
    """Portfolio-Check-Card mit IST vs. SOLL entfaellt."""
    page = _page_rv(_html())
    # Card-Header 'Portfolio-Check' darf nicht mehr in page-rv stehen.
    assert ">Portfolio-Check<" not in page
    assert "IST vs. SOLL" not in page
    # Container-Id fuer den IST/SOLL-Vergleich wurde entfernt.
    assert 'id="rv-strategy-compare"' not in page


def test_review_protokoll_bleibt_im_dokumente_hub():
    """Dokumente-Section + Beratungs-/Advisory-Protokoll bleibt erhalten."""
    page = _page_rv(_html())
    assert 'id="rv-output-section"' in page
    assert 'id="rv-output-hub"' in page
    # Protokoll-Druck-Trigger ist in der Page-Header-Action.
    assert "printAdvisoryProtocol()" in page


def test_review_advisory_log_bleibt_erhalten():
    """Entscheid- & Advisory-Log-Card bleibt erhalten."""
    page = _page_rv(_html())
    assert "Entscheid &amp; Advisory-Log" in page or "Entscheid & Advisory-Log" in page
    assert 'id="rv-log-list"' in page


def test_renderReviewStrategyComparison_ist_noop():
    """Renderer darf nur noch das verwaiste DOM-Element clearen,
    keine IST/SOLL-Tabelle mehr aufbauen."""
    text = _html()
    fn_start = text.find("function renderReviewStrategyComparison(")
    # Nach der No-op-Funktion folgt eine `var _renderStrategySummaryGoalTiming=...`
    # Zuweisung, also als Boundary nehmen wir das naechste "\nvar " ODER
    # "\nfunction ".
    boundaries = [
        text.find("\nvar ", fn_start + 1),
        text.find("\nfunction ", fn_start + 1),
    ]
    boundaries = [b for b in boundaries if b > 0]
    fn_end = min(boundaries) if boundaries else -1
    assert fn_start > 0 and fn_end > fn_start, (
        f"fn_start={fn_start} fn_end={fn_end}"
    )
    body = text[fn_start:fn_end]
    assert "Bug-#9 (2026-06-07)" in body
    # Nichts mehr von den Drift-/Hotspot-/Trade-Sektionen.
    assert "reviewBandStateMeta" not in body
    assert "reviewImplementationHotspots" not in body
    assert "openTradeList" not in body
    assert "Massnahme" not in body
    assert "Handelsliste" not in body


def test_legacy_renderer_ist_nicht_mehr_im_file():
    """Drift-Wache: die alte Renderer-Implementation darf nicht in einer
    parallelen _bug9LegacyRender*-Funktion ueberleben."""
    text = _html()
    assert "_bug9LegacyRenderReviewStrategyComparison" not in text
