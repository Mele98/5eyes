"""SHADOW-ZERO-RISK-BUDGET-FALSY-001 (Kontrollrunde 2026-09-25).

services.shadow_comparison.build_shadow_comparison_payload() behandelte
risk_budget_bps==0 bisher identisch zu "kein Budget bekannt" (Python-
Truthiness auf einem `int`). Ein HouseMatrix-Tier darf laut Schema
(max_risky_fraction_bps: ge=0) aber legitim 0 bps Risikobudget haben --
ein Mandat mit echtem 0%-Risikobudget UND einer korrekt 0%-risky
HouseMatrix-Allokation zeigte dadurch faelschlich "Budget-Konformitaet:
Nein" in der Methodology-Sektion, obwohl 0<=0 tatsaechlich konform ist.
"""
from __future__ import annotations

import datetime
import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
import models.tenant  # noqa: F401
import models.review  # noqa: F401
import models.profiling  # noqa: F401
import models.wealth  # noqa: F401
import models.snapshots  # noqa: F401
from models.allocation import TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from services.shadow_comparison import build_shadow_comparison_payload


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


BAND_KW = dict(
    band_equities_min_bps=0, band_equities_max_bps=10000,
    band_bonds_min_bps=0, band_bonds_max_bps=10000,
    band_real_estate_min_bps=0, band_real_estate_max_bps=10000,
    band_alternatives_min_bps=0, band_alternatives_max_bps=10000,
    band_liquidity_min_bps=0, band_liquidity_max_bps=10000,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'shadow_zero_budget.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_shadow_ta(
    session_factory, *, shadow_payload: dict, risk_budget_bps_at_generation=None,
    risky_fraction_bps_at_generation=0,
):
    mandate_id = f"m-{uuid.uuid4().hex[:8]}"
    with session_factory() as s:
        s.add(User(
            id="advisor-szb", username="advisor-szb", password_hash="h",
            full_name="A", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.add(Client(
            id=f"c-{mandate_id}", client_number=f"C-{mandate_id}",
            first_name="A", last_name="B", country_of_residence="CH",
            language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="advisor-szb",
            created_at=_now(), updated_at=_now(),
        ))
        s.add(Mandate(
            id=mandate_id, client_id=f"c-{mandate_id}", mandate_number=f"MN-{mandate_id}",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-01-01",
            created_at=_now(), updated_at=_now(),
        ))
        s.add(TargetAllocation(
            id=f"ta-{mandate_id}", mandate_id=mandate_id, is_current=1,
            target_equities_bps=0, target_bonds_bps=10000, target_real_estate_bps=0,
            target_alternatives_bps=0, target_liquidity_bps=0,
            based_on_assessment_id="x", capital_market_assumptions_id="y",
            policy_id="p1", set_by="advisor-szb", set_at=_now(),
            risky_fraction_bps_at_generation=risky_fraction_bps_at_generation,
            risk_budget_bps_at_generation=risk_budget_bps_at_generation,
            shadow_optimization_json=json.dumps(shadow_payload),
            created_at=_now(), updated_at=_now(),
            **BAND_KW,
        ))
        s.commit()
    return mandate_id


def test_zero_risk_budget_with_zero_active_risky_is_compliant(session_factory):
    """Kern-Repro: echtes 0-bps-Risikobudget, house_matrix-Allokation haelt
    korrekt 0% risky. Muss budget_compliance.house_matrix == True zeigen
    (0 <= 0), nicht faelschlich False."""
    mandate_id = _seed_mandate_with_shadow_ta(
        session_factory,
        shadow_payload={
            "engine": "stochastic",
            "allocation_bps": {"equities": 0, "bonds": 10000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
            "risky_fraction_bps": 0,
            "risk_budget_bps": 0,
        },
        risk_budget_bps_at_generation=0,
        risky_fraction_bps_at_generation=0,
    )
    with session_factory() as s:
        result = build_shadow_comparison_payload(s, mandate_id)

    assert result["risk_budget_bps"] == 0
    # Vor dem Fix: False (risk_budget=0 wurde als "kein Budget" behandelt).
    assert result["budget_compliance"]["house_matrix"] is True
    assert result["budget_compliance"]["stochastic"] is True


def test_zero_risk_budget_with_nonzero_active_risky_is_not_compliant(session_factory):
    """Gegenprobe: echtes 0-bps-Budget, aber die Allokation haelt TROTZDEM
    risky Assets -> muss weiterhin korrekt als nicht konform gemeldet
    werden (die Logik darf nicht einfach immer True liefern)."""
    mandate_id = _seed_mandate_with_shadow_ta(
        session_factory,
        shadow_payload={
            "engine": "stochastic",
            "allocation_bps": {"equities": 2000, "bonds": 8000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
            "risky_fraction_bps": 2000,
            "risk_budget_bps": 0,
        },
        risk_budget_bps_at_generation=0,
        risky_fraction_bps_at_generation=2000,
    )
    with session_factory() as s:
        result = build_shadow_comparison_payload(s, mandate_id)

    assert result["risk_budget_bps"] == 0
    assert result["budget_compliance"]["house_matrix"] is False
    assert result["budget_compliance"]["stochastic"] is False


def test_missing_risk_budget_everywhere_stays_not_compliant(session_factory):
    """Gegenprobe: WEDER Shadow-Payload NOCH TargetAllocation kennen je ein
    Risikobudget (echtes "unbekannt") -> bleibt korrekt nicht konform,
    identisch zum bisherigen Verhalten."""
    mandate_id = _seed_mandate_with_shadow_ta(
        session_factory,
        shadow_payload={
            "engine": "stochastic",
            "allocation_bps": {"equities": 2000, "bonds": 8000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
            "risky_fraction_bps": 2000,
        },
        risk_budget_bps_at_generation=None,
        risky_fraction_bps_at_generation=2000,
    )
    with session_factory() as s:
        result = build_shadow_comparison_payload(s, mandate_id)

    assert result["risk_budget_bps"] == 0
    assert result["budget_compliance"]["house_matrix"] is False
    assert result["budget_compliance"]["stochastic"] is False
