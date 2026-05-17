"""Frontend-Contract-Tests fuer Auto-Recompute mit Debounce (Sprint 1 Item 2).

3eyes-Methodik Slide 9 Differenzierungsfaktor 'Interaktivitaet':
'Unmittelbare Berechnung und direktes Aufzeigen der Konsequenzen nach
jeder Eingabe im Beratungsgespraech'.

Statt manuellem 'Anlagestrategie berechnen'-Klick triggert jede
markStrategyDirty()-Aenderung nach 800ms Debounce einen Solver-Lauf.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def test_auto_recompute_config_constants_present():
    html = _html()
    assert "AUTO_RECOMPUTE_ENABLED = true" in html
    assert "AUTO_RECOMPUTE_DEBOUNCE_MS = 800" in html
    assert "_autoRecomputeTimer" in html


def test_schedule_auto_recompute_function_exists():
    html = _html()
    assert "function scheduleAutoRecompute(" in html


def test_mark_strategy_dirty_triggers_auto_recompute():
    """markStrategyDirty muss am Ende scheduleAutoRecompute aufrufen."""
    html = _html()
    # Function-Body extrahieren
    idx = html.find("function markStrategyDirty(message,invalidateOutputs){")
    assert idx >= 0
    end = html.find("\n}\n", idx)
    body = html[idx : end + 3]
    assert "scheduleAutoRecompute()" in body, "Auto-Recompute-Trigger fehlt in markStrategyDirty"


def test_auto_recompute_respects_demo_mandate_guard():
    """scheduleAutoRecompute skipt bei Demo-Mandate (kein API-Call ohne echte ID)."""
    html = _html()
    idx = html.find("function scheduleAutoRecompute(")
    assert idx >= 0
    end = html.find("\n}\n", idx)
    body = html[idx : end + 3]
    assert "isDemoMandateId" in body
    assert "getActiveMandateId" in body


def test_auto_recompute_respects_loading_guard():
    """scheduleAutoRecompute skipt wenn strategyState.loading bereits aktiv."""
    html = _html()
    idx = html.find("function scheduleAutoRecompute(")
    end = html.find("\n}\n", idx)
    body = html[idx : end + 3]
    assert "strategyState" in body and "loading" in body


def test_auto_recompute_debounce_clears_pending_timer():
    """Bei schnellen Aenderungen muss der Timer reset werden (Debounce)."""
    html = _html()
    idx = html.find("function scheduleAutoRecompute(")
    end = html.find("\n}\n", idx)
    body = html[idx : end + 3]
    assert "clearTimeout(_autoRecomputeTimer)" in body
    assert "setTimeout(" in body


def test_auto_recompute_calls_calculate_investment_strategy():
    """Im Timer-Callback wird calculateInvestmentStrategy gerufen."""
    html = _html()
    idx = html.find("function scheduleAutoRecompute(")
    end = html.find("\n}\n", idx)
    body = html[idx : end + 3]
    assert "calculateInvestmentStrategy()" in body


def test_auto_recompute_recheck_preconditions_at_fire_time():
    """Pre-Conditions (mandate, loading, dirty) werden zur Timer-Fire-Zeit re-checked,
    nicht nur beim Schedule (wichtig fuer Race-Conditions)."""
    html = _html()
    idx = html.find("function scheduleAutoRecompute(")
    end = html.find("\n}\n", idx)
    body = html[idx : end + 3]
    # Im Timer-Callback (setTimeout-Body) muss erneut isDemoMandateId aufgerufen werden
    timer_body_start = body.find("setTimeout(function(){")
    assert timer_body_start >= 0
    timer_body = body[timer_body_start:]
    assert "strategyState.dirty" in timer_body, "dirty re-check fehlt"
    assert "strategyState.loading" in timer_body, "loading re-check fehlt"
    assert "isDemoMandateId" in timer_body, "demo re-check fehlt"
