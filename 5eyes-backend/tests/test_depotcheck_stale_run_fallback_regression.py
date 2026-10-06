"""Regression test for audit finding DEPOT-E2E-SOURCE-001.

Audit source (NOT mirrored into this worktree — read it in the Ares
worktree): ``docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-
and-publication-integrity-audit.md`` in
``C:\\Users\\Emanuele\\Documents\\ChatGPT\\5eyes wird zu Ares\\
asset-allocation-stochastic-core``.

Finding (P1, open at the time of this test): the JSON Depot-Check API
(``services/depot_check.py``) and the Depot-Check PDF
(``routers/pdf_reports.py::_build_depotcheck_data``) each resolve "the
current recommended portfolio" differently from the plain Portfolio PDF
(``routers/pdf_reports.py::get_portfolio_pdf`` /
``_build_portfolio_data``):

- ``_build_portfolio_data`` is strict: it requires a Final-or-Draft
  ``RecommendationRun`` whose ``target_allocation_id`` matches the
  mandate's *current* ``TargetAllocation``. If the only run(s) on file are
  bound to an older, superseded ``TargetAllocation`` (e.g. right after a
  fresh SAA recalc before the advisor regenerates the recommendation), it
  raises ``HTTPException(409, ...)`` — and ``get_portfolio_pdf`` lets that
  propagate straight to the client. This is the correct "block on domain
  conflict" behaviour.

- ``_build_anlagestrategie_data`` (``routers/pdf_reports.py`` ~line 495-499)
  builds ``strategy.products`` from the *globally latest* RecommendationRun
  for the mandate, with **no** ``target_allocation_id`` filter at all — the
  same unscoped resolution ``services/depot_check.py`` uses for its own
  "IST depot" fallback (``depot_check.py`` ~line 319-321).

- ``_build_depotcheck_data`` (``routers/pdf_reports.py`` ~line 1566-1612)
  calls ``_build_portfolio_data`` and, on exactly the ``HTTPException`` that
  ``_build_portfolio_data`` raises for this conflict, silently swallows it
  and substitutes ``strategy.products`` as the position list (the
  fail-open ``except HTTPException: positions = list(strategy.products or
  [])`` around current line 1582-1583). Because ``strategy.products`` is
  sourced from the very same stale, superseded run that caused the
  conflict, the Depot-Check PDF ends up silently presenting that stale
  recommendation as if it were the mandate's current one — exactly the
  state the Portfolio PDF correctly blocks on.

This test reproduces the conflict mechanically: seed a mandate whose
RecommendationRun matches its (first) current TargetAllocation, then
trigger a fresh SAA recalc so a *new* TargetAllocation becomes current
while the existing RecommendationRun is left bound to the now-superseded
one. ``_build_portfolio_data`` must then raise 409 (asserted as a sanity
check — this part already works correctly today). The Depot-Check PDF data
builder must raise/propagate the identical conflict instead of silently
substituting the stale run's products.

Today it does not: ``_build_depotcheck_data`` returns successfully with a
``DepotCheckData`` populated from the stale run. This test is therefore
expected to fail (red) until DEPOT-E2E-SOURCE-001 is fixed by routing the
Depot-Check PDF through the same strict, TA-scoped resolver used by the
plain Portfolio PDF (no fallback across incompatible sources).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.allocation import TargetAllocation  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from routers.pdf_reports import (  # noqa: E402
    _build_depotcheck_data,
    _build_portfolio_data,
)
from services.portfolio_engine import generate_target_allocation  # noqa: E402
from test_portfolio_generate_after_saa_recalc import (  # noqa: E402
    _seed_foundation,
    session_factory,  # noqa: F401 - shared isolated-database pytest fixture
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEPOT-E2E-SOURCE-001 (open): _build_depotcheck_data "
        "(routers/pdf_reports.py) catches the HTTPException that "
        "_build_portfolio_data correctly raises for a stale/unmatched "
        "RecommendationRun and silently falls back to strategy.products "
        "(itself sourced from the same unscoped, globally-latest run) "
        "instead of propagating the 409 domain conflict. See "
        "docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-"
        "publication-integrity-audit.md (Ares worktree)."
    ),
)
def test_depotcheck_pdf_data_must_not_fall_back_to_stale_run_after_saa_recalc(
    session_factory,
):
    """Depot-Check PDF must block on the same conflict the Portfolio PDF blocks on."""
    with session_factory() as s:
        mandate = _seed_foundation(s)
        advisor = s.query(User).filter(User.id == "advisor-1").one()

        # Sanity: before the recalc, the foundation seed's RecommendationRun
        # matches the (first) current TargetAllocation, so the strict
        # resolver already returns real positions.
        portfolio_before = _build_portfolio_data(mandate, s)
        assert portfolio_before.positions

        # Trigger a fresh SAA recalc: a NEW TargetAllocation becomes current.
        # The existing RecommendationRun from the foundation seed stays bound
        # to the OLD (now non-current) TargetAllocation id -> stale.
        generate_target_allocation(
            db=s, mandate=mandate, user_id=advisor.id, preferences=None,
        )
        s.commit()

        current_ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
        ).one()
        existing_runs = s.query(RecommendationRun).filter(
            RecommendationRun.mandate_id == mandate.id,
        ).all()
        assert existing_runs, "foundation seed must leave a stale run behind"
        assert all(
            str(run.target_allocation_id) != str(current_ta.id)
            for run in existing_runs
        ), "fixture invariant broken: a run already matches the new current TA"

        # The strict, TargetAllocation-scoped resolver used by the plain
        # Portfolio PDF correctly detects and blocks on this domain conflict.
        with pytest.raises(HTTPException) as portfolio_exc:
            _build_portfolio_data(mandate, s)
        assert portfolio_exc.value.status_code == 409

        # The Depot-Check PDF data builder must surface the SAME conflict --
        # not silently substitute the stale run's products instead.
        with pytest.raises(HTTPException) as depotcheck_exc:
            _build_depotcheck_data(mandate, s)
        assert depotcheck_exc.value.status_code == 409
