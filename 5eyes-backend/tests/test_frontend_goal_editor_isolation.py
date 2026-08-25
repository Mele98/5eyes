from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_goal_editor_stage6_fields_exist():
    html = _html()
    assert 'data-stage6-id="m-acf-type-select"' in html
    assert 'id="m-acf-family-hint"' in html
    assert 'data-stage6-id="m-acf-target-return-bps"' in html
    assert 'id="nz-target-return-bps"' in html
    assert 'data-stage6-id="m-acf-success-prob-min"' in html
    assert 'id="m-acf-derived"' in html


def test_goal_type_visibility_config_covers_stage6_types():
    html = _html()
    assert "var GOAL_TYPE_FIELDS=" in html
    for goal_type in [
        "Einmalige_Ausgabe",
        "Pensionsausgabe",
        "Wiederkehrende_Ausgabe",
        "Renditeziel",
        "Maximierung",
    ]:
        assert goal_type in html
    assert "applyGoalTypeVisibility(type)" in html
    assert "updateGoalDerivedDiagnostics()" in html


def test_return_goal_hardness_hart_is_disabled_and_saved_as_return_bps():
    html = _html()
    assert 'id="nz-prio-hart-option"' in html
    assert "hartOpt.disabled=!cfg.hardness_hart" in html
    assert "Renditeziele koennen nicht als Hart gespeichert werden" in html
    assert "returnRaw=getInputValue('nz-target-return-bps')" in html
    assert "payload.target_return_bps=targetReturnBps" in html


def test_success_probability_override_is_payload_wired():
    html = _html()
    assert "success_probability_min_x100:" in html
    assert "getInputValue('nz-success-prob-min')" in html
    assert "success_probability_min_x100:payload.success_probability_min_x100" in html
    assert "goal.success_probability_min_x100==null?'':String" in html
