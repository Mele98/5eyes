"""DB-ENGINE-DEFAULT-BINDING-001: keine Engine-/Session-Objekte als Default-Argument.

Ein Default wie ``def f(target_engine=engine)`` oder ``db=SessionLocal()`` wird
beim IMPORT ausgewertet und bindet die Funktion fuer immer an die damals
konfigurierte Datenbank. Erlaubt ist nur ``None`` mit Aufloesung zur Aufrufzeit
(``database._resolve_engine``). FastAPI-``Depends(get_db)`` ist unkritisch (die
Abhaengigkeit wird pro Request aufgeloest) und wird nicht erfasst.

Ratsche auf 0: jeder neue Treffer im Produktionscode laesst diesen Test scheitern.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SKIP_DIRS = {"tests", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
_DB_NAMES = {"engine", "SessionLocal", "Session", "sessionmaker", "create_engine", "create_app_engine"}

def _references_db_object(default: ast.expr) -> bool:
    for node in ast.walk(default):
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        else:
            continue
        if name in _DB_NAMES or name.endswith("_engine") or name.endswith("SessionLocal"):
            return True
    return False


def _production_files():
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT)
        if _SKIP_DIRS.intersection(rel.parts):
            continue
        yield path, rel.as_posix()


def _violations() -> list[str]:
    found: list[str] = []
    for path, rel in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            args = node.args
            defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
            for default in defaults:
                if _references_db_object(default):
                    name = getattr(node, "name", "<lambda>")
                    found.append(f"{rel}:{default.lineno} {name}(... = {ast.unparse(default)})")
    return found


def test_no_engine_or_session_default_arguments_in_production_code():
    violations = _violations()
    assert violations == [], (
        "Default-Argumente binden die DB beim Import; None + database._resolve_engine() "
        "verwenden:\n" + "\n".join(violations)
    )


def test_guard_detects_import_time_engine_default():
    samples = {
        "def f(target_engine=engine): pass": True,
        "def f(*, db=SessionLocal()): pass": True,
        "def f(bind=database.engine): pass": True,
        "def f(e=create_engine('sqlite://')): pass": True,
        "def f(target_engine=None): pass": False,
        "def f(db=Depends(get_db)): pass": False,
    }
    for source, expected in samples.items():
        func = ast.parse(source).body[0]
        defaults = list(func.args.defaults) + [d for d in func.args.kw_defaults if d is not None]
        assert any(_references_db_object(d) for d in defaults) is expected, source
