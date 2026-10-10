"""SUBRISK-CONTEXT-REPLAY-001 (round 53 red tests).

Audit: docs/audits/2026-10-05-sub-asset-risk-aggregation-cache-and-replay-integrity-audit.md

The global setting ``settings.sub_class_intra_correlation`` (Sprint U-P8 Fix
M1, see ``services/portfolio_engine_cma.py::_weighted_bucket_metrics`` around
line 419-546) materially changes the computed bucket volatility whenever a
bucket holds more than one sub-asset-class: when ``< 1.0`` it switches the
bucket vol from a simple weighted-average scalar to a true block-diagonal
``sqrt(w' Sigma w)`` with intra-bucket diversification. A quick direct check
against the real function (not asserted here, just documented) with two
50/50-weighted equity sub-classes ("Aktien Schweiz" vol 1450bps / "Aktien
Schwellenlaender" vol 1900bps) gives bucket vol 1675bps at rho=1.0, 1455bps at
rho=0.5 and 1195bps at rho=0.0 -- a ~40% swing on the exact same portfolio
weights and CMA inputs. This is a real, material change to the stochastic
risk basis, not a cosmetic one.

None of the three places that are supposed to make a persisted allocation's
model basis replay-verifiable ever read this setting:

1. ``_build_allocation_model_basis()`` (``services/portfolio_engine.py``,
   confirmed ~line 2854-3093 in this checkout) builds the
   ``optimization_model_basis`` dict returned as ``model_basis["optimization"]``
   purely from ``optimizer_result.context`` (n_paths/horizon/tax_regime/
   dividend yields/scenario_weights), ``optimizer_result.method`` and the raw
   ``optimizer_mode`` string. It never touches
   ``settings.sub_class_intra_correlation`` -- grepping its body confirms zero
   references to ``settings`` at all.

2. ``allocation_context_hash`` (``generate_target_allocation()``, hashed
   ~line 4286-4293) is `sha256(json(allocation_context_payload))` where
   ``allocation_context_payload["effective_constraints"]["optimization_model_basis"]``
   is exactly the dict from (1) -- so it transitively inherits the same gap.

3. The sensitivity endpoint's ``_model_input_hash()`` closure inside
   ``evaluate_goal_sensitivity()`` (~line 5529-5578) builds its payload from a
   column-dump snapshot of the ``CapitalMarketAssumption`` row
   (``cma_snapshot``, ~line 5482-5485) plus goals/seed/horizon/bounds/tax/
   mortality/fx -- again never reading ``settings.sub_class_intra_correlation``,
   which lives on the global ``Settings`` object, not on the CMA row.

Net effect: an advisor (or an attacker with config access) can flip
``sub_class_intra_correlation`` between generating an allocation and a client
reviewing/re-verifying it. The bucket risk the solver actually used, and the
bucket risk a sensitivity re-run would actually use, silently changes -- but
``allocation_context_hash`` / ``model_input_hash`` still "verify" successfully,
because they only ever proved the JSON structure of the stored context, never
the actual stochastic risk basis.

``_strategy_drift_warnings()`` (``services/portfolio_engine.py``, grep
confirms the only definition at ~line 3096) does not help either: it compares
``cma.id`` and ``current_input_snapshot_hash`` (position/cashflow/goal
fingerprints), not this global setting -- a CMA-id-identical, snapshot-
identical reload with a changed ``sub_class_intra_correlation`` triggers no
drift warning at all.

Three hash-binding surfaces are exercised below, one test function each:

- ``test_model_basis_optimization_dict_identical_despite_rho_change``: calls
  the real ``_build_allocation_model_basis()`` directly, twice, with
  identical ``optimizer_result``/``context``/``mandate``/``monte_carlo``
  inputs and only ``settings.sub_class_intra_correlation`` changed (1.0 vs
  0.5). No DB needed -- this is the narrowest, most direct proof of gap (1).

- ``test_allocation_context_hash_identical_despite_rho_change``: runs the
  real ``generate_target_allocation()`` (stochastic mode, reusing the
  realistic-mandate fixture already established in
  ``tests/test_optimizer_integration.py::_seed_realistic_mandate``) twice on
  the *same* mandate/cma/goals/session so the solver's seed
  (``deterministic_seed(cma_id, goal_ids, score_x10, horizon_years, n_paths)``,
  see ``services/optimizer/solver.py`` line ~387) is pinned identically across
  both calls -- isolating the comparison to exactly the one changed setting.
  Compares the persisted ``TargetAllocation.allocation_context_hash``.

- ``test_sensitivity_model_input_hash_identical_despite_rho_change``: runs
  the real ``evaluate_goal_sensitivity()`` (reusing the mandate fixture
  established in ``tests/test_optimizer_phase6.py::_seed_mandate``) twice
  against the same persisted allocation/goal with ``target_delta_pct=0``,
  ``horizon_delta_years=0`` and only the setting changed. Compares
  ``live_model_input_hash`` (== ``baseline_model_input_hash`` for a no-op
  delta).

All three assert the hashes/dicts DIFFER (the desired, replay-safe
behaviour). All three currently FAIL that assertion -- the real code
produces byte-identical output regardless of the setting -- which is exactly
the documented gap, hence ``xfail(strict=True)`` below.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)

configure_mappers()

import services.portfolio_engine as pe  # noqa: E402
from config import settings  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from services.portfolio_engine import (  # noqa: E402
    _build_allocation_model_basis,
    evaluate_goal_sensitivity,
    generate_target_allocation,
)

@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'subrisk_context_replay.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def _restore_optimizer_mode_and_rho():
    """Belt-and-suspenders: monkeypatch already reverts, but these are
    process-global mutable singletons touched by direct attribute
    assignment further below (not every mutation here goes through
    monkeypatch, since _build_allocation_model_basis is called outside any
    monkeypatch-managed scope in the first test)."""
    original_mode = settings.optimizer_mode
    original_rho = settings.sub_class_intra_correlation
    yield
    settings.optimizer_mode = original_mode
    settings.sub_class_intra_correlation = original_rho


# ---------------------------------------------------------------------------
# Surface 1: optimization_model_basis (_build_allocation_model_basis)
# ---------------------------------------------------------------------------


def test_model_basis_optimization_dict_identical_despite_rho_change():
    """Direct, DB-free call of the real model-basis builder.

    Identical optimizer_result/context/mandate/monte_carlo/simulation_prefs
    across both calls; only settings.sub_class_intra_correlation differs
    (1.0 vs 0.5). Desired: the two 'optimization' dicts differ, because they
    describe genuinely different stochastic risk bases. Actual (the bug):
    they are byte-for-byte identical, because the function never reads this
    setting at all.
    """
    mandate = Mandate(id=f"mandate-rho-{uuid.uuid4().hex[:8]}", base_currency="CHF")
    context = SimpleNamespace(
        n_paths=500,
        horizon_years=20,
        tax_regime=None,
        dividend_yield_bps_per_bucket=None,
        scenario_weights=None,
    )
    optimizer_result = SimpleNamespace(
        context=context, method="stochastic", seed=123, n_paths=500,
    )
    monte_carlo = {"seed": 123, "simulations": 500, "horizon_years": 20}

    settings.sub_class_intra_correlation = 1.0
    basis_rho_1 = _build_allocation_model_basis(
        optimizer_mode="stochastic",
        optimizer_result=optimizer_result,
        allocation=None,
        monte_carlo=monte_carlo,
        simulation_prefs={},
        mandate=mandate,
    )

    settings.sub_class_intra_correlation = 0.5
    basis_rho_05 = _build_allocation_model_basis(
        optimizer_mode="stochastic",
        optimizer_result=optimizer_result,
        allocation=None,
        monte_carlo=monte_carlo,
        simulation_prefs={},
        mandate=mandate,
    )

    assert basis_rho_1["optimization"] != basis_rho_05["optimization"], (
        "optimization_model_basis is byte-identical for "
        "sub_class_intra_correlation=1.0 vs 0.5 -- the stochastic risk basis "
        "it is supposed to describe is NOT identical between these two "
        "settings (SUBRISK-CONTEXT-REPLAY-001)."
    )


# ---------------------------------------------------------------------------
# Surface 2: allocation_context_hash (generate_target_allocation, end-to-end)
# ---------------------------------------------------------------------------


def test_allocation_context_hash_identical_despite_rho_change(session_factory):
    """End-to-end generate_target_allocation() on the SAME mandate/cma/goals.

    Reuses the realistic-mandate fixture already established today for
    OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001-style hash-binding-gap tests
    (tests/test_optimizer_integration.py::_seed_realistic_mandate). Both
    generate_target_allocation() calls run against the identical mandate/cma/
    goal set in the same session, in stochastic mode, so the solver's seed
    (deterministic_seed(cma_id, goal_ids, score_x10, horizon_years, n_paths))
    is pinned identically across both calls -- isolating the comparison to
    exactly the one changed setting. Desired: allocation_context_hash
    differs. Actual (the bug): identical.
    """
    from tests.test_optimizer_integration import _seed_realistic_mandate

    settings.optimizer_mode = "stochastic"
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(
        session_factory, suffix=f"subrisk-{uuid.uuid4().hex[:8]}",
    )

    hashes = []
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).first()
        for rho in (1.0, 0.5):
            settings.sub_class_intra_correlation = rho
            result = generate_target_allocation(
                db=session, mandate=mandate, user_id=advisor_id, preferences=None,
            )
            hashes.append(result["target_allocation"].allocation_context_hash)

    assert hashes[0] != hashes[1], (
        "allocation_context_hash is identical for sub_class_intra_correlation="
        "1.0 vs 0.5 on the exact same mandate/CMA/goals/seed -- it re-verifies "
        "successfully on reload even though the actual stochastic risk basis "
        "the solver used would differ (SUBRISK-CONTEXT-REPLAY-001)."
    )


# ---------------------------------------------------------------------------
# Surface 3: sensitivity model_input_hash (evaluate_goal_sensitivity)
# ---------------------------------------------------------------------------


def test_sensitivity_model_input_hash_identical_despite_rho_change(session_factory):
    """End-to-end evaluate_goal_sensitivity() on the SAME persisted allocation.

    Reuses the mandate fixture already established today for the Phase 6
    sensitivity tests (tests/test_optimizer_phase6.py::_seed_mandate). A
    single generate_target_allocation() call (stochastic mode) establishes
    the required allocation basis; evaluate_goal_sensitivity() is then called
    twice with target_delta_pct=0 / horizon_delta_years=0 (a no-op delta, so
    baseline == modified) with only sub_class_intra_correlation changed
    between calls. Desired: live_model_input_hash differs. Actual (the bug):
    identical, because _model_input_hash()'s payload is built from a column
    dump of the CMA row plus goals/seed/horizon/bounds -- never from the
    global sub_class_intra_correlation setting.
    """
    from tests.test_optimizer_phase6 import _seed_mandate

    settings.optimizer_mode = "stochastic"
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(
        session_factory, suffix=f"subrisk-{uuid.uuid4().hex[:8]}",
    )

    hashes = []
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(
            db=session, mandate=mandate, user_id=advisor_id, preferences=None,
        )
        for rho in (1.0, 0.5):
            settings.sub_class_intra_correlation = rho
            out = evaluate_goal_sensitivity(
                db=session,
                mandate=mandate,
                user_id=advisor_id,
                goal_id=gid,
                target_delta_pct=0,
                horizon_delta_years=0,
            )
            hashes.append(out["live_model_input_hash"])

    assert hashes[0] != hashes[1], (
        "evaluate_goal_sensitivity()'s live_model_input_hash is identical for "
        "sub_class_intra_correlation=1.0 vs 0.5 against the same persisted "
        "allocation/goal -- a sensitivity re-run's claimed model-input basis "
        "re-verifies successfully even though the actual bucket risk it would "
        "use differs (SUBRISK-CONTEXT-REPLAY-001)."
    )
