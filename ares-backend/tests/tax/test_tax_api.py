from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import models.tax  # noqa: F401
from database import Base, get_db
from main import app
from models.users import User
from services.auth import get_current_user
from services.tax.parameters import seed_default_tax_parameter_sets


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")


def _user() -> User:
    return User(
        id="tax-user",
        username="tax-user",
        password_hash="h",
        full_name="Tax User",
        role="advisor",
        is_active=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


def _client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tax_api.db'}",
        connect_args={"check_same_thread": False},
    )
    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionFactory() as session:
        seed_default_tax_parameter_sets(session)
        session.commit()

    def override_db():
        with SessionFactory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app), engine


def test_tax_jurisdictions_endpoint_lists_ch(tmp_path):
    client, engine = _client(tmp_path)
    try:
        response = client.get("/tax/jurisdictions")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert any(item["country_code"] == "CH" for item in payload)
        ch = next(item for item in payload if item["country_code"] == "CH")
        assert "ZH" in ch["supported_regions"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_tax_estimate_endpoint_returns_schema(tmp_path):
    client, engine = _client(tmp_path)
    try:
        response = client.post(
            "/tax/estimate",
            json={
                "country_code": "CH",
                "region": "ZH",
                "year": 2026,
                "taxable_income_rappen": 12_000_000,
                "taxable_wealth_rappen": 100_000_000,
                "capital_gains_rappen": 20_000_000,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["country_code"] == "CH"
        assert payload["region"] == "ZH"
        assert payload["total_tax_rappen"] == (
            payload["income_tax_rappen"]
            + payload["wealth_tax_rappen"]
            + payload["capital_gains_tax_rappen"]
        )
        assert payload["assumptions"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_tax_estimate_unknown_country_returns_404(tmp_path):
    client, engine = _client(tmp_path)
    try:
        response = client.post(
            "/tax/estimate",
            json={"country_code": "NO", "taxable_income_rappen": 1_000_000},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

