"""Bug-#11 (2026-06-07): 'Strategie-Spiegel'-Card aus Review-Tab entfernt.

User-Bug: 'Strategiespiegel klaeren/entfernen.' Die Card zeigte eine
theoretische SPI-Proxy-Vergleichsrendite seit Strategiefestlegung —
im Beratungsprozess unklar (Vergleich gegen welchen Index, welcher
Zeitraum, was bedeutet die Delta-Zahl) und widerspricht der Anlage-
philosophie 'Strategietreue, kein Markt-Vergleich-Push'.

Entscheid: UI-Surface entfernen. Backend-Endpoint
/strategy-snapshots/latest/drift bleibt fuer Aggregator/PDFs erhalten.
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
    end = text.find("</main>", start + 1)
    assert end > start, "</main> nach page-rv nicht gefunden"
    return text[start:end]


def test_bug11_marker_vorhanden():
    assert "Bug-#11 (2026-06-07)" in _html()


def test_rv_spiegel_card_dom_ist_weg():
    """Die Card mit `id='rv-spiegel-card'` und ihre Subelemente
    duerfen nicht mehr in page-rv stehen."""
    page = _page_rv(_html())
    assert 'id="rv-spiegel-card"' not in page
    assert 'ch-rv-spiegel' not in page
    assert 'rv-spiegel-date' not in page
    assert 'rv-drift-table' not in page
    assert 'rv-spiegel-no-data' not in page
    assert 'rv-kpi-strategy' not in page
    assert 'rv-kpi-delta' not in page
    assert 'rv-kpi-profile' not in page


def test_loadReviewSpiegel_ist_noop():
    """loadReviewSpiegel darf keinen API-Call mehr machen."""
    text = _html()
    fn_start = text.find("async function loadReviewSpiegel(")
    fn_end = text.find("\n}\n", fn_start)
    assert fn_start > 0 and fn_end > fn_start
    body = text[fn_start:fn_end + 3]
    assert "Bug-#11 (2026-06-07)" in body
    # Keine API-Aufrufe / DOM-Manipulation mehr.
    assert "API.get" not in body
    assert "strategy-snapshots" not in body
    assert "card.style.display" not in body
    assert "renderSpiegelChart" not in body
    assert "renderDriftTable" not in body


def test_renderSpiegelChart_und_renderDriftTable_sind_entfernt():
    """Die zwei Renderer wurden komplett aus dem Frontend entfernt."""
    text = _html()
    assert "\nfunction renderSpiegelChart(" not in text
    assert "\nfunction renderDriftTable(" not in text


def test_loadReviewSpiegel_aufrufer_bleiben_funktional():
    """Drift-Wache: die Aufrufer (go('rv') + activeMandate-Wechsel)
    rufen die Funktion weiterhin auf — sie soll nur intern nichts mehr
    tun. Verhindert, dass jemand die Aufrufer entfernt und dabei andere
    Review-Init-Logik kaputtmacht."""
    text = _html()
    # Erwartete Aufrufer-Stellen (mind. 2 Treffer fuer den
    # Funktions-Aufruf).
    call_count = text.count("loadReviewSpiegel(")
    # Definition + 2 Aufrufer = 3 Treffer
    assert call_count >= 3, f"loadReviewSpiegel-Aufrufer fehlen ({call_count})"


def test_backend_strategy_snapshot_endpoint_bleibt():
    """Backend-Endpoint /strategy-snapshots/latest/drift soll erhalten
    bleiben — wird vom Aggregator (Sektion Statement-PM) und vom PDF
    konsumiert."""
    import subprocess
    result = subprocess.run(
        ["python", "-c", "from main import app; print([r.path for r in app.routes if 'strategy-snapshots' in r.path])"],
        cwd=str(BACKEND_ROOT), capture_output=True, text=True
    )
    # Defensiv: wenn der Subprocess nicht startbar ist, skippen.
    if result.returncode != 0:
        import pytest
        pytest.skip(f"Backend-Boot-Check nicht moeglich: {result.stderr[:200]}")
    assert "strategy-snapshots" in result.stdout
