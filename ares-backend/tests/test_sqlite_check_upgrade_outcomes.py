"""UPGRADE-PATH-CHECK-DRIFT-001: grammar and typed-outcome contract.

All probes run on disposable databases in ``tmp_path``. Failure paths are
simulated by monkeypatching module internals only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


def _backend_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate
    raise AssertionError("backend directory (main.py + database.py) not found")


BACKEND_ROOT = _backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.sqlite_check_constraint_upgrade as mod  # noqa: E402
from services.sqlite_check_constraint_upgrade import (  # noqa: E402
    CheckUpgradeOutcome as Outcome,
)

SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"


def _make(tmp_path: Path, legacy_ddl: str, reference_ddl: str) -> tuple[Path, Path]:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_ddl)
    schema_path = tmp_path / "reference.sql"
    schema_path.write_text(reference_ddl, encoding="utf-8")
    return db_path, schema_path


def _ddl(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        return dict(conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))


def _insert_ok(db_path: Path, sql: str, params=()) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, params)
        conn.rollback()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _run(db_path: Path, schema_path: Path, tmp_path: Path) -> mod.CheckUpgradeResult:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return mod.upgrade_sqlite_check_in_lists(engine, schema_path, backup_dir=tmp_path / "bk")
    finally:
        engine.dispose()


def _writable(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


# --- Grammatik -------------------------------------------------------------


def test_nullable_form_is_widened_and_null_stays_allowed(tmp_path):
    db_path, schema_path = _make(
        tmp_path,
        "CREATE TABLE advisory_log (id INTEGER PRIMARY KEY, communication_channel TEXT "
        "CHECK(communication_channel IS NULL OR communication_channel IN ('persoenlich')));",
        "CREATE TABLE IF NOT EXISTS advisory_log (id INTEGER PRIMARY KEY, communication_channel "
        "TEXT CHECK(communication_channel IS NULL OR communication_channel IN\n"
        "    ('persoenlich','video')));",
    )
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.APPLIED_VERIFIED
    assert result.added == {"advisory_log": {"communication_channel": ["'video'"]}}
    insert = "INSERT INTO advisory_log (communication_channel) VALUES (?)"
    assert _insert_ok(db_path, insert, ("video",))
    assert _insert_ok(db_path, insert, (None,))
    assert _insert_ok(db_path, insert, ("persoenlich",))
    assert not _insert_ok(db_path, insert, ("brieftaube",))


def test_quoted_identifiers_comments_parens_and_escaped_literals(tmp_path):
    db_path, schema_path = _make(
        tmp_path,
        'CREATE TABLE "docs" (id INTEGER PRIMARY KEY, "kind" TEXT CHECK ((("kind" IN (\n'
        "  'a', -- alt\n  'it''s' /* block */)))));",
        "CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, kind TEXT "
        "CHECK([kind] IN ('a','it''s','neu''wert')));",
    )
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.APPLIED_VERIFIED
    assert result.added == {"docs": {"kind": ["'neu''wert'"]}}
    insert = "INSERT INTO docs (kind) VALUES (?)"
    for value in ("a", "it's", "neu'wert"):
        assert _insert_ok(db_path, insert, (value,)), value
    assert not _insert_ok(db_path, insert, ("b",))
    stored = _ddl(db_path)["docs"]
    assert "-- alt" in stored and "/* block */" in stored  # nur angehaengt


@pytest.mark.parametrize(
    "legacy_check",
    [
        "CHECK(kind IN ('a') OR kind = 'b')",
        "CHECK(kind IN ('a') OR kind IS NULL)",
        "CHECK(kind NOT IN ('a'))",
        "CHECK(other IS NULL OR kind IN ('a'))",
    ],
)
def test_unsupported_form_requires_manual_migration_and_changes_nothing(tmp_path, legacy_check):
    db_path, schema_path = _make(
        tmp_path,
        f"CREATE TABLE docs (id INTEGER PRIMARY KEY, other TEXT, kind TEXT {legacy_check});",
        "CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, other TEXT, "
        "kind TEXT CHECK(kind IN ('a','b')));",
    )
    before = _ddl(db_path)
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.MANUAL_MIGRATION_REQUIRED
    assert not result.startup_safe
    assert any("docs" in problem for problem in result.problems)
    assert _ddl(db_path) == before
    assert not (tmp_path / "bk").exists()
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with pytest.raises(mod.ManualMigrationRequired):
            mod.ensure_sqlite_check_in_lists_current(engine, schema_path, backup_dir=tmp_path / "bk")
    finally:
        engine.dispose()


def test_multiple_value_list_checks_on_one_column_are_not_unioned(tmp_path):
    db_path, schema_path = _make(
        tmp_path,
        "CREATE TABLE docs (id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('a','b')), "
        "CHECK(kind IN ('a')));",
        "CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, kind TEXT "
        "CHECK(kind IN ('a','b','c')));",
    )
    before = _ddl(db_path)
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.MANUAL_MIGRATION_REQUIRED
    assert _ddl(db_path) == before


def test_ambiguous_reference_requires_manual_migration(tmp_path):
    db_path, schema_path = _make(
        tmp_path,
        "CREATE TABLE docs (id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('a')));",
        "CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, kind TEXT "
        "CHECK(kind IN ('a','b')), CHECK(kind IN ('a','c')));",
    )
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.MANUAL_MIGRATION_REQUIRED


def test_reference_schema_is_unambiguous_and_fresh_install_is_noop(tmp_path):
    reference = mod._reference(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert reference.problems == ()
    assert ("advisory_log", "communication_channel") in reference.lists
    assert ("advisory_log", "language") in reference.lists
    db_path = tmp_path / "fresh.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    result = _run(db_path, SCHEMA_FILE, tmp_path)
    assert result.outcome is Outcome.NOOP
    assert not (tmp_path / "bk").exists()


def test_legacy_cost_disclosure_document_type_becomes_writable(tmp_path):
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    start = sql.index("document_type   TEXT NOT NULL CHECK(document_type IN (")
    end = sql.index("'Kostenausweis')),", start) + len("'Kostenausweis')),")
    region = sql[start:end]
    region = region[:region.index("'Sonstiges',")] + "'Sonstiges')),"
    legacy = sql[:start] + region + sql[end:]
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(legacy)
    update = (
        "UPDATE contract_documents SET document_type = ? WHERE rowid = "
        "(SELECT rowid FROM contract_documents LIMIT 1)"
    )
    with sqlite3.connect(db_path) as conn:
        # Dummy-Zeile verletzt bewusst andere CHECKs: vorbestehende Befunde
        # (Baseline) duerfen die Verifikation nicht kippen.
        conn.execute("PRAGMA ignore_check_constraints = ON")
        cols = conn.execute("PRAGMA table_info(contract_documents)").fetchall()
        names = [c[1] for c in cols if c[5] or (c[3] and c[4] is None)]
        conn.execute(
            f"INSERT INTO contract_documents ({','.join(names)}) VALUES ({','.join('?' * len(names))})",
            ["x"] * len(names),
        )
        conn.commit()
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(update, ("Kostenausweis",))
    result = _run(db_path, SCHEMA_FILE, tmp_path)
    assert result.outcome is Outcome.APPLIED_VERIFIED
    assert result.added == {"contract_documents": {"document_type": ["'Kostenausweis'"]}}
    with sqlite3.connect(db_path) as conn:
        conn.execute(update, ("Kostenausweis",))
        conn.execute(update, ("Beratungsvertrag",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(update, ("Phantasie",))


# --- Typisierte Ergebnisse / Recovery --------------------------------------

_LEGACY = "CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT CHECK(role IN ('readonly')));"
_REFERENCE = (
    "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, "
    "role TEXT CHECK(role IN ('readonly','client')));"
)


def test_backup_failure_is_typed_and_unchanged(tmp_path, monkeypatch):
    import services.backup as backup

    db_path, schema_path = _make(tmp_path, _LEGACY, _REFERENCE)
    before = _ddl(db_path)
    monkeypatch.setattr(
        backup, "_perform_atomic_copy",
        lambda *a, **k: (_ for _ in ()).throw(OSError("voll (simuliert)")),
    )
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.SKIPPED_BACKUP_FAILED
    assert result.startup_safe
    assert _ddl(db_path) == before


def test_failed_apply_is_verified_rollback(tmp_path, monkeypatch):
    db_path, schema_path = _make(tmp_path, _LEGACY, _REFERENCE)
    before = _ddl(db_path)
    monkeypatch.setattr(
        mod, "_apply", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )
    result = _run(db_path, schema_path, tmp_path)
    assert result.outcome is Outcome.RESTORED_VERIFIED
    assert _ddl(db_path) == before


def test_failed_revert_with_verified_backup_restore_rebuilds_pool(tmp_path, monkeypatch):
    db_path, schema_path = _make(tmp_path, _LEGACY, _REFERENCE)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO users (role) VALUES ('readonly')")
    before = _ddl(db_path)
    real_apply = mod._apply
    calls = []

    def apply_then_fail(target_engine, sql_by_table):
        calls.append(1)
        if len(calls) == 1:
            return real_apply(target_engine, sql_by_table)
        raise OSError("simulated revert failure")

    monkeypatch.setattr(mod, "_apply", apply_then_fail)
    monkeypatch.setattr(mod, "_post_change_problems", lambda *a, **k: ["simuliert"])
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        result = mod.upgrade_sqlite_check_in_lists(engine, schema_path, backup_dir=tmp_path / "bk")
        assert result.outcome is Outcome.RESTORED_VERIFIED
        with engine.connect() as conn:  # neu aufgebauter Pool funktioniert
            assert conn.execute(text("SELECT role FROM users")).scalar_one() == "readonly"
    finally:
        engine.dispose()
    assert _ddl(db_path) == before
    assert not list((tmp_path / "bk").glob("*restore-staging*"))
    assert not mod.quarantine_marker_path(db_path).exists()


def test_tampered_backup_is_never_restored_and_db_is_quarantined(tmp_path, monkeypatch):
    db_path, schema_path = _make(tmp_path, _LEGACY, _REFERENCE)
    real_apply = mod._apply
    calls = []

    def apply_then_tamper(target_engine, sql_by_table):
        calls.append(1)
        if len(calls) == 1:
            return real_apply(target_engine, sql_by_table)
        backup = next((tmp_path / "bk").glob("*.db"))
        with backup.open("ab") as handle:
            handle.write(b"\0manipuliert")
        raise OSError("simulated revert failure")

    monkeypatch.setattr(mod, "_apply", apply_then_tamper)
    monkeypatch.setattr(mod, "_post_change_problems", lambda *a, **k: ["simuliert"])
    copies = []
    real_copy = mod._sqlite_copy
    monkeypatch.setattr(mod, "_sqlite_copy", lambda *a, **k: copies.append(a) or real_copy(*a, **k))
    try:
        result = _run(db_path, schema_path, tmp_path)
        assert result.outcome is Outcome.FATAL_RECOVERY_FAILED
        assert copies == []  # nie eingespielt
        assert any("nicht authentisch" in problem for problem in result.problems)
        marker = mod.quarantine_marker_path(db_path)
        assert result.quarantine_marker == marker and marker.exists()
        evidence = json.loads(marker.read_text(encoding="utf-8"))
        assert evidence["event"] == "UPGRADE-PATH-CHECK-DRIFT-001"
        assert evidence["outcome"] == "fatal_recovery_failed"
        assert evidence["db_marked_read_only"] is True
        assert not os.access(db_path, os.W_OK)
        assert db_path.exists()  # nichts geloescht
        with pytest.raises(mod.FatalRecoveryFailed):
            mod.raise_if_startup_unsafe(result)
        with pytest.raises(mod.FatalRecoveryFailed):
            mod.raise_if_quarantined(db_path)
    finally:
        _writable(db_path)


def test_init_db_refuses_to_start_on_quarantined_db(tmp_path, monkeypatch):
    import database as db_module
    from config import settings

    db_path = tmp_path / "q.db"
    sqlite3.connect(db_path).close()
    mod.quarantine_marker_path(db_path).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "db_path", str(db_path))
    touched = []
    monkeypatch.setattr(db_module, "bootstrap_sqlite_schema", lambda *a, **k: touched.append("b"))
    monkeypatch.setattr(db_module, "_create_or_migrate_schema", lambda *a, **k: touched.append("c"))
    with pytest.raises(mod.FatalRecoveryFailed):
        db_module.init_db()
    assert touched == []


def test_legacy_maintenance_stops_on_unsafe_outcome(tmp_path, monkeypatch):
    import database as db_module

    for name in ("ensure_runtime_columns", "ensure_current_anchor_unique_indexes"):
        monkeypatch.setattr(db_module, name, lambda *a, **k: None)
    later = []
    monkeypatch.setattr(
        db_module, "migrate_house_matrix_real_estate_cap_20", lambda *a, **k: later.append(1),
    )
    fatal = mod.CheckUpgradeResult(Outcome.FATAL_RECOVERY_FAILED, problems=("simuliert",))
    monkeypatch.setattr(mod, "upgrade_sqlite_check_in_lists", lambda *a, **k: fatal)
    with pytest.raises(mod.FatalRecoveryFailed):
        db_module._run_sqlite_legacy_schema_maintenance()
    assert later == []
