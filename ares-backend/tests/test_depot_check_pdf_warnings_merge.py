"""DEPOT-E2E-WARNING-001 (docs/audits/2026-10-05-depotcheck-end-to-end-
product-identity-and-publication-integrity-audit.md, Ares worktree).

``_build_depotcheck_data`` in routers/pdf_reports.py calls
``services.depot_check.compute_depot_check()`` and reuses many of its values
(buckets, exposures, concentration-HHI, liquidity profile, ...) for other PDF
sections -- BUT populated the PDF's ``warnings`` field EXCLUSIVELY from
``_depotcheck_data_quality_warnings(costs, performance)`` (cost/performance
data-quality warnings only). ``compute_depot_check()``'s own structured
warnings (band-limit violations, country/sector/currency drift,
concentration, missing-advisory-wealth, illiquid-position share, ...) were
silently dropped and never reached the PDF -- a client reading only the
printed Depot-Check PDF could see a "clean" warnings section while the live
app (which reads ``compute_depot_check()`` directly) showed real, actionable
warnings for the exact same depot.

This test seeds a real mandate (via the Foundation example-case fixture, the
same engine-backed seeding used by
tests/test_portfolio_generate_after_saa_recalc.py and
tests/test_asset_allocation_reference_integrity_edges.py) and then
concentrates the entire IST holding into a single recommended position, which
guarantees at least one ``compute_depot_check()`` band-limit/concentration
warning (mirrors
tests/test_depot_check.py::test_bucket_drift_against_target_allocation).  It
then calls the real ``_build_depotcheck_data`` PDF-builder and asserts every
``compute_depot_check()`` warning text is present in the PDF payload's
``warnings`` field.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import TargetAllocation
from models.review import RecommendationPosition, RecommendationRun
from services.depot_check import compute_depot_check
from test_portfolio_generate_after_saa_recalc import _seed_foundation


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'depotcheck_pdf_warnings.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_depotcheck_pdf_includes_depot_check_service_warnings(session_factory):
    """DEPOT-E2E-WARNING-001: depot-check PDF must not silently drop
    compute_depot_check()'s own warnings (it must merge them with the
    cost/performance data-quality warnings, not replace them)."""
    from routers.pdf_reports import _build_depotcheck_data

    with session_factory() as s:
        mandate = _seed_foundation(s)

        s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
        ).one()  # sanity: Foundation fixture has a current SAA
        run = (
            s.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        assert run is not None, "Foundation fixture must generate a RecommendationRun"
        positions = (
            s.query(RecommendationPosition)
            .filter(RecommendationPosition.run_id == run.id)
            .all()
        )
        assert len(positions) >= 1
        total = sum(int(p.target_amount_rappen or 0) for p in positions)
        assert total > 0

        # Concentrate the entire IST holding into ONE position: that
        # position's bucket jumps to ~100% IST, guaranteed outside any
        # realistic TargetAllocation band, and top-position concentration
        # (HHI) is maximal -- deterministically produces at least one
        # compute_depot_check() warning without depending on the specific
        # numbers the stochastic engine happened to generate. Mirrors
        # tests/test_depot_check.py::test_bucket_drift_against_target_allocation.
        positions[0].current_amount_rappen = total
        for other in positions[1:]:
            # Tiny but nonzero: current_amount_rappen<=0 would make
            # depot_check fall back to target_amount_rappen for that
            # position, which would undo the concentration.
            other.current_amount_rappen = 1
        s.commit()

        dc = compute_depot_check(s, mandate)
        assert dc["warnings"], (
            "Seeding must produce at least one compute_depot_check() warning "
            "for this regression test to be meaningful"
        )

        data = _build_depotcheck_data(mandate, s)

    for warning in dc["warnings"]:
        assert warning in data.warnings, (
            "compute_depot_check() warning missing from depot-check PDF "
            f"payload (DEPOT-E2E-WARNING-001): {warning!r} not in "
            f"{data.warnings!r}"
        )
