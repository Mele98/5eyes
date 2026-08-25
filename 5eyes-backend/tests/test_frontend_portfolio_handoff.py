"""Weiterleitung ans Asset Management -- Frontend-Wiring (2026-08-08).

Pinnt per Quelltext-Assertion (konsistent mit den uebrigen test_frontend_*-
Tests, kein Node/DOM-Runtime im Testbaum), dass der "An Asset Management
weiterleiten"-Block im Handelsliste-Modal (#m-tl) korrekt verdrahtet ist:
nur fuer discretionaere Mandate sichtbar (dasselbe Gate wie die Handelsliste
selbst), ruft die drei Backend-Endpunkte korrekt auf, und der Verlauf wird
nach jeder Statusaenderung neu geladen.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_handoff_functions_exist():
    html = _html()
    for fn in (
        "function renderPortfolioHandoffSection()",
        "async function submitPortfolioHandoff()",
        "async function loadPortfolioHandoffHistory()",
        "function renderPortfolioHandoffHistory(items)",
        "async function markPortfolioHandoffExecuted(handoffId)",
        "async function cancelPortfolioHandoffPrompt(handoffId)",
    ):
        assert fn in html


def test_handoff_section_gated_by_discretionary_mandate_check():
    html = _html()
    start = html.index("function renderPortfolioHandoffSection()")
    end = html.index("function submitPortfolioHandoff()", start)
    body = html[start:end]
    # Identisches Gate wie die Handelsliste-CTA selbst -- Anlageberatung ohne
    # Ausfuehrungsbefugnis darf diese Aktion nie sehen.
    assert "_reviewIsDiscretionaryMandate()" in body


def test_open_trade_list_seeds_handoff_context_from_run_id():
    html = _html()
    start = html.index("function openTradeList()")
    end = html.index("function renderPortfolioHandoffSection()", start)
    body = html[start:end]
    assert "_tlHandoffCtx={mandateId:getActiveMandateId(),runId:runId}" in body
    assert "renderPortfolioHandoffSection();" in body


def test_submit_calls_create_handoff_endpoint_with_run_id():
    html = _html()
    start = html.index("async function submitPortfolioHandoff()")
    end = html.index("function _handoffStatusColor(status)", start)
    body = html[start:end]
    assert "API.post('/mandates/'+_tlHandoffCtx.mandateId+'/recommendations/'+_tlHandoffCtx.runId+'/portfolio-handoffs',payload)" in body


def test_mark_executed_and_cancel_call_correct_endpoints():
    html = _html()
    assert "/portfolio-handoffs/'+handoffId+'/mark-executed'" in html
    assert "/portfolio-handoffs/'+handoffId+'/cancel'" in html
    # Stornierung verlangt eine Begruendung (window.prompt), kein stiller Abbruch.
    start = html.index("async function cancelPortfolioHandoffPrompt(handoffId)")
    end = html.index("\n}", start)
    body = html[start:end]
    assert "window.prompt(" in body
    assert "cancelled_reason:reason.trim()" in body


def _next_top_level_function_index(html: str, after: int) -> int:
    candidates = [
        idx for idx in (
            html.find("\nfunction ", after),
            html.find("\nasync function ", after),
        ) if idx != -1
    ]
    assert candidates, "keine folgende Top-Level-Funktion gefunden"
    return min(candidates)


def test_history_reloaded_after_status_changing_actions():
    html = _html()
    for fn_start in (
        "async function submitPortfolioHandoff()",
        "async function markPortfolioHandoffExecuted(handoffId)",
        "async function cancelPortfolioHandoffPrompt(handoffId)",
    ):
        start = html.index(fn_start)
        fn_end = _next_top_level_function_index(html, start + len(fn_start))
        body = html[start:fn_end]
        assert "loadPortfolioHandoffHistory()" in body


def test_trade_list_modal_gets_handoff_host_div():
    html = _html()
    start = html.index("function openTradeList()")
    end = html.index("function renderPortfolioHandoffSection()", start)
    body = html[start:end]
    assert "id=\"m-tl-handoff\"" in body or "id='m-tl-handoff'" in body
