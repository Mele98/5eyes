"""N-873-06 (Dok. 86, Pruefrunde H2, vorbestehend): Fehlte einer SQLite-
Installation je ``ux_goals_rank_active`` und entstanden doppelte aktive
Zielraenge, brach der naechste Start im Schema-Bootstrap mit einem rohen
``IntegrityError`` ab. Jetzt bleibt der Abbruch (fail-closed), aber mit
CRITICAL-Betreibermeldung, betroffenen Mandaten und Handlungsanweisung.
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

import database


def _goal(conn, gid: str, rank: int, mandate: str = "m-dup") -> None:
    conn.execute(
        "INSERT INTO goals (id, mandate_id, client_id, goal_family, goal_type, label, rank, goal_scope,"
        " value_mode, target_wealth_rappen, is_ongoing, hardness, is_active, created_at, updated_at)"
        " VALUES (?, ?, 'c-1', 'Vermögen', 'Vermögensziel', ?, ?, 'Beratungsvermögen', 'nominal',"
        " 10000000, 0, 'Primär', 1, '2026-11-07T00:00:00Z', '2026-11-07T00:00:00Z')",
        (gid, mandate, gid, rank),
    )


def test_duplicate_active_ranks_abort_bootstrap_with_operator_message(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(database.settings, "db_use_sqlcipher", False, raising=False)
    db_file = tmp_path / "n873_06.db"
    database.bootstrap_sqlite_schema(db_path=db_file)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP INDEX ux_goals_rank_active")
        _goal(conn, "g-1", 1)
        _goal(conn, "g-2", 1)
        conn.commit()

    with caplog.at_level(logging.CRITICAL, logger=database.logger.name):
        with pytest.raises(RuntimeError) as exc_info:
            database.bootstrap_sqlite_schema(db_path=db_file)
    message = str(exc_info.value)
    assert "Datenbankstart abgebrochen" in message
    assert "ux_goals_rank_active" in message
    assert "m-dup/1/2" in message
    assert "Backup" in message
    assert isinstance(exc_info.value.__cause__, sqlite3.IntegrityError)
    assert any(r.levelno == logging.CRITICAL and "m-dup/1/2" in r.getMessage() for r in caplog.records)


def test_clean_database_still_bootstraps(tmp_path, monkeypatch):
    monkeypatch.setattr(database.settings, "db_use_sqlcipher", False, raising=False)
    db_file = tmp_path / "n873_06_ok.db"
    database.bootstrap_sqlite_schema(db_path=db_file)
    with sqlite3.connect(str(db_file)) as conn:
        _goal(conn, "g-1", 1)
        _goal(conn, "g-2", 2)
        conn.commit()
    database.bootstrap_sqlite_schema(db_path=db_file)
