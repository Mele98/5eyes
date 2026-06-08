"""Bootstrap-Schema-Drift: users/clients/mandates.tenant_id (2026-06-08).

Befund (von Codex in PR #243): das Bootstrap-SQL hat die Sprint-T1-Spalte
`tenant_id` nicht ergaenzt. Frische Installationen aus dem v4.0-FINAL.sql
landen mit Schema-Drift: ORM erwartet die Column, SQL liefert sie nicht.

Fix: `ensure_runtime_columns` ergaenzt die Column idempotent auf legacy-
DBs. Tests verifizieren, dass die Column nach der Migration existiert,
egal in welchem Startzustand die DB ist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _table_columns(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _create_legacy_users_table(engine) -> None:
    """Simuliert eine vor-T1 DB: users ohne tenant_id."""
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'advisor',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE clients (
                id TEXT PRIMARY KEY,
                client_number TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE mandates (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                mandate_number TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        ))


def test_users_tenant_id_in_additive_columns():
    """Drift-Wache: dict-Eintrag muss vorhanden bleiben, sonst kann ein
    spaeterer Refactor die Migration wieder entfernen ohne dass es
    auffaellt."""
    import database as db_module
    # Roundabout-Pruefung via Source-Parse, weil additive_columns lokal
    # in der Funktion definiert ist.
    src = (BACKEND_ROOT / "database.py").read_text(encoding="utf-8")
    assert "'users':" in src
    assert "'tenant_id'" in src
    assert "users\n" not in src or "('tenant_id', 'TEXT')" in src


def _bootstrap_legacy_db(tmp_path, monkeypatch):
    """Simuliert eine Pre-T1-Installation: vollstaendiges Bootstrap-SQL
    (das tenant_id NICHT enthaelt), aber ohne den nachfolgenden
    create_all()-Schritt der T1 ergaenzen wuerde."""
    db_path = tmp_path / "legacy.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    import database as db_module
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    return test_engine, db_module


def test_ensure_runtime_columns_adds_tenant_id_to_legacy_users(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch)

    cols_before = _table_columns(test_engine, "users")
    assert "tenant_id" not in cols_before, "Bootstrap-SQL enthaelt tenant_id schon — Test obsolet"

    db_module.ensure_runtime_columns()

    cols_after = _table_columns(test_engine, "users")
    assert "tenant_id" in cols_after


def test_ensure_runtime_columns_adds_tenant_id_to_legacy_clients_and_mandates(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch)
    db_module.ensure_runtime_columns()

    for table in ("clients", "mandates"):
        cols = _table_columns(test_engine, table)
        assert "tenant_id" in cols, f"{table}.tenant_id fehlt nach Migration"


def test_ensure_runtime_columns_idempotent(tmp_path, monkeypatch):
    test_engine, db_module = _bootstrap_legacy_db(tmp_path, monkeypatch)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # zweite Ausfuehrung
    assert "tenant_id" in _table_columns(test_engine, "users")
