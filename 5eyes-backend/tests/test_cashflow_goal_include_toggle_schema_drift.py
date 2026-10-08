"""CASHFLOW-GOAL-INCLUDE-TOGGLE-001 (Audit-Feedback, 2026-10-08): neue Spalte
is_included auf Cashflow und Goal, GETRENNT von is_active/deleted_at. Siehe
models/wealth.py::Cashflow.is_included fuer die volle Semantik.

Dieselbe Bugklasse wie test_wealth_positions_fresh_bootstrap_schema_drift.py
und Geschwister: eine neue Spalte muss in ALLEN 4 Schema-Quellen konsistent
auftauchen (ORM-Model, Alembic-Migration, roher Bootstrap-SQL-DDL,
ensure_runtime_columns()-Patcher), sonst driftet eine frische Erstinstallation
(bootstrap_sqlite_schema) von einer bereits migrierten Alt-DB
(ensure_runtime_columns) auseinander.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401,E501
configure_mappers()


def _fresh_session(tmp_path, monkeypatch, name):
    import database as db_module

    db_path = tmp_path / name
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    return sessionmaker(bind=test_engine)


def _seed_client(session):
    from models.users import User
    from models.clients import Client
    now = "2026-10-08T00:00:00.000Z"
    session.add(User(
        id="user-inc-test", username="inc-tester", password_hash="x", full_name="Tester",
        role="advisor", is_active=1, created_at=now, updated_at=now,
    ))
    session.add(Client(
        id="client-inc-test", client_number="K-INC-1", first_name="Inc", last_name="Toggle",
        country_of_residence="CH", advisor_id="user-inc-test", created_at=now, updated_at=now,
    ))
    session.flush()


def test_fresh_bootstrap_cashflow_defaults_is_included_to_one(tmp_path, monkeypatch):
    """Ein frisch bootstrapptes (nicht-ORM) Schema muss is_included=1 als
    Default liefern, wenn eine Zeile sie nicht explizit setzt -- sonst
    verschwinden bei einer echten Erstinstallation ALLE Bestandszeilen
    stillschweigend aus jeder Berechnung."""
    from models.wealth import Cashflow

    TestSession = _fresh_session(tmp_path, monkeypatch, "fresh_cf_included.db")
    now = "2026-10-08T00:00:00.000Z"
    with TestSession() as session:
        _seed_client(session)
        session.add(Cashflow(
            id="cf-inc-test", client_id="client-inc-test", cashflow_type="Income",
            label="Lohn", amount_rappen=100_000_00, currency="CHF",
            frequency="jährlich", nature="wiederkehrend",
            created_at=now, updated_at=now,
        ))
        session.commit()
        stored = session.query(Cashflow).filter(Cashflow.id == "cf-inc-test").one()
    assert stored.is_included == 1


def test_fresh_bootstrap_goal_defaults_is_included_to_one(tmp_path, monkeypatch):
    from models.mandates import Mandate
    from models.wealth import Goal

    TestSession = _fresh_session(tmp_path, monkeypatch, "fresh_goal_included.db")
    now = "2026-10-08T00:00:00.000Z"
    with TestSession() as session:
        _seed_client(session)
        session.add(Mandate(
            id="mandate-inc-test", client_id="client-inc-test", mandate_number="M-INC-1",
            mandate_type="Anlageberatung", opened_at=now, created_at=now, updated_at=now,
        ))
        session.flush()
        session.add(Goal(
            id="goal-inc-test", mandate_id="mandate-inc-test", client_id="client-inc-test",
            goal_family="Cashflow", goal_type="Einmalige_Ausgabe", label="Reserve",
            rank=1, target_amount_rappen=100_000_00, horizon_years=5,
            created_at=now, updated_at=now,
        ))
        session.commit()
        stored = session.query(Goal).filter(Goal.id == "goal-inc-test").one()
    assert stored.is_included == 1


def test_fresh_bootstrap_rejects_invalid_is_included_values(tmp_path, monkeypatch):
    """CHECK(is_included IN (0,1)) im rohen Bootstrap-SQL muss greifen --
    Regressionsschutz fuer die exakte gleiche Bugklasse wie
    test_wealth_positions_fresh_bootstrap_schema_drift.py (ein Rohwert, den
    die Engine nicht kennt, darf nicht unbemerkt in der DB landen)."""
    import sqlite3

    from models.wealth import Cashflow

    TestSession = _fresh_session(tmp_path, monkeypatch, "fresh_cf_invalid.db")
    now = "2026-10-08T00:00:00.000Z"
    with TestSession() as session:
        _seed_client(session)
        session.add(Cashflow(
            id="cf-inc-invalid", client_id="client-inc-test", cashflow_type="Income",
            label="Lohn", amount_rappen=100_000_00, currency="CHF",
            frequency="jährlich", nature="wiederkehrend", is_included=2,
            created_at=now, updated_at=now,
        ))
        try:
            session.commit()
            raised = False
        except Exception as exc:  # sqlite3.IntegrityError wrapped by SQLAlchemy
            raised = True
            assert "is_included" in str(exc) or "CHECK" in str(exc)
        finally:
            session.rollback()
    assert raised, "CHECK-Constraint auf is_included muss ungültige Rohwerte ablehnen."
