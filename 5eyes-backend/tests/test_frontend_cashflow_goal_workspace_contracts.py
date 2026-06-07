from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cashflow_workspace_uses_balanced_fifty_fifty_columns():
    html = _html()

    assert (
        "#page-cf .cashflow-client-layout{display:grid;"
        "grid-template-columns:repeat(2,minmax(0,1fr));"
    ) in html
    assert "#page-cf .cashflow-lists{grid-column:1;" in html
    assert "#page-cf .cf-ist-panel{grid-column:2;position:sticky;" in html


def test_cashflow_totals_are_rendered_below_ist_projection():
    html = _html()
    panel = html.split('<section class="cf-ist-panel" id="cf-ist-panel">', 1)[1].split(
        "</section>", 1
    )[0]

    assert panel.index('id="cf-goals-projection"') < panel.index(
        'class="cf-summary-strip"'
    )
    assert 'id="cf-summary-income"' in panel
    assert 'id="cf-summary-expense"' in panel
    assert 'id="cf-summary-net"' in panel


def test_cashflow_hud_is_moved_below_chart_and_above_totals():
    html = _html()
    panel = html.split('<section class="cf-ist-panel" id="cf-ist-panel">', 1)[1].split(
        "</section>", 1
    )[0]

    assert panel.index('id="cf-goals-projection"') < panel.index(
        'id="cf-cashflow-hud-slot"'
    )
    assert panel.index('id="cf-cashflow-hud-slot"') < panel.index(
        'class="cf-summary-strip"'
    )
    assert (
        "if(cashflowHudSlot&&cashflowHud&&cashflowHud.parentNode!==cashflowHudSlot)"
        "cashflowHudSlot.appendChild(cashflowHud);"
    ) in html
    assert 'class="cf-hud-grid"' in html
    assert "#page-cf #cf-projection{display:none" not in html


def test_goal_create_and_edit_actions_remain_visible_and_functional():
    html = _html()

    assert '<button class="btn" onclick="om(\'m-nz\')">Ziel erfassen</button>' in html
    assert "if(goalAdd){goalAdd.textContent='Ziel erfassen';" in html
    assert "goalAdd.style.removeProperty('display')" in html
    assert 'class="btn btn-sm goal-edit-action" type="button">Bearbeiten</button>' in html
    assert "openGoalEditor(card.getAttribute('data-goalid')||'');" in html
    assert "btn.classList.contains('goal-delete-action')" in html


def test_goal_editor_supports_description_and_persists_it():
    html = _html()

    assert 'id="nz-notes"' in html
    assert "setInputValue('nz-notes',goal.notes||'');" in html
    assert "var notes=getInputValue('nz-notes').trim();" in html
    assert "notes:notes||null," in html
    assert "notes:payload.notes," in html
    assert "#m-nz .modal{width:min(720px,calc(100vw - 32px));}" in html
    assert ".gf.fg{background:var(--pos);}" in html
    assert "\n.fg{background:var(--pos);}" not in html
    assert 'id="nz-label" type="text" autocomplete="off"' in html
    assert "function bindGoalEditorTyping()" in html
    assert "event.stopPropagation();" in html


def test_hard_goal_is_only_disabled_for_non_binding_goal_types():
    html = _html()

    assert "'Einmalige_Ausgabe':{show:" in html
    assert "'Verm\\u00f6gensziel':{show:" in html
    assert "hardness_hart:true" in html
    assert (
        "'Renditeziel':{show:['target-return-bps','target-date','duration-years',"
        "'priority-rank','success-prob-min'],required:['target-return-bps'],"
        "hardness_hart:false"
    ) in html
    assert "if(hartOpt)hartOpt.disabled=!cfg.hardness_hart;" in html
    assert "prioritySelect.options[0].textContent='Hart - muss erreicht werden';" in html


def test_return_goal_accepts_typed_swiss_decimal_values():
    html = _html()

    assert (
        'id="nz-target-return-bps" type="text" inputmode="decimal" '
        'autocomplete="off"'
    ) in html
    assert "replace(',','.')" in html
    assert "parsePercentToBps(returnRaw)" in html


def test_saved_goal_is_immediately_upserted_with_backend_id_for_re_editing():
    html = _html()

    assert "function upsertSavedGoal(savedGoal,fallbackId,payload)" in html
    assert "var goalIdBeforeSave=currentGoalEditId;" in html
    assert "var savedGoal=isEdit" in html
    assert "upsertSavedGoal(savedGoal,goalIdBeforeSave,payload);" in html
    assert "renderGoalList(currentGoals,false);" in html


def test_goal_change_marks_visible_allocation_as_stale():
    html = _html()

    assert (
        "Die angezeigte Soll-Allokation ist noch der alte Stand - "
        "bitte Anlagestrategie neu berechnen."
    ) in html
    assert "Dieses ältere Renditeziel war als Hart gespeichert." in html
