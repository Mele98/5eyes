"""CASHFLOW-GOAL-INCLUDE-TOGGLE-001: Source-Vertrag fuer den Ein-/Ausschalt-
Switch bei Einnahmen/Ausgaben (Cashflow-Zeilen) und Zielen (Goal-Karten).

Deckt NICHT die Backend-Berechnungs-Semantik ab (siehe
test_cashflow_goal_include_toggle_filters.py dafuer) -- nur, dass die UI
tatsaechlich einen Switch rendert, ihn verdrahtet und den ausgegrauten
Zustand anwendet, wie vom Berater gefordert ("ausgeblichen, wie bei jedem
anderen Anbieter/Games").
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_inc_switch_css_widget_exists():
    html = _html()
    assert ".inc-switch{" in html
    assert ".inc-switch-input{" in html
    assert ".inc-switch-track{" in html
    assert ".inc-switch-thumb{" in html
    assert ".inc-switch-input:checked+.inc-switch-track{" in html


def test_excluded_row_css_fades_but_keeps_switch_visible():
    html = _html()
    assert ".cf-row.is-excluded,.goal.is-excluded{opacity:.45;}" in html
    assert ".cf-row.is-excluded .inc-switch,.goal.is-excluded .inc-switch{opacity:1;}" in html


def test_cashflow_row_template_renders_toggle_and_excluded_class():
    html = _html()
    assert "var included=c.is_included!==0;" in html
    assert "(included?'':' is-excluded')" in html
    assert 'class="inc-switch-input"' in html


def test_cashflow_toggle_is_wired_on_both_income_and_expense_lists():
    html = _html()
    assert "function wireCashflowIncludeSwitches(container,cid){" in html
    assert "function toggleCashflowIncluded(input,cid){" in html
    assert "wireCashflowIncludeSwitches(zf,cid);" in html
    assert "wireCashflowIncludeSwitches(af,cid);" in html
    # PUT statt Loeschen -- der Eintrag bleibt erhalten.
    assert "API.put('/clients/'+activeCid+'/cashflows/'+cfId,{is_included:included})" in html


def test_goal_card_template_renders_toggle_and_excluded_class():
    html = _html()
    assert "var goalIncluded=goal.is_included!==0;" in html
    assert "(goalIncluded?'':' is-excluded')" in html
    assert 'class="inc-switch-input goal-include-toggle"' in html


def test_goal_toggle_is_wired_and_calls_put():
    html = _html()
    assert "function toggleGoalIncluded(input){" in html
    assert ".goal-include-toggle'),function(input){" in html
    assert "API.put('/mandates/'+mid+'/goals/'+gId,{is_included:included})" in html
