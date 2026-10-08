"""CASHFLOW-GOAL-INCLUDE-TOGGLE-001: ein vom Berater per Switch auf
is_included=0 gesetzter Cashflow/Goal muss

  (a) weiterhin in list_cashflows()/list_goals() sichtbar sein (Frontend
      zeigt ihn ausgegraut, nicht geloescht), ABER
  (b) aus JEDER Geldberechnung verschwinden: cashflow_summary,
      cashflow_projection, services/portfolio_engine._load_allocation_inputs
      (und damit transitiv aus der Engine/PDF).

Siehe models/wealth.py::Cashflow.is_included fuer die volle Architektur-
Begruendung (bewusst getrennt von is_active/Soft-Delete).
"""
from __future__ import annotations
import sys
import uuid
import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import Cashflow, Goal
from services.auth import get_current_user
from services.portfolio_engine import _load_allocation_inputs


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'inc_toggle.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(id="adv-inc", username="adv-inc", password_hash="h", full_name="Adv",
                role="advisor", is_active=1, created_at=_now(), updated_at=_now())


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client(session_factory, advisor_id):
    cid = str(uuid.uuid4())
    with session_factory() as s:
        s.add(Client(id=cid, client_number=f"INC-{cid[:6]}", first_name="Inc",
                     last_name="Toggle", advisor_id=advisor_id, created_at=_now(), updated_at=_now()))
        s.commit()
    return cid


def _make_mandate(session_factory, client_id):
    mid = str(uuid.uuid4())
    with session_factory() as s:
        s.add(Mandate(id=mid, client_id=client_id, mandate_number=f"M-INC-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=_now(),
                      created_at=_now(), updated_at=_now()))
        s.commit()
    return mid


def _add_cashflow(session_factory, client_id, *, included=True, **fields):
    cf_id = str(uuid.uuid4())
    with session_factory() as s:
        s.add(Cashflow(
            id=cf_id, client_id=client_id,
            label=fields.pop("label", "Manual"),
            cashflow_type=fields.pop("cashflow_type", "Income"),
            amount_rappen=fields.pop("amount_rappen", 0),
            currency="CHF", frequency=fields.pop("frequency", "jährlich"),
            nature="wiederkehrend", is_active=1, is_included=1 if included else 0,
            created_at=_now(), updated_at=_now(),
            **fields,
        ))
        s.commit()
    return cf_id


def _add_goal(session_factory, mandate_id, client_id, *, included=True, **fields):
    goal_id = str(uuid.uuid4())
    with session_factory() as s:
        s.add(Goal(
            id=goal_id, mandate_id=mandate_id, client_id=client_id,
            goal_family=fields.pop("goal_family", "Cashflow"),
            goal_type=fields.pop("goal_type", "Einmalige_Ausgabe"),
            label=fields.pop("label", "Ziel"),
            rank=fields.pop("rank", 1),
            target_amount_rappen=fields.pop("target_amount_rappen", 100_000_00),
            horizon_years=fields.pop("horizon_years", 5),
            is_active=1, is_included=1 if included else 0,
            created_at=_now(), updated_at=_now(),
            **fields,
        ))
        s.commit()
    return goal_id


# ---- Router-Sichtbarkeit: list_cashflows / list_goals zeigen is_included=0 weiterhin ----

def test_list_cashflows_still_shows_excluded_row(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    excluded_id = _add_cashflow(session_factory, cid, included=False, label="Mieteinnahme (aus)",
                                amount_rappen=20_000_00)
    rows = auth_client.get(f"/clients/{cid}/cashflows").json()
    ids = {r["id"] for r in rows}
    assert excluded_id in ids, "Ausgeschlossener Cashflow muss weiterhin in der Liste sichtbar bleiben."
    row = next(r for r in rows if r["id"] == excluded_id)
    assert row["is_included"] == 0


def test_list_goals_still_shows_excluded_row(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    mid = _make_mandate(session_factory, cid)
    excluded_id = _add_goal(session_factory, mid, cid, included=False, label="Weltreise (aus)")
    rows = auth_client.get(f"/mandates/{mid}/goals").json()
    ids = {r["id"] for r in rows}
    assert excluded_id in ids, "Ausgeschlossenes Ziel muss weiterhin in der Liste sichtbar bleiben."
    row = next(r for r in rows if r["id"] == excluded_id)
    assert row["is_included"] == 0


# ---- Berechnungen: cashflow_summary / cashflow_projection schliessen is_included=0 aus ----

def test_cashflow_summary_excludes_toggled_off_cashflow(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(session_factory, cid, included=True, label="Lohn", cashflow_type="Income",
                  amount_rappen=100_000_00, frequency="jährlich", valid_from=f"{this_year}-01-01")
    _add_cashflow(session_factory, cid, included=False, label="Mieteinnahme (aus)", cashflow_type="Income",
                  amount_rappen=20_000_00, frequency="jährlich", valid_from=f"{this_year}-01-01")
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_income_rappen"] == 100_000_00, (
        "Ausgeschlossener Cashflow darf nicht in die Summary-Einnahmen einfliessen."
    )


def test_cashflow_projection_excludes_toggled_off_cashflow(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(session_factory, cid, included=True, label="Lohn", cashflow_type="Income",
                  amount_rappen=100_000_00, frequency="jährlich", valid_from=f"{this_year}-01-01")
    _add_cashflow(session_factory, cid, included=False, label="Mieteinnahme (aus)", cashflow_type="Income",
                  amount_rappen=20_000_00, frequency="jährlich", valid_from=f"{this_year}-01-01")
    body = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=3").json()
    first = body["years"][0]
    assert first["recurring_income_rappen"] == 100_000_00, (
        "Ausgeschlossener Cashflow darf nicht in die Projektion einfliessen."
    )


# ---- Engine: _load_allocation_inputs schliesst is_included=0 fuer BEIDE Entitaeten aus ----

def test_load_allocation_inputs_excludes_toggled_off_cashflow_and_goal(session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    mid = _make_mandate(session_factory, cid)
    _add_cashflow(session_factory, cid, included=True, label="Lohn", cashflow_type="Income",
                  amount_rappen=100_000_00, frequency="jährlich")
    _add_cashflow(session_factory, cid, included=False, label="Mieteinnahme (aus)", cashflow_type="Income",
                  amount_rappen=20_000_00, frequency="jährlich")
    included_goal = _add_goal(session_factory, mid, cid, included=True, label="Reserve")
    excluded_goal = _add_goal(session_factory, mid, cid, included=False, label="Weltreise (aus)", rank=2)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        inputs = _load_allocation_inputs(s, mandate, simulation_prefs={}, cma=None)

    cashflow_labels = {cf.label for cf in inputs["cashflows"]}
    assert "Lohn" in cashflow_labels
    assert "Mieteinnahme (aus)" not in cashflow_labels
    assert inputs["annual_inflows"] == 100_000_00, (
        "Ausgeschlossener Cashflow darf die Engine-Jahreseinnahmen nicht beeinflussen."
    )

    goal_ids = {str(g.id) for g in inputs["goals"]}
    assert included_goal in goal_ids
    assert excluded_goal not in goal_ids
