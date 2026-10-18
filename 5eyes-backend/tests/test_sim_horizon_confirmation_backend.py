"""SIM-HORIZON-CONFIRM-001 -- Backend: Flag, Bestaetigungs-Endpoint, Migration.

CIO-Entscheid (2026-10-17): Horizont-Werte, die VOR SIM-HORIZON-ALWAYS-
EXPLICIT-001 (#611) gespeichert wurden, werden NICHT automatisch migriert.
Der Berater bestaetigt sie einmalig (Banner "Horizont bestaetigen").

* ``simulation.horizonExplicit`` (strikt bool) kennzeichnet ab jetzt jede
  ausdrueckliche Wahl im Snapshot. "Vor der Umstellung" = ``horizonYears``
  vorhanden OHNE dieses Flag.
* ``preferences_json`` ist Teil des ``allocation_context_hash`` und bleibt
  unveraendert; die nachtraegliche Bestaetigung landet in
  ``target_allocations.sim_horizon_confirmed_at/_by``.
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
        q_wealth_points=2, investment_horizon_label="8 bis 11 Jahre",
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


def _confirm(auth_client, mid: str, years: int):
    return auth_client.post(
        f"/mandates/{mid}/target-allocation/current/sim-horizon-confirmation",
        json={"horizon_years": years},
    )


# ---------------------------------------------------------------------------
# Schema: horizonExplicit
# ---------------------------------------------------------------------------


def test_schema_accepts_horizon_explicit_bool_and_keeps_it():
    payload = AllocationPreferencesPayload.model_validate(
        {"simulation": {"horizonYears": "15", "horizonExplicit": True}}
    ).model_dump()
    assert payload["simulation"]["horizonExplicit"] is True


@pytest.mark.parametrize("value", ["true", 1, "yes", None])
def test_schema_rejects_non_bool_horizon_explicit(value):
    with pytest.raises(ValidationError):
        AllocationPreferencesPayload.model_validate(
            {"simulation": {"horizonYears": "15", "horizonExplicit": value}}
        )


def test_engine_horizon_ignores_explicit_flag():
    """Das Flag ist rein dokumentarisch: die Engine liest nur horizonYears."""
    assert _simulation_horizon_years(
        {"horizonYears": "15", "horizonExplicit": True}, [], None
    ) == _simulation_horizon_years({"horizonYears": "15"}, [], None) == 15


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def test_new_allocation_snapshot_carries_explicit_flag(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    ta = _generate(auth_client, mid, {"horizonYears": "15", "horizonExplicit": True})
    prefs = json.loads(ta["preferences_json"])
    assert prefs["simulation"]["horizonExplicit"] is True
    assert ta["sim_horizon_confirmed_at"] is None


def test_confirm_legacy_horizon_persists_without_touching_snapshot(
    auth_client, session_factory, advisor_user
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    # Alt-Snapshot: horizonYears ohne horizonExplicit (so schrieb die UI vor #611).
    ta = _generate(auth_client, mid, {"horizonYears": "10"})
    assert "horizonExplicit" not in json.loads(ta["preferences_json"])["simulation"]
    with session_factory() as s:
        row = s.get(TargetAllocation, ta["id"])
        before = (row.preferences_json, row.allocation_context_hash, row.updated_at)

    resp = _confirm(auth_client, mid, 10)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["already_confirmed"] is False
    assert body["target_allocation_id"] == ta["id"]
    assert body["horizon_years"] == 10
    assert body["sim_horizon_confirmed_by"] == advisor_user.id
    assert body["sim_horizon_confirmed_at"]

    with session_factory() as s:
        row = s.get(TargetAllocation, ta["id"])
        assert row.sim_horizon_confirmed_at == body["sim_horizon_confirmed_at"]
        assert row.sim_horizon_confirmed_by == advisor_user.id
        # Snapshot + Hash (Audit-Anker) unveraendert.
        assert (row.preferences_json, row.allocation_context_hash, row.updated_at) == before

    # Der Reload-Payload liefert die Bestaetigung ans Frontend (Hydration).
    payload = auth_client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert payload.status_code == 200, payload.text
    assert payload.json()["target_allocation"]["sim_horizon_confirmed_at"] == body["sim_horizon_confirmed_at"]


def test_confirm_is_idempotent(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(auth_client, mid, {"horizonYears": "27"})
    first = _confirm(auth_client, mid, 27).json()
    second = _confirm(auth_client, mid, 27)
    assert second.status_code == 200, second.text
    assert second.json()["already_confirmed"] is True
    assert second.json()["sim_horizon_confirmed_at"] == first["sim_horizon_confirmed_at"]


def test_confirm_rejects_value_differing_from_snapshot(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    ta = _generate(auth_client, mid, {"horizonYears": "10"})
    resp = _confirm(auth_client, mid, 15)
    assert resp.status_code == 409, resp.text
    with session_factory() as s:
        assert s.get(TargetAllocation, ta["id"]).sim_horizon_confirmed_at is None


def test_confirm_rejects_auto_snapshot(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(auth_client, mid, {"stressMultiplier": "1.0"})
    resp = _confirm(auth_client, mid, 10)
    assert resp.status_code == 409, resp.text


def test_confirm_on_already_explicit_snapshot_is_noop(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    ta = _generate(auth_client, mid, {"horizonYears": "15", "horizonExplicit": True})
    resp = _confirm(auth_client, mid, 15)
    assert resp.status_code == 200, resp.text
    assert resp.json()["already_confirmed"] is True
    with session_factory() as s:
        assert s.get(TargetAllocation, ta["id"]).sim_horizon_confirmed_at is None


def test_confirm_without_allocation_is_404(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    resp = _confirm(auth_client, mid, 10)
    assert resp.status_code == 404
    # Nicht das 404 einer fehlenden Route: die fachliche Meldung muss kommen.
    assert resp.json()["detail"] == "Keine Soll-Allokation gefunden"


def test_confirm_rejects_out_of_range_years(auth_client, session_factory, advisor_user):
    mid = _seed_mandate(session_factory, advisor_user.id)
    assert _confirm(auth_client, mid, 0).status_code == 422
    assert _confirm(auth_client, mid, 121).status_code == 422


# ---------------------------------------------------------------------------
# Schema-Migration (SQLite create_all + ensure_column, Alembic-Head)
# ---------------------------------------------------------------------------


def test_orm_model_declares_confirmation_columns():
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
