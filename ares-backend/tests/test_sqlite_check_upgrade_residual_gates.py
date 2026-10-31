"""UPGRADE-PATH-CHECK-DRIFT-001: residual gates for the SQLite CHECK-list upgrader.

Adopted from the audit reproducer (2026-10-23) as regular tests without xfail.

The probes use disposable databases only.  They cover a CHECK grammar that is
already present in the reference schema and the last-resort recovery branch
where neither direct DDL reversion nor backup restore succeeds.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine


def _backend_root() -> Path:
    """Backend directory located by structure (main.py + database.py), not by name."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate
    raise AssertionError("backend directory (main.py + database.py) not found")


_BACKEND_ROOT = _backend_root()
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _ddl(db_path: Path, table: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_nullable_or_in_constraint_is_upgraded_end_to_end(tmp_path: Path) -> None:
    """The upgrader must cover the nullable OR/IN form used by advisory_log."""
    from services.sqlite_check_constraint_upgrade import (
        ensure_sqlite_check_in_lists_current,
    )

    db_path = tmp_path / "legacy-nullable.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE advisory_log ("
            "communication_channel TEXT CHECK("
            "communication_channel IS NULL OR "
            "communication_channel IN ('persoenlich')))"
        )
    schema_path = tmp_path / "reference.sql"
    schema_path.write_text(
        "CREATE TABLE IF NOT EXISTS advisory_log ("
        "communication_channel TEXT CHECK("
        "communication_channel IS NULL OR "
        "communication_channel IN ('persoenlich','video')));",
        encoding="utf-8",
    )

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        added = ensure_sqlite_check_in_lists_current(
            engine,
            schema_path,
            backup_dir=tmp_path / "backups",
        )
    finally:
        engine.dispose()

    assert added == {
        "advisory_log": {"communication_channel": ["'video'"]}
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO advisory_log (communication_channel) VALUES ('video')"
        )


def test_unrecoverable_revert_and_restore_failure_stops_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup may continue only if the pre-upgrade schema was restored."""
    import services.sqlite_check_constraint_upgrade as mod

    db_path = tmp_path / "legacy-recovery.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE users (role TEXT CHECK(role IN ('readonly')))"
        )
    schema_path = tmp_path / "reference.sql"
    schema_path.write_text(
        "CREATE TABLE IF NOT EXISTS users ("
        "role TEXT CHECK(role IN ('readonly','client')));",
        encoding="utf-8",
    )
    original_ddl = _ddl(db_path, "users")
    engine = create_engine(f"sqlite:///{db_path}")

    real_apply = mod._apply
    apply_calls = 0

    def apply_then_fail_revert(target_engine, sql_by_table):
        nonlocal apply_calls
        apply_calls += 1
        if apply_calls == 1:
            return real_apply(target_engine, sql_by_table)
        raise OSError("simulated direct DDL revert failure")

    monkeypatch.setattr(mod, "_apply", apply_then_fail_revert)
    monkeypatch.setattr(
        mod,
        "_post_change_problems",
        lambda *args, **kwargs: ["simulated post-change integrity failure"],
    )
    monkeypatch.setattr(
        mod,
        "_restore_from_backup",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("simulated backup restore failure")
        ),
    )

    raised = None
    try:
        mod.ensure_sqlite_check_in_lists_current(
            engine,
            schema_path,
            backup_dir=tmp_path / "backups",
        )
    except Exception as exc:  # A fatal startup error is an accepted fail-closed result.
        raised = exc
    finally:
        engine.dispose()

    if raised is not None:
        return
    assert _ddl(db_path, "users") == original_ddl, (
        "the upgrader swallowed both recovery failures and returned while the "
        "database still contained the rejected schema change"
    )
