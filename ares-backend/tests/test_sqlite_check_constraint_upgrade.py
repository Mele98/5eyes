"""UPGRADE-PATH-CHECK-DRIFT-001.

Bestehende SQLite-DBs behielten veraltete ``CHECK(col IN (...))``-Listen, weil
``bootstrap_sqlite_schema`` nur ``CREATE TABLE IF NOT EXISTS`` ausfuehrt. Auf
einer Kopie der echten Desktop-DB (Sicherung 2026-10-20) blieben nach zwei
App-Starts u.a. 'client'/'super_admin' (users.role), 'Teilweise unterzeichnet'
und 'Kostenausweis' (contract_documents) sowie 'Indirekt (Säule 3a)'
(wealth_positions) per CHECK blockiert.

Die Legacy-DB hier wird aus dem Referenzschema mit genau den alten Listen der
realen DB gebaut.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"

# (aktuelles Referenzfragment, Fragment der realen Alt-DB)
_LEGACY_FRAGMENTS = (
    (
        "CHECK(role IN ('admin', 'advisor', 'readonly', 'super_admin', 'portfolio_management', 'client'))",
        "CHECK(role IN ('admin', 'advisor', 'readonly'))",
    ),
    (
        "CHECK(mortgage_amortization_type IN ('Direkt','Indirekt (Säule 3a)','Keine'))",
        "CHECK(mortgage_amortization_type IN ('Direkt','Indirekt (3a)','Keine'))",
    ),
    (
        "CHECK(status IN ('Entwurf','Bereit','Teilweise unterzeichnet','Unterzeichnet','Archiviert'))",
        "CHECK(status IN ('Entwurf','Bereit','Unterzeichnet','Archiviert'))",
    ),
)


def _legacy_db(tmp_path: Path) -> Path:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    for current, legacy in _LEGACY_FRAGMENTS:
        assert sql.count(current) == 1, current
        sql = sql.replace(current, legacy)
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, full_name, role) "
            "VALUES ('u-legacy', 'legacy', 'x', 'Legacy', 'readonly')"
        )
        conn.commit()
    return db_path


def _accepts(db_path: Path, table: str, column: str, value: str, row_id: str) -> bool:
    """Echter Schreibtest: Dummy-Zeile ohne CHECKs anlegen, dann genau die
    Zielspalte per UPDATE setzen (SQLite prueft beim UPDATE nur CHECKs der
    geaenderten Spalten)."""
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names, values = [], []
        for _cid, name, col_type, notnull, default, pk in cols:
            if pk or (notnull and default is None):
                names.append(name)
                values.append(row_id or "probe" if pk else (0 if "INT" in (col_type or "").upper() else "x"))
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' * len(names))})",
            values,
        )
        conn.execute("PRAGMA ignore_check_constraints = OFF")
        try:
            conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = last_insert_rowid()", (value,))
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        conn.execute("ROLLBACK")
        conn.close()


def _schema_objects(db_path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(db_path) as conn:
        return sorted(conn.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall())


def test_legacy_maintenance_path_widens_stale_check_lists(tmp_path, monkeypatch):
    """Startpfad (_run_sqlite_legacy_schema_maintenance) muss die Listen erweitern."""
    import database as db_module

    db_path = _legacy_db(tmp_path)
    assert not _accepts(db_path, "users", "role", "client", "u-red")  # Vorbedingung

    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    for name in (
        "ensure_runtime_columns", "ensure_current_anchor_unique_indexes",
        "migrate_house_matrix_real_estate_cap_20", "ensure_snapshot_tables",
        "ensure_purge_history_table", "run_risk_assessment_answer_migration",
        "run_advisory_log_migration",
        "migrate_advisory_log_hash_scheme_cost_disclosure_snapshot",
        "ensure_audit_log_actions", "ensure_audit_log_indexes",
        "ensure_audit_log_triggers",
    ):
        monkeypatch.setattr(db_module, name, lambda *a, **k: None)
    import services.market_data.provider_health_registry as health
    monkeypatch.setattr(health, "ensure_provider_health_table", lambda *a, **k: None)
    monkeypatch.setattr(db_module, "resolve_schema_path", lambda: SCHEMA_FILE)
    from config import settings
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "bk"))

    objects_before = _schema_objects(db_path)
    db_module._run_sqlite_legacy_schema_maintenance()
    test_engine.dispose()

    for role in ("client", "super_admin", "portfolio_management"):
        assert _accepts(db_path, "users", "role", role, f"u-{role}"), role
    assert _accepts(db_path, "contract_documents", "status", "Teilweise unterzeichnet", "")
    assert _accepts(db_path, "wealth_positions", "mortgage_amortization_type", "Indirekt (Säule 3a)", "")
    # Nie enger: Altwert bleibt erlaubt.
    assert _accepts(db_path, "wealth_positions", "mortgage_amortization_type", "Indirekt (3a)", "")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT role FROM users WHERE id='u-legacy'").fetchone()[0] == "readonly"
    assert _schema_objects(db_path) == objects_before
    assert len(list((tmp_path / "bk").glob("ares_pre_check_upgrade_*.db"))) == 1


_EXPECTED_ADDED = {
    "users": {"role": ["'super_admin'", "'portfolio_management'", "'client'"]},
    "wealth_positions": {"mortgage_amortization_type": ["'Indirekt (Säule 3a)'"]},
    "contract_documents": {"status": ["'Teilweise unterzeichnet'"]},
}


def _table_ddl(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        return dict(conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))


def test_widening_is_idempotent_union_only_with_backup_and_protocol(tmp_path):
    import json

    from services.sqlite_check_constraint_upgrade import ensure_sqlite_check_in_lists_current

    db_path = _legacy_db(tmp_path)
    ddl_before = _table_ddl(db_path)
    backup_dir = tmp_path / "bk"
    engine = create_engine(f"sqlite:///{db_path}")
    first = ensure_sqlite_check_in_lists_current(engine, SCHEMA_FILE, backup_dir=backup_dir)
    assert first == _EXPECTED_ADDED
    # Zweiter Lauf: nichts zu tun, KEINE weitere Sicherung.
    assert ensure_sqlite_check_in_lists_current(engine, SCHEMA_FILE, backup_dir=backup_dir) == {}
    engine.dispose()
    backups = sorted(backup_dir.glob("ares_pre_check_upgrade_*.db"))
    assert len(backups) == 1
    assert not list(backup_dir.glob("*.partial*"))  # keine verwaisten Temp-Reste
    # Sicherung = Zustand VOR der Aenderung.
    assert _table_ddl(backups[0]) == ddl_before
    protocol = json.loads(backups[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert protocol["added_values"] == _EXPECTED_ADDED
    assert protocol["event"] == "UPGRADE-PATH-CHECK-DRIFT-001"
    # Echter Schreibtest mit vollem Datensatz: neue Rolle wird akzeptiert.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, full_name, role) "
            "VALUES ('u-client', 'client1', 'x', 'Client', 'client')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO users (id, username, password_hash, full_name, role) "
                "VALUES ('u-bad', 'bad', 'x', 'Bad', 'hacker')"
            )


def test_fresh_reference_schema_needs_no_change(tmp_path):
    from services.sqlite_check_constraint_upgrade import ensure_sqlite_check_in_lists_current

    db_path = tmp_path / "fresh.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    engine = create_engine(f"sqlite:///{db_path}")
    backup_dir = tmp_path / "bk"
    assert ensure_sqlite_check_in_lists_current(engine, SCHEMA_FILE, backup_dir=backup_dir) == {}
    engine.dispose()
    # Keine Aenderung -> keine Sicherung.
    assert not backup_dir.exists() or not any(backup_dir.iterdir())


def _assert_unchanged_and_readable(db_path: Path, ddl_before: dict[str, str]) -> None:
    assert _table_ddl(db_path) == ddl_before
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT role FROM users WHERE id='u-legacy'").fetchone()[0] == "readonly"
    assert not _accepts(db_path, "users", "role", "client", "u-still-old")


def test_simulated_integrity_failure_rolls_back_to_old_schema(tmp_path, monkeypatch):
    import services.sqlite_check_constraint_upgrade as mod

    db_path = _legacy_db(tmp_path)
    ddl_before = _table_ddl(db_path)
    real_check = mod._post_change_problems
    calls = []

    def failing_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return ["integrity_check: ['simuliert']"]
        return real_check(*args, **kwargs)

    monkeypatch.setattr(mod, "_post_change_problems", failing_once)
    engine = create_engine(f"sqlite:///{db_path}")
    assert mod.ensure_sqlite_check_in_lists_current(
        engine, SCHEMA_FILE, backup_dir=tmp_path / "bk"
    ) == {}
    engine.dispose()
    assert len(calls) == 2  # Pruefung + Pruefung nach Ruecksetzen
    _assert_unchanged_and_readable(db_path, ddl_before)
    # Sicherung existiert (wurde vor der Aenderung angelegt), kein Erfolgsprotokoll.
    assert len(list((tmp_path / "bk").glob("*.db"))) == 1
    assert not list((tmp_path / "bk").glob("*.json"))


def test_failed_revert_restores_from_backup(tmp_path, monkeypatch):
    import services.sqlite_check_constraint_upgrade as mod

    db_path = _legacy_db(tmp_path)
    ddl_before = _table_ddl(db_path)
    monkeypatch.setattr(mod, "_post_change_problems", lambda *a, **k: ["simuliert"])
    restored = []
    real_restore = mod._restore_from_backup

    def spy(*args, **kwargs):
        restored.append(1)
        return real_restore(*args, **kwargs)

    monkeypatch.setattr(mod, "_restore_from_backup", spy)
    engine = create_engine(f"sqlite:///{db_path}")
    assert mod.ensure_sqlite_check_in_lists_current(
        engine, SCHEMA_FILE, backup_dir=tmp_path / "bk"
    ) == {}
    engine.dispose()
    assert restored == [1]
    _assert_unchanged_and_readable(db_path, ddl_before)


def test_backup_failure_means_no_change(tmp_path, monkeypatch):
    import services.backup as backup
    import services.sqlite_check_constraint_upgrade as mod

    db_path = _legacy_db(tmp_path)
    ddl_before = _table_ddl(db_path)

    def broken_copy(*args, **kwargs):
        raise OSError("Datentraeger voll (simuliert)")

    monkeypatch.setattr(backup, "_perform_atomic_copy", broken_copy)
    engine = create_engine(f"sqlite:///{db_path}")
    assert mod.ensure_sqlite_check_in_lists_current(
        engine, SCHEMA_FILE, backup_dir=tmp_path / "bk"
    ) == {}
    engine.dispose()
    _assert_unchanged_and_readable(db_path, ddl_before)
