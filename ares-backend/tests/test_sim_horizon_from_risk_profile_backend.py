"""SIM-HORIZON-FROM-RISK-PROFILE-001 -- Backend: Prognosehorizont ohne Berater-Wahl.

CIO-Entscheid (2026-10-18, ersetzt SIM-HORIZON-CONFIRM-001 / #622 und den
Horizont-Select aus SIM-HORIZON-ALWAYS-EXPLICIT-001 / #611): der Horizont wird
im Risikoprofil erhoben und von dort uebernommen. Er ist keine Einstellung
mehr und muss nicht bestaetigt werden.

* Horizont = max(10, Anlagehorizont des aktuellen Risikoprofils, letztes
  datiertes Ziel, Lebenserwartung) -- fuer Solver, Payload-Reload und
  Report-MC dieselbe Herleitung.
* ``simulation.horizonYears`` / ``horizonExplicit`` werden angenommen (Alt-
  Snapshots crashen nicht), aber verworfen und nie ausgewertet.
* Der Bestaetigungs-Endpoint ist entfernt; die Spalten
  ``sim_horizon_confirmed_at/_by`` bleiben (keine Down-Migration).
* Reasoning und Report nennen die bestimmende Groesse.
"""
from __future__ import annotations

import datetime
import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from schemas.allocation import AllocationPreferencesPayload  # noqa: E402
from services.portfolio_engine_allocation_integrity import allocation_context_hash_for  # noqa: E402
from services.auth import get_current_user, require_advisor  # noqa: E402
from services.portfolio_engine import ensure_runtime_reference_data  # noqa: E402
from services.portfolio_engine_mc_simulation import _simulation_horizon_years  # noqa: E402
from tests.risk_fixture_helpers import (  # noqa: E402
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
    noop_lifespan,
)

