"""CASHFLOW-GOAL-INCLUDE-TOGGLE-001-STALE-REFRESH-FIX: toggling two
DIFFERENT cashflow/goal rows in quick succession each starts its own
refreshCashflowsUI()/refreshGoalsUI() run (several parallel GETs). Without a
sequencing guard, an OLDER run (e.g. triggered by toggling "Lohn 2") can
resolve AFTER a NEWER run (triggered by toggling "Lohn") and overwrite the
newer run's freshly rendered rows with a stale snapshot -- the just-toggled
switch visually "jumps back" even though the server already has the correct
state. Live evidence (2026-10-08, user report "Togle lässt sich nicht ein
und ausschalten"): two PUTs on the same cashflow ~500ms apart, because the
user clicked a second time after the first click's visual result silently
reverted.

Fix: a per-function epoch/generation counter. Each call captures the epoch
value at its own start; before touching the DOM (both on the success path
and in the catch handler), it checks whether that epoch is still the latest
one. If a newer call has started since, the stale call's result is silently
dropped instead of being applied.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cashflow_refresh_has_epoch_counter():
    html = _html()
    assert "var _cashflowsUiRefreshEpoch=0;" in html
    assert "var __epoch=++_cashflowsUiRefreshEpoch;" in html


def test_cashflow_refresh_checks_epoch_before_rendering():
    html = _html()
    fn_start = html.index("async function refreshCashflowsUI(cid){")
    # Scope to this function only (up to the next top-level "async function").
    fn_end = html.index("async function loadPlanningAssumptions", fn_start)
    body = html[fn_start:fn_end]
    assert body.count("if(__epoch!==_cashflowsUiRefreshEpoch)return;") >= 2, (
        "Der Epoch-Check muss sowohl im Erfolgspfad (vor dem DOM-Update) als "
        "auch im catch-Block vorkommen, sonst kann ein veralteter Fehlerfall "
        "noch einen frischeren, erfolgreichen Lauf ueberschreiben."
    )


def test_cashflow_epoch_check_comes_before_dom_write():
    html = _html()
    fn_start = html.index("async function refreshCashflowsUI(cid){")
    idx_epoch_check = html.index("if(__epoch!==_cashflowsUiRefreshEpoch)return;", fn_start)
    idx_dom_write = html.index("currentCashflows=clientScopedItems(items,cid);", fn_start)
    assert idx_epoch_check < idx_dom_write


def test_goal_refresh_has_epoch_counter():
    html = _html()
    assert "var _goalsUiRefreshEpoch=0;" in html
    assert "var __epoch=++_goalsUiRefreshEpoch;" in html


def test_goal_refresh_checks_epoch_before_rendering():
    html = _html()
    fn_start = html.index("async function refreshGoalsUI(mid){")
    fn_end = html.index("\n}", html.index("catch(e){", fn_start))
    body = html[fn_start:fn_end]
    assert body.count("if(__epoch!==_goalsUiRefreshEpoch)return;") >= 2
