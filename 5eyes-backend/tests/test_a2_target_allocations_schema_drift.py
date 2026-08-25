"""A2-Visual-Smoke-Test-Fund (2026-07-22): 'target_allocations' hatte einen
DOPPELTEN Dict-Key im 'additive_columns'-Literal von ensure_runtime_columns().
In Python gewinnt bei einem Dict-Literal der ZWEITE Key — der erste Block war
dadurch tote Migration. Auf einer per Raw-SQL (5eyes_schema_v4.0_FINAL.sql)
frisch gebooteten Installation (= JEDE echte Erstinstallation, der Pfad, den
init_db() tatsaechlich nutzt) fehlten deshalb 12 Spalten (u.a. preferences_json)
dauerhaft -> 'no such column: target_allocations.preferences_json' auf
/target-allocation/current/payload + /recommendations/current/payload. Das
war der Blocker fuer den allerersten echten Mandanten (First-Client-Readiness).

Fix: beide Bloecke zu einem gemergt. Diese Suite haelt die Bugklasse
strukturell fern (kein Duplicate-Key kann sich mehr unbemerkt einschleichen)
UND pinnt den konkreten Crash-Fall (Fresh-Bootstrap-Spalten-Vollstaendigkeit).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _additive_columns_dict_node() -> ast.Dict:
    src = (BACKEND_ROOT / "database.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "ensure_runtime_columns":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.AnnAssign)
                    and isinstance(sub.target, ast.Name)
                    and sub.target.id == "additive_columns"
                    and isinstance(sub.value, ast.Dict)
                ):
                    return sub.value
    raise AssertionError("additive_columns-Dict-Literal nicht gefunden — hat sich die Struktur geaendert?")


def test_additive_columns_has_no_duplicate_table_keys():
    """Struktureller Guard: kein Tabellen-Key darf im additive_columns-Dict-
    Literal mehrfach vorkommen. Ein Duplikat wuerde den ersten Block in Python
    silently zur toten Migration machen (last-key-wins bei Dict-Literalen)."""
    dict_node = _additive_columns_dict_node()
    keys = [k.value for k in dict_node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, (
        f"Doppelte(r) Tabellen-Key(s) in additive_columns: {duplicates} — "
        "der erste Block wird von Python beim Dict-Aufbau lautlos verworfen "
        "(genau der A2-Smoke-Test-Fund vom 2026-07-22). Bloecke zusammenfuehren."
    )


def _table_columns(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def test_fresh_bootstrap_target_allocations_has_all_orm_columns(tmp_path, monkeypatch):
    """Pinnt den konkreten Crash: eine fabrikneue, per Raw-SQL gebootete DB
    (= der echte init_db()-Pfad) muss nach ensure_runtime_columns() ALLE vom
    ORM-Modell TargetAllocation erwarteten Spalten haben — insbesondere die,
    die vorher im toten ersten Dict-Block hingen (preferences_json etc.)."""
    import database as db_module
    from models.allocation import TargetAllocation

    db_path = tmp_path / "fresh.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    db_module.ensure_runtime_columns()

    actual = _table_columns(test_engine, "target_allocations")
    expected = {c.name for c in TargetAllocation.__table__.columns}
    missing = expected - actual
    assert not missing, (
        f"Nach ensure_runtime_columns() fehlen auf einer fabrikneuen DB die "
        f"ORM-Spalten: {sorted(missing)} — das crasht /target-allocation/"
        f"current/payload + /recommendations/current/payload fuer jeden "
        f"neuen Mandanten (sqlite3.OperationalError: no such column)."
    )


def test_ensure_runtime_columns_idempotent_on_merged_target_allocations_block(tmp_path, monkeypatch):
    """Der gemergte Block darf zweimal laufen (Boot-Robustheit) ohne 'duplicate
    column'-Fehler — verifiziert ensure_column()s idempotente ALTER-Logik
    weiterhin nach dem Merge."""
    import database as db_module

    db_path = tmp_path / "fresh2.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # zweiter Lauf darf nicht crashen

    assert "preferences_json" in _table_columns(test_engine, "target_allocations")
