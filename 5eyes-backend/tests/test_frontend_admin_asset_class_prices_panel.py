"""U-P19: Frontend-Contract fuer Daily-Asset-Class-Price-Backfill."""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def _admin_asset_class_price_block(html: str) -> str:
    start = html.find('id="sec-acprices"')
    assert start != -1, "sec-acprices fehlt"
    end = html.find('id="sec-cma"', start)
    assert end != -1, "Folge-Section nach sec-acprices nicht gefunden"
    return html[start:end]


def test_asset_class_price_section_exists():
    html = _html()
    block = _admin_asset_class_price_block(html)
    assert 'class="admin-sec-panel"' in block
    assert 'id="admin-acp-summary"' in block
    assert 'id="admin-acp-grid"' in block
    assert 'id="admin-acp-error"' in block
    assert "admin-summary-panel" in block
    assert "admin-compact-grid" in block


def test_asset_class_price_nav_button_registered():
    html = _html()
    assert 'id="asec-acprices"' in html
    assert "adminShowSection('sec-acprices')" in html


def test_asset_class_price_buttons_call_frontend_handlers():
    html = _html()
    block = _admin_asset_class_price_block(html)
    assert 'id="btn-admin-acp-load"' in block
    assert "loadAdminAssetClassPriceStatus(true)" in block
    assert 'id="btn-admin-acp-backfill"' in block
    assert "backfillAdminAssetClassPrices()" in block
    assert "admin-primary-btn" in block


def test_asset_class_price_js_contract_exists():
    html = _html()
    assert "function renderAdminAssetClassPriceStatus" in html
    assert "async function loadAdminAssetClassPriceStatus" in html
    assert "async function backfillAdminAssetClassPrices" in html
    assert "adminAssetClassPriceKeys" in html
    assert "'Aktien','Obligationen','Immobilien','Alternative','Liquiditaet'" in html


def test_asset_class_price_api_routes_and_timeout_referenced():
    html = _html()
    assert "'/admin/system/asset-class-prices/status'" in html
    assert "'/admin/system/asset-class-prices/backfill'" in html
    assert "timeoutMs: 120000" in html
    assert "method: 'POST'" in html


def test_admin_modal_loads_asset_class_price_status():
    html = _html()
    start = html.find("async function openAdminModal")
    assert start != -1, "openAdminModal nicht gefunden"
    block = html[start:start + 1200]
    assert "loadAdminAssetClassPriceStatus(false)" in block


def test_daily_backtest_toggle_contract_preserved():
    html = _html()
    assert 'id="bt-fallback-badge"' in html
    assert 'id="bt-res-annual"' in html
    assert 'id="bt-res-daily"' in html
    assert 'name="bt-resolution"' in html
    assert "function btReadResolution" in html
    assert "resolution=' + encodeURIComponent(btReadResolution())" in html
    assert "data.resolution_used === 'annual'" in html
