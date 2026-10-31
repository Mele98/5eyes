"""BENCHMARK-ATTRIBUTION-SCORE-001 (Core-Coverage-Audit 2026-10-05): the
Brinson performance-attribution benchmark lookup in
services/advisory_report.py::_build_performance_attribution() compared the
raw 0..100 `RiskAssessment.final_score_x10` directly against
`HouseMatrix.score_from`/`score_to` -- which are on a 1..10 bucket scale in
real production data (confirmed via services/house_matrix_loader.py's
canonical default seed tuples, e.g. (1, 2, "Kapitalschutz", ...) ...
(10, 10, "Aktien", ...)) and via the canonical conversion helper
services/risk_assessment_semantics.py::risk_score_bucket_from_validated_score()
("Map a validated 0..100 score to the 1..10 House-Matrix bucket").

A valid score like 80 therefore almost never found a matching HouseMatrix
row and silently degraded to _performance_attribution_empty() -- while the
sibling consumer _depotcheck_house_matrix_benchmark()
(routers/pdf_reports.py) resolves the *same* score correctly via
services/risk_matrix.py::score_bucket_from_assessment(), which performs
exactly this 0..100 -> 1..10 conversion.

See docs/audits/2026-10-05-core-coverage-benchmark-governance-audit.md
(finding BENCHMARK-ATTRIBUTION-SCORE-001).

Fix: _build_performance_attribution() now converts via the same
score_bucket_from_assessment() helper before querying HouseMatrix, matching
the depotcheck consumer's already-correct behavior.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import CapitalMarketAssumption, HouseMatrix  # noqa: E402

from tests.test_advisory_log_aggregator import (  # noqa: E402
    _seed,
    _seed_ta_within_budget,
    _NOW,
)
from models.profiling import RiskAssessment  # noqa: E402
from tests.risk_fixture_helpers import derive_current_risk_fields  # noqa: E402
from services.risk_assessment_semantics import (  # noqa: E402
    risk_score_bucket_from_validated_score,
)


def _seed_fully_consistent_risk_assessment(s, mandate, advisor):
    """Uses the shared derive_current_risk_fields() helper (same one
    tests/test_advisory_report.py relies on) to produce a RiskAssessment
    whose every derived field (score, profile, capacity/willingness
    breakdown) is genuinely internally consistent -- required because the
    fix now routes through validate_risk_assessment_model_input(), which
    correctly rejects any inconsistency, unlike hand-picking a bare
    final_score_x10/final_profile pair which several unrelated internal
    cross-checks then reject one at a time.

    Returns the real final_score_x10 this produces, so the caller can seed
    a matching HouseMatrix bucket instead of assuming a specific score."""
    aid = str(uuid.uuid4())
    risk_fields = derive_current_risk_fields(
        q_income_points=2,
        q_obligations_points=3,
        q_savings_points=8,
        q_wealth_points=8,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=4,
        q_risk_behavior_points=3,
    )
    s.add(RiskAssessment(
        id=aid, mandate_id=mandate.id, version=1, is_current=1,
        valid_from=_NOW,
        **risk_fields,
        is_overridden=0,
        knowledge_services_json="{}",
        knowledge_instruments_json="{}",
        income_sources_json='["Berufliche Taetigkeit"]',
        assessed_at=_NOW,
        assessed_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    ))
    s.commit()
    return risk_fields["final_score_x10"]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'benchmark_attr_001.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_real_scale_house_matrix_row(s, policy, *, score_bucket: int, profile_name: str):
    """A single HouseMatrix row on the REAL production 1..10 bucket scale
    (mirrors services/house_matrix_loader.py's canonical default tuples,
    e.g. (10, 10, "Aktien", ...)), not the 0..100 raw-score-range convention
    some unrelated test fixtures in this suite use."""
    s.add(HouseMatrix(
        id=str(uuid.uuid4()), policy_id=policy.id,
        score_from=score_bucket, score_to=score_bucket, profile_name=profile_name,
        liq_min_bps=0, liq_target_bps=500, liq_max_bps=1000,
        bonds_min_bps=0, bonds_target_bps=1000, bonds_max_bps=2000,
        equity_min_bps=7000, equity_target_bps=8500, equity_max_bps=9500,
        real_estate_min_bps=0, real_estate_target_bps=500, real_estate_max_bps=1000,
        alt_min_bps=0, alt_target_bps=0, alt_max_bps=1000, equity_minimum_bps=0,
        max_risky_fraction_bps=9500,
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))
    s.commit()


def _seed_current_cma(s, advisor):
    s.add(CapitalMarketAssumption(
        id=str(uuid.uuid4()), assumption_set_name="Standard", version=1,
        valid_from=_NOW[:10], is_current=1,
        bonds_chf_ig_return_bps=150, equity_ch_return_bps=550,
        real_estate_ch_return_bps=300, alternatives_gold_return_bps=200,
        liquidity_return_bps=50,
        source="Test-Fixture", created_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    ))
    s.commit()


def test_performance_attribution_resolves_house_matrix_for_valid_score(session_factory):
    """A real, valid final_score_x10 (derived from a fully self-consistent
    risk fixture, converted to its canonical 1..10 House-Matrix bucket) must
    find the matching HouseMatrix row and produce a real Brinson
    attribution -- not silently degrade to the empty/error result, as it
    did before the fix."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        ta, policy = _seed_ta_within_budget(s, mandate, advisor, risky_bps=8500)
        final_score_x10 = _seed_fully_consistent_risk_assessment(s, mandate, advisor)
        score_bucket = risk_score_bucket_from_validated_score(final_score_x10)
        _seed_real_scale_house_matrix_row(s, policy, score_bucket=score_bucket, profile_name="Wachstum")
        _seed_current_cma(s, advisor)

        from services.advisory_report import _build_performance_attribution
        from models.mandates import Mandate as MandateModel

        reloaded_mandate = s.query(MandateModel).filter(MandateModel.id == mandate.id).one()
        result = _build_performance_attribution(s, reloaded_mandate)

    assert "error" not in result, (
        f"expected a real Brinson attribution for a valid score-{final_score_x10} "
        f"mandate with a matching 1..10-scale HouseMatrix row (bucket "
        f"{score_bucket}), got a degraded result instead: {result}"
    )
    assert result.get("method") == "brinson_fachler_hood_1986"


def test_positive_control_truly_missing_house_matrix_still_degrades_gracefully(session_factory):
    """Positive control: if genuinely NO HouseMatrix row exists for the
    mandate's policy at all, the function must still degrade gracefully
    (not crash) -- the fix must not turn a real absence into an exception."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        ta, policy = _seed_ta_within_budget(s, mandate, advisor, risky_bps=8500)
        # Deliberately no HouseMatrix row at all.
        _seed_fully_consistent_risk_assessment(s, mandate, advisor)

        from services.advisory_report import _build_performance_attribution
        from models.mandates import Mandate as MandateModel

        reloaded_mandate = s.query(MandateModel).filter(MandateModel.id == mandate.id).one()
        result = _build_performance_attribution(s, reloaded_mandate)

    assert "error" in result
