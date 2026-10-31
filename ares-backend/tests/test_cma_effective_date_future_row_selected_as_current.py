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

Behaviour (fixed): a row whose valid_from lies in the future relative to
"today" is never selected as the effective CMA; with no other row the
resolver fails closed (JurisdictionReferenceDataMissingError).
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
from services.jurisdiction.exceptions import (  # noqa: E402
    JurisdictionReferenceDataConflictError,
    JurisdictionReferenceDataMissingError,
)
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


def test_future_dated_current_cma_is_not_selected_as_effective_today(db_session):
    """A CMA row staged for 2099 (is_current=1, valid_from/valid_until both
    far in the future) must not resolve as today's effective CH CMA.

    Vor dem Fix hatte resolve_cma_for_jurisdiction() keine as_of-/
    valid_from-Filterung und lieferte diese Zeile (CMA-EFFECTIVE-DATE-001)."""
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

    # Test-Korrektur (CMA-EFFECTIVE-DATE-001): die urspruengliche Assertion
    # `resolved.id != future` konnte nach dem Fix nie gruen werden -- ohne
    # andere Zeile ist das korrekte Verhalten des fail-closed-Resolvers eine
    # JurisdictionReferenceDataMissingError, kein Rueckgabewert.
    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_cma_for_jurisdiction(db_session, "CH")


def test_future_dated_row_does_not_displace_currently_valid_row(db_session):
    """ADR-6b (Effective-Resolver): eine vorab erfasste 2099-Zeile und die
    heute gueltige Zeile duerfen koexistieren; wirksam ist die heute gueltige,
    ohne Mehrdeutigkeits-Konflikt. Am 2099-Stichtag kehrt sich das um."""
    db_session.add_all([
        CapitalMarketAssumption(
            id="cma-current", assumption_set_name="Current", version=1,
            valid_from="2020-01-01", valid_until=None, is_current=1,
            jurisdiction=None, tenant_id=None, status="committee_approved",
            created_by="tester", created_at=NOW, updated_at=NOW,
        ),
        CapitalMarketAssumption(
            id="cma-future-2099", assumption_set_name="Future-Staged-2099",
            version=2, valid_from="2099-01-01", valid_until="2099-12-31",
            is_current=1, jurisdiction=None, tenant_id=None,
            status="committee_approved", created_by="tester",
            created_at=NOW, updated_at=NOW,
        ),
    ])
    db_session.commit()

    assert resolve_cma_for_jurisdiction(db_session, "CH").id == "cma-current"
    # 2099-06-01: beide Fenster ueberlappen -> echte Mehrdeutigkeit, fail-closed.
    with pytest.raises(JurisdictionReferenceDataConflictError):
        resolve_cma_for_jurisdiction(db_session, "CH", as_of=date(2099, 6, 1))


def test_unparseable_validity_date_fails_closed(db_session):
    """Ein nicht lesbares valid_from darf weder still ein- noch ausgeschlossen
    werden -- die Gueltigkeit ist unbestimmbar."""
    db_session.add(CapitalMarketAssumption(
        id="cma-bad-date", assumption_set_name="Bad", version=1,
        valid_from="kein-datum", is_current=1, jurisdiction=None,
        tenant_id=None, status="committee_approved", created_by="tester",
        created_at=NOW, updated_at=NOW,
    ))
    db_session.commit()
    with pytest.raises(JurisdictionReferenceDataConflictError):
        resolve_cma_for_jurisdiction(db_session, "CH")
