"""RC-CH-1-F1 / N-903-07: AST-Waechter fuer ``except IntegrityError``-Zweige.

Bugklasse: ein Zweig, der jeden Integritaetsfehler als Konflikt meldet
(409, "existiert bereits", "gleichzeitig gespeichert"), meldet auch eine
CHECK-Verletzung falsch (Befund ``POST /clients``: 409 "Kundennummer bereits
vergeben" fuer einen ungueltigen Familienstand).

Regel: jeder ``except IntegrityError``-Zweig (SQLAlchemy) im Backend-Code ruft
``raise_if_check_violation`` oder ``is_check_constraint_violation`` aus
``core.db_integrity`` -- oder steht mit Begruendung in ``ALLOWED``. Ein neuer
Zweig ohne beides macht den Test rot; ein veralteter ALLOWED-Eintrag auch.

Mutationskontrolle: wird der Helfer an einer Stelle entfernt, meldet der
Scanner genau diese Stelle (``test_mutation_*``).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {"tests", "alembic", "scripts", "migrations", ".venv", "venv", "node_modules", "__pycache__"}
HELPERS = {"raise_if_check_violation", "is_check_constraint_violation"}

# (Datei, Funktion) -> Begruendung. Nur Zweige, die gezielt EINEN bekannten
# Constraint abbilden und jeden anderen Integritaetsfehler unveraendert
# weiterwerfen -- eine CHECK-Verletzung erreicht dort den zentralen Handler.
ALLOWED: dict[tuple[str, str], str] = {
    ("routers/review.py", "create_trigger"):
        "bildet nur die review_triggers.frequency-CHECK-Meldung auf 422 ab, sonst bare raise",
    ("routers/review.py", "create_advisory_log_entry"):
        "bildet nur die advisory_log.decision-CHECK-Meldung auf 422 ab, sonst bare raise",
    ("routers/wealth.py", "_commit_inflow_or_422"):
        "bildet nur den aktiven Verknuepfungs-Index auf 422 ab, sonst bare raise",
    ("routers/wealth.py", "reorder_goals"):
        "bildet nur ux_goals_rank_active (is_goal_rank_unique_violation) auf 409 ab, sonst bare raise",
}


_EXC_MODULES = frozenset({"exc", "sqlalchemy.exc", "sa_exc"})


def _import_aliases(tree: ast.AST) -> tuple[frozenset[str], frozenset[str]]:
    """F1-Hinweis (H11): Import-Aliase der SQLAlchemy-Ausnahme aufloesen.

    Liefert (Namen fuer ``IntegrityError``, Namen fuer das Modul ``sqlalchemy.exc``):
    ``from sqlalchemy.exc import IntegrityError as Dup``, ``from sqlalchemy import exc as e``,
    ``import sqlalchemy.exc as sqla_exc``. ``sqlite3.IntegrityError`` bleibt aussen vor.
    """
    names, modules = {"IntegrityError"}, set(_EXC_MODULES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("sqlalchemy.exc", "sqlalchemy"):
            for alias in node.names:
                if node.module == "sqlalchemy.exc" and alias.name == "IntegrityError":
                    names.add(alias.asname or alias.name)
                elif node.module == "sqlalchemy" and alias.name == "exc":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlalchemy.exc" and alias.asname:
                    modules.add(alias.asname)
    return frozenset(names), frozenset(modules)


def _is_sqlalchemy_integrity_error(node: ast.expr | None, names: frozenset[str] = frozenset({"IntegrityError"}),
                                   modules: frozenset[str] = _EXC_MODULES) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Tuple):
        return any(_is_sqlalchemy_integrity_error(e, names, modules) for e in node.elts)
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute) and node.attr == "IntegrityError":
        # sqlalchemy.exc.IntegrityError / exc.IntegrityError (auch per Alias), nicht sqlite3.*
        return ast.unparse(node.value) in modules
    return False


def _calls_helper(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name in HELPERS:
                return True
    return False


def scan_source(rel: str, source: str) -> list[tuple[str, str, int, bool]]:
    """[(Datei, Funktion, Zeile, ruft_Helfer)] fuer alle IntegrityError-Zweige."""
    tree = ast.parse(source)
    names, modules = _import_aliases(tree)
    found: list[tuple[str, str, int, bool]] = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            if isinstance(child, ast.ExceptHandler) and _is_sqlalchemy_integrity_error(child.type, names, modules):
                found.append((rel, func, child.lineno, _calls_helper(child)))
            visit(child, name)

    visit(tree, "<module>")
    return found


def _backend_files() -> list[Path]:
    out = []
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT)
        if rel.parts and rel.parts[0] in EXCLUDED_DIRS:
            continue
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        out.append(path)
    return out


def _all_branches() -> list[tuple[str, str, int, bool]]:
    branches = []
    for path in _backend_files():
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if "IntegrityError" in source:
            branches.extend(scan_source(rel, source))
    return branches


def test_scanner_finds_the_known_branches():
    """Positivkontrolle: ohne Funde waere der Waechter gruen ohne Aussage."""
    branches = _all_branches()
    assert len(branches) >= 20, branches
    files = {rel for rel, *_ in branches}
    assert {"routers/clients.py", "routers/mandates.py", "services/onsite_signature/service.py"} <= files


def test_every_integrity_error_branch_handles_check_violations_or_is_allowed():
    offenders = [
        f"{rel}:{line} ({func})"
        for rel, func, line, helper in _all_branches()
        if not helper and (rel, func) not in ALLOWED
    ]
    assert not offenders, (
        "except IntegrityError ohne raise_if_check_violation/is_check_constraint_violation "
        "(CHECK-Verstoss wuerde als Konflikt gemeldet) -- Helfer aufrufen oder in ALLOWED "
        "begruenden:\n" + "\n".join(offenders)
    )


def test_allowed_entries_are_current_and_reraise():
    branches = {(rel, func): helper for rel, func, _line, helper in _all_branches()}
    stale = [key for key in ALLOWED if key not in branches or branches[key]]
    assert not stale, f"veraltete ALLOWED-Eintraege (Zweig weg oder ruft inzwischen den Helfer): {stale}"
    # Jeder erlaubte Zweig endet in einem bare ``raise`` (Weitergabe an den Handler).
    for rel, func in ALLOWED:
        tree = ast.parse((BACKEND_ROOT / rel).read_text(encoding="utf-8"))
        names, modules = _import_aliases(tree)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func)
        handlers = [h for h in ast.walk(fn)
                    if isinstance(h, ast.ExceptHandler) and _is_sqlalchemy_integrity_error(h.type, names, modules)]
        assert handlers, (rel, func)
        for handler in handlers:
            assert any(isinstance(s, ast.Raise) and s.exc is None for s in handler.body), (rel, func)


@pytest.mark.parametrize("rel, func", [
    ("routers/mandates.py", "create_mandate"),
    ("services/onsite_signature/service.py", "_commit"),
    ("routers/clients.py", "create_client"),
])
def test_mutation_removing_the_helper_is_detected(rel, func):
    source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
    before = [b for b in scan_source(rel, source) if b[1] == func]
    assert before and all(helper for *_x, helper in before), before
    mutated = (
        source.replace("raise_if_check_violation(exc)", "pass")
        .replace("if is_check_constraint_violation(exc):", "if False:")
    )
    after = [b for b in scan_source(rel, mutated) if b[1] == func]
    assert after and not any(helper for *_x, helper in after), after
    assert (rel, func) not in ALLOWED


def test_profiling_uses_the_shared_detection():
    """N-903-06: kein eigener pgcode-Check mehr (psycopg 3: sqlstate); Log ohne exc.orig."""
    import inspect

    import routers.profiling as profiling

    assert not hasattr(profiling, "_is_check_violation")
    source = inspect.getsource(profiling.create_risk_assessment)
    assert "is_check_constraint_violation(exc)" in source
    assert "check_constraint_label(exc)" in source and "exc.orig" not in source


# ── H11 (F1-Hinweis): Import-Alias von IntegrityError ────────────────────────

_ALIAS_SOURCES = [
    "from sqlalchemy.exc import IntegrityError as Dup\n"
    "def f(db):\n    try:\n        db.commit()\n    except Dup:\n        raise Conflict()\n",
    "from sqlalchemy import exc as sqla\n"
    "def f(db):\n    try:\n        db.commit()\n    except sqla.IntegrityError:\n        raise Conflict()\n",
    "import sqlalchemy.exc as sx\n"
    "def f(db):\n    try:\n        db.commit()\n    except (ValueError, sx.IntegrityError):\n        raise Conflict()\n",
]


@pytest.mark.parametrize("source", _ALIAS_SOURCES)
def test_import_alias_of_integrity_error_is_detected(source):
    assert scan_source("routers/x.py", source) == [("routers/x.py", "f", 5, False)]


def test_alias_branch_with_helper_counts_as_handled():
    source = _ALIAS_SOURCES[0].replace("raise Conflict()", "raise_if_check_violation(exc)\n        raise Conflict()")
    assert scan_source("routers/x.py", source) == [("routers/x.py", "f", 5, True)]


def test_sqlite3_alias_is_not_sqlalchemy():
    source = ("from sqlite3 import IntegrityError as SqliteDup\nimport sqlite3 as sq\n"
              "def f(db):\n    try:\n        db.commit()\n    except SqliteDup:\n        pass\n"
              "    try:\n        db.commit()\n    except sq.IntegrityError:\n        pass\n")
    assert scan_source("routers/x.py", source) == []
