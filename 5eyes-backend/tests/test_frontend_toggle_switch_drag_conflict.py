"""CASHFLOW-GOAL-INCLUDE-TOGGLE-001-DRAG-FIX: the include/exclude toggle
switch (.inc-switch, a <label> wrapping a checkbox) lives inside a
draggable="true" cashflow/goal row. A real mouse click on the switch almost
always involves a tiny amount of cursor movement between mousedown and
mouseup -- enough to cross the browser's native HTML5 drag-initiation
threshold. Without excluding the switch from the row's dragstart handler,
that movement hijacks the interaction into a row-drag instead of a normal
click, so the checkbox's click/change event never fires and the switch
cannot be reliably toggled with a real mouse (user report, 2026-10-08:
"sehe ihn, kann aber nicht sauber ein- und ausschalten").

The cashflow row's dragstart handler already excluded `<button>` targets
(the edit/delete icons) for the identical reason -- this fix extends that
same exclusion to `.inc-switch`, and adds the previously entirely-missing
exclusion to the goal row's dragstart handler.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cashflow_row_dragstart_excludes_include_switch():
    html = _html()
    assert "ev.target.closest('button,.inc-switch')" in html, (
        "Cashflow-Zeilen-Dragstart muss den Include-Switch (ein <label>, kein "
        "<button>) explizit ausschliessen, sonst hijackt ein Klick darauf den "
        "Zeilen-Drag statt den Switch umzuschalten."
    )


def test_goal_row_dragstart_excludes_include_switch():
    html = _html()
    assert "e.target.closest('button,.inc-switch')" in html, (
        "Goal-Karten-Dragstart hatte bisher GAR KEINEN Ausschluss fuer "
        "interaktive Controls -- muss den Include-Switch ausschliessen, "
        "analog zum Cashflow-Pattern."
    )


def test_cashflow_dragstart_guard_comes_before_drag_assignment():
    """Die preventDefault-Pruefung muss VOR 'dragging=row' stehen, sonst wird
    der Drag trotzdem initiiert, bevor er abgebrochen wird."""
    html = _html()
    idx_guard = html.index("ev.target.closest('button,.inc-switch')")
    idx_drag_assign = html.index("dragging=row;", idx_guard)
    assert idx_guard < idx_drag_assign


def test_goal_dragstart_guard_comes_before_drag_assignment():
    html = _html()
    idx_guard = html.index("e.target.closest('button,.inc-switch')")
    idx_drag_assign = html.index("drag=this;this.style.opacity='0.4';", idx_guard)
    assert idx_guard < idx_drag_assign
