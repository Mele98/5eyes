from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_allocation_message_banner_dom_exists():
    html = _html()
    assert 'id="al-message-banner"' in html
    assert "al-banner-conflict" in html
    assert "al-banner-warning" in html
    assert "al-banner-title" in html
    assert "al-banner-body" in html
    assert "al-banner-actions" in html


def test_allocation_message_banner_renderer_uses_backend_messages():
    html = _html()
    assert "function allocationMessages(result)" in html
    assert "function firstVisibleAllocationMessage(messages)" in html
    assert "function renderAllocationMessageBanner(result)" in html
    assert "msg.severity==='conflict'" in html
    assert "msg.body_client||msg.body_advisor" in html
    assert "renderAllocationMessageBanner(result)" in html


def test_optimizer_panel_has_limiting_factor_and_achievability_table():
    html = _html()
    assert 'id="opt-limiting-factor-badge"' in html
    assert 'id="opt-achievability-block"' in html
    assert 'id="opt-achievability-table"' in html
    assert "function renderOptimizerAchievability(result)" in html
    assert "renderOptimizerAchievability(result)" in html


def test_no_forbidden_customer_copy_added_in_stage6_surface():
    html = _html()
    for forbidden in [
        "Erhöhen Sie Ihr Risiko",
        "Erhoehen Sie Ihr Risiko",
        "raise your risk",
        "garantiert",
        "Garantieversprechen",
        "perfekt",
        "Top-Strategie",
    ]:
        assert forbidden not in html
