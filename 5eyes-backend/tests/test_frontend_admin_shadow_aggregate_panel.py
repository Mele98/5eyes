"""Stage 8 Phase 2: Frontend-Contract fuer Admin Shadow-Aggregat-Panel."""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def _section(html: str) -> str:
    start = html.find('<section id="sec-shadow-comparison-aggregate"')
    assert start != -1, "Shadow-Aggregat-Section fehlt"
    end = html.find("<!-- SEC: AUDIT-LOG -->", start)
    assert end != -1, "Section-Ende nicht gefunden"
    return html[start:end]


def test_shadow_aggregate_section_and_kpi_anchors_exist():
    html = _html()
    section = _section(html)
    assert "<section" in section
    assert "Shadow-Vergleich Aggregat" in section
    assert 'id="admin-shadow-aggregate-status-pill"' in section
    assert 'id="admin-shadow-default-badge"' in section
    assert 'id="admin-shadow-default-reason"' in section
    for verdict in ("green", "yellow", "red"):
        assert f'id="admin-shadow-{verdict}-count"' in section
        assert f'id="admin-shadow-{verdict}-pct"' in section


def test_shadow_aggregate_examples_lists_have_required_anchors():
    section = _section(_html())
    assert 'id="admin-shadow-examples-green"' in section
    assert 'id="admin-shadow-examples-yellow"' in section
    assert 'id="admin-shadow-examples-red"' in section
    assert 'id="admin-shadow-aggregate-errors"' in section
    assert 'id="admin-shadow-aggregate-meta"' in section


def test_shadow_aggregate_nav_button_registered():
    html = _html()
    assert 'id="asec-shadow-comparison-aggregate"' in html
    assert "adminShowSection('sec-shadow-comparison-aggregate')" in html
    assert "adm-nav-btn" in html


def test_shadow_aggregate_reload_button_calls_loader():
    section = _section(_html())
    assert 'id="btn-admin-shadow-aggregate-refresh"' in section
    assert "loadShadowAggregate(true)" in section


def test_shadow_aggregate_js_functions_and_endpoint_exist():
    html = _html()
    assert "async function loadShadowAggregate(showSpinner=true)" in html
    assert "function renderShadowAggregate(data)" in html
    assert "function renderShadowAggregateError(error)" in html
    assert "'/admin/system/shadow-comparison-aggregate'" in html


def test_shadow_aggregate_renderer_mentions_required_payload_fields():
    html = _html()
    assert "default_switch_ready" in html
    assert "default_switch_reason" in html
    assert "verdict_notes" in html
    assert "total_drift_bps" in html
    assert "limiting_factor" in html
    assert "mandate_id" in html


def test_shadow_aggregate_open_admin_and_section_switch_load_data():
    html = _html()
    open_start = html.find("async function openAdminModal")
    assert open_start != -1
    open_end = html.find("\n}\n", open_start) + 1
    open_block = html[open_start:open_end]
    assert "sec-shadow-comparison-aggregate" in open_block
    assert "loadShadowAggregate(false)" in open_block

    switch_start = html.find("function adminShowSection")
    assert switch_start != -1
    switch_end = html.find("function adminSwitchTab", switch_start)
    switch_block = html[switch_start:switch_end]
    assert "sec-shadow-comparison-aggregate" in switch_block
    assert "loadShadowAggregate(false)" in switch_block


def test_shadow_aggregate_copy_is_neutral_and_not_polling():
    html = _html()
    section = _section(html)
    forbidden = ("garantiert", "Erhoehen Sie Ihr Risiko", "Erhöhen Sie Ihr Risiko")
    for phrase in forbidden:
        assert phrase.lower() not in section.lower()
    assert "Default-Wechsel freigegeben" in html
    assert "Default-Wechsel blockiert" in html

    loader_start = html.find("async function loadShadowAggregate")
    loader_end = html.find("function shadowAggregateTone", loader_start)
    loader_block = html[loader_start:loader_end]
    assert "setInterval" not in loader_block
