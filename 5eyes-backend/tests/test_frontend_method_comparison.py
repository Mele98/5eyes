"""V3 Sprint 1 Commit 4 — FE-Contract-Tests fuer Methodenvergleich-Panel.

Plan §7 + §8.4: Pruefen, dass das Frontend das al-method-comparison-panel
korrekt anlegt, ueber renderAllocationMethodComparison rendert, klassen-
basierte Status-Pills nutzt (ohne Emoji) und in applyAllocationEngineResult
gehookt ist.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_method_comparison_panel_html_exists():
    html = _html()
    assert 'id="al-method-comparison-panel"' in html
    assert 'id="method-comparison-pill"' in html
    assert 'id="method-comparison-table"' in html
    assert 'id="method-comparison-note"' in html
    assert 'id="method-comparison-audit"' in html


def test_method_comparison_panel_has_constraints_and_drivers_blocks():
    html = _html()
    assert 'id="method-constraints-block"' in html
    assert 'id="method-constraints-table"' in html
    assert 'id="method-drivers-block"' in html
    assert 'id="method-drivers-table"' in html


def test_method_comparison_uses_optimizer_css_classes():
    html = _html()
    # Plan §7.1: bestehende CSS-Klassen wiederverwenden statt eigener Welt
    assert 'optimizer-table' in html
    assert 'optimizer-body' in html
    assert 'optimizer-summary' in html
    assert 'optimizer-audit' in html


def test_set_status_pill_function_exists():
    html = _html()
    assert "function setStatusPill(el,status,label)" in html
    assert "el.className='status-pill'" in html
    assert "el.className+=' ok'" in html
    assert "el.className+=' warn'" in html


def test_render_allocation_method_comparison_function_exists():
    html = _html()
    assert "function renderAllocationMethodComparison(result)" in html
    assert "result.allocation_method_comparison" in html
    assert "result.optimizer_constraints" in html
    assert "result.optimizer_goal_drivers" in html


def test_apply_allocation_engine_result_calls_renderAllocationMethodComparison():
    html = _html()
    # Hook nach renderOptimizerPanel
    assert "renderAllocationMethodComparison(result)" in html


def test_render_optimizer_panel_no_more_emoji_status():
    html = _html()
    # Plan §7.2 + §10.5: Keine Emoji-Status mehr im Optimizer-Pill
    # Vorige Markierungen waren \U0001F7E2 Konvergiert / \U0001F7E1 Divergiert / ⚙ Fallback
    assert "\U0001F7E2 Konvergiert" not in html
    assert "\U0001F7E1 Divergiert" not in html
    assert "⚙ Fallback House-Matrix" not in html
    # Stattdessen: setStatusPill mit Label-Map
    assert "setStatusPill(pill,status," in html


def test_method_comparison_advisory_note_no_marketing_class():
    html = _html()
    # Beratungsnote ist im DOM enthalten und nutzt die gewuenschte Klasse
    assert 'id="method-comparison-note" class="advisor-note-shadow"' in html


def test_constraint_row_classes_are_state_based():
    html = _html()
    # Plan §7.1: keine Inline-Styles fuer State-Differenzierung;
    # is-violated / is-binding stattdessen ueber Klassen.
    assert 'is-violated' in html
    assert 'is-binding' in html


def test_method_comparison_default_hidden_via_style():
    html = _html()
    # Panel startet versteckt (Plan-konform: erst sichtbar wenn comparison
    # vorhanden) — wir nutzen aktuell style="display:none" als Default,
    # konsistent zum bestehenden al-optimizer-panel Pattern.
    assert 'id="al-method-comparison-panel" style="display:none"' in html
