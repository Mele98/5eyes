"""Red test for GOAL-REAL-SPENDING-INFLATION-PARITY-001 (round 40 audit).

Finding (sub-finding: missing model attribute):

``routers/pdf_reports.py`` builds the PDF's SOLL-Goal-Analysis section like
this (around line 672)::

    goal_json = getattr(ta_obj, "goal_analysis_json", None)
    if goal_json:
        parsed = json.loads(goal_json)
        ...

but ``models.allocation.TargetAllocation`` has NO column named
``goal_analysis_json`` at all -- see ``models/allocation.py``. Because the
read uses ``getattr(..., None)`` (a safe default) instead of a direct
attribute access, this never raises ``AttributeError``. It just silently
and *permanently* returns ``None`` for every real ``TargetAllocation`` row
that has ever existed or ever will exist, because nothing anywhere in the
codebase ever assigns to an attribute of that name (confirmed via
repository-wide grep: zero writers, zero ``Column`` definition, zero
migration).

Net effect: the "goal_analysis" list passed into the PDF template
(``routers/pdf_reports.py`` line ~800, ``goal_analysis=goal_analysis``) is
always an empty list. Whatever PDF section is supposed to render the
SOLL-goal-analysis from this value renders empty, in every report, for
every mandate, with no error surfaced to anyone -- a silent, permanent data
gap.

Likely intended fix: ``TargetAllocation`` already has a sibling column,
``goal_achievability_json`` (model line ~77, with a real DB column, a real
Alembic migration entry, and real writers in
``services/portfolio_engine.py``), which carries essentially the same kind
of payload (a JSON list of per-goal analysis/achievability entries) and is
read correctly via the identical ``getattr(ta_obj, "goal_achievability_json",
None)`` pattern a few lines below (line ~768) in the very same function.
That strongly suggests the ``goal_analysis_json`` read at line 672 is a
copy-paste/rename artifact that should have read
``goal_achievability_json`` (or a real ``goal_analysis_json`` column should
be added and populated) -- not a second, never-populated field.

This test is wrapped ``xfail(strict=True)`` so the suite stays green until
a human decides which of the two fixes is correct; see the audit doc
2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md (not
committed in this worktree).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402 - importing registers full SQLAlchemy metadata
from models.allocation import TargetAllocation  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ta_goal_analysis_json_missing.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_target_allocation(**overrides) -> TargetAllocation:
    now = _utc_now_iso()
    defaults = dict(
        id="ta-goal-analysis-missing",
        mandate_id="mandate-goal-analysis-missing",
        version=1,
        is_current=1,
        target_equities_bps=4000,
        target_bonds_bps=4000,
        target_real_estate_bps=1000,
        target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=3000,
        band_equities_max_bps=5000,
        band_bonds_min_bps=3000,
        band_bonds_max_bps=5000,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=2000,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=1000,
        band_liquidity_min_bps=200,
        band_liquidity_max_bps=1000,
        policy_id="policy-goal-analysis-missing",
        set_by="user-goal-analysis-missing",
        set_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return TargetAllocation(**defaults)


def test_target_allocation_model_has_no_goal_analysis_json_column():
    """Introspection: confirm `goal_analysis_json` is not a real column.

    This is the root cause the PDF-reading code at
    `routers/pdf_reports.py:672` silently relies on `getattr(..., None)`
    for -- there genuinely is no such column on the ORM model.
    """
    column_names = {c.name for c in TargetAllocation.__table__.columns}

    assert "goal_analysis_json" not in column_names, (
        "goal_analysis_json now exists as a real column -- the round-40 "
        "finding GOAL-REAL-SPENDING-INFLATION-PARITY-001 may be fixed; "
        "re-check routers/pdf_reports.py line ~672 and remove/update this "
        "xfail if the PDF SOLL-goal-analysis section is now populated."
    )
    # The sibling field that IS a real, persisted, written-to column and
    # that already carries the equivalent payload (per-goal JSON list),
    # confirming a real data source exists -- it is simply not the one the
    # PDF SOLL-goal-analysis section reads from.
    assert "goal_achievability_json" in column_names


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-REAL-SPENDING-INFLATION-PARITY-001 — round 40 red test, see "
        "audit 2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_pdf_reports_goal_analysis_json_read_is_always_none_for_real_ta_row(session_factory):
    """Replicates the exact `getattr` call from `routers/pdf_reports.py`
    (line ~672) against a real, persisted `TargetAllocation` row and shows
    it always yields `None` -- even though the row carries real per-goal
    achievability data in the sibling `goal_achievability_json` column that
    the very same function reads correctly a few lines later (line ~768).
    """
    achievability_payload = [
        {
            "rank": 1,
            "label": "Hauskauf",
            "achievement_score": 0.82,
            "target_text": "CHF 250'000 bis 2032",
            "shortfall_rappen": 0,
        }
    ]

    with session_factory() as session:
        ta = _make_target_allocation(
            goal_achievability_json=json.dumps(achievability_payload),
        )
        session.add(ta)
        session.commit()
        session.refresh(ta)

        # Exact code path from routers/pdf_reports.py:672.
        goal_json = getattr(ta, "goal_analysis_json", None)

        # Sanity: the row genuinely has real per-goal data available --
        # just not under the attribute name the PDF SOLL-section reads.
        raw_achievability = getattr(ta, "goal_achievability_json", None)
        assert raw_achievability is not None
        assert json.loads(raw_achievability) == achievability_payload

        # This is the bug: `goal_json` must carry the same kind of
        # non-None, real per-goal payload so the PDF's SOLL-goal-analysis
        # section has something to render. Today it is always None.
        assert goal_json is not None, (
            "ta.goal_analysis_json is always None because no such column "
            "exists on TargetAllocation -- the PDF SOLL-goal-analysis "
            "section (routers/pdf_reports.py ~672-690) silently renders "
            "empty for every mandate. Likely intended fix: read from the "
            "sibling `goal_achievability_json` column instead (see module "
            "docstring), or add+populate a real `goal_analysis_json` "
            "column."
        )
