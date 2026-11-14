"""H11 (Hygiene-Folgepunkt H9/Codex-Note): GET-Pfade seeden keine Referenzdaten.

Befund: ``GET /mandates/{id}/ist-projection-basis`` und der Allokations-Lesepfad
(``GET .../target-allocation/current/payload``, Empfehlungs-Payloads ueber
``build_recommendation_payload_from_run``) riefen ``ensure_runtime_reference_data``
auf -- der CH-Zweig legt ausserhalb der Produktion Policy, House-Matrix,
Bausteine und CMA an. Ein Schreibeffekt im Lesepfad.

Vertrag jetzt:
- GET ist rein lesend (``ensure_runtime_reference_data(..., seed=False)``); ohne
  Referenzdaten antwortet der Pfad mit seinem bestehenden 409 und schreibt nichts.
- Das Seeding passiert im Bootstrap (``POST /auth/bootstrap-admin`` ruft die in
  main.py registrierten ``post_bootstrap_hooks``; routers.auth bleibt ohne
  Engine-Abhaengigkeit, Architektur-Ratsche).
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401  (Mapper registrieren)
from core.reason_codes import ReasonCode
from database import Base, get_db
from models.allocation import BuildingBlock, CapitalMarketAssumption, OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import WealthPosition

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def session_factory(tmp_path):
    import main  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'h11_refdata.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(session) -> User:
    owner = User(id="adv-h11", username="adv-h11", password_hash="h", full_name="adv", role="advisor",
                 is_active=1, created_at=NOW, updated_at=NOW)
    session.add(owner)
    session.add(Client(
        id="cl-h11", client_number="C-H11", first_name="Max", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=owner.id, created_at=NOW, updated_at=NOW,
    ))
    session.add(Mandate(
        id="m-h11", client_id="cl-h11", mandate_number="M-H11", mandate_type="Anlageberatung",
        status="Aktiv", base_currency="CHF", advisory_language="DE", opened_at="2026-01-01",
        created_at=NOW, updated_at=NOW,
    ))
    session.add(WealthPosition(
        id="wp-h11", client_id="cl-h11", label="Depot", position_type="Depot",
        assignment="Beratungsvermögen", current_value_rappen=50_000_000, currency="CHF",
        alloc_equities_bps=5000, alloc_bonds_bps=5000, created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    return owner


def _reference_counts(session) -> tuple[int, int, int]:
    return (session.query(OptimizerPolicy).count(), session.query(CapitalMarketAssumption).count(),
            session.query(BuildingBlock).count())


def test_ist_projection_basis_without_reference_data_is_409_and_writes_nothing(session_factory):
    from routers.allocation import get_ist_projection_basis

    with session_factory() as session:
        owner = _seed_mandate(session)
        with pytest.raises(HTTPException) as exc:
            get_ist_projection_basis("m-h11", db=session, current_user=owner)
        session.commit()  # ein Seeding im Lesepfad waere spaetestens jetzt persistiert
    with session_factory() as session:
        counts = _reference_counts(session)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == ReasonCode.IST_PROJECTION_BASIS_UNAVAILABLE.value
    assert counts == (0, 0, 0)


def test_read_only_resolution_matches_seeding_path_once_bootstrapped(session_factory):
    from services.jurisdiction.exceptions import JurisdictionReferenceDataMissingError
    from services.portfolio_engine import ensure_runtime_reference_data

    with session_factory() as session:
        owner = _seed_mandate(session)
        with pytest.raises(JurisdictionReferenceDataMissingError):
            ensure_runtime_reference_data(session, owner.id, jurisdiction="CH", seed=False)
        assert _reference_counts(session) == (0, 0, 0)
        policy, cma = ensure_runtime_reference_data(session, owner.id, jurisdiction="CH")
        session.commit()
        before = _reference_counts(session)
        r_policy, r_cma = ensure_runtime_reference_data(session, owner.id, jurisdiction="CH", seed=False)
        assert (r_policy.id, r_cma.id) == (policy.id, cma.id)
        assert _reference_counts(session) == before


def _reference_calls_in_get_routes() -> list[tuple[str, bool]]:
    """(Route, seed=False gesetzt) fuer jeden ensure_runtime_reference_data-Aufruf in GET-Routen."""
    hits = []
    for path in sorted((BACKEND / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_get = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "get"
                         for d in fn.decorator_list)
            for call in ast.walk(fn) if is_get else ():
                if isinstance(call, ast.Call) and getattr(call.func, "id", getattr(call.func, "attr", None))                         == "ensure_runtime_reference_data":
                    read_only = any(k.arg == "seed" and isinstance(k.value, ast.Constant) and k.value.value is False
                                    for k in call.keywords)
                    hits.append((f"{path.name}::{fn.name}", read_only))
    return hits


def test_no_get_route_seeds_reference_data():
    calls = _reference_calls_in_get_routes()
    assert {"allocation.py::get_ist_projection_basis", "allocation.py::get_current_allocation_payload"} <= {
        route for route, _ro in calls}  # Positivkontrolle
    assert [route for route, read_only in calls if not read_only] == []


def test_recommendation_payload_reader_does_not_seed():
    from services import portfolio_engine as pe

    src = inspect.getsource(pe.build_recommendation_payload_from_run)
    assert "ensure_runtime_reference_data(" in src and "seed=False" in src


@pytest.fixture()
def api_client(session_factory):
    from main import app

    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _bootstrap(client):
    return client.post("/auth/bootstrap-admin", json={
        "username": "admin-h11", "password": "Sehr-sicheres-Passwort-11!", "full_name": "Admin H11"})


def test_bootstrap_admin_seeds_ch_reference_data(api_client, session_factory):
    resp = _bootstrap(api_client)
    assert resp.status_code == 201, resp.text
    with session_factory() as session:
        policies, cmas, blocks = _reference_counts(session)
        admin = session.query(User).filter(User.username == "admin-h11").one()
        policy = session.query(OptimizerPolicy).one()
    assert (policies, cmas) == (1, 1) and blocks > 0
    assert policy.created_by == admin.id


def test_bootstrap_without_autoseeding_in_production_still_succeeds(session_factory, monkeypatch):
    from config import settings
    from routers.allocation import seed_reference_data_at_bootstrap

    monkeypatch.setattr(settings, "app_env", "production")
    with session_factory() as session:
        owner = _seed_mandate(session)
        assert seed_reference_data_at_bootstrap(session, owner.id) is False
    with session_factory() as session:
        assert _reference_counts(session) == (0, 0, 0)


def test_bootstrap_hook_is_registered_and_auth_has_no_engine_import():
    from main import app
    from routers.allocation import seed_reference_data_at_bootstrap

    assert seed_reference_data_at_bootstrap in app.state.post_bootstrap_hooks
    auth_src = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
    assert "portfolio_engine" not in auth_src and "post_bootstrap_hooks" in auth_src
