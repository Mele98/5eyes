"""CMA-EFFECTIVE-DATE-001 (round 40 red test):

services/jurisdiction/resolve.py::resolve_cma_for_jurisdiction() (and its
helpers _current_cma_query()/_ch_current_cma_query(), ~line 55-71) select
the "current" CapitalMarketAssumption row purely by
``is_current == 1 AND deleted_at IS NULL``. There is no ``as_of`` parameter
anywhere in the function signature, and no filter against
``valid_from``/``valid_until`` at all. models/allocation.py also defines
``valid_from``/``valid_until`` as plain ``Column(String)`` with no date type
and no DB check constraint, so nothing downstream enforces temporal
ordering either.

Consequence: a CMA row staged ahead of time for a future effective date
(is_current=1, valid_from/valid_until both far in the future, e.g. for a
2099 assumption set prepared in advance) is returned TODAY as if it were
already in force -- there is no temporal gate preventing a not-yet-valid
row from being used as the live assumption basis for allocation/reporting.

Desired behaviour (not yet implemented): a row whose valid_from lies in the
future relative to "today" must never be selected as the effective CMA.
This test documents that it currently IS selected -- the exact bug.
"""
from __future__ import annotations

import sys
from datetime import date
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
from services.jurisdiction.resolve import resolve_cma_for_jurisdiction  # noqa: E402

NOW = "2026-07-30T00:00:00.000Z"


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-EFFECTIVE-DATE-001 -- round 40 red test, see audit "
        "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_future_dated_current_cma_is_not_selected_as_effective_today(db_session):
    """A CMA row staged for 2099 (is_current=1, valid_from/valid_until both
    far in the future) must not resolve as today's effective CH CMA.

    resolve_cma_for_jurisdiction() has no as_of parameter and applies no
    valid_from/valid_until filtering whatsoever -- it currently returns this
    row anyway, which is the documented bug (CMA-EFFECTIVE-DATE-001)."""
    future_cma = CapitalMarketAssumption(
        id="cma-future-2099",
        assumption_set_name="Future-Staged-2099",
        version=1,
        valid_from="2099-01-01",
        valid_until="2099-12-31",
        is_current=1,
        jurisdiction=None,
        tenant_id=None,
        status="committee_approved",
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(future_cma)
    db_session.commit()

    today = date.today().isoformat()
    assert today < future_cma.valid_from, (
        "Test-Praemisse verletzt: 'heute' muss vor valid_from liegen, sonst "
        "testet dieser Fall nichts."
    )

    resolved = resolve_cma_for_jurisdiction(db_session, "CH")

    assert resolved.id != "cma-future-2099", (
        "resolve_cma_for_jurisdiction() darf eine erst ab "
        f"{future_cma.valid_from} gueltige CMA-Zeile nicht schon heute "
        f"({today}) als aktuell liefern -- die Funktion hat jedoch gar "
        "keine as_of/valid_from-Filterung (CMA-EFFECTIVE-DATE-001)."
    )
