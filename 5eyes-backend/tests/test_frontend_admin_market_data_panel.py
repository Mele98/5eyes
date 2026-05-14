"""P17 Re-Implementation: Frontend-Contract-Test fuer Admin-Datenpipeline-Sub-Section.

Im Gegensatz zum urspruenglichen P17 ist das Panel jetzt eine eigene Admin-Sub-Section
(sec-market-data, analog zu sec-cma-sub) mit eigenem Nav-Button (asec-market-data),
nicht mehr ein Single-Pane-Anhang ans Admin-Modal.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def test_market_data_section_exists():
    html = _html()
    assert 'id="sec-market-data"' in html, "Sub-Section fehlt im Admin-Panel"
    assert 'class="admin-sec-panel"' in html
    # Container der 4 Status-Bereiche
    assert 'id="admin-mdata-providers"' in html
    assert 'id="admin-mdata-cache"' in html
    assert 'id="admin-mdata-validation"' in html
    assert 'id="admin-mdata-jobs"' in html
    assert 'id="admin-mdata-meta"' in html


def test_nav_button_registered():
    html = _html()
    assert 'id="asec-market-data"' in html, "Nav-Button fehlt im Admin-Sidebar"
    assert "adminShowSection('sec-market-data')" in html


def test_refresh_button_calls_loader():
    html = _html()
    assert 'id="btn-admin-mdata-refresh"' in html
    assert 'loadMarketDataStatus(true)' in html


def test_loader_function_exists():
    html = _html()
    assert 'async function loadMarketDataStatus' in html


def test_renderer_function_exists():
    html = _html()
    assert 'function renderMarketDataStatus' in html
    assert 'function renderMarketDataStatusError' in html


def test_polling_setup_exists():
    html = _html()
    assert 'function startMarketDataPolling' in html
    assert 'function stopMarketDataPolling' in html
    # Polling-Intervall = 60s
    assert '60000' in html


def test_api_route_referenced():
    html = _html()
    assert "'/admin/market-data/status'" in html


def test_admin_modal_opens_market_data_panel():
    """openAdminModal() soll loadMarketDataStatus() und startMarketDataPolling() aufrufen."""
    html = _html()
    start = html.find("async function openAdminModal")
    assert start != -1, "openAdminModal nicht gefunden"
    end = html.find("\n}\n", start) + 1
    block = html[start:end]
    assert "loadMarketDataStatus" in block, \
        "openAdminModal() ruft loadMarketDataStatus nicht auf"
    assert "startMarketDataPolling" in block, \
        "openAdminModal() startet kein Polling"


def test_renderer_handles_empty_state():
    """Renderer-Code muss Empty-State-Branches fuer Provider/Cache/Logs/Jobs haben."""
    html = _html()
    assert "Keine Provider konfiguriert" in html
    assert "Cache leer" in html
    assert "Keine Validation-Logs" in html
    assert "Scheduler inaktiv" in html


def test_polling_stops_when_modal_hidden():
    """Polling-Loop muss sich selbst stoppen wenn das Admin-Modal nicht sichtbar ist."""
    html = _html()
    start = html.find("function startMarketDataPolling")
    assert start != -1
    end = html.find("function stopMarketDataPolling", start)
    block = html[start:end]
    assert "stopMarketDataPolling()" in block, \
        "Polling-Loop ruft stopMarketDataPolling nicht auf"
