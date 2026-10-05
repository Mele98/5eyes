"""CMA-APPROVAL-PREFLIGHT-001 -- round 50 red test.

See docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md
(Kontrollrunde 48 per the audit's own numbering, auditing commit 5c88d07).

Confirmed by direct reading of routers/jurisdiction.py::approve_capital_market_assumption
(the real production function, not a summary): it loads the CMA row by id,
sets status="committee_approved" and is_current=1, and commits -- with NO
check whatsoever of completeness (any capital-market return/vol field),
source status transition validity, source freshness, model version, or
candidate hash. The existing test fixture `_make_cma()` in
tests/test_cma_approval_endpoint.py constructs rows with NONE of the
equity/bond/correlation fields set (they default to NULL), and the existing
green test `test_approve_de_candidate_promotes_to_current_and_supersedes_previous`
approves exactly such a row and asserts HTTP 200 + committee_approved +
is_current=1 as the expected, correct behavior.

This file proves the missing-preflight defect directly: approving a CMA
candidate with every capital-market assumption field NULL currently
succeeds and promotes it to the live "current" CMA for its jurisdiction --
i.e. a completely empty capital market model can become what the solver,
Monte Carlo engine and advisory reports treat as the authoritative market
assumption for real client mandates.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.allocation import CapitalMarketAssumption
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_approval_empty.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_empty_cma(row_id, *, jurisdiction, status="data_derived", is_current=0):
    """Mirrors tests/test_cma_approval_endpoint.py::_make_cma exactly --
    sets only identity/status fields, leaving every capital-market
    return/vol/correlation field at its column default (NULL)."""
    now = _now()
    return CapitalMarketAssumption(
        id=row_id, assumption_set_name=f"Standard-{row_id}", version=1,
        valid_from="2026-01-01", is_current=is_current, jurisdiction=jurisdiction,
        tenant_id=None, status=status,
        created_by="tester", created_at=now, updated_at=now,
    )


@pytest.fixture()
def session_with_pm_user(session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(id="main", display_name="Main", slug="main", created_at=now, updated_at=now))
        s.add(User(
            id="pm-a", username="pm-a", password_hash="h", full_name="PM A",
            role="portfolio_management", is_active=1, tenant_id="main",
            created_at=now, updated_at=now,
        ))
        s.commit()
    return session_factory


@pytest.fixture()
def client(session_with_pm_user):
    def override_db():
        with session_with_pm_user() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    user = User(id="pm-a", username="pm-a", password_hash="h", full_name="PM A",
                role="portfolio_management", is_active=1, tenant_id="main")
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_positive_control_empty_cma_has_no_capital_market_fields_set(session_with_pm_user):
    """Sanity check: confirm the fixture really does leave every return/vol
    field NULL, so the red test below isn't accidentally testing a
    populated row."""
    with session_with_pm_user() as s:
        cma = _make_empty_cma("cma-empty-check", jurisdiction="DE")
        s.add(cma)
        s.commit()
        s.refresh(cma)
        assert cma.equity_ch_return_bps is None
        assert cma.equity_intl_return_bps is None
        assert cma.bonds_chf_ig_return_bps is None
        assert cma.bonds_fx_hedged_return_bps is None
        assert cma.real_estate_ch_return_bps is None
        assert cma.alternatives_gold_return_bps is None
        assert cma.liquidity_return_bps is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-APPROVAL-PREFLIGHT-001 -- round 50 red test (approve endpoint "
        "performs no completeness/preflight check; a CMA candidate with "
        "every capital-market return/vol field NULL is promoted to "
        "committee_approved + is_current=1), see audit "
        "docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md"
    ),
)
def test_approve_rejects_completely_empty_candidate(client, session_with_pm_user):
    """A CMA candidate with no capital-market assumptions at all must not
    be approvable -- it cannot serve as a market basis for any solver,
    Monte Carlo run or advisory report. Today's endpoint approves it
    anyway with HTTP 200."""
    with session_with_pm_user() as s:
        s.add(_make_empty_cma("cma-de-empty", jurisdiction="DE"))
        s.commit()

    resp = client.post("/capital-market-assumptions/cma-de-empty/approve")

    assert resp.status_code in (409, 422), (
        f"expected a completeness-preflight rejection (409/422) for a "
        f"fully empty CMA candidate, got {resp.status_code}: {resp.text}"
    )

    with session_with_pm_user() as s:
        reloaded = s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == "cma-de-empty"
        ).one()
        assert reloaded.status == "data_derived", (
            "an empty candidate must remain in data_derived status, "
            "not be silently promoted to committee_approved"
        )
        assert reloaded.is_current == 0
