"""Schema-Validator-Hardening (Audit-Cluster SCHEMA-01..06 + RT-1).

Reine Pydantic-/Service-Unit-Tests, keine DB nötig. Stellt sicher dass:
- SCHEMA-01: RiskAssessmentCreate-Ranges via raise (auch unter `python -O`).
- SCHEMA-02: StrategySnapshotCreate bps-Bounds + Summen-Check via raise.
- SCHEMA-04: TargetAllocationCreate bps-Felder auf [0,10000] begrenzt.
- SCHEMA-05: Client/Mandate-Update nutzen dieselben Literal-Enums wie Create.
- SCHEMA-06: Mandate-Jahre plausibilisiert + chronologische Reihenfolge.
- RT-1:      Unbekanntes Horizont-Label wird hart abgewiesen.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.profiling import RiskAssessmentCreate
from schemas.snapshots import StrategySnapshotCreate
from schemas.allocation import TargetAllocationCreate
from schemas.clients import ClientUpdate
from schemas.mandates import MandateUpdate
from services.risk_scoring import compute_scores


def _valid_risk_kwargs(**over):
    base = dict(
        q_income_points=2,
        q_obligations_points=2,
        q_savings_points=6,
        q_wealth_points=6,
        investment_horizon_label="4 bis 5 Jahre",
        investment_horizon_years=5,
        q_investment_goal_points=2,
        q_risk_preference_points=2,
        q_risk_behavior_points=2,
    )
    base.update(over)
    return base


# ── SCHEMA-01 ────────────────────────────────────────────────────────────────

def test_schema01_valid_risk_assessment_accepts():
    RiskAssessmentCreate(**_valid_risk_kwargs())


@pytest.mark.parametrize("field,bad", [
    ("q_income_points", 5),
    ("q_obligations_points", -1),
    ("q_savings_points", 13),
    ("q_wealth_points", 99),
    ("q_investment_goal_points", 0),
    ("q_risk_preference_points", 5),
    ("q_risk_behavior_points", 0),
])
def test_schema01_out_of_range_points_rejected(field, bad):
    with pytest.raises(ValidationError):
        RiskAssessmentCreate(**_valid_risk_kwargs(**{field: bad}))


def test_schema01_uses_raise_not_assert():
    """Validator muss unter `python -O` (assert gestrippt) weiterhin greifen."""
    import schemas.profiling as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    fn = src.split("def validate_points")[1].split("def ")[0]
    # Kommentare entfernen, sonst triggert das Wort "assert" im Erklär-Kommentar.
    code_lines = [ln.split("#", 1)[0] for ln in fn.splitlines()]
    code = "\n".join(code_lines)
    assert "assert " not in code, "validate_points darf kein assert-Statement verwenden"
    assert "raise ValueError" in code


# ── SCHEMA-02 ────────────────────────────────────────────────────────────────

def _snapshot_kwargs(**over):
    base = dict(
        snapshot_date="2026-06-27",
        advisory_assets_rappen=10_000_000,
        risk_profile_score=50,
        risk_profile_label="Ausgewogen",
        soll_equities_bps=4000,
        soll_bonds_bps=3000,
        soll_real_estate_bps=1000,
        soll_liquidity_bps=1000,
        soll_alternatives_bps=1000,
    )
    base.update(over)
    return base


def test_schema02_balanced_snapshot_accepts():
    StrategySnapshotCreate(**_snapshot_kwargs())


def test_schema02_sum_off_rejected():
    with pytest.raises(ValidationError):
        StrategySnapshotCreate(**_snapshot_kwargs(soll_equities_bps=8000))


def test_schema02_negative_bps_rejected():
    with pytest.raises(ValidationError):
        StrategySnapshotCreate(**_snapshot_kwargs(soll_equities_bps=-100))


def test_schema02_over_max_bps_rejected():
    with pytest.raises(ValidationError):
        StrategySnapshotCreate(**_snapshot_kwargs(soll_equities_bps=10001))


# ── SCHEMA-04 ────────────────────────────────────────────────────────────────

def _alloc_kwargs(**over):
    base = dict(
        target_equities_bps=4000,
        target_bonds_bps=3000,
        target_real_estate_bps=1000,
        target_alternatives_bps=1000,
        target_liquidity_bps=1000,
        band_equities_min_bps=3000,
        band_equities_max_bps=5000,
        band_bonds_min_bps=2000,
        band_bonds_max_bps=4000,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=2000,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=2000,
        band_liquidity_min_bps=0,
        band_liquidity_max_bps=2000,
        policy_id="policy-1",
    )
    base.update(over)
    return base


def test_schema04_valid_allocation_accepts():
    TargetAllocationCreate(**_alloc_kwargs())


def test_schema04_negative_target_rejected():
    with pytest.raises(ValidationError):
        TargetAllocationCreate(**_alloc_kwargs(target_equities_bps=-1))


def test_schema04_over_max_band_rejected():
    with pytest.raises(ValidationError):
        TargetAllocationCreate(**_alloc_kwargs(band_equities_max_bps=10001))


def test_schema04_risky_fraction_bounds():
    TargetAllocationCreate(**_alloc_kwargs(risky_fraction_bps=5000))
    with pytest.raises(ValidationError):
        TargetAllocationCreate(**_alloc_kwargs(risky_fraction_bps=20000))


# ── SCHEMA-05 ────────────────────────────────────────────────────────────────

def test_schema05_client_update_rejects_bad_enum():
    ClientUpdate(salutation="Herr", language="FR", household_type="Paar")
    with pytest.raises(ValidationError):
        ClientUpdate(salutation="Mister")
    with pytest.raises(ValidationError):
        ClientUpdate(language="ES")
    with pytest.raises(ValidationError):
        ClientUpdate(client_classification="VIP")


def test_schema05_mandate_update_rejects_bad_enum():
    MandateUpdate(mandate_type="Anlageberatung", advisory_language="IT")
    with pytest.raises(ValidationError):
        MandateUpdate(mandate_type="Hausverwaltung")
    with pytest.raises(ValidationError):
        MandateUpdate(advisory_language="ES")


# ── SCHEMA-06 ────────────────────────────────────────────────────────────────

def test_schema06_year_bounds():
    with pytest.raises(ValidationError):
        MandateUpdate(client_birth_year=1800)
    with pytest.raises(ValidationError):
        MandateUpdate(retirement_year=3000)


def test_schema06_year_order():
    MandateUpdate(client_birth_year=1980, retirement_year=2045, life_expectancy_year=2070)
    with pytest.raises(ValidationError):
        MandateUpdate(client_birth_year=1980, retirement_year=1975)
    with pytest.raises(ValidationError):
        MandateUpdate(retirement_year=2045, life_expectancy_year=2040)
    with pytest.raises(ValidationError):
        MandateUpdate(client_birth_year=1980, life_expectancy_year=1979)


def test_schema06_partial_update_no_false_positive():
    # Nur ein Jahr gesetzt -> kein Reihenfolge-Check.
    MandateUpdate(retirement_year=2045)
    MandateUpdate(client_birth_year=1980)


# ── RT-1 ─────────────────────────────────────────────────────────────────────

def test_rt1_unknown_horizon_label_rejected():
    with pytest.raises(ValueError):
        compute_scores(
            q_income_points=2, q_obligations_points=2,
            q_savings_points=6, q_wealth_points=6,
            investment_horizon_label="irgendwas Falsches",
            q_investment_goal_points=2, q_risk_preference_points=2,
            q_risk_behavior_points=2,
        )


def test_rt1_known_horizon_label_accepted():
    res = compute_scores(
        q_income_points=2, q_obligations_points=2,
        q_savings_points=6, q_wealth_points=6,
        investment_horizon_label="10 Jahre und mehr",  # legacy -> canonical
        q_investment_goal_points=2, q_risk_preference_points=2,
        q_risk_behavior_points=2,
    )
    assert res is not None
