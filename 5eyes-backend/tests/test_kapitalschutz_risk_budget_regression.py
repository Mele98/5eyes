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


@pytest.mark.parametrize("score_x10,profile", [
    (10, "Sicherheit"),   # Kapitalschutz (Score-Bucket 1) — crashte frueher (#AA-1)
    (35, "Defensiv"),     # Defensiv (Score 3-4) — spurious Fallback (#AA-3)
    (55, "Ausgewogen"),   # Ausgewogen (Score 5-6) — spurious Fallback (#AA-3)
])
def test_low_risk_profiles_generate_without_crash(session_factory, score_x10, profile):
    """Validierung 2026-06-11 Befund #AA-1/#AA-3 (GEFIXT): konservative Profile crashten
    frueher mit RiskBudgetExceeded (ungewichtetes Bonds-BB-Risky-Mittel 3375 > Cap), weil
    der finale assert_risk_budget_ok ungefangen war. Fix: (1) sub-allocation-gewichtetes
    Risky-Mass, (2) _enforce_risk_budget allow_best_effort, (3) graceful Fallback +
    Compliance-Warnung. Erwartung: KEIN Crash, valide Allokation (Summe 10000 bps)."""
    advisor_id, cid, mid, aid = _seed_realistic_mandate(session_factory, suffix=f"lr{score_x10}")
    with session_factory() as s:
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).first()
        ra.final_score_x10 = score_x10
        ra.final_profile = profile
        ra.risk_capacity_score_x10 = score_x10
        ra.risk_capacity_profile = profile
        ra.risk_willingness_score_x10 = score_x10
        ra.risk_willingness_profile = profile
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        # Darf NICHT crashen (frueher: RiskBudgetExceeded).
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        ta = result["target_allocation"]
        buckets = {k: int(getattr(ta, k, 0) or 0) for k in
                   ("target_equities_bps", "target_bonds_bps", "target_real_estate_bps",
                    "target_alternatives_bps", "target_liquidity_bps")}
        assert sum(buckets.values()) == 10000, (score_x10, buckets)
        if score_x10 == 10:  # Kapitalschutz: konservativ (niedrige Aktien, Schwerpunkt Obli)
            assert buckets["target_equities_bps"] <= 1500, buckets
            assert buckets["target_bonds_bps"] >= 6000, buckets
        if score_x10 in (35, 55):
            # #AA-3 (GELOEST durch #AA-1-Fix): mit dem sub-allocation-gewichteten
            # Risky-Mass laufen Defensiv/Ausgewogen NICHT mehr in den spurious
            # WARN_FALLBACK (Mid-Reset). Erwartung: keine Fallback-Warnung.
            warnings = result.get("warnings") or []
            assert not any("fallback" in str(w).lower() for w in warnings), (score_x10, warnings)
