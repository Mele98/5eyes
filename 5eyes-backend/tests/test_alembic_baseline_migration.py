"""Roadmap #90 (Standpunkt 2026-08-07): Alembic-Erstmigration + init_db-Switch
create_all<->alembic.

SQLite (Dev/Test/Electron-Desktop) bleibt bei Base.metadata.create_all() --
kein Risiko fuer den bestehenden, sehr gut getesteten Pfad. Postgres
(Produktion) laeuft ab jetzt ueber `alembic upgrade head` gegen die
Baseline-Revision (alembic/versions/*_baseline_schema.py), die aus demselben
Base.metadata generiert wurde.

Verifiziert:
1. Dispatch: SQLite-URL -> create_all, Postgres-URL -> alembic upgrade (nie
   beides / nie das falsche).
2. Baseline-Migration ist kein Drift: gegen eine leere Wegwerf-SQLite-DB
   angewendet, muss sie exakt dieselben Tabellen erzeugen wie
   Base.metadata.create_all() -- sonst waeren Postgres-Produktion und
   SQLite-Dev/Test auf unterschiedlichen Schemas.
3. Upgrade + Downgrade sind rueckstandsfrei umkehrbar (kein halb angewendeter
   Zustand moeglich).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database  # noqa: E402
from database import Base, _create_or_migrate_schema  # noqa: E402
# Alle Model-Module importieren, exakt wie alembic/env.py es tut --
# Base.metadata muss jede Tabelle kennen, damit der Drift-Vergleich fair ist.
import models.allocation  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.jurisdiction  # noqa: E402,F401
import models.login_attempt  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.market_data_cache  # noqa: E402,F401
import models.market_data_validation_log  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tax  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401


def test_sqlite_url_dispatches_to_create_all(monkeypatch):
    calls = {"create_all": 0, "alembic_upgrade": 0}
    monkeypatch.setattr(Base.metadata, "create_all", lambda **kw: calls.__setitem__("create_all", calls["create_all"] + 1))
    import alembic.command as alembic_command
    monkeypatch.setattr(alembic_command, "upgrade", lambda *a, **kw: calls.__setitem__("alembic_upgrade", calls["alembic_upgrade"] + 1))

    _create_or_migrate_schema("sqlite:///irrelevant.db")

    assert calls == {"create_all": 1, "alembic_upgrade": 0}


def test_postgres_url_dispatches_to_alembic_upgrade(monkeypatch):
    calls = {"create_all": 0, "alembic_upgrade": 0, "upgraded_to": None}
    monkeypatch.setattr(Base.metadata, "create_all", lambda **kw: calls.__setitem__("create_all", calls["create_all"] + 1))
    import alembic.command as alembic_command

    def _fake_upgrade(cfg, revision):
        calls["alembic_upgrade"] += 1
        calls["upgraded_to"] = revision

    monkeypatch.setattr(alembic_command, "upgrade", _fake_upgrade)

    _create_or_migrate_schema("postgresql://user:pw@localhost/fivetest")

    assert calls == {"create_all": 0, "alembic_upgrade": 1, "upgraded_to": "head"}


def test_baseline_migration_matches_current_models(tmp_path):
    """Wendet die eingecheckte Baseline-Revision auf eine leere Wegwerf-DB an
    und vergleicht das Tabellen-Set 1:1 gegen Base.metadata -- eine neue
    Tabelle im Code ohne passende Migration faellt hier auf."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    db_file = tmp_path / "alembic_drift_check.db"
    db_url = f"sqlite:///{db_file}"

    alembic_ini = BACKEND_ROOT / "alembic.ini"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    migrated_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()

    expected_tables = set(Base.metadata.tables.keys())
    missing_from_migration = expected_tables - migrated_tables
    extra_in_migration = migrated_tables - expected_tables
    assert not missing_from_migration, (
        f"Tabellen in Base.metadata, aber NICHT in der Baseline-Migration: {missing_from_migration}. "
        "Neue Alembic-Revision generieren (siehe alembic/README oder Roadmap #90)."
    )
    assert not extra_in_migration, (
        f"Tabellen in der Baseline-Migration, aber nicht mehr in Base.metadata: {extra_in_migration}."
    )


def test_baseline_migration_upgrade_and_downgrade_are_reversible(tmp_path):
    from alembic import command
    from alembic.config import Config as AlembicConfig

    db_file = tmp_path / "alembic_reversible.db"
    db_url = f"sqlite:///{db_file}"

    alembic_ini = BACKEND_ROOT / "alembic.ini"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    assert len(inspect(engine).get_table_names()) > 1
    engine.dispose()

    command.downgrade(cfg, "base")
    engine = create_engine(db_url)
    remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert not remaining, f"downgrade('base') liess Tabellen zurueck: {remaining}"
