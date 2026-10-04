"""RISK-FALLBACK-CONTEXT-001 (round 46 red test).

When the risk budget is structurally unachievable (``#AA-1``: Bausteine +
Pflicht-Bandbreiten lassen die Risky-Fraction nicht unter den Risikoprofil-Cap),
``generate_target_allocation`` in ``services/portfolio_engine.py`` falls back to
the House-Matrix-Mitte and persists ``optimization_method = "fallback_house_matrix"``
on the ``TargetAllocation`` (see ``risk_budget_fallback`` handling around line
4102-4107, confirmed by ``tests/test_risk_budget_cap.py::test_cap_breach_falls_back_to_house_matrix_mid``).

However, the separately-built, hashed ``optimization_model_basis`` dict (built by
``_build_allocation_model_basis``, called at line ~4023 *before* the
``risk_budget_fallback`` override exists) derives its own ``active_method`` solely
from ``optimizer_result.method`` / ``allocation.optimization_method`` / the raw
``optimizer_mode`` string -- it never sees the ``risk_budget_fallback`` flag. In
``house_matrix`` mode (``optimizer_result`` is ``None``), this falls through to
plain ``"house_matrix"`` instead of ``"fallback_house_matrix"``.

That stale value is embedded verbatim into ``effective_constraints_json`` as
``optimization_model_basis.active_method`` (line ~4266) and persisted. The
top-level ``effective_constraints_json["active_method"]`` field is computed
separately from ``optimizer_audit`` (line ~4257-4259), which *does* see the
fallback and is correct. So the persisted record contains two internally
inconsistent "active method" values for the exact same, successfully-generated,
current TargetAllocation.

``_verified_persisted_allocation_context`` (line ~4465) is the integrity gate
used by downstream consumers (``build_target_payload_from_allocation`` --
current-payload read / finalization basis; ``evaluate_goal_sensitivity`` --
recommendation sensitivity). It compares
``stored_constraints["optimization_model_basis"]["active_method"]`` against
``allocation.optimization_method`` (line ~4590-4598) and raises ``ValueError``
on disagreement. Because of the bug above, this raises for every fallback
allocation generated in house_matrix mode -- the freshly-created, current
TargetAllocation becomes immediately unusable by its own downstream readers.

Desired behaviour (asserted below): the persisted ``optimization_method`` and
the model-basis's ``active_method`` must always agree.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

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

import services.portfolio_engine as pe
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.test_risk_budget_cap import _prefs_for_equity, _seed_risk_cap_case


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_fallback_model_basis.db'}",
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
def fast_monte_carlo(monkeypatch):
    monkeypatch.setattr(pe, "_run_allocation_monte_carlo", lambda **_kwargs: {"goal_summaries": []})


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RISK-FALLBACK-CONTEXT-001 — round 46 red test, see audit "
        "2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_fallback_model_basis_active_method_matches_persisted_optimization_method(
    session_factory, monkeypatch
):
    # Reproduce the exact structurally-unachievable risk-budget scenario from
    # tests/test_risk_budget_cap.py::test_cap_breach_falls_back_to_house_matrix_mid:
    # house_matrix mode, equity preference (7200 bps) above the profile's
    # max_risky_fraction_bps cap (7000 bps), with the mandatory bands unable to
    # bring the realized risky fraction under the cap.
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    with session_factory() as session:
        mandate, policy, cma, assessment = _seed_risk_cap_case(session)
        prefs = _prefs_for_equity(7200)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=prefs,
        )
        ta = result["target_allocation"]

        # Sanity: this is genuinely the documented house-matrix risk-budget
        # fallback, not some other code path.
        assert ta.optimization_method == "fallback_house_matrix"
        assert ta.optimization_status == "fallback_house_matrix"

        persisted_active_method = str(ta.optimization_method)
        model_basis_active_method = str(
            result["model_basis"]["optimization"]["active_method"]
        )

        # DESIRED behaviour: the model-basis's active_method must agree with
        # the persisted optimization_method for this exact, current,
        # successfully-generated TargetAllocation.
        assert model_basis_active_method == persisted_active_method, (
            "optimization_model_basis.active_method "
            f"({model_basis_active_method!r}) disagrees with the persisted "
            f"TargetAllocation.optimization_method ({persisted_active_method!r})"
        )

        # The same disagreement is also embedded in the persisted,
        # hash-anchored effective_constraints_json -- confirm both views
        # (top-level active_method vs. nested model-basis active_method)
        # agree with each other there too.
        effective_constraints = json.loads(ta.effective_constraints_json)
        nested_active_method = str(
            effective_constraints["optimization_model_basis"]["active_method"]
        )
        assert nested_active_method == effective_constraints["active_method"], (
            "effective_constraints_json top-level active_method "
            f"({effective_constraints['active_method']!r}) disagrees with its "
            f"nested optimization_model_basis.active_method "
            f"({nested_active_method!r})"
        )

        # DOWNSTREAM CONSUMER: build_target_payload_from_allocation re-reads
        # the just-generated, current TargetAllocation (e.g. for a
        # current-payload read or finalization) via
        # _verified_persisted_allocation_context, which raises ValueError the
        # moment the model-basis active_method disagrees with the persisted
        # optimization_method. With correct metadata, this call must succeed.
        reloaded = build_target_payload_from_allocation(
            session,
            mandate,
            ta,
            policy,
            cma,
            assessment,
            prefs,
        )
        assert reloaded["risk_budget_bps"] == result["risk_budget_bps"]
