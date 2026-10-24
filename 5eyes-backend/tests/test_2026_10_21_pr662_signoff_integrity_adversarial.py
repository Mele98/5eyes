"""Adversarial residual contracts for merged PR #662.

PR #662 closes the two concrete signoff gaps from the PR #657 review.  This
gate covers the narrower integrity boundaries that remain:

* a later verifier must compare the immutable signoff snapshot with the
  assessment state it claims to certify, not merely recompute the row's own
  hash; and
* sensitive signoff/override evidence tables must be included in the
  PostgreSQL tenant-isolation plan instead of disappearing from discovery
  because they lack a physical ``tenant_id`` column.

Adopted from the audit reproducer (2026-10-21) as a regular test without
xfail. The backend directory is located by structure (the directory
containing ``main.py`` and ``database.py``), not by name.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _backend_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate
    raise AssertionError("backend directory (main.py + database.py) not found")


if str(_backend_root()) not in sys.path:
    sys.path.insert(0, str(_backend_root()))

from sqlalchemy import text  # noqa: E402

from models.profiling import RiskAssessment, RiskProfileSignoff  # noqa: E402
from routers import profiling as profiling_router  # noqa: E402
from services.postgres_rls import tenant_scoped_table_names  # noqa: E402
from services.risk_profile_signoff import assessment_input_hash, build_signoff_view  # noqa: E402
from tests.test_risk_capacity_plausibility import (  # noqa: E402
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401 - pytest fixture re-export
)
from tests.test_risk_override_current_gate_decision_log import _assessment  # noqa: E402


def _sign(session, advisor):
    return profiling_router.sign_risk_profile(
        mandate_id="m-rcp",
        request=_FakeRequest(),
        body=None,
        db=session,
        current_user=advisor,
    )


def test_verified_signoff_rejects_assessment_semantic_drift(session_factory):
    """A self-consistent row hash is not proof of the assessment it certifies."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        result = _sign(session, advisor)

        assessment = session.get(RiskAssessment, "ra-current")
        signoff = session.get(RiskProfileSignoff, result["signoff_id"])
        assert build_signoff_view(session, assessment)["signoff_verified"] is True
        assert signoff.assessment_input_hash == assessment_input_hash(session, assessment)

        # The assessment and its answers have no append-only DB boundary.  A
        # maintenance/import/buggy write can therefore change the certified
        # semantics without changing version or the signoff pointer.
        session.execute(text(
            "UPDATE risk_assessments SET final_score_x10 = final_score_x10 + 10 "
            "WHERE id = 'ra-current'"
        ))
        session.commit()
        session.expire_all()

        changed = session.get(RiskAssessment, "ra-current")
        signoff = session.get(RiskProfileSignoff, result["signoff_id"])
        assert signoff.assessment_input_hash != assessment_input_hash(session, changed)
        assert signoff.final_score_x10 != changed.final_score_x10

        # Fail closed: consumers must not continue to call this snapshot
        # verified once its assessment semantics no longer match.
        assert build_signoff_view(session, changed)["signoff_verified"] is not True


def test_signoff_evidence_tables_are_in_tenant_rls_plan():
    """Sensitive append-only evidence needs a DB tenant boundary as well."""
    scoped = set(tenant_scoped_table_names())
    assert {
        "risk_override_decisions",
        "risk_profile_signoffs",
    }.issubset(scoped)
