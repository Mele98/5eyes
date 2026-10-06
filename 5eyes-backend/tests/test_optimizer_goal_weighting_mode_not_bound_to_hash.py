"""Round 47 red tests - OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001.

Audit: docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md

``OPTIMIZER_GOAL_WEIGHTING`` ("equal" vs "hardness",
services/optimizer/objective.py:_goal_weighting_mode) changes the optimizer's
objective-function mathematics by up to a factor of 50 between a "hart" and
an "opportunistisch" goal (services/optimizer/objective.py HARDNESS_WEIGHT:
10.0 vs 0.2). Despite that, this mode is read directly from ``os.environ``
and is never folded into:

  1. the "optimization model basis" dict
     (services/portfolio_engine.py:_build_allocation_model_basis), which is
     persisted verbatim inside TargetAllocation.effective_constraints_json
     and therefore inside allocation_context_hash;
  2. allocation_context_hash itself
     (services/portfolio_engine.py, generate_target_allocation); and
  3. the sensitivity-analysis ``model_input_hash``
     (services/portfolio_engine.py:evaluate_goal_sensitivity's local
     ``_model_input_hash`` closure).

Consequence: two runs that used genuinely different objective mathematics
(equal-weighting vs. hardness-weighting) can be persisted with the IDENTICAL
input hash. A stored Allocation/OptimizerRun therefore cannot prove which of
the two methods actually produced it - the hash is not an honest fingerprint
of the inputs that drove the solve.

All three tests below build the real production hash/model-basis twice,
with everything held constant except ``OPTIMIZER_GOAL_WEIGHTING``, and
assert the two results DIFFER (because the objective mathematics differed).
That assertion currently fails - the real outputs are byte-identical across
modes - which is exactly the evidence-integrity gap this finding describes.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
from models import tenant as _tenant_model  # noqa: F401
configure_mappers()

import services.portfolio_engine as pe
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    evaluate_goal_sensitivity,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'opt_goal_weighting_hash.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mixed_hardness_mandate(session_factory, suffix: str = ""):
    """Mandant mit einem harten und einem opportunistischen Ziel.

    Unter OPTIMIZER_GOAL_WEIGHTING=hardness unterscheidet sich der
    Zielfunktions-Beitrag dieser beiden Ziele um Faktor 50 (10.0 vs 0.2,
    HARDNESS_WEIGHT in services/optimizer/objective.py). Unter "equal"
    tragen beide mit Gewicht 1.0 bei. Genau dieser Unterschied ist es, der
    im Hash nachweisbar sein müsste - und es nicht ist.
    """
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-gw-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()
    pension_goal_id = f"goal-gw-hard-{suffix}"

    with session_factory() as s:
        s.add(User(
            id=advisor_id, username=f"adv-gw-{suffix}", password_hash="h",
            full_name="Adv GW", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-GW-{cid[:6]}",
            first_name="GW", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-GW-{mid[:6]}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=f"pos-gw-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-gw-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        # Hartes Ziel: HARDNESS_WEIGHT["hart"] = 10.0
        s.add(Goal(
            id=pension_goal_id, mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        # Opportunistisches Ziel: HARDNESS_WEIGHT["opportunistisch"] = 0.2
        s.add(Goal(
            id=f"goal-gw-opp-{suffix}", mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Zweitwohnsitz", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00,
            target_date=wealth_target_date,
            is_ongoing=0, hardness="Opportunistisch",
            is_active=1, created_at=now, updated_at=now,
        ))
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
            id=aid, mandate_id=mid, version=1, is_current=1,
            valid_from=now[:10],
            **risk_fields,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid, pension_goal_id


# ============================================================================
# Surface 1: optimization_model_basis
# (services/portfolio_engine.py:_build_allocation_model_basis)
# ============================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001 — round 47 red test "
        "(goal-weighting mode not bound to model basis / context hash / "
        "sensitivity input hash), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
    ),
)
def test_optimization_model_basis_identical_despite_differing_goal_weighting_mode(
    monkeypatch,
):
    """_build_allocation_model_basis() must change with the weighting mode.

    It currently does not read OPTIMIZER_GOAL_WEIGHTING at all (confirmed by
    reading services/portfolio_engine.py:_build_allocation_model_basis in
    full - no os.environ / settings access anywhere in its body), so calling
    it twice with byte-identical arguments except the env var produces a
    byte-identical "optimization" model-basis dict both times, even though
    the mode genuinely changes which objective the solver optimized.
    """
    optimizer_result = SimpleNamespace(
        context=None,
        method="stochastic",
        seed=4242,
        n_paths=2000,
    )
    monte_carlo = {"seed": 4242, "simulations": 2000, "horizon_years": 20}
    common_kwargs = dict(
        optimizer_mode="stochastic",
        optimizer_result=optimizer_result,
        allocation=None,
        monte_carlo=monte_carlo,
        simulation_prefs=None,
        mandate=None,
        stored_optimization_basis=None,
        reporting_tax_cashflow_present=False,
    )

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "equal")
    basis_equal = pe._build_allocation_model_basis(**common_kwargs)

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    basis_hardness = pe._build_allocation_model_basis(**common_kwargs)

    assert basis_equal["optimization"] != basis_hardness["optimization"], (
        "optimization_model_basis is identical for 'equal' and 'hardness' "
        "goal-weighting modes, even though those modes optimize genuinely "
        "different objective functions (up to 50x weight difference "
        "between hard and opportunistic goals). The model basis that is "
        "persisted into TargetAllocation.effective_constraints_json (and "
        "therefore into allocation_context_hash) cannot distinguish which "
        "mode actually produced a given allocation."
    )


# ============================================================================
# Surface 2: allocation_context_hash
# (services/portfolio_engine.py, generate_target_allocation)
# ============================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001 — round 47 red test "
        "(goal-weighting mode not bound to model basis / context hash / "
        "sensitivity input hash), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
    ),
)
def test_allocation_context_hash_identical_despite_differing_goal_weighting_mode(
    session_factory, monkeypatch,
):
    """generate_target_allocation's allocation_context_hash must change too.

    Same mandate (mixed hard/opportunistic goals), same stochastic optimizer
    mode, same everything else - only OPTIMIZER_GOAL_WEIGHTING differs
    between the two generation calls. Because the hash's inputs
    (effective_constraints_payload / optimization_model_basis) never carry
    the weighting mode, the resulting allocation_context_hash is identical
    across modes even though the solver used a different objective.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mixed_hardness_mandate(session_factory)

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "equal")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result_equal = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        hash_equal = result_equal["target_allocation"].allocation_context_hash

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result_hardness = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        hash_hardness = result_hardness["target_allocation"].allocation_context_hash

    assert hash_equal and hash_hardness
    assert hash_equal != hash_hardness, (
        "allocation_context_hash is identical for the exact same mandate "
        "under OPTIMIZER_GOAL_WEIGHTING='equal' vs 'hardness', even though "
        "the two runs optimized genuinely different objective mathematics "
        "(hard goals weighted 10x, opportunistic goals 0.2x under "
        "'hardness'; all goals weighted 1.0x under 'equal'). A stored "
        "TargetAllocation's context hash therefore cannot prove which "
        "weighting mode actually produced it."
    )


