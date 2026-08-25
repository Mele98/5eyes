"""Roadmap #24-Rest (2026-08-09): Soft-Limit-Warn-UI im Team-Panel.

Pinnt per Quelltext-Assertion (konsistent mit den uebrigen test_frontend_*-
Tests), dass teamRender() die Auslastungs-Anzeige aus GET /tenants/me
(current_users/max_users) korrekt in eine Warn-/Limit-Anzeige uebersetzt,
BEVOR der harte 409-Block (services/quota.py) greift.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _team_render_body() -> str:
    html = _html()
    start = html.index("async function teamRender()")
    end = html.index("\nfunction teamMsg(", start)
    return html[start:end]


def test_team_render_fetches_tenant_usage():
    body = _team_render_body()
    assert "API.get('/tenants/me')" in body


def test_team_render_shows_warning_below_limit_and_block_message_at_limit():
    body = _team_render_body()
    assert "qWarn=!qAtLimit&&(qCur/qLim)>=0.8" in body
    assert "Fast ausgeschöpft" in body
    assert "Limit erreicht" in body


def test_team_render_quota_bar_uses_established_progress_bar_pattern():
    body = _team_render_body()
    # Identisches Balken-Muster wie das bestehende Governance-Status-Widget
    # (height:8px pill-bar mit farbcodierter Fuellung) -- kein neu erfundenes
    # UI-Idiom.
    assert "height:8px;background:var(--bg2);border-radius:999px;overflow:hidden" in body


def test_team_render_gracefully_handles_missing_tenant_info():
    body = _team_render_body()
    assert "try{ tenantInfo=await API.get('/tenants/me'); }catch(e){}" in body
    assert "if(tenantInfo&&Number(tenantInfo.max_users||0)>0){" in body
