"""Bugfix A3-Pilot (2026-08-17): WealthPositionCreate.pension_type/mortgage_type/
mortgage_amortization_type/property_usage waren als `Optional[str]` typisiert,
obwohl die DB (5eyes_schema_v4.0_FINAL.sql, wealth_positions) fuer alle vier
Felder harte CHECK-Constraints hat, z.B.:

    pension_type TEXT CHECK(pension_type IN
        ('BVG','Säule 3a','Freizügigkeit','Säule 3b','Lebensversicherung'))
    mortgage_type TEXT CHECK(mortgage_type IN
        ('Festhypothek','SARON','Gemischt'))

Ein ungueltiger Wert (konkret reproduziert: pension_type="3a" statt
"Säule 3a") passierte damit Pydantic unbeanstandet und crashte erst beim
db.commit() mit einer unbehandelten sqlite3.IntegrityError -> FastAPI liefert
dafuer standardmaessig einen 500, kein sauberes 422 mit brauchbarer Meldung.

Fix: die fuenf Felder mit Enum-Charakter (pension_type, mortgage_type,
mortgage_amortization_type, property_usage) sind jetzt Optional[Literal[...]]
mit exakt den DB-CHECK-Werten (asset_subtype hat bewusst KEIN Literal, weil
die DB dafuer gar kein CHECK hat -- siehe Kommentar in schemas/wealth.py).

Diese Tests bootstrappen eine ECHTE SQLite-DB aus dem Rohschema (nicht ueber
Base.metadata.create_all(), das kennt keine CHECK-Constraints -- siehe auch
tests/test_audit_log_action_check_constraint_drift.py fuer denselben Kniff),
damit der Vorher/Nachher-Unterschied (500 vs. 422) echt nachvollziehbar ist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module
from database import (
    Base,
    bootstrap_sqlite_schema,
    ensure_audit_log_actions,
    ensure_audit_log_triggers,
    ensure_runtime_columns,
    get_db,
)
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
from models.users import User
from models.wealth import WealthPosition
from services.auth import get_current_user

configure_mappers()

SCHEMA_PATH = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"


def _utc_now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    """Echte Rohschema-Bootstrap-DB (mit CHECK-Constraints), nicht
    Base.metadata.create_all()."""
    db_path = tmp_path / "wealth_position_enum_validation.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(SCHEMA_PATH))
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    ensure_runtime_columns()
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-wp-enum",
        username="advisor-wp-enum",
        password_hash="h",
        full_name="WP Enum Advisor",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _create_client(auth_client: TestClient, advisor_user: User, number: str) -> str:
    response = auth_client.post(
        "/clients",
        json={
            "client_number": number,
            "first_name": "WP",
            "last_name": "Enum",
            "advisor_id": advisor_user.id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# 1. API-Ebene: ungueltiger Enum-Wert -> sauberes 422, kein 500
# ---------------------------------------------------------------------------


def test_invalid_pension_type_returns_422_not_500(auth_client, advisor_user):
    """Konkret reproduziert: pension_type='3a' (User meinte 'Säule 3a')."""
    client_id = _create_client(auth_client, advisor_user, "WP-ENUM-001")

    response = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_type": "3a",
        },
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    detail_text = str(body["detail"])
    assert "pension_type" in detail_text


def test_invalid_mortgage_type_returns_422_not_500(auth_client, advisor_user):
    """Ungueltiger mortgage_type ('Hypothek-Fix' existiert nicht im
    CHECK -- nur 'Festhypothek','SARON','Gemischt')."""
    client_id = _create_client(auth_client, advisor_user, "WP-ENUM-002")

    response = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Hypothek Eigenheim",
            "position_type": "Hypothek",
            "assignment": "Verbindlichkeit",
            "current_value_rappen": 78_000_000,
            "mortgage_type": "Hypothek-Fix",
        },
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    detail_text = str(body["detail"])
    assert "mortgage_type" in detail_text


def test_valid_pension_type_still_accepted(auth_client, advisor_user):
    """Regressionsschutz: die tatsaechlich erlaubten Werte duerfen NICHT
    durch die Verschaerfung mit-abgelehnt werden."""
    client_id = _create_client(auth_client, advisor_user, "WP-ENUM-003")

    response = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_type": "Säule 3a",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["pension_type"] == "Säule 3a"


def test_valid_mortgage_type_still_accepted(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user, "WP-ENUM-004")

    response = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Hypothek Eigenheim",
            "position_type": "Hypothek",
            "assignment": "Verbindlichkeit",
            "current_value_rappen": 78_000_000,
            "mortgage_type": "SARON",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["mortgage_type"] == "SARON"


# ---------------------------------------------------------------------------
# 2. Beweis, dass die DB-CHECK-Constraint real ist (rechtfertigt den Fix)
# ---------------------------------------------------------------------------


def test_db_check_constraint_really_rejects_invalid_pension_type_when_bypassing_pydantic(
    session_factory,
):
    """Zeigt, dass die IntegrityError echt ist, wenn man Pydantic umgeht
    (z.B. direkter ORM-Insert) -- genau das, was vor dem Fix ueber den
    API-Endpoint bei einem ungueltigen Wert passierte (dort dann unbehandelt
    als 500)."""
    with session_factory() as session:
        with pytest.raises(IntegrityError):
            session.add(WealthPosition(
                id="wp-bad-pension",
                client_id="does-not-matter-for-this-check",
                label="Vorsorgekonto",
                position_type="Vorsorge",
                assignment="Anderes Vermögen",
                current_value_rappen=5_000_000,
                currency="CHF",
                pension_type="3a",
                is_active=1,
                created_at=_utc_now_iso(),
                updated_at=_utc_now_iso(),
            ))
            session.commit()
