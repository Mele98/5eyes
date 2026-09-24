"""FX-CURRENT-LIST-DEFAULT-DROP-001 (Kontrollrunde 2026-09-24).

GET /fx-rates/current war vorher ein reines Entweder-Oder: sobald auch nur
eine Waehrung eine DB-Zeile (is_current=1) hatte, verschwanden alle
uebrigen, noch nie manuell gepflegten Default-Waehrungen komplett aus der
Liste -- obwohl fuer sie weiterhin ein gueltiger Default-Kurs existiert und
in der tatsaechlichen Konvertierung (FXRateSource.from_db_for_model)
bereits korrekt als Fallback verwendet wird. Live reproduziert.

Der Endpoint muss jetzt fuer JEDE Waehrung aus DEFAULT_FX_RATES einen
Eintrag liefern -- Default-Kurs, ausser eine DB-Zeile ueberschreibt ihn.
"""
from __future__ import annotations

import datetime
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
from models.fx_rate import FXRate
from models.users import User
from services.auth import get_current_user
from services.currency.fx_rates import DEFAULT_FX_RATES


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fx_current_default_merge.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-fxmerge", username="advisor-fxmerge", password_hash="h",
        full_name="FX-Merge Advisor", role="advisor", is_active=1,
        created_at=_now_iso(), updated_at=_now_iso(),
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


def test_current_endpoint_returns_all_defaults_when_db_empty(auth_client):
    response = auth_client.get("/fx-rates/current")
    assert response.status_code == 200
    data = response.json()
    currencies = {row["currency"] for row in data}
    assert currencies == set(DEFAULT_FX_RATES.keys())
    assert all(row["source"] == "Default" for row in data)


def test_current_endpoint_merges_single_db_row_with_remaining_defaults(
    session_factory, auth_client,
):
    """Kern-Repro: NUR EIN Waehrung wird in der DB gepflegt -- die restlichen
    12 Default-Waehrungen duerfen NICHT aus der Liste verschwinden."""
    with session_factory() as db:
        db.add(FXRate(
            id="fx-usd-1", currency="USD", rate_x10000=9000,
            valid_from=_now_iso(), valid_until=None, is_current=1,
            source="Manual", created_at=_now_iso(), updated_at=_now_iso(),
            created_by="advisor-fxmerge",
        ))
        db.commit()

    response = auth_client.get("/fx-rates/current")
    assert response.status_code == 200
    data = response.json()
    currencies = {row["currency"] for row in data}
    # Vor dem Fix: currencies == {"USD"} -- alle anderen 12 verschwunden.
    assert currencies == set(DEFAULT_FX_RATES.keys())

    by_currency = {row["currency"]: row for row in data}
    assert by_currency["USD"]["rate"] == pytest.approx(0.9)
    assert by_currency["USD"]["source"] == "Manual"
    # Nicht manuell gepflegte Waehrungen bleiben auf dem Default-Kurs.
    assert by_currency["EUR"]["rate"] == pytest.approx(DEFAULT_FX_RATES["EUR"])
    assert by_currency["EUR"]["source"] == "Default"
    assert by_currency["JPY"]["rate"] == pytest.approx(DEFAULT_FX_RATES["JPY"])
    assert by_currency["JPY"]["source"] == "Default"


def test_current_endpoint_includes_custom_currency_not_in_defaults(
    session_factory, auth_client,
):
    """Gegenprobe: eine DB-gepflegte Waehrung, die gar nicht Teil des
    Default-Sets ist (z.B. eine exotische Waehrung), muss weiterhin
    erscheinen."""
    with session_factory() as db:
        db.add(FXRate(
            id="fx-pln-1", currency="PLN", rate_x10000=2200,
            valid_from=_now_iso(), valid_until=None, is_current=1,
            source="Manual", created_at=_now_iso(), updated_at=_now_iso(),
            created_by="advisor-fxmerge",
        ))
        db.commit()

    response = auth_client.get("/fx-rates/current")
    assert response.status_code == 200
    data = response.json()
    currencies = {row["currency"] for row in data}
    assert "PLN" in currencies
    assert currencies == set(DEFAULT_FX_RATES.keys()) | {"PLN"}
