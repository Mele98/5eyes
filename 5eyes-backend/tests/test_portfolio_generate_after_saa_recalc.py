"""Regression (U-P19 Debug): Portfolio-Generierung nach SAA-Neuberechnung.

Schreibt das verifizierte Verhalten fest, nachdem "Portfolio generiert nicht
mehr" untersucht wurde:

- Das U-P18 Stale-Run-Blocking (current/payload -> 409, wenn kein Run zur
  aktuellen Soll-Allokation passt) ist KORREKT und gewollt.
- Der Regenerate-Pfad (wie ihn das Frontend nach dem 409 ausführt) generiert
  mit Default-Präferenzen sauber ein Portfolio.
- Die bewussten Präferenz-Hard-Blocks (alle Alternativen / alle Bonds aus)
  werfen weiterhin eine KLARE ValueError -> 409 (kein stilles Verpuffen).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import RecommendationRun
from models.users import User
from services.foundation_example import FOUNDATION_MANDATE_NUMBER, upsert_foundation_example_case
from services.portfolio_engine import (
    _build_sub_allocations,
    generate_recommendation_run,
    generate_target_allocation,
)
from routers.review import get_current_recommendation_payload


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'po_recalc.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _advisor() -> User:
    return User(id="advisor-1", username="advisor", password_hash="h",
                full_name="Advisor", role="advisor", is_active=1,
                created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z")


def _seed_foundation(s) -> Mandate:
    adv = _advisor()
    s.add(User(id=adv.id, username=adv.username, password_hash=adv.password_hash,
               full_name=adv.full_name, role=adv.role, is_active=adv.is_active,
               created_at=adv.created_at, updated_at=adv.updated_at))
    s.commit()
    upsert_foundation_example_case(s, adv)
    s.commit()
    return s.query(Mandate).filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER).one()


def test_current_payload_blocks_stale_run_then_regenerate_succeeds(session_factory):
    """Nach SAA-Recalc liefert current/payload 409 (stale), Regenerate generiert."""
    with session_factory() as s:
        mandate = _seed_foundation(s)
        adv = s.query(User).filter(User.id == "advisor-1").one()

        # Vor Recalc: Foundation-Run matcht aktuelle TA -> payload OK
        before = get_current_recommendation_payload(mandate.id, db=s, current_user=adv)
        assert before["run"] is not None

        # SAA neu berechnen -> neue is_current TA, alte Runs werden stale
        gen = generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)
        s.commit()
        ta2 = gen["target_allocation"]

        # current/payload muss jetzt mit 409 blockieren (U-P18 Stale-Schutz)
        with pytest.raises(HTTPException) as exc:
            get_current_recommendation_payload(mandate.id, db=s, current_user=adv)
        assert exc.value.status_code == 409

        # Regenerate (wie das Frontend nach dem 409) generiert sauber
        result = generate_recommendation_run(
            db=s, mandate=mandate, user_id=adv.id, preferences=None,
            target_allocation_id=ta2.id, run_type="Optimizer", depot_bank="UBS AG Zürich")
        s.commit()
        assert len(result.get("positions") or []) > 0
        assert str(result["run"].target_allocation_id) == str(ta2.id)

        # Danach matcht der frische Run die aktuelle TA -> payload wieder OK
        after = get_current_recommendation_payload(mandate.id, db=s, current_user=adv)
        assert after["run"].id == result["run"].id


def test_default_ui_preferences_generate_a_portfolio(session_factory):
    """Frontend-Default-Präferenzen (collectAllocationPreferencesFromUI) generieren."""
    fe_default = {"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {},
                  "assetClasses": {"equitiesLargeCap": True, "bondsInvestmentGrade": True,
                                   "realestateFunds": True, "altsGold": True}}
    with session_factory() as s:
        mandate = _seed_foundation(s)
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id, TargetAllocation.is_current == 1).one()
        result = generate_recommendation_run(
            db=s, mandate=mandate, user_id="advisor-1", preferences=fe_default,
            target_allocation_id=ta.id, run_type="Optimizer", depot_bank="UBS AG Zürich")
        assert len(result.get("positions") or []) > 0


def test_low_risk_override_does_not_empty_existing_saa_portfolio(session_factory):
    """Produkt-Suitability darf eine vorhandene SAA nicht komplett leer filtern."""
    with session_factory() as s:
        mandate = _seed_foundation(s)
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
        ).one()
        assessment = s.query(RiskAssessment).filter(
            RiskAssessment.mandate_id == mandate.id,
            RiskAssessment.is_current == 1,
        ).one()
        assessment.is_overridden = 1
        assessment.override_score_x10 = 20
        assessment.override_profile = "Kapitalschutz"
        assessment.override_reason = "Kundenseitig konservativer dokumentiert"
        s.commit()

        result = generate_recommendation_run(
            db=s,
            mandate=mandate,
            user_id="advisor-1",
            preferences={
                "policy": {"esg": "best_in_class", "homeBias": "ch_focus", "universe": "standard"},
                "tilts": {"tobacco": "overweight", "alcohol": "overweight", "gaming": "overweight"},
                "product": {"fundsOnly": False, "listedOnly": False, "noDerivatives": False, "noLeverage": False, "noStructured": False},
                "limits": {},
                "geo": {"chfOnly": False, "hedgingRequired": False, "noUsd": False},
                "assetClasses": {"altsGold": True, "equitiesLargeCap": True, "realestateFunds": True},
            },
            target_allocation_id=ta.id,
            run_type="Optimizer",
            depot_bank="UBS AG ZÃ¼rich",
        )

    assert len(result.get("positions") or []) > 0
    assert any("Suitability" in warning for warning in result.get("warnings") or [])


def test_preference_hard_blocks_raise_clear_errors():
    """Die bewussten Hard-Blocks (Handoff 2026-05-18) werfen klare Meldungen."""
    targets = {"equities": 6000, "bonds": 3000, "real_estate": 0,
               "alternatives": 500, "liquidity": 500}
    # Alle Alternativen aus -> klarer Fehler (gewollt, test-festgeschrieben)
    with pytest.raises(ValueError, match="Alternativen Anlagen"):
        _build_sub_allocations(targets, {"assetClasses": {
            "altsGold": False, "altsLiquidAlts": False, "altsHedge": False,
            "altsPe": False, "altsCrypto": False}})
    # Alle Bond-Segmente aus -> klarer Fehler
    with pytest.raises(ValueError, match="Obligationen-Auswahl"):
        _build_sub_allocations(targets, {"assetClasses": {
            "bondsInvestmentGrade": False, "bondsHighYield": False, "bondsEmerging": False}})
