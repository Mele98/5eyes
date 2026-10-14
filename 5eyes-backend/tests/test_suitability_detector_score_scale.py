"""SUITABILITY-DETECTOR-SCALE-001: HouseMatrix-Cap-Check in
detect_suitability_mismatches muss den 1..10-Score-Bucket verwenden.

HouseMatrix.score_from/score_to liegen in Produktion auf der 1..10-Bucket-
Skala (Seeding via ensure_runtime_reference_data). Der Detektor verglich den
rohen 0..100-score_x10 dagegen:
- Score 11..100 fand keine Zeile -> Cap-Warnung feuerte nie (fail-open);
- Score 10 (Kapitalschutz) traf die Zeile (10,10) "Aktien" mit 100 % Cap;
- Score 0 (Kapitalschutz, kurzer Horizont) wurde komplett uebersprungen.

Diese Tests nutzen den echten Seeding-Pfad der App, keine handgebauten
HouseMatrix-Zeilen, und selbstkonsistente Risikoprofile (aus den
Fragebogen-Punkten hergeleitet), damit die Bucket-Abbildung ueber
services.risk_matrix.score_bucket_from_assessment() wie in Produktion laeuft.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = BACKEND_ROOT / "tests"
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.allocation import HouseMatrix, TargetAllocation  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from risk_fixture_helpers import derive_current_risk_fields  # noqa: E402
from services.advisory_log_service import detect_suitability_mismatches  # noqa: E402
from services.portfolio_engine import ensure_runtime_reference_data  # noqa: E402
from test_advisory_log_aggregator import (  # noqa: E402,F401
    _NOW,
    _seed,
    session_factory,
)

# Fragebogen-Punkte -> hergeleiteter final_score_x10 (risk_scoring.compute_scores)
_ANSWERS_BY_SCORE = {
    0: dict(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=0,
            investment_horizon_label="Bis 2 Jahre",
            q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=1),
    10: dict(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=0,
             investment_horizon_label="4 bis 5 Jahre",
             q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=1),
    30: dict(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=0,
             investment_horizon_label="Mehr als 12 Jahre",
             q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=3),
    75: dict(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=12,
             investment_horizon_label="Mehr als 12 Jahre",
             q_investment_goal_points=2, q_risk_preference_points=4, q_risk_behavior_points=4),
}

_REASON = (
    "Kunde hat ausdruecklich konservativere Anlage gewuenscht wegen "
    "geplantem Liegenschaftskauf in drei Jahren"
)


def _seed_mandate_with_production_matrix(s, *, risky_bps: int):
    advisor, mandate = _seed(s)
    policy, _cma = ensure_runtime_reference_data(s, advisor.id)
    s.flush()
    ta = TargetAllocation(
        id=str(uuid.uuid4()), mandate_id=mandate.id, policy_id=policy.id,
        version=1, is_current=1,
        target_equities_bps=3500, target_bonds_bps=5000,
        target_real_estate_bps=1000, target_alternatives_bps=300,
        target_liquidity_bps=200,
        band_equities_min_bps=3000, band_equities_max_bps=4000,
        band_bonds_min_bps=4000, band_bonds_max_bps=6000,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=0, band_alternatives_max_bps=800,
        band_liquidity_min_bps=0, band_liquidity_max_bps=500,
        risky_fraction_bps=risky_bps,
        # bewusst hoch: der Generate-Zeitpunkt-Check soll hier nicht feuern,
        # nur der HouseMatrix-Cap-Check ist Gegenstand dieser Tests.
        risk_budget_bps_at_generation=10000,
        set_by=advisor.id, set_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(ta)
    s.commit()
    return advisor, mandate, policy


def _seed_valid_ra(s, mandate, advisor, *, final_score_x10: int,
                   override_score_x10: int | None = None, override_profile: str | None = None):
    fields = derive_current_risk_fields(**_ANSWERS_BY_SCORE[final_score_x10])
    assert fields["final_score_x10"] == final_score_x10, fields
    s.add(RiskAssessment(
        id=str(uuid.uuid4()), mandate_id=mandate.id, version=1, is_current=1,
        valid_from=_NOW[:10],
        **fields,
        is_overridden=1 if override_score_x10 is not None else 0,
        override_score_x10=override_score_x10,
        override_profile=override_profile,
        override_reason=_REASON if override_score_x10 is not None else None,
        assessed_at=_NOW, assessed_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    ))
    s.commit()


def _cap_warnings(warnings):
    return [w for w in warnings if "HouseMatrix-Cap" in w]


def test_production_house_matrix_is_on_bucket_scale(session_factory):
    """Praemisse des Befunds: Produktion seedet 1..10, nicht 0..100."""
    with session_factory() as s:
        _advisor, _mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=4000)
        rows = s.query(HouseMatrix).filter(HouseMatrix.policy_id == policy.id).all()
    assert rows
    assert min(r.score_from for r in rows) == 1
    assert max(r.score_to for r in rows) == 10


@pytest.mark.parametrize(
    "score_x10, risky_bps, expected_profile, expected_cap",
    [
        (75, 9000, "Wachstumsorientiert", "80.0 %"),  # vorher: keine Zeile -> stumm
        (30, 6000, "Defensiv", "45.0 %"),             # vorher: keine Zeile -> stumm
        (10, 6000, "Kapitalschutz", "30.0 %"),        # vorher: Zeile "Aktien" 100 %
        (0, 6000, "Kapitalschutz", "30.0 %"),         # vorher: komplett uebersprungen
    ],
)
def test_cap_violation_detected_with_production_matrix(
    session_factory, score_x10, risky_bps, expected_profile, expected_cap,
):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=risky_bps)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=score_x10)
        warnings = detect_suitability_mismatches(s, mandate)
    cap = _cap_warnings(warnings)
    assert len(cap) == 1, warnings
    assert f"HouseMatrix-Cap {expected_cap} ({expected_profile})" in cap[0], cap


@pytest.mark.parametrize(
    "score_x10, risky_bps",
    [(75, 8000), (75, 7000), (30, 4500), (10, 3000), (0, 2000)],
)
def test_positive_control_within_cap_no_warning(session_factory, score_x10, risky_bps):
    """Positivkontrolle: Allokation auf/unter dem Cap -> keine Cap-Warnung.
    Schuetzt davor, dass der Fix einfach immer warnt."""
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=risky_bps)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=score_x10)
        warnings = detect_suitability_mismatches(s, mandate)
    assert _cap_warnings(warnings) == [], warnings
    assert warnings == [], warnings


def test_downward_override_uses_override_bucket(session_factory):
    """Override 75 -> 35 (Defensiv, Cap 45 %), 60 % Risiko-Anteil -> Warnung."""
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=6000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75,
                       override_score_x10=35, override_profile="Defensiv")
        warnings = detect_suitability_mismatches(s, mandate)
    cap = _cap_warnings(warnings)
    assert len(cap) == 1 and "45.0 % (Defensiv)" in cap[0], warnings


def test_inconsistent_risk_profile_fails_closed(session_factory):
    """Ein nicht herleitbares Risikoprofil darf den Cap-Check nicht still
    ueberspringen: der Detektor meldet, dass die Pruefung nicht moeglich ist."""
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=9000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate.id).one()
        ra.final_profile = "Ausgewogen"  # passt nicht zu final_score_x10=75
        s.commit()
        warnings = detect_suitability_mismatches(s, mandate)
    cap = _cap_warnings(warnings)
    assert len(cap) == 1 and "nicht pruefbar" in cap[0], warnings
