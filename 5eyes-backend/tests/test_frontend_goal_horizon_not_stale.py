"""GOAL-HORIZON-STALE-001 (Audit-Finding, 2026-10-07): source-level contract
for saveGoal() in 5eyes_v2.html.

Befund: saveGoal() las bisher den rohen, nie nachgefuehrten Wert aus dem
#nz-horizon-Eingabefeld, waehrend die live angezeigte Zielrendite-Kennzahl
(updateGoalDerivedDiagnostics) bereits goalEditorHorizonYears() nutzt, das
bei gesetztem Zieldatum korrekt daraus rechnet. Konkret reproduziert (live
im Browser): ein Ziel mit Zieldatum in ~5.6 Jahren speicherte trotzdem
horizon_years=10 (unveraenderter Default). services/portfolio_engine_mc_
simulation.py::_dated_goal_horizon() nutzt max(horizon_years, datums-
abgeleitete-Jahre) als NULL-Sicherheitsnetz -- ein nicht-null-aber-
veralteter, zu grosser Wert blaeht dadurch den Monte-Carlo-Horizont des
gesamten Mandats stillschweigend auf."""
from __future__ import annotations

from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _save_goal_fn() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    return html.split(
        "async function saveGoal(options){", 1
    )[1].split("function strategyGoalTargetText(", 1)[0]


def test_save_goal_does_not_read_raw_horizon_field_independently():
    fn = _save_goal_fn()
    assert "parseInt(getInputValue('nz-horizon')" not in fn, (
        "saveGoal() darf horizon_years nicht mehr unabhaengig aus dem rohen "
        "#nz-horizon-Feld lesen -- das Feld wird beim Setzen eines Zieldatums "
        "nie sichtbar nachgefuehrt, siehe GOAL-HORIZON-STALE-001."
    )


def test_save_goal_reuses_the_same_horizon_function_as_the_live_diagnostic():
    fn = _save_goal_fn()
    assert "goalEditorHorizonYears()" in fn, (
        "saveGoal() muss horizon_years ueber dieselbe Funktion ableiten, die "
        "auch die Live-Diagnose (updateGoalDerivedDiagnostics) verwendet, "
        "damit gespeicherter und angezeigter Wert nie auseinanderlaufen."
    )
