"""P17: Frontend-Contract-Test fuer das Admin-Datenpipeline-Panel.

Pruefen dass:
- Das HTML enthaelt #admin-market-data-panel und die 3 Karten-IDs.
- Es gibt eine loadMarketDataStatus() JS-Funktion.
- Polling-Setup (startMarketDataPolling) ist vorhanden.
- Der Refresh-Button referenziert die Funktion.
- Die API-Route '/admin/market-data/status' wird im Frontend angesteuert.

Reine Static-File-Inspektion. Kein Browser noetig.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def test_market_data_panel_html_exists():
    html = _html()
    assert 'id="admin-market-data-panel"' in html, \
        "Panel-Container fehlt im Frontend"
    assert 'id="admin-mdata-providers"' in html
    assert 'id="admin-mdata-cache"' in html
    assert 'id="admin-mdata-validation"' in html
    assert 'id="admin-mdata-jobs"' in html
    assert 'id="admin-mdata-meta"' in html


def test_refresh_button_calls_loader():
    html = _html()
    assert 'id="btn-admin-mdata-refresh"' in html
    assert 'loadMarketDataStatus' in html


def test_loader_function_exists():
    html = _html()
    assert 'async function loadMarketDataStatus' in html


def test_renderer_function_exists():
    html = _html()
    assert 'function renderMarketDataStatus' in html


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
    """openAdminModal() soll loadMarketDataStatus() auch aufrufen."""
    html = _html()
    # Finde openAdminModal-Block und pruefe ob loadMarketDataStatus drin steht
    start = html.find("async function openAdminModal")
    assert start != -1, "openAdminModal nicht gefunden"
    end = html.find("\n}\n", start) + 1
    block = html[start:end]
    assert "loadMarketDataStatus" in block, \
        "openAdminModal() ruft loadMarketDataStatus nicht auf"


def test_renderer_handles_empty_state():
    """Renderer-Code muss Empty-State-Branches fuer Provider/Cache/Logs/Jobs haben."""
    html = _html()
    # Suche nach Empty-State-Strings
    assert "Keine Provider konfiguriert" in html
    assert "Cache leer" in html
    assert "Keine Validation-Logs" in html
    assert "Scheduler inaktiv" in html