# ============================================================================
# Surface 3: sensitivity model_input_hash
# (services/portfolio_engine.py:evaluate_goal_sensitivity -> _model_input_hash)
# ============================================================================


def _fake_run_solver(monkeypatch) -> None:
    """Swap the expensive stochastic solver for a cheap deterministic stub.

    Mirrors the established pattern in tests/test_optimizer_phase6.py
    (_capture_sensitivity_solver_calls) - evaluate_goal_sensitivity imports
    run_solver lazily from services.optimizer.solver at call time, so
    patching the module attribute is sufficient. We only need a stable
    converged result here; the sensitivity hash is computed from the
    *inputs* handed to the solver, not from its output.
    """
    import services.optimizer.solver as optimizer_solver

    def fake_run_solver(**kwargs):
        return SimpleNamespace(
            objective_value=1.0,
            weights_bps={
                "liquidity": 2000,
                "bonds": 3000,
                "equities": 4000,
                "real_estate": 500,
                "alternatives": 500,
            },
            status="converged",
        )

    monkeypatch.setattr(optimizer_solver, "run_solver", fake_run_solver)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001 — round 47 red test "
        "(goal-weighting mode not bound to model basis / context hash / "
        "sensitivity input hash), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
    ),
)
def test_sensitivity_model_input_hash_identical_despite_differing_goal_weighting_mode(
    session_factory, monkeypatch,
):
    """evaluate_goal_sensitivity's live_model_input_hash must change too.

    Same mandate, same goal, target_delta_pct=0 (baseline run) - only
    OPTIMIZER_GOAL_WEIGHTING differs between the two calls. The solver is
    stubbed out (see _fake_run_solver) purely for speed/determinism; the
    hash under test is built from the *inputs* passed into
    evaluate_goal_sensitivity's local _model_input_hash closure before the
    solver ever runs, so stubbing the solver does not affect what is being
    proven here.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, goal_id = _seed_mixed_hardness_mandate(session_factory)
    _fake_run_solver(monkeypatch)

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "equal")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out_equal = evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
        )

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out_hardness = evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
        )

    hash_equal = out_equal["live_model_input_hash"]
    hash_hardness = out_hardness["live_model_input_hash"]

    assert hash_equal and hash_hardness
    assert hash_equal != hash_hardness, (
        "evaluate_goal_sensitivity's live_model_input_hash is identical "
        "for the same mandate/goal under OPTIMIZER_GOAL_WEIGHTING='equal' "
        "vs 'hardness'. The sensitivity model_input_hash cannot prove which "
        "objective mathematics (equal vs. hardness goal weighting) actually "
        "drove the baseline solve it is supposed to fingerprint."
    )
