"""FIDLEG Art. 8/9 Ex-ante Kostenausweis — Endpoint-Tests.

Standalone JSON-Endpoint /mandates/{id}/cost-disclosure/ex-ante wrappt
services.cost_disclosure.build_cost_disclosure mit typsicheren Schemas.

Backend-Logik (TER-Aggregation, Service-Fees, Transaktionskosten,
Estimates-Flag) ist in tests/pdf/test_kostenausweis.py separat gedeckt;
hier nur Endpoint-Verhalten + Schema-Compliance.
"""
from __future__ import annotations

import datetime
import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.allocation import OptimizerPolicy, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.review import Product, RecommendationPosition, RecommendationRun
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cost_disclosure.db'}",
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
        id="advisor-cd",
        username="advisor-cd",
        password_hash="h",
        full_name="Test Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
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


def _seed_mandate(
    session_factory, advisor_user, mandate_id: str = "mdt-cd", *, base_currency: str = "CHF",
) -> str:
    with session_factory() as db:
        db.add(advisor_user)
        db.add(Client(
            id="cli-cd", client_number="C-CD", first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id="cli-cd", mandate_number="M-CD",
            mandate_type="Anlageberatung", status="Aktiv", base_currency=base_currency,
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id


def _seed_recommendation_with_ter(
    session_factory,
    advisor_user,
    mandate_id: str,
    *,
    target_amount_rappen: int,
    ter_bps: int,
    fee_assumptions: dict,
) -> str:
    """Erstellt RecommendationRun + Position + Product fuer den Cost-Disclosure-Pfad."""
    with session_factory() as db:
        policy = OptimizerPolicy(
            id="pol-cd",
            policy_name="default",
            is_current=1,
            version=1,
            valid_from=_now(),
            created_by=advisor_user.id,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(policy)
        product = Product(
            id="prd-cd",
            isin="CH0000000001",
            product_name="Demo ETF",
            product_type="ETF",
            asset_class="equities",
            currency="CHF",
            ter_bps=ter_bps,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(product)
        ta = TargetAllocation(
            id="ta-cd",
            mandate_id=mandate_id,
            is_current=1,
            band_equities_min_bps=0, band_equities_max_bps=10000,
            band_bonds_min_bps=0, band_bonds_max_bps=10000,
            band_real_estate_min_bps=0, band_real_estate_max_bps=10000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=10000,
            band_liquidity_min_bps=0, band_liquidity_max_bps=10000,
            policy_id="pol-cd",
            set_by=advisor_user.id,
            set_at=_now(),
            advisory_wealth_at_generation_rappen=target_amount_rappen,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(ta)
        run = RecommendationRun(
            id="run-cd",
            mandate_id=mandate_id,
            client_id="cli-cd",
            target_allocation_id="ta-cd",
            policy_id="pol-cd",
            run_type="initial",
            fee_assumptions_json=json.dumps(fee_assumptions),
            created_by=advisor_user.id,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(run)
        db.add(RecommendationPosition(
            id="pos-cd",
            run_id=run.id,
            product_id=product.id,
            target_weight_bps=10000,
            target_amount_rappen=target_amount_rappen,
            created_at=_now(),
            updated_at=_now(),
        ))
        db.commit()
    return "run-cd"


# ---------------------------------------------------------------------------
# Endpoint-Verhalten
# ---------------------------------------------------------------------------


def test_endpoint_unknown_mandate_404(auth_client):
    resp = auth_client.get("/mandates/does-not-exist/cost-disclosure/ex-ante")
    assert resp.status_code == 404


def test_endpoint_pending_wenn_keine_empfehlung(auth_client, advisor_user, session_factory):
    """Mandat ohne Recommendation -> data_pending=True, valides Schema."""
    mandate_id = _seed_mandate(session_factory, advisor_user)
    resp = auth_client.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_pending"] is True
    assert body["currency"] == "CHF"
    assert body["cost_items"] == []
    assert body["warnings"] != []
    # FIDLEG-Basis ist auch im pending-Fall gefuellt
    assert "FIDLEG" in body["fidleg_basis"]


def test_endpoint_voll_befuellt_bei_recommendation_mit_ter(
    auth_client, advisor_user, session_factory
):
    """1 Mio CHF Wealth, 50 bps TER, 25 bps Beratungsfee -> beide Posten +
    Transaktionskosten erscheinen, Totals sind konsistent."""
    mandate_id = _seed_mandate(session_factory, advisor_user)
    _seed_recommendation_with_ter(
        session_factory, advisor_user, mandate_id,
        target_amount_rappen=1_000_000_00,  # 1 Mio CHF in Rappen
        ter_bps=50,
        fee_assumptions={
            "default_advisory_fee_bps": 25,
            "custody_fee_bps": 10,
            "transaction_cost_bps": 12,
        },
    )
    resp = auth_client.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_pending"] is False
    keys = {item["key"] for item in body["cost_items"]}
    # Service-Fees + TER + Transaktionskosten alle sichtbar
    assert "default_advisory_fee_bps" in keys
    assert "custody_fee_bps" in keys
    assert "product_ter" in keys
    assert "initial_transaction_costs" in keys
    # Annual-Totals > 0 (25 bps + 10 bps + 50 bps TER auf 1 Mio = > 0)
    assert body["totals"]["annual_rappen"] > 0
    # One-time-Total > 0 (12 bps Transaktion)
    assert body["totals"]["one_time_rappen"] > 0
    # Vollstaendigkeit: alle Service-Fees + TER 100% -> is_complete=True
    assert body["is_complete"] is True


# ---------------------------------------------------------------------------
# Mega-Audit (2026-08-04): "currency" war hartcodiert "CHF", unabhaengig von
# mandate.base_currency -- ein EUR-/USD-Mandat zeigte den korrekten Betrag
# mit falscher Waehrungs-Beschriftung im Kostenausweis.
# ---------------------------------------------------------------------------

def test_endpoint_pending_reflects_mandate_base_currency(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate(session_factory, advisor_user, base_currency="EUR")
    resp = auth_client.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert resp.status_code == 200, resp.text
    assert resp.json()["currency"] == "EUR"


def test_endpoint_voll_befuellt_reflects_mandate_base_currency(
    auth_client, advisor_user, session_factory
):
    mandate_id = _seed_mandate(session_factory, advisor_user, base_currency="EUR")
    _seed_recommendation_with_ter(
        session_factory, advisor_user, mandate_id,
        target_amount_rappen=1_000_000_00,
        ter_bps=50,
        fee_assumptions={"default_advisory_fee_bps": 25},
    )
    resp = auth_client.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert resp.status_code == 200, resp.text
    assert resp.json()["currency"] == "EUR"


def test_endpoint_ter_unvollstaendig_meldet_warnung(
    auth_client, advisor_user, session_factory
):
    """Wenn ein Teil der TER fehlt, ist is_complete=False und warnings nennt das."""
    mandate_id = _seed_mandate(session_factory, advisor_user)
    # Produkt ohne TER -> Coverage < 100%
    with session_factory() as db:
        advisor_user.id = "advisor-cd"
        db.add(advisor_user)
        db.add(Client(
            id="cli-cd2", client_number="C-CD2", first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        ))
        m2 = Mandate(
            id="mdt-cd2", client_id="cli-cd2", mandate_number="M-CD2",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        )
        db.add(m2)
        policy = OptimizerPolicy(
            id="pol-cd2", policy_name="d", is_current=1, version=1,
            valid_from=_now(), created_by=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        )
        db.add(policy)
        prd_known = Product(
            id="prd-cd2a", product_name="With TER", product_type="ETF",
            asset_class="equities", currency="CHF", ter_bps=40,
            created_at=_now(), updated_at=_now(),
        )
        prd_unknown = Product(
            id="prd-cd2b", product_name="No TER", product_type="ETF",
            asset_class="bonds", currency="CHF", ter_bps=None,
            created_at=_now(), updated_at=_now(),
        )
        db.add(prd_known)
        db.add(prd_unknown)
        ta = TargetAllocation(
            id="ta-cd2", mandate_id="mdt-cd2", is_current=1,
            band_equities_min_bps=0, band_equities_max_bps=10000,
            band_bonds_min_bps=0, band_bonds_max_bps=10000,
            band_real_estate_min_bps=0, band_real_estate_max_bps=10000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=10000,
            band_liquidity_min_bps=0, band_liquidity_max_bps=10000,
            policy_id="pol-cd2",
            set_by=advisor_user.id,
            set_at=_now(),
            advisory_wealth_at_generation_rappen=1_000_000_00,
            created_at=_now(), updated_at=_now(),
        )
        db.add(ta)
        run = RecommendationRun(
            id="run-cd2", mandate_id="mdt-cd2", client_id="cli-cd2",
            target_allocation_id="ta-cd2", policy_id="pol-cd2",
            run_type="initial",
            fee_assumptions_json=json.dumps({"default_advisory_fee_bps": 30}),
            created_by=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        )
        db.add(run)
        db.add(RecommendationPosition(
            id="pos-cd2a", run_id=run.id, product_id="prd-cd2a",
            target_weight_bps=5000, target_amount_rappen=500_000_00,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(RecommendationPosition(
            id="pos-cd2b", run_id=run.id, product_id="prd-cd2b",
            target_weight_bps=5000, target_amount_rappen=500_000_00,
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()

    resp = auth_client.get("/mandates/mdt-cd2/cost-disclosure/ex-ante")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_complete"] is False
    # Coverage < 100% (nur die Haelfte hat TER)
    assert 0 < body["product_cost_coverage_bps"] < 10000
    # Eine Warnung muss die TER-Luecke explizit nennen
    assert any("TER" in w for w in body["warnings"])


def test_endpoint_in_route_table_registriert():
    from main import app
    paths = {getattr(r, "path", None) for r in app.routes if hasattr(r, "methods")}
    assert "/mandates/{mandate_id}/cost-disclosure/ex-ante" in paths
