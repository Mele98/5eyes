"""CASHFLOW-GOAL-INCLUDE-TOGGLE-001-RACE-FIX: after toggling a cashflow or
goal's include/exclude switch, the frontend does an async PUT followed by a
full UI refresh (refreshCashflowsUI/refreshGoalsUI -- several sequential API
calls plus a projection-chart rebuild, which can take long enough to be
perceptible). If the switch stays interactive during that window, a second,
impatient click lands on the still-live checkbox and fires a second PUT that
flips the value right back -- the two requests race and cancel each other
out, so the toggle appears to silently "not work".

Confirmed live (2026-10-08) in the real backend's access log: two successful
PUT /clients/{id}/cashflows/{id} requests to the SAME cashflow, ~500ms apart,
net result identical to the pre-click state.

Fix: disable the checkbox immediately after reading its new value, so a
second click during the in-flight window is a no-op (disabled form controls
don't fire click/change). The success path doesn't need an explicit
re-enable: refreshCashflowsUI/refreshGoalsUI replaces the row's entire DOM
with a freshly rendered (enabled-by-default) input. The failure path keeps
the same input, so it IS re-enabled explicitly there.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cashflow_toggle_disables_input_before_put():
    html = _html()
    fn_start = html.index("function toggleCashflowIncluded(input,cid){")
    fn_end = html.index("\n}", fn_start)
    body = html[fn_start:fn_end]
    idx_disable = body.index("input.disabled=true;")
    idx_put = body.index("API.put('/clients/'+activeCid+'/cashflows/'+cfId")
    assert idx_disable < idx_put, (
        "input.disabled=true muss VOR dem PUT-Aufruf stehen, sonst kann ein "
        "zweiter Klick waehrend des PUT noch durchkommen."
    )


def test_cashflow_toggle_reenables_input_only_on_failure():
    html = _html()
    fn_start = html.index("function toggleCashflowIncluded(input,cid){")
    fn_end = html.index("\n}", fn_start)
    body = html[fn_start:fn_end]
    # Erfolgsfall: KEIN explizites input.disabled=false -- refreshCashflowsUI
    # ersetzt die Zeile durch ein frisches, automatisch enabled Element.
    then_start = body.index(".then(function(){")
    catch_start = body.index(".catch(function(e){")
    then_block = body[then_start:catch_start]
    catch_block = body[catch_start:]
    assert "input.disabled=false" not in then_block
    assert "input.disabled=false" in catch_block


def test_goal_toggle_disables_input_before_put():
    html = _html()
    fn_start = html.index("function toggleGoalIncluded(input){")
    fn_end = html.index("\n}", fn_start)
    body = html[fn_start:fn_end]
    idx_disable = body.index("input.disabled=true;")
    idx_put = body.index("API.put('/mandates/'+mid+'/goals/'+gId")
    assert idx_disable < idx_put


def test_goal_toggle_reenables_input_only_on_failure():
    html = _html()
    fn_start = html.index("function toggleGoalIncluded(input){")
    fn_end = html.index("\n}", fn_start)
    body = html[fn_start:fn_end]
    then_start = body.index(".then(async function(){")
    catch_start = body.index(".catch(function(e){")
    then_block = body[then_start:catch_start]
    catch_block = body[catch_start:]
    assert "input.disabled=false" not in then_block
    assert "input.disabled=false" in catch_block


def test_disabled_switch_css_exists():
    html = _html()
    assert ".inc-switch-input:disabled+.inc-switch-track{opacity:.55;}" in html
