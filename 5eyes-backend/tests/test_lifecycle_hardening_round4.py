"""Lifecycle-Haertung (Audit Runde 4, 2026-07-09):

F1: Snapshot-"latest" deterministisch bei gleichem snapshot_date (Tie-Breaker
    created_at) -> get_drift/list_snapshots duerfen nicht den aelteren Snapshot
    desselben Kalendertags als aktuell waehlen.
F4: finalize_recommendation verlangt, dass die referenzierte Soll-Allokation
    is_current ist -> sonst wuerde ein finalisierter Run "verwaisen".
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401 — registriert alle Modelle (FK 'tenants'/'mandates')
from database import new_uuid
from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.review import RecommendationRun
from models.snapshots import StrategySnapshot
from routers.review import _validate_recommendation_for_finalization
from routers.snapshots import list_snapshots
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _add_snapshot(session_factory, mandate_id, created_by, *, snapshot_date, created_at) -> str:
    sid = new_uuid()
    with session_factory() as s:
        s.add(StrategySnapshot(
            id=sid, mandate_id=mandate_id, snapshot_date=snapshot_date,
            advisory_assets_rappen=100_000_00, risk_profile_score=50,
            risk_profile_label="Ausgewogen",
            soll_equities_bps=4000, soll_bonds_bps=3000, soll_real_estate_bps=1500,
            soll_liquidity_bps=500, soll_alternatives_bps=1000,
            created_by=created_by, created_at=created_at, updated_at=created_at,
        ))
        s.commit()
    return sid


def _make_allocation(session_factory, mandate_id, assessment_id, set_by, *, is_current) -> str:
    aid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        s.add(TargetAllocation(
            id=aid, mandate_id=mandate_id, version=1, is_current=(1 if is_current else 0),
            target_equities_bps=4000, target_bonds_bps=3000, target_real_estate_bps=1500,
            target_alternatives_bps=1000, target_liquidity_bps=500,
            band_equities_min_bps=3000, band_equities_max_bps=5000,
            band_bonds_min_bps=2000, band_bonds_max_bps=4000,
            band_real_estate_min_bps=1000, band_real_estate_max_bps=2000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=2000,
            band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
            based_on_assessment_id=assessment_id, policy_id="policy-f4", set_by=set_by,
            set_at=now, created_at=now, updated_at=now,
        ))
        s.commit()
    return aid


def _make_run(session_factory, mandate_id, allocation_id, assessment_id, created_by) -> str:
    rid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        s.add(RecommendationRun(
            id=rid, mandate_id=mandate_id, client_id=mandate.client_id,
            assessment_id=assessment_id, target_allocation_id=allocation_id,
            policy_id="policy-f4", run_type="Optimizer", result_status="Draft",
            created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()
    return rid


# --- F1 --------------------------------------------------------------------

def test_snapshot_latest_deterministic_on_same_day(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="lc-f1")
    day = "2026-07-09"
    older = _add_snapshot(session_factory, mid, advisor_id,
                          snapshot_date=day, created_at=_iso(datetime(2026, 7, 9, 8, 0, 0)))
    newer = _add_snapshot(session_factory, mid, advisor_id,
                          snapshot_date=day, created_at=_iso(datetime(2026, 7, 9, 15, 0, 0)))
    user = SimpleNamespace(id=advisor_id, role="advisor", tenant_id=None, is_admin=False)
    with session_factory() as db:
        rows = list_snapshots(mid, db=db, current_user=user)
    # Bei gleichem snapshot_date gewinnt der zuletzt ERSTELLTE (created_at desc).
    assert rows[0].id == newer, "list_snapshots muss bei Datums-Gleichstand den neueren zuerst liefern"
    assert rows[1].id == older


# --- F4 --------------------------------------------------------------------

def test_finalize_rejects_non_current_allocation(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="lc-f4")
    MSG = "Empfehlung basiert nicht auf der aktuellen Soll-Allokation."

    # Allokation NICHT aktuell -> Finalisierung muss den Fehler melden.
    alloc_old = _make_allocation(session_factory, mid, aid, advisor_id, is_current=False)
    run_old = _make_run(session_factory, mid, alloc_old, aid, advisor_id)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_old).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
    assert MSG in errors

    # Allokation aktuell -> genau dieser Fehler darf NICHT mehr auftreten.
    alloc_cur = _make_allocation(session_factory, mid, aid, advisor_id, is_current=True)
    run_cur = _make_run(session_factory, mid, alloc_cur, aid, advisor_id)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_cur).first()
        errors2, _w2 = _validate_recommendation_for_finalization(db, mandate, run)
    assert MSG not in errors2
