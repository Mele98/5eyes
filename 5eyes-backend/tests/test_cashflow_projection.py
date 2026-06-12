from __future__ import annotations
import sys
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
from models.wealth import Cashflow
from models.users import User
from services.auth import get_current_user
import uuid, datetime


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_cf_proj.db'}",
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
    return User(
        id="user-cfp-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at="2026-04-02T00:00:00.000Z",
        updated_at="2026-04-02T00:00:00.000Z",
    )


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


def _make_client(session_factory, advisor_id: str) -> str:
    cid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number="CF-001", first_name="Hans", last_name="Muster",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _add_cashflow(session_factory, client_id: str, amount_rappen: int,
                  cf_type: str = "Income", frequency: str = "Jährlich") -> None:
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client_id,
            cashflow_type=cf_type, label="Test CF",
            amount_rappen=amount_rappen, frequency=frequency,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


def test_cashflow_projection_returns_5_years(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_cashflow(session_factory, cid, 12_000_000)  # CHF 120k Income

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=5")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["years"]) == 5
    assert all(row["income_rappen"] == 12_000_000 for row in data["years"])
    assert all(row["recurring_income_rappen"] == 12_000_000 for row in data["years"])
    assert all(row["capital_inflow_rappen"] == 0 for row in data["years"])
    assert all(row["recurring_expense_rappen"] == 0 for row in data["years"])
    assert all(row["capital_outflow_rappen"] == 0 for row in data["years"])


def test_cashflow_projection_net_calculation(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_cashflow(session_factory, cid, 10_000_000, "Income")
    _add_cashflow(session_factory, cid, 4_000_000, "Expense")

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert rows[0]["net_rappen"] == 6_000_000


def test_cashflow_projection_empty_client_returns_zeros(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert all(r["net_rappen"] == 0 for r in rows)


def test_cashflow_projection_segments_one_off_flows(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()),
            client_id=cid,
            cashflow_type="Income",
            label="3a Bezug",
            amount_rappen=5_000_000,
            frequency="einmalig",
            nature="einmalig",
            valid_from="2028-01-01",
            valid_until="2028-01-01",
            is_active=1,
            created_at=now,
            updated_at=now,
        ))
        s.add(Cashflow(
            id=str(uuid.uuid4()),
            client_id=cid,
            cashflow_type="Expense",
            label="Leben",
            amount_rappen=2_000_000,
            frequency="jährlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until="2029-12-31",
            is_active=1,
            created_at=now,
            updated_at=now,
        ))
        s.commit()

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=4")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert rows[0]["recurring_income_rappen"] == 0
    assert rows[0]["capital_inflow_rappen"] == 0
    assert rows[0]["recurring_expense_rappen"] == 2_000_000
    assert rows[0]["capital_outflow_rappen"] == 0
    assert rows[2]["capital_inflow_rappen"] == 5_000_000
    assert rows[2]["net_rappen"] == 3_000_000


# ---------------------------------------------------------------------------
# Zeitraum-Fix (2026-06-12): Projektions-Horizont aus Stammdaten bis Lebensende,
# damit der Vermoegensverzehr nach Pensionierung sichtbar ist (statt hartes 40).
# ---------------------------------------------------------------------------

def _make_client_full(session_factory, advisor_id: str, **fields) -> str:
    cid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number="CF-" + cid[:6], first_name="Leart", last_name="Test",
            advisor_id=advisor_id, created_at=now, updated_at=now, **fields,
        ))
        s.commit()
    return cid


def test_horizon_derives_to_life_end_from_birthdate(session_factory, auth_client, advisor_user):
    """Ohne Override: Geburtsjahr + 90 (CH-Lebenserwartung) -> Projektion bis Lebensende."""
    cid = _make_client_full(session_factory, advisor_user.id, date_of_birth="1970-05-01")
    rows = auth_client.get(f"/clients/{cid}/cashflow-projection").json()["years"]
    # 1970 + 90 = 2060, inklusive -> letztes Projektionsjahr ist 2060
    assert rows[-1]["year"] == 2060


def test_horizon_uses_investment_horizon_end_without_birthdate(session_factory, auth_client, advisor_user):
    """investment_horizon_end (Stammdatum) wird als Lebensende-Quelle genutzt."""
    cid = _make_client_full(session_factory, advisor_user.id, investment_horizon_end="2058-06-30")
    rows = auth_client.get(f"/clients/{cid}/cashflow-projection").json()["years"]
    assert rows[-1]["year"] == 2058


def test_explicit_override_beats_stammdaten(session_factory, auth_client, advisor_user):
    """Expliziter Berater-Override (?horizon_years=) hat Vorrang vor der Ableitung."""
    cid = _make_client_full(session_factory, advisor_user.id, date_of_birth="1970-01-01")
    rows = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=5").json()["years"]
    assert len(rows) == 5


def test_horizon_falls_back_to_40_without_stammdaten(session_factory, auth_client, advisor_user):
    """Ohne Geburtsdatum/Horizont-Ende/Mandat -> konservatives Default 40."""
    cid = _make_client(session_factory, advisor_user.id)
    rows = auth_client.get(f"/clients/{cid}/cashflow-projection").json()["years"]
    assert len(rows) == 40


def _add_cashflow_dated(session_factory, client_id, amount_rappen, cf_type,
                        valid_from, valid_until, frequency="jährlich"):
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client_id,
            cashflow_type=cf_type, label="Dated CF", nature="wiederkehrend",
            amount_rappen=amount_rappen, frequency=frequency,
            valid_from=valid_from, valid_until=valid_until,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


def test_horizon_covers_all_cashflows_beyond_life_expectancy(session_factory, auth_client, advisor_user):
    """Leart-Szenario: AHV/Verzehr laufen via valid_until ueber die reine
    Lebenserwartung (Geburt+90) hinaus -> die Projektion MUSS bis zum letzten
    Cashflow-Jahr reichen, sonst wird der Vermoegensverzehr abgeschnitten."""
    cid = _make_client_full(session_factory, advisor_user.id, date_of_birth="1965-01-01")
    # Geburt 1965 + 90 = 2055; Cashflow laeuft aber bis 2060.
    _add_cashflow_dated(session_factory, cid, 3_500_000, "Income",
                        valid_from="2030-01-01", valid_until="2060-01-01")
    rows = auth_client.get(f"/clients/{cid}/cashflow-projection").json()["years"]
    assert rows[-1]["year"] == 2060
