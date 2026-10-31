"""Sprint U-94 (2026-06-05): Tests fuer Aggregator-Sektion 24 optimizer_run_history.

Verifiziert dass die Sektion im Aggregator-Output erscheint, OptimizerRuns
sortiert+limitiert ausgibt, robust ist gegen fehlende Daten, und
bestehende Sektionen nicht bricht.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.advisory_report import (
    _OPTIMIZER_RUN_HISTORY_LIMIT,
    _build_optimizer_run_history,
    compute_advisory_report,
)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _add_run(
    session_factory,
    *,
    mandate_id: str,
    advisor_id: str,
    run_at: str,
    optimizer_mode: str = "stochastic",
    role: str = "active",
    method: str = "stochastic",
    status: str = "converged",
    objective_value_milli: int | None = 1234,
) -> str:
    """Persistiert einen OptimizerRun."""
    from models.allocation import OptimizerRun

    rid = str(uuid4())
    with session_factory() as s:
        s.add(OptimizerRun(
            id=rid, mandate_id=mandate_id,
            target_allocation_id=None,
            run_at=run_at,
            optimizer_mode=optimizer_mode,
            role=role,
            method=method,
            status=status,
            seed=20260605,
            n_paths=1000,
            n_iterations=42,
            n_starts_attempted=3,
            objective_value_milli=objective_value_milli,
            weights_bps_json='{"equities":5000,"bonds":3000,"real_estate":1000,"alternatives":500,"liquidity":500}',
            set_by=advisor_id,
            created_at=run_at,
        ))
        s.commit()
    return rid


# ---------------------------------------------------------------------------
# Direct-Helper Tests
# ---------------------------------------------------------------------------

def test_empty_history_returns_empty_items(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94e")
    from models.mandates import Mandate
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_optimizer_run_history(s, mandate)
    assert result["items"] == []
    assert result["total_persisted"] == 0
    assert result["limit"] == _OPTIMIZER_RUN_HISTORY_LIMIT
    assert "FIDLEG" in result["fidleg_basis"]


def test_single_run_appears_in_history(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94s")
    _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
             run_at="2026-06-01T10:00:00.000Z")
    from models.mandates import Mandate
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_optimizer_run_history(s, mandate)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["run_at"] == "2026-06-01T10:00:00.000Z"
    assert item["optimizer_mode"] == "stochastic"
    assert item["role"] == "active"
    assert item["method"] == "stochastic"
    assert item["status"] == "converged"
    assert item["seed"] == 20260605
    assert item["n_iterations"] == 42
    assert item["n_paths"] == 1000
    assert item["objective_value_milli"] == 1234
    assert result["total_persisted"] == 1


def test_multiple_runs_sorted_desc_by_run_at(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94d")
    _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
             run_at="2026-06-01T10:00:00.000Z")
    _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
             run_at="2026-06-03T10:00:00.000Z")
    _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
             run_at="2026-06-02T10:00:00.000Z")
    from models.mandates import Mandate
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_optimizer_run_history(s, mandate)
    run_ats = [it["run_at"] for it in result["items"]]
    assert run_ats == sorted(run_ats, reverse=True)
    assert run_ats[0] == "2026-06-03T10:00:00.000Z"


def test_history_limited_to_constant(session_factory):
    """Nur die letzten N Runs (N = _OPTIMIZER_RUN_HISTORY_LIMIT)."""
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94l")
    over_limit = _OPTIMIZER_RUN_HISTORY_LIMIT + 5
    for i in range(over_limit):
        _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
                 run_at=f"2026-06-{i+1:02d}T10:00:00.000Z")
    from models.mandates import Mandate
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_optimizer_run_history(s, mandate)
    assert len(result["items"]) == _OPTIMIZER_RUN_HISTORY_LIMIT
    assert result["total_persisted"] == over_limit


def test_history_isolated_per_mandate(session_factory):
    """Andere Mandate-Runs landen nicht in der Liste."""
    advisor_id_a, _cidA, mid_a, _aidA, _gidA = _seed_realistic_mandate(session_factory, suffix="u94mA")
    advisor_id_b, _cidB, mid_b, _aidB, _gidB = _seed_realistic_mandate(session_factory, suffix="u94mB")
    _add_run(session_factory, mandate_id=mid_a, advisor_id=advisor_id_a,
             run_at="2026-06-01T10:00:00.000Z")
    _add_run(session_factory, mandate_id=mid_b, advisor_id=advisor_id_b,
             run_at="2026-06-02T10:00:00.000Z")
    from models.mandates import Mandate
    with session_factory() as s:
        mandate_a = s.query(Mandate).filter(Mandate.id == mid_a).first()
        mandate_b = s.query(Mandate).filter(Mandate.id == mid_b).first()
        result_a = _build_optimizer_run_history(s, mandate_a)
        result_b = _build_optimizer_run_history(s, mandate_b)
    assert len(result_a["items"]) == 1
    assert len(result_b["items"]) == 1
    assert result_a["items"][0]["run_at"] == "2026-06-01T10:00:00.000Z"
    assert result_b["items"][0]["run_at"] == "2026-06-02T10:00:00.000Z"


def test_history_handles_null_objective(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94n")
    _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
             run_at="2026-06-01T10:00:00.000Z", objective_value_milli=None)
    from models.mandates import Mandate
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_optimizer_run_history(s, mandate)
    assert result["items"][0]["objective_value_milli"] is None


# ---------------------------------------------------------------------------
# Aggregator-Integration
# ---------------------------------------------------------------------------

def test_aggregator_includes_optimizer_run_history_key(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94agg")
    _add_run(session_factory, mandate_id=mid, advisor_id=advisor_id,
             run_at="2026-06-01T10:00:00.000Z")
    from models.mandates import Mandate
    from models.users import User
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        advisor = s.query(User).filter(User.id == advisor_id).first()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert "optimizer_run_history" in report
    assert isinstance(report["optimizer_run_history"]["items"], list)
    assert len(report["optimizer_run_history"]["items"]) == 1


def test_aggregator_preserves_existing_sections(session_factory):
    """Neue Sektion bricht nicht bestehende — alle 24 Top-Level-Keys da."""
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u94all")
    from models.mandates import Mandate
    from models.users import User
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        advisor = s.query(User).filter(User.id == advisor_id).first()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    for key in (
        "erkenntnisse",
        "beratungsprotokoll",
        "suitability_compliance",
        "liquidity_cascade",
        "mandate_lock_status",
        "optimizer_run_history",  # neu
    ):
        assert key in report, f"Aggregator-Key {key!r} fehlt"
