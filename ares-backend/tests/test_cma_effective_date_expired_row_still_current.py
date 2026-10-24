"""CMA-EFFECTIVE-DATE-001 (expired-row variant, round 40 red test).

services/jurisdiction/resolve.py::resolve_cma_for_jurisdiction (via
_current_cma_query, ~line 55-65) filters only on
CapitalMarketAssumption.is_current == 1 and deleted_at IS NULL. It never
checks CapitalMarketAssumption.valid_until. A row that is flagged
is_current=1 but whose own valid_until lies long in the past (e.g. the
assumption set was superseded on 2021-01-01 but the is_current flag was
never flipped, or a data-entry error back-dated valid_until) is therefore
still selected as "the" effective CMA for CH -- even though it is, by its
own validity window, expired.

Desired behaviour: resolve_cma_for_jurisdiction must NOT return a row whose
valid_until is in the past relative to "today". This test documents the
current (wrong) behaviour as a red test; see audit
2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md
(not committed in this repo).

Fixture/construction pattern copied from
tests/test_jurisdiction_resolvers.py::_make_cma / db_session.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
# Alle Models importieren, damit SQLAlchemy alle FK-Beziehungen aufloesen
# kann (Vorbild: tests/test_jurisdiction_resolvers.py).
import models.allocation  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.jurisdiction  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401

from models.allocation import CapitalMarketAssumption  # noqa: E402
from services.jurisdiction.exceptions import (  # noqa: E402
    JurisdictionReferenceDataMissingError,
)
from services.jurisdiction.resolve import resolve_cma_for_jurisdiction  # noqa: E402

NOW = "2026-10-04T00:00:00.000Z"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cma_effective_date_test.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_expired_but_current_cma(row_id: str) -> CapitalMarketAssumption:
    """is_current=1, but valid_until is long in the past (2020-12-31)."""
    return CapitalMarketAssumption(
        id=row_id,
        assumption_set_name=f"Standard-{row_id}",
        version=1,
        valid_from="2019-01-01",
        valid_until="2020-12-31",
        is_current=1,
        jurisdiction=None,
        tenant_id=None,
        status="committee_approved",
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-EFFECTIVE-DATE-001 -- round 40 red test, see audit "
        "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_resolve_cma_rejects_row_whose_valid_until_is_in_the_past(db_session):
    """An is_current=1 row that is expired by its own valid_until must NOT
    be returned as the effective CH CMA. With no other candidate row
    present, the resolver's own fail-closed contract (see resolve.py
    docstring: "es wird NIEMALS eine erfundene Zahl oder None
    zurueckgegeben") means an expired-only state must behave like "no
    current data found" -> JurisdictionReferenceDataMissingError.

    Currently resolve_cma_for_jurisdiction ignores valid_until entirely and
    happily returns this expired row instead of raising, which is the bug
    this test documents."""
    expired = _make_expired_but_current_cma("cma-ch-expired-but-flagged-current")
    db_session.add(expired)
    db_session.commit()

    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_cma_for_jurisdiction(db_session, "CH")
