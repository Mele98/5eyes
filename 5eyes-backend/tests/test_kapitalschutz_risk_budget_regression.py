"""TEMP empirischer Repro: crasht generate_target_allocation fuer Kapitalschutz?

Befund #1 (2026-06-11): Bonds-Bucket-Risky-Fraction = ungewichteter Mittelwert
(2000+2500+5000+4000)/4 = 3375 bps > Kapitalschutz-Cap 3000. Behauptung: Score-1-2
crasht mit uncaught ValueError.

Nutzt den bestehenden Integ-Seed und setzt den Risk-Score auf Kapitalschutz (10) um.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: F401
import models.client_login  # noqa: F401
import models.protocol_bausteine  # noqa: F401
configure_mappers()

from models.mandates import Mandate
from models.profiling import RiskAssessment
from services.portfolio_engine import generate_target_allocation
from test_optimizer_integration import _seed_realistic_mandate


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'kaprepro.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.xfail(
    reason="Validierung 2026-06-11 Befund #1 (KRITISCH, empirisch bestaetigt): "
    "Bonds-Bucket-Risky-Fraction = ungewichteter BB-Mittel (2000+2500+5000+4000)/4 "
    "= 3375 bps > Kapitalschutz-Cap 3000 -> generate_target_allocation crasht mit "
    "RiskBudgetExceeded am ungefangenen assert_risk_budget_ok (portfolio_engine.py:5824). "
    "Fix: sub-allocation-gewichtete Risky-Fraction (constraints.py:189-224) ODER Cap-Review "
    "ODER konservativer graceful Fallback statt hartem Crash. Siehe "
    "docs/audits/2026-06-11-engine-validation-findings.md. XPASS = Bug behoben.",
    strict=False,
    raises=Exception,
)
def test_kapitalschutz_generation_does_not_crash(session_factory):
    advisor_id, cid, mid, aid = _seed_realistic_mandate(session_factory, suffix="kap")
    # Risk-Score auf KAPITALSCHUTZ (Score-Bucket 1) umsetzen.
    with session_factory() as s:
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).first()
        ra.final_score_x10 = 10
        ra.final_profile = "Sicherheit"
        ra.risk_capacity_score_x10 = 10
        ra.risk_capacity_profile = "Sicherheit"
        ra.risk_willingness_score_x10 = 10
        ra.risk_willingness_profile = "Sicherheit"
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        ta = result["target_allocation"]
        print("KAPITALSCHUTZ-ALLOKATION OK:",
              {k: getattr(ta, k, None) for k in
               ("target_equities_bps", "target_bonds_bps", "target_real_estate_bps",
                "target_alternatives_bps", "target_liquidity_bps")})
