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

from io import StringIO
import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

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


# Operational tables intentionally use raw SQL services instead of ORM
# entities.  They are nevertheless part of the Alembic-owned PostgreSQL
# schema and therefore expected in a fully upgraded database.
ALEMBIC_ONLY_RUNTIME_TABLES = {
    "provider_health_events",
    "market_data_purge_history",
}


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

    expected_tables = set(Base.metadata.tables.keys()) | ALEMBIC_ONLY_RUNTIME_TABLES
    missing_from_migration = expected_tables - migrated_tables
    extra_in_migration = migrated_tables - expected_tables
    assert not missing_from_migration, (
        f"Tabellen in Base.metadata, aber NICHT in der Baseline-Migration: {missing_from_migration}. "
        "Neue Alembic-Revision generieren (siehe alembic/README oder Roadmap #90)."
    )
    assert not extra_in_migration, (
        f"Tabellen in der Baseline-Migration, aber nicht mehr in Base.metadata: {extra_in_migration}."
    )


def test_alembic_upgrade_preserves_existing_application_logger(tmp_path):
    """Running migrations in-process must not disable application logging.

    Alembic's ``fileConfig`` defaults to ``disable_existing_loggers=True``.
    That global mutation only becomes visible in the complete test process (or
    when the application invokes Alembic in-process), where service loggers
    already exist before the migration starts.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    db_file = tmp_path / "alembic_logging_isolation.db"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    app_logger = logging.getLogger("services.alembic_logging_isolation_probe")
    original_disabled = app_logger.disabled
    original_level = app_logger.level
    original_propagate = app_logger.propagate
    output = StringIO()
    probe_handler = logging.StreamHandler(output)
    app_logger.disabled = False
    app_logger.setLevel(logging.WARNING)
    app_logger.propagate = False
    app_logger.addHandler(probe_handler)

    try:
        command.upgrade(cfg, "head")

        assert app_logger.disabled is False
        assert probe_handler in app_logger.handlers
        app_logger.warning("application logger survived Alembic")
        assert "application logger survived Alembic" in output.getvalue()
    finally:
        app_logger.removeHandler(probe_handler)
        probe_handler.close()
        app_logger.disabled = original_disabled
        app_logger.setLevel(original_level)
        app_logger.propagate = original_propagate


def test_head_migration_matches_target_allocation_model_columns(tmp_path):
    """Decision artefacts must exist in the versioned production schema.

    Postgres is created exclusively through ``alembic upgrade head``.  A
    SQLite runtime-column repair therefore cannot compensate for a missing
    Alembic revision.  Applying the complete revision chain to an empty DB
    and comparing it with the ORM catches that deployment-only failure.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    db_file = tmp_path / "alembic_target_allocation_columns.db"
    db_url = f"sqlite:///{db_file}"

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    migrated_columns = {
        column["name"] for column in inspect(engine).get_columns("target_allocations")
    }
    engine.dispose()

    expected_columns = set(Base.metadata.tables["target_allocations"].columns.keys())
    assert migrated_columns == expected_columns, (
        "Alembic head und TargetAllocation-ORM haben unterschiedliche Spalten: "
        f"missing={expected_columns - migrated_columns}, "
        f"extra={migrated_columns - expected_columns}"
    )
    engine = create_engine(db_url)
    optimizer_run_columns = {
        column["name"] for column in inspect(engine).get_columns("optimizer_runs")
    }
    engine.dispose()
    assert optimizer_run_columns == set(
        Base.metadata.tables["optimizer_runs"].columns.keys()
    )


def test_head_emits_postgres_ddl_for_allocation_decision_artifacts():
    """The production dialect must receive all three additive columns."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    output = StringIO()
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"), output_buffer=output)
    cfg.set_main_option(
        "sqlalchemy.url", "postgresql://migration-test:unused@localhost/unused"
    )
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head", sql=True)

    ddl = output.getvalue().lower()
    for column_name in (
        "sub_allocations_json",
        "effective_constraints_json",
        "allocation_context_hash",
        "context_artifacts_required",
    ):
        expected_type = "integer" if column_name == "context_artifacts_required" else "varchar"
        assert (
            f"alter table target_allocations add column {column_name} {expected_type}" in ddl
        ), f"Postgres-DDL fuer {column_name} fehlt"
    assert (
        "alter table optimizer_runs add column robustification_json varchar"
        in ddl
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
