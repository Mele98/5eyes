"""RETIREMENT-ALLOCATION-BASIS-001 (round 46 red test).

Audit claim (verified against code before writing this test): the
Max-Pension-Spending endpoint

    POST /mandates/{mandate_id}/goals/calculate-max-pension-spending
    -> routers/wealth.py::calculate_max_pension_spending()

computes the expected-return / expected-volatility basis for its published
retirement-spending annuity purely from

    targets, _, _ = _baseline_target_bands(house_matrix, policy)

(services/portfolio_engine_house_matrix.py) -- i.e. the RAW, unconstrained
house-matrix target bands for the client's risk bucket. It never loads the
mandate's actual, verified-current ``TargetAllocation`` row (the strategy
that was actually approved for this client, after floors/caps/overrides were
applied and which may legitimately diverge from the raw house-matrix
baseline -- e.g. an equity floor pushing equities up while real estate /
alternatives get capped down).

This means: if an advisor has an approved, current strategy of, say,
7000/1800/600/400/200 bps (equities/bonds/real_estate/alternatives/
liquidity) because an equity floor and RE/alt caps were applied, but the raw
house-matrix baseline for that risk bucket is something else entirely (e.g.
6800/1600/800/600/200), the Max-Pension-Spending endpoint silently computes
its numbers from the latter -- ignoring the real, approved strategy.

Reproduction strategy here: seed a mandate, read the raw house-matrix
baseline for its bucket, then persist a TargetAllocation whose bps are
DELIBERATELY shifted away from that baseline (equities +200bps via a
floor-style override, bonds +200bps, real_estate/alternatives -200bps each,
mirroring the audit's repro pattern) as the mandate's actual verified
current strategy. The endpoint's result with this TargetAllocation present
must differ from (and must match the approved-allocation-derived metrics,
not) the result for a mandate that has no TargetAllocation at all.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.allocation import TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import WealthPosition
from services.auth import get_current_user, require_advisor
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers


def _now() -> str:
    return datetime.now().isoformat() + "Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retirement_alloc_basis.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def _seed_mandate(session_factory, suffix: str = ""):
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-rab-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Test", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="Dynamisch",
            risk_capacity_score_x10=100,
            investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=80,
            final_score_x10=80, final_profile="Wachstumsorientiert",
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        from services.portfolio_engine import ensure_runtime_reference_data
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def _client_with_user(session_factory, user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_advisor] = lambda: user
    return TestClient(app)


@pytest.mark.xfail(
    strict=True,
    reason="RETIREMENT-ALLOCATION-BASIS-001 — round 46 red test, see audit "
           "2026-10-04-house-matrix-policy-constraint-and-retirement-basis-"
           "integrity-audit.md (not committed in this repo)",
)
def test_max_pension_spending_must_use_real_target_allocation_not_raw_baseline(
    session_factory, cleanup_overrides,
):
    advisor_id, cid, mid, aid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    payload = {"retirement_year": 2035, "life_expectancy_year": 2065,
               "value_mode": "real", "safety_margin_pct": 0}

    # 1) Control: mandate has NO TargetAllocation row at all. The endpoint
    #    must fall back to *some* basis here (today it uses the raw
    #    house-matrix baseline band for the risk bucket).
    control = client.post(
        f"/mandates/{mid}/goals/calculate-max-pension-spending", json=payload,
    )
    assert control.status_code == 200, control.text
    control_body = control.json()

    # 2) Compute what the engine would produce for the mandate's *actually
    #    approved* strategy -- deliberately shifted away from the raw
    #    house-matrix baseline, mirroring the audit's repro (an equity floor
    #    override pushing equities up, with real_estate/alternatives capped
    #    down and bonds absorbing the rest).
    with session_factory() as s:
        from services.portfolio_engine import (
            ensure_runtime_reference_data, _house_matrix_or_default,
            _baseline_target_bands, _risk_score_bucket, _building_block_risky_map,
            _build_sub_allocations, _enrich_sub_allocations_with_risk,
            _expected_metrics, _normalize_preferences,
        )
        from services.jurisdiction.resolve import resolve_mandate_jurisdiction

        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        assessment = (
            s.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id == mid, RiskAssessment.is_current == 1)
            .first()
        )
        jurisdiction = resolve_mandate_jurisdiction(mandate)
        policy, cma = ensure_runtime_reference_data(
            s, advisor_id, jurisdiction=jurisdiction,
            tenant_id=getattr(mandate, "tenant_id", None),
        )
        score_bucket = _risk_score_bucket(assessment)
        house_matrix = _house_matrix_or_default(s, policy, score_bucket)
        raw_baseline_targets, _, _ = _baseline_target_bands(house_matrix, policy)

        approved_targets = {
            "equities": raw_baseline_targets["equities"] + 200,
            "bonds": raw_baseline_targets["bonds"] + 200,
            "real_estate": max(0, raw_baseline_targets["real_estate"] - 200),
            "alternatives": max(0, raw_baseline_targets["alternatives"] - 200),
            "liquidity": raw_baseline_targets["liquidity"],
        }
        assert sum(approved_targets.values()) == 10000
        # Scenario sanity check: the approved strategy must genuinely diverge
        # from the raw baseline, otherwise this isn't testing the bug.
        assert approved_targets != raw_baseline_targets

        prefs = _normalize_preferences(None)
        risky_map = _building_block_risky_map(
            s, policy.id, getattr(mandate, "investment_universe", None), jurisdiction,
        )
        approved_sub_allocs = _build_sub_allocations(
            approved_targets, prefs, jurisdiction=jurisdiction, db=s,
        )
        approved_sub_allocs, _, _ = _enrich_sub_allocations_with_risk(approved_sub_allocs, risky_map)
        approved_metrics = _expected_metrics(approved_targets, cma, approved_sub_allocs)
        expected_correct_return_bps = int(approved_metrics.get("expected_return_bps") or 0)
        expected_correct_vol_bps = int(approved_metrics.get("expected_volatility_bps") or 0)

        # Persist this as the mandate's real, current, verified-approved
        # TargetAllocation (zero-width bands: this *is* the exact approved
        # point allocation, not a range).
        now = _now()
        s.add(TargetAllocation(
            id=str(uuid.uuid4()), mandate_id=mid, version=1, is_current=1,
            target_equities_bps=approved_targets["equities"],
            target_bonds_bps=approved_targets["bonds"],
            target_real_estate_bps=approved_targets["real_estate"],
            target_alternatives_bps=approved_targets["alternatives"],
            target_liquidity_bps=approved_targets["liquidity"],
            band_equities_min_bps=approved_targets["equities"],
            band_equities_max_bps=approved_targets["equities"],
            band_bonds_min_bps=approved_targets["bonds"],
            band_bonds_max_bps=approved_targets["bonds"],
            band_real_estate_min_bps=approved_targets["real_estate"],
            band_real_estate_max_bps=approved_targets["real_estate"],
            band_alternatives_min_bps=approved_targets["alternatives"],
            band_alternatives_max_bps=approved_targets["alternatives"],
            band_liquidity_min_bps=approved_targets["liquidity"],
            band_liquidity_max_bps=approved_targets["liquidity"],
            policy_id=policy.id, set_by=advisor_id, set_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()

    # 3) Same endpoint call, now that the mandate has a real, approved,
    #    current TargetAllocation diverging from the raw house-matrix
    #    baseline.
    with_alloc = client.post(
        f"/mandates/{mid}/goals/calculate-max-pension-spending", json=payload,
    )
    assert with_alloc.status_code == 200, with_alloc.text
    with_alloc_body = with_alloc.json()

    # DESIRED behaviour: the endpoint must use the mandate's actual approved
    # TargetAllocation as the basis for expected return/volatility (and
    # therefore the published max-spending figure) -- NOT the raw,
    # unconstrained house-matrix baseline band for the risk bucket.
    assert with_alloc_body["expected_return_bps"] == expected_correct_return_bps, (
        f"expected_return_bps={with_alloc_body['expected_return_bps']} does not match "
        f"the approved TargetAllocation basis ({expected_correct_return_bps}); "
        "endpoint is using some other (raw baseline) allocation instead."
    )
    assert with_alloc_body["expected_volatility_bps"] == expected_correct_vol_bps, (
        f"expected_volatility_bps={with_alloc_body['expected_volatility_bps']} does not match "
        f"the approved TargetAllocation basis ({expected_correct_vol_bps}); "
        "endpoint is using some other (raw baseline) allocation instead."
    )

    # Today's actual (wrong) behaviour: adding a real, diverging
    # TargetAllocation changes NOTHING -- the endpoint keeps returning
    # exactly the same figures as for a mandate with no TargetAllocation at
    # all, because it only ever reads _baseline_target_bands().
    assert (
        with_alloc_body["expected_return_bps"] != control_body["expected_return_bps"]
        or with_alloc_body["expected_volatility_bps"] != control_body["expected_volatility_bps"]
    ), "endpoint result is unaffected by the mandate's real TargetAllocation (uses raw baseline basis instead)"
