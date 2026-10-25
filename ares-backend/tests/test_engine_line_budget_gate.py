"""ENGINE-LINE-BUDGET-RATCHET-001 (Kontrollrunde 2026-09-27).

ADR-014 (2026-08-03) reduzierte services/portfolio_engine.py von 8'820 auf
~3'671 Zeilen -- ohne Schutzmechanismus wuchs die Datei binnen 7,5 Wochen
wieder auf 7'215 Zeilen (+95%) an. scripts/check_engine_line_budget.py ist
ein dependency-freier CI-Gate (eigener Job, kein pip install) dagegen.

Diese Tests laden das Script per importlib (analog test_security_gate_
manifest.py) statt es als Subprozess auszufuehren -- erlaubt, MAX_LINES
fuer die Grenzfall-Tests zu ueberschreiben, ohne die echte Engine-Datei
anzufassen.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
GATE_SCRIPT = REPO_ROOT / "scripts" / "check_engine_line_budget.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_engine_line_budget", GATE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_gate_script_exists():
    assert GATE_SCRIPT.is_file(), f"Line-Budget-Gate-Skript fehlt: {GATE_SCRIPT}"


def test_gate_points_at_the_correct_engine_file():
    gate = _load_gate()
    assert gate.ENGINE_FILE == BACKEND_ROOT / "services" / "portfolio_engine.py"
    assert gate.ENGINE_FILE.is_file()


def test_current_engine_file_is_within_budget():
    """Der Gate selbst darf develop nicht rot machen -- das Budget muss beim
    tatsaechlichen Ist-Stand (mit kleinem Puffer) liegen, nicht beim
    urspruenglichen ADR-014-Zielkorridor."""
    gate = _load_gate()
    actual_lines = gate.count_lines(gate.ENGINE_FILE)
    assert actual_lines <= gate.MAX_LINES, (
        f"services/portfolio_engine.py ({actual_lines} Zeilen) ueberschreitet "
        f"bereits das eben erst eingefuehrte Budget ({gate.MAX_LINES}) -- "
        "Budget-Konstante bei der Einfuehrung falsch gesetzt."
    )


def test_main_returns_zero_when_within_budget(monkeypatch):
    gate = _load_gate()
    monkeypatch.setattr(gate, "MAX_LINES", gate.count_lines(gate.ENGINE_FILE) + 100)
    assert gate.main() == 0


def test_main_returns_nonzero_when_budget_exceeded(monkeypatch, capsys):
    gate = _load_gate()
    monkeypatch.setattr(gate, "MAX_LINES", 1)  # garantiert ueberschritten
    exit_code = gate.main()
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ENGINE-ZEILENBUDGET UEBERSCHRITTEN" in captured.err
    assert "ADR-014" in captured.err


def test_main_returns_nonzero_when_engine_file_missing(monkeypatch, capsys):
    gate = _load_gate()
    monkeypatch.setattr(gate, "ENGINE_FILE", REPO_ROOT / "does" / "not" / "exist.py")
    exit_code = gate.main()
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "nicht gefunden" in captured.err


def test_count_lines_matches_wc_style_count(tmp_path):
    gate = _load_gate()
    sample = tmp_path / "sample.py"
    sample.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert gate.count_lines(sample) == 3
