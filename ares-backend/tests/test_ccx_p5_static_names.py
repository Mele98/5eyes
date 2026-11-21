"""CCX P5 Fixrunde 1 / N-925-02: statischer Waechter (ohne neue Abhaengigkeit).

Im Prueflauf H-178 stand in ``routers/review.py::sign_document`` ein Block NACH
``return doc``, der Namen benutzte, die im Modul nirgends gebunden waren. CI hat
kein Lint; dieser AST-Test faengt beide Klassen fuer die von P5 geaenderten
Router und Gate-Module:

* unerreichbare Anweisungen direkt nach ``return``/``raise``/``continue``/``break``;
* in Funktionen gelesene Namen, die weder lokal, in einer umschliessenden
  Funktion, auf Modulebene noch als Builtin gebunden sind (konservative
  Naeherung wie pyflakes F821: jede Bindung irgendwo in der Funktion zaehlt).
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CHECKED = (
    "routers/review.py",
    "routers/onsite_signature.py",
    "routers/portfolio_handoff.py",
    "routers/pdf_reports.py",
    "services/allocation_publication_gate.py",
    "services/recommendation_release_gate.py",
    "services/advisory_decision_envelope.py",
    "core/risk_parameter_set.py",
    "core/goal_metric_contract.py",
)
_TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            names.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(sub.name)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(sub, ast.arg):
            names.add(sub.arg)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            names.add(sub.name)
        elif isinstance(sub, (ast.Global, ast.Nonlocal)):
            names.update(sub.names)
        elif isinstance(sub, ast.MatchAs) and sub.name:
            names.add(sub.name)
    return names


def unreachable_statements(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for index, stmt in enumerate(block[:-1]):
                if isinstance(stmt, _TERMINAL):
                    lines.append(block[index + 1].lineno)
                    break
    return lines


def undefined_names(tree: ast.Module) -> list[tuple[int, str]]:
    module_names = _bound_names(tree) | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    found: list[tuple[int, str]] = []

    def visit(func: ast.AST, enclosing: set[str]) -> None:
        local = enclosing | _bound_names(func)
        for sub in ast.walk(func):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id not in local \
                    and sub.id not in module_names:
                found.append((sub.lineno, sub.id))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, set())
    return sorted(set(found))


@pytest.mark.parametrize("rel", CHECKED)
def test_no_unreachable_code_and_no_undefined_names(rel):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    assert unreachable_statements(tree) == [], rel
    assert undefined_names(tree) == [], rel


def test_guard_detects_the_h178_dead_block():
    """Gegenprobe: genau die Form des Befunds wird erkannt."""
    source = (
        "def sign_document(doc):\n"
        "    return doc\n"
        "    if document_type in DECISION_ARTIFACT_DOCUMENT_TYPES:\n"
        "        return require_signable_decision_artifact(doc)\n"
    )
    tree = ast.parse(source)
    assert unreachable_statements(tree) == [3]
    assert {name for _line, name in undefined_names(tree)} == {
        "document_type", "DECISION_ARTIFACT_DOCUMENT_TYPES", "require_signable_decision_artifact",
    }
