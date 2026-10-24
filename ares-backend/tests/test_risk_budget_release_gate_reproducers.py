r"""Residual RISK-BUDGET-FINALIZATION-001 release-gate contracts.

Uebernommen aus dem Codex-Reproducer
docs/audits/reproducers/test_2026_10_14_risk_budget_release_gate_adversarial_replay.py
(Branch codex/asset-allocation-stochastic-core) als regulaerer Test ohne
xfail; Fix: services/recommendation_release_gate.py.

A direct Finalize comparison alone is not closure: missing
modern evidence must fail closed and every stronger release channel must call
the same central eligibility gate.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from routers.pdf_reports import get_advisory_report_pdf  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from routers.review import (  # noqa: E402
    _validate_recommendation_for_finalization,
    sign_document,
)
from test_finalization_ignores_risk_budget_violated_lock import (  # noqa: E402
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _make_run,
    _seed_realistic_mandate,
    session_factory,
)


def test_missing_modern_risk_evidence_cannot_be_relabelled_as_legacy_warning(
    session_factory,
) -> None:
    """Deleting required context/risk evidence must block, never warn only."""
    advisor_id, _cid, mandate_id, assessment_id, _gid = _seed_realistic_mandate(
        session_factory,
        suffix="risk-budget-evidence-downgrade-audit",
    )
    allocation_id = _current_allocation_id(
        session_factory, mandate_id, advisor_id
    )

    # Simulate the currently possible in-place downgrade: the nullable
    # artifacts and discriminator are rewritten together so the verifier
    # treats this modern allocation as legacy.  No migration/DB constraint
    # prevents this state.
    with session_factory() as db:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.id == allocation_id
        ).one()
        allocation.risky_fraction_bps_at_generation = None
        allocation.sub_allocations_json = None
        allocation.effective_constraints_json = None
        allocation.allocation_context_hash = None
        allocation.context_artifacts_required = 0
        db.commit()

    policy_id, cma_id = _allocation_policy_and_cma(
        session_factory, allocation_id
    )
    run_id = _make_run(
        session_factory,
        mandate_id,
        allocation_id,
        assessment_id,
        advisor_id,
        policy_id,
        cma_id,
        result_status="Draft",
    )
    _add_full_position(session_factory, run_id)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).one()
        run = db.query(RecommendationRun).filter(
            RecommendationRun.id == run_id
        ).one()
        errors, warnings = _validate_recommendation_for_finalization(
            db, mandate, run
        )

    assert any("Risikobudget" in error for error in errors), (errors, warnings)
    assert not any("nicht belegbar" in warning for warning in warnings), warnings


def test_all_stronger_release_channels_call_one_central_eligibility_gate() -> None:
    """PDF, signature and handoff must enforce the same persisted verdict."""
    expected_gate = "assert_recommendation_release_eligible"
    channel_sources = {
        "advisory_pdf": inspect.getsource(get_advisory_report_pdf),
        "signature": inspect.getsource(sign_document),
        "handoff": inspect.getsource(create_portfolio_handoff),
    }

    missing = [
        channel
        for channel, source in channel_sources.items()
        if expected_gate not in source
    ]
    assert not missing, (
        "release channels do not call the central risk/eligibility gate: "
        f"{missing}"
    )
