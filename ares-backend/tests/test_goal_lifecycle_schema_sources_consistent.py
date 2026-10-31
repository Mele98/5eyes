"""Das Lifecycle-Schema muss in ALLEN vier Quellen stehen (ADR-3).

Dieselbe Bugklasse wie test_cashflow_goal_include_toggle_schema_drift.py und
Geschwister. Der Vertrag, woertlich aus jenem Modul-Docstring:

    eine neue Spalte muss in ALLEN 4 Schema-Quellen konsistent auftauchen
    (ORM-Model, Alembic-Migration, roher Bootstrap-SQL-DDL,
    ensure_runtime_columns()-Patcher), sonst driftet eine frische
    Erstinstallation (bootstrap_sqlite_schema) von einer bereits migrierten
    Alt-DB (ensure_runtime_columns) auseinander.

Diese Datei existiert, weil ich genau das beim ersten Versuch verletzt habe:
``lifecycle_decision`` landete nur im ORM-Modell und in der Alembic-Revision,
und die Tabelle ``goal_lifecycle_transitions`` fehlte im Bootstrap-DDL
vollstaendig. Gefangen hat das der is_included-Drift-Test -- also Zufall,
weil jener Test dieselbe Tabelle anfasst. Fuer die Lifecycle-Spalte selbst
gab es keine Absicherung.

Warum beide Strecken existieren: SQLite laeuft ueber den Bootstrap-Pfad OHNE
Alembic (siehe den Kommentar an ``database.py::readiness_probe``), Postgres
ueber Alembic. Zwei getrennte Wege, die dasselbe Schema erzeugen muessen.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import (  # noqa: F401,E501
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.wealth import Goal, GoalLifecycleTransition  # noqa: E402
from services.goal_lifecycle import DECIDED_STATES  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"
MIGRATION = (
    BACKEND_ROOT / "alembic" / "versions" / "f4a81c6b2e37_goal_lifecycle_adr3.py"
)
NOW = "2026-10-12T00:00:00.000Z"


@pytest.fixture()
def fresh_bootstrap_db(tmp_path, monkeypatch):
    """Eine Erstinstallation: Bootstrap-DDL + ensure_runtime_columns, kein Alembic."""
    import database as db_module

    db_path = tmp_path / "bootstrap.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    try:
        yield db_path, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _columns(db_path: Path, table: str) -> dict[str, bool]:
    """Spaltenname -> nullable."""
    connection = sqlite3.connect(db_path)
    try:
        return {
            row[1]: not bool(row[3])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Quelle 1+3: ORM-Modell gegen Bootstrap-DDL
# ---------------------------------------------------------------------------


def test_fresh_bootstrap_has_the_lifecycle_decision_column(fresh_bootstrap_db):
    """Ohne diese Spalte stuerzt eine Erstinstallation bei JEDEM Ziel-Insert ab.

    Gemessen, als sie fehlte:
        sqlite3.OperationalError: table goals has no column named
        lifecycle_decision
    """
    db_path, _ = fresh_bootstrap_db
    assert "lifecycle_decision" in _columns(db_path, "goals")


def test_fresh_bootstrap_has_the_transition_table(fresh_bootstrap_db):
    """Die Tabelle fehlte im Bootstrap-DDL vollstaendig."""
    db_path, _ = fresh_bootstrap_db
    columns = _columns(db_path, "goal_lifecycle_transitions")
    assert columns, "goal_lifecycle_transitions existiert in der Erstinstallation nicht"

    orm_columns = {c.name for c in GoalLifecycleTransition.__table__.columns}
    assert set(columns) == orm_columns, (
        "Bootstrap-DDL und ORM-Modell beschreiben verschiedene Spalten: "
        f"nur im DDL {set(columns) - orm_columns}, "
        f"nur im Modell {orm_columns - set(columns)}"
    )


def test_bootstrap_enforces_the_evidence_fields_as_not_null(fresh_bootstrap_db):
    """ADR-3c ist eine Schema-Pflicht, nicht eine Konvention im Service.

    Waere ``reason`` nullable, koennte ein Terminal-Zustand ohne Nachweis
    in der Datenbank landen -- auch wenn der Service es ablehnt. Ein
    direkter SQL-Insert (Migration, Skript, Support-Eingriff) umgeht den
    Service.
    """
    db_path, _ = fresh_bootstrap_db
    nullable = _columns(db_path, "goal_lifecycle_transitions")

    for required in ("to_state", "reason", "actor_user_id", "created_at"):
        assert nullable[required] is False, f"{required} muss NOT NULL sein"

    # from_state darf NULL sein: die erste Transition hat keinen
    # persistierten Vorzustand (der war abgeleitet).
    assert nullable["from_state"] is True


def test_bootstrap_and_orm_agree_on_the_goals_lifecycle_column(fresh_bootstrap_db):
    db_path, _ = fresh_bootstrap_db
    bootstrap = _columns(db_path, "goals")
    orm = {c.name for c in Goal.__table__.columns}
    assert set(bootstrap) == orm, (
        "goals driftet zwischen Bootstrap-DDL und ORM: "
        f"nur im DDL {set(bootstrap) - orm}, nur im Modell {orm - set(bootstrap)}"
    )


# ---------------------------------------------------------------------------
# Quelle 3: der CHECK-Constraint muss die Zustandsmenge treffen
# ---------------------------------------------------------------------------


def test_bootstrap_check_constraint_matches_the_decided_states(fresh_bootstrap_db):
    """Der CHECK im DDL und ``DECIDED_STATES`` im Code duerfen nicht driften.

    Sonst waere entweder ein Zustand per SQL einfuegbar, den der Resolver
    nicht kennt (und bei dem er fail-closed wirft), oder ein gueltiger
    Zustand liesse sich nicht speichern.
    """
    db_path, session_factory = fresh_bootstrap_db
    ddl = SCHEMA_FILE.read_text(encoding="utf-8")

    for state in DECIDED_STATES:
        assert f"'{state}'" in ddl, (
            f"Zustand {state!r} fehlt im CHECK-Constraint des Bootstrap-DDL"
        )

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        # Die goals-Tabelle hat einen CHECK, der Zieltyp und Betragsfeld
        # koppelt: Einmalige_Ausgabe verlangt target_amount_rappen und
        # verbietet die anderen beiden. Deshalb hier vollstaendig.
        connection.execute(
            "INSERT INTO goals (id, mandate_id, client_id, goal_family, goal_type,"
            " label, rank, target_amount_rappen, created_at, updated_at)"
            " VALUES ('g1','m1','c1','Cashflow','Einmalige_Ausgabe','L',1,100000,?,?)",
            (NOW, NOW),
        )
        connection.commit()

        # Jeder bekannte Zustand ist speicherbar.
        for state in sorted(DECIDED_STATES):
            connection.execute(
                "UPDATE goals SET lifecycle_decision = ? WHERE id = 'g1'", (state,)
            )
        connection.commit()

        # Ein erfundener Zustand nicht.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE goals SET lifecycle_decision = 'phantasiezustand'"
                " WHERE id = 'g1'"
            )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Quelle 2+4: Alembic-Revision und Runtime-Patcher
# ---------------------------------------------------------------------------


def test_alembic_revision_covers_column_table_and_index():
    """Die Postgres-Strecke muss dasselbe erzeugen wie der Bootstrap."""
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'add_column("goals"' in source
    assert "lifecycle_decision" in source
    assert 'create_table(\n        "goal_lifecycle_transitions"' in source
    assert "ix_goal_lifecycle_transitions_goal_id" in source

    # Symmetrisches downgrade: sonst laesst sich die Revision nicht
    # zurueckrollen, und ein fehlgeschlagenes Deployment bleibt haengen.
    downgrade = source[source.index("def downgrade()"):]
    assert 'drop_column("goals", "lifecycle_decision")' in downgrade
    assert 'drop_table("goal_lifecycle_transitions")' in downgrade
    assert "drop_index" in downgrade


def test_ensure_runtime_columns_patches_legacy_databases():
    """Alt-DBs ohne die Spalte bekommen sie beim Start nachgezogen."""
    source = (BACKEND_ROOT / "database.py").read_text(encoding="utf-8")
    goals_block_start = source.index("'goals': [")
    goals_block = source[goals_block_start:source.index("],", goals_block_start)]
    assert "'lifecycle_decision'" in goals_block, (
        "ensure_runtime_columns() zieht die Spalte fuer bestehende "
        "SQLite-Installationen nicht nach"
    )