_MIGRATION_REVISION = "e7b2c9d41f08"
_PREVIOUS_HEAD = "c4e9a1f73b28"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sim_horizon_confirm.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    now = _now()
    return User(
        id="user-shc-1", username="advisor-shc", password_hash="h",
        full_name="Advisor SHC", role="advisor", is_active=1,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")

    def override_db():
        with session_factory() as s:
            yield s

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    app.dependency_overrides[require_advisor] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_mandate(session_factory, advisor_id: str) -> str:
    cid, mid, aid = (str(uuid.uuid4()) for _ in range(3))
    now = _now()
    risk_fields = derive_current_risk_fields(
        q_income_points=2, q_obligations_points=3, q_savings_points=2,
        q_wealth_points=2, investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=3, q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number=f"C-SHC-{cid[:6]}", first_name="Test",
            last_name="Mandant", advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-SHC-{mid[:6]}",
            mandate_type="Vermoegensverwaltung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid, label="Depot", position_type="Depot",
            assignment="Beratungsvermögen", current_value_rappen=1_000_000_00,
            currency="CHF", alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=1000, is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            **risk_fields, is_overridden=0, **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id, created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return mid


def _generate(auth_client, mid: str, simulation: dict) -> dict:
    resp = auth_client.post(
        f"/mandates/{mid}/target-allocation/generate",
        json={"preferences": {"simulation": simulation}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["target_allocation"]


def _generate_full(auth_client, mid: str, simulation: dict) -> dict:
    resp = auth_client.post(
        f"/mandates/{mid}/target-allocation/generate",
        json={"preferences": {"simulation": simulation}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_risk_horizon(session_factory, mid: str, years: int, label: str) -> None:
    with session_factory() as s:
        ra = s.query(RiskAssessment).filter(
            RiskAssessment.mandate_id == mid, RiskAssessment.is_current == 1
        ).one()
        ra.investment_horizon_years = years
        ra.investment_horizon_label = label
        s.commit()


# Der Seed-Mandant hat KEIN Geburtsdatum (keine Lebenserwartung) und keine
# Ziele: der Anlagehorizont des Risikoprofils ("Mehr als 12 Jahre" = 15) ist
# die einzige fachliche Groesse. Vor dem Entscheid ergab das 10 (generische
# Untergrenze, "Auto") bzw. den gespeicherten Praeferenzwert (z.B. 25).
_RISK_HORIZON = 15
_SENTENCE = (
    f"Prognosehorizont {_RISK_HORIZON} Jahre, hergeleitet aus dem "
    "Anlagehorizont des Risikoprofils."
)


# ---------------------------------------------------------------------------
# Schema: Alt-Keys werden angenommen und verworfen
# ---------------------------------------------------------------------------


def test_schema_drops_legacy_horizon_keys():
    payload = AllocationPreferencesPayload.model_validate(
        {"simulation": {"horizonYears": "15", "horizonExplicit": True, "stressMultiplier": "1.0"}}
    ).model_dump()
    assert payload["simulation"] == {"stressMultiplier": "1.0"}


@pytest.mark.parametrize("value", ["true", 1, "yes", None])
def test_schema_tolerates_any_legacy_horizon_explicit_value(value):
    """Frueher strikt bool validiert -- jetzt bedeutungslos: kein 422 auf
    Alt-Snapshots, kein Persistieren."""
    payload = AllocationPreferencesPayload.model_validate(
        {"simulation": {"horizonYears": "15", "horizonExplicit": value}}
    ).model_dump()
    assert payload["simulation"] == {}


# ---------------------------------------------------------------------------
# Engine: Herleitung
# ---------------------------------------------------------------------------


def test_engine_horizon_ignores_preference_horizon():
    assert _simulation_horizon_years(
        {"horizonYears": "15", "horizonExplicit": True}, [], None
    ) == _simulation_horizon_years({}, [], None) == 10


def test_risk_profile_horizon_drives_projection(session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    with session_factory() as s:
        mandate = s.get(Mandate, mid)
        assert _simulation_horizon_years({}, [], mandate) == _RISK_HORIZON
        # Ein Alt-Praeferenzwert aendert daran nichts.
        assert _simulation_horizon_years({"horizonYears": "25"}, [], mandate) == _RISK_HORIZON
    _set_risk_horizon(session_factory, mid, 9, "8 bis 11 Jahre")
    with session_factory() as s:
        # 9 < Solver-Mindestdauer 10 (siehe SIMULATION_HORIZON_MIN_YEARS).
        assert _simulation_horizon_years({}, [], s.get(Mandate, mid)) == 10


def test_short_risk_horizon_keeps_ten_year_minimum(session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _set_risk_horizon(session_factory, mid, 2, "2 bis 3 Jahre")
    from services.portfolio_engine_mc_simulation import _simulation_horizon_derivation

    with session_factory() as s:
        derivation = _simulation_horizon_derivation([], s.get(Mandate, mid))
    assert derivation["years"] == 10
    assert derivation["sources"] == ["minimum"]
    assert derivation["components"]["risk_profile"] == 2
    assert derivation["sentence"] == (
        "Prognosehorizont 10 Jahre, hergeleitet aus der Mindestdauer von 10 Jahren."
    )


def test_life_expectancy_beyond_risk_horizon_wins_and_is_named(session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    life_year = datetime.date.today().year + 24
    with session_factory() as s:
        s.get(Mandate, mid).life_expectancy_year = life_year
        s.commit()
    from services.portfolio_engine_mc_simulation import _simulation_horizon_derivation

    with session_factory() as s:
        derivation = _simulation_horizon_derivation([], s.get(Mandate, mid))
    assert derivation["years"] == 25
    assert derivation["components"]["risk_profile"] == _RISK_HORIZON
    assert derivation["sentence"] == (
        "Prognosehorizont 25 Jahre, hergeleitet aus der Lebenserwartung."
    )


# ---------------------------------------------------------------------------
# Generate / Reload / Report
# ---------------------------------------------------------------------------


def test_generate_uses_risk_profile_horizon_and_ignores_legacy_preference(
    auth_client, session_factory, advisor_user
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    body = _generate_full(
        auth_client, mid, {"horizonYears": "25", "horizonExplicit": True}
    )
    assert body["monte_carlo"]["horizon_years"] == _RISK_HORIZON
    assert body["simulation"]["horizon_years"] == _RISK_HORIZON
    assert body["projection_horizon"]["years"] == _RISK_HORIZON
    assert body["projection_horizon"]["sources"] == ["risk_profile"]
    assert _SENTENCE in body["reasoning"]
    ta = body["target_allocation"]
    simulation = json.loads(ta["preferences_json"])["simulation"]
    assert "horizonYears" not in simulation
    assert "horizonExplicit" not in simulation
    # Die Bestaetigungsfelder werden nicht mehr ausgeliefert.
    assert "sim_horizon_confirmed_at" not in ta


def test_reload_of_legacy_snapshot_ignores_stored_horizon_without_drift_warning(
    auth_client, session_factory, advisor_user
):
    """Alt-Snapshot mit horizonYears (so schrieb die UI vor diesem Entscheid):
    der Reload crasht nicht, rechnet mit dem Risikoprofil-Horizont und meldet
    KEINE Praeferenz-Drift nur wegen des verworfenen Alt-Keys."""
    mid = _seed_mandate(session_factory, advisor_user.id)
    ta = _generate(auth_client, mid, {"stressMultiplier": "1.0"})
    with session_factory() as s:
        row = s.get(TargetAllocation, ta["id"])
        prefs = json.loads(row.preferences_json)
        prefs["simulation"]["horizonYears"] = "25"
        prefs["simulation"]["horizonExplicit"] = True
        row.preferences_json = json.dumps(prefs, sort_keys=True, default=str)
        constraints = json.loads(row.effective_constraints_json)
        row.allocation_context_hash = allocation_context_hash_for(
            engine_version=constraints["engine_version"],
            policy_id=row.policy_id,
            cma_id=row.capital_market_assumptions_id,
            assessment_id=row.based_on_assessment_id,
            input_snapshot_hash=row.input_snapshot_hash,
            preferences_json=row.preferences_json,
            targets={b: int(getattr(row, f"target_{b}_bps")) for b in pe.BUCKET_FIELDS},
            sub_allocations=json.loads(row.sub_allocations_json),
            effective_constraints=constraints,
            optimization_seed=row.optimization_seed,
        )
        s.commit()

    resp = auth_client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["monte_carlo"]["horizon_years"] == _RISK_HORIZON
    assert payload["projection_horizon"]["years"] == _RISK_HORIZON
    assert _SENTENCE in payload["reasoning"]
    assert not any("Mandatspraeferenzen" in item for item in payload["reasoning"])


def test_report_monte_carlo_uses_same_horizon_and_names_it(
    auth_client, session_factory, advisor_user
):
    from services.advisory_report import _build_monte_carlo_paths_section

    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(auth_client, mid, {"stressMultiplier": "1.0"})
    with session_factory() as s:
        section = _build_monte_carlo_paths_section(s, s.get(Mandate, mid))
    assert section["horizon_years"] == _RISK_HORIZON
    assert section["horizon_note"] == _SENTENCE


# ---------------------------------------------------------------------------
# Bestaetigungs-Endpoint entfernt
# ---------------------------------------------------------------------------


def test_confirmation_endpoint_is_removed(auth_client, session_factory, advisor_user):
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any("sim-horizon-confirmation" in path for path in paths)
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(auth_client, mid, {"stressMultiplier": "1.0"})
    resp = auth_client.post(
        f"/mandates/{mid}/target-allocation/current/sim-horizon-confirmation",
        json={"horizon_years": 10},
    )
    assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Schema-Migration (SQLite create_all + ensure_column, Alembic-Head)
# ---------------------------------------------------------------------------


def test_orm_model_keeps_confirmation_columns():
    """Spalten bleiben (keine Down-Migration), werden aber nicht mehr gelesen."""
    columns = set(TargetAllocation.__table__.columns.keys())
    assert {"sim_horizon_confirmed_at", "sim_horizon_confirmed_by"} <= columns


def test_sqlite_ensure_column_list_covers_confirmation_columns():
    src = (BACKEND_ROOT / "database.py").read_text(encoding="utf-8")
    block = src.split("'target_allocations': [", 1)[1].split("],", 1)[0]
    assert "('sim_horizon_confirmed_at', 'TEXT')" in block
    assert "('sim_horizon_confirmed_by', 'TEXT')" in block


def _alembic_cfg(db_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_single_head_is_confirmation_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    # Genau ein Head; spaetere Revisionen (z.B. d7c3e9a2f5b1, ESG-PREMIUM-
    # CRITERIA-001) duerfen darauf aufbauen, solange die Bestaetigungs-
    # Revision in der linearen Kette bleibt.
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert _MIGRATION_REVISION in chain


def _ta_columns(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return {c["name"] for c in inspect(engine).get_columns("target_allocations")}
    finally:
        engine.dispose()


def test_alembic_migration_upgrade_downgrade_and_idempotent(tmp_path):
    from alembic import command

    db_url = f"sqlite:///{tmp_path / 'alembic_shc.db'}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "head")
    cols = _ta_columns(db_url)
    assert {"sim_horizon_confirmed_at", "sim_horizon_confirmed_by"} <= cols

    command.downgrade(cfg, _PREVIOUS_HEAD)
    assert not ({"sim_horizon_confirmed_at", "sim_horizon_confirmed_by"} & _ta_columns(db_url))

    # Idempotenz: Spalte existiert bereits (z.B. via ensure_column), Revision
    # steht aber noch auf dem Vorgaenger -> upgrade darf nicht crashen.
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE target_allocations ADD COLUMN sim_horizon_confirmed_at TEXT"))
    engine.dispose()
    command.upgrade(cfg, "head")
    assert {"sim_horizon_confirmed_at", "sim_horizon_confirmed_by"} <= _ta_columns(db_url)
