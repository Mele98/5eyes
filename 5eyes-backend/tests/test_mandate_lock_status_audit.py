"""Sprint U-22 (Roadmap-Punkt 22, 2026-06-03): Mandate-Lock-Status Audit.

Pre-U-22
--------
Mandate sind read-only wenn deleted_at/closed_at gesetzt oder Status
!= 'Aktiv'. Risikobudget-Verletzung machte Read-Only-State silent.
Kein einheitlicher Lock-Status-Check.

Post-U-22
---------
- services/mandate_lock_audit.py: audit_mandate_editability(db, mandate)
  -> {is_editable, lock_reasons[], labels, status-snapshot}
- Aggregator-Sektion 22 mandate_lock_status
- Reasons: soft_deleted, mandate_closed, status_not_aktiv,
  optimizer_diverged, risk_budget_violated
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.mandate_lock_audit import (  # noqa: E402
    ACTIVE_STATUSES,
    REASON_CLOSED,
    REASON_DELETED,
    REASON_INACTIVE_STATUS,
    REASON_LABELS,
    REASON_OPTIMIZER_DIVERGED,
    REASON_RISK_BUDGET_VIOLATED,
    audit_mandate_editability,
)


def _mandate(**overrides):
    base = {
        "id": "MX-TEST",
        "status": "Aktiv",
        "deleted_at": None,
        "closed_at": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _opt_run(**overrides):
    base = {
        "id": "run-001",
        "role": "active",
        "status": "converged",
        "run_at": "2026-06-01T10:00:00Z",
    }
    base.update(overrides)
    return MagicMock(**base)


def _ta(**overrides):
    base = {
        "id": "ta-001",
        "is_current": 1,
        "deleted_at": None,
        "risky_fraction_bps_at_generation": None,
        "risk_budget_bps_at_generation": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _stub_db(*, optimizer_runs=None, target_allocation=None):
    db = MagicMock()
    runs = optimizer_runs or []

    def _chain_for(model):
        name = getattr(model, "__name__", str(model))
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        if "OptimizerRun" in name:
            chain.first.return_value = runs[0] if runs else None
        elif "TargetAllocation" in name:
            chain.first.return_value = target_allocation
        else:
            chain.first.return_value = None
        return chain

    db.query.side_effect = _chain_for
    return db


# ---------------------------------------------------------------------------
# Konstanten + Labels
# ---------------------------------------------------------------------------

def test_active_statuses_include_aktiv_and_entwurf():
    assert "Aktiv" in ACTIVE_STATUSES
    assert "Entwurf" in ACTIVE_STATUSES


def test_active_statuses_exclude_inaktiv_geschlossen():
    assert "Inaktiv" not in ACTIVE_STATUSES
    assert "Geschlossen" not in ACTIVE_STATUSES


def test_reason_labels_cover_all_codes():
    """Drift-Schutz: jeder Reason-Code hat einen Berater-Text."""
    for code in (
        REASON_DELETED, REASON_CLOSED, REASON_INACTIVE_STATUS,
        REASON_OPTIMIZER_DIVERGED, REASON_RISK_BUDGET_VIOLATED,
    ):
        assert code in REASON_LABELS
        assert len(REASON_LABELS[code]) > 10


# ---------------------------------------------------------------------------
# audit_mandate_editability — Szenarien
# ---------------------------------------------------------------------------

def test_active_mandate_is_editable():
    db = _stub_db()
    result = audit_mandate_editability(db, _mandate())
    assert result["is_editable"] is True
    assert result["lock_reasons"] == []
    assert result["lock_reason_labels"] == {}
    assert result["mandate_status"] == "Aktiv"


def test_soft_deleted_mandate_locked():
    db = _stub_db()
    result = audit_mandate_editability(
        db, _mandate(deleted_at="2026-05-01T10:00:00Z"),
    )
    assert result["is_editable"] is False
    assert REASON_DELETED in result["lock_reasons"]


def test_closed_mandate_locked():
    db = _stub_db()
    result = audit_mandate_editability(
        db, _mandate(closed_at="2026-05-01T10:00:00Z"),
    )
    assert result["is_editable"] is False
    assert REASON_CLOSED in result["lock_reasons"]


def test_inactive_status_locks():
    db = _stub_db()
    result = audit_mandate_editability(db, _mandate(status="Geschlossen"))
    assert result["is_editable"] is False
    assert REASON_INACTIVE_STATUS in result["lock_reasons"]


def test_entwurf_status_is_editable():
    """'Entwurf' ist in ACTIVE_STATUSES -> kein Lock."""
    db = _stub_db()
    result = audit_mandate_editability(db, _mandate(status="Entwurf"))
    assert result["is_editable"] is True


def test_diverged_optimizer_locks():
    db = _stub_db(optimizer_runs=[_opt_run(status="diverged")])
    result = audit_mandate_editability(db, _mandate())
    assert result["is_editable"] is False
    assert REASON_OPTIMIZER_DIVERGED in result["lock_reasons"]


def test_diverged_infeasible_optimizer_locks():
    db = _stub_db(optimizer_runs=[_opt_run(status="diverged_infeasible")])
    result = audit_mandate_editability(db, _mandate())
    assert REASON_OPTIMIZER_DIVERGED in result["lock_reasons"]


def test_converged_optimizer_does_not_lock():
    db = _stub_db(optimizer_runs=[_opt_run(status="converged")])
    result = audit_mandate_editability(db, _mandate())
    assert REASON_OPTIMIZER_DIVERGED not in result["lock_reasons"]
    assert result["is_editable"] is True


def test_risk_budget_violated_locks():
    """Wenn risky > budget -> Lock-Reason."""
    db = _stub_db(target_allocation=_ta(
        risky_fraction_bps_at_generation=6000,  # 60%
        risk_budget_bps_at_generation=4500,     # 45%
    ))
    result = audit_mandate_editability(db, _mandate())
    assert REASON_RISK_BUDGET_VIOLATED in result["lock_reasons"]
    assert result["is_editable"] is False


def test_risk_budget_at_limit_does_not_lock():
    """Risky == budget ist OK (genau am Limit)."""
    db = _stub_db(target_allocation=_ta(
        risky_fraction_bps_at_generation=4500,
        risk_budget_bps_at_generation=4500,
    ))
    result = audit_mandate_editability(db, _mandate())
    assert REASON_RISK_BUDGET_VIOLATED not in result["lock_reasons"]


def test_risk_budget_missing_values_no_lock():
    """NULL-Werte (pre-Optimizer-TA) -> kein Lock."""
    db = _stub_db(target_allocation=_ta(
        risky_fraction_bps_at_generation=None,
        risk_budget_bps_at_generation=None,
    ))
    result = audit_mandate_editability(db, _mandate())
    assert REASON_RISK_BUDGET_VIOLATED not in result["lock_reasons"]


def test_multiple_reasons_dedupe_and_all_listed():
    """Mehrere Reasons gleichzeitig moeglich."""
    db = _stub_db(
        optimizer_runs=[_opt_run(status="diverged")],
        target_allocation=_ta(
            risky_fraction_bps_at_generation=6000,
            risk_budget_bps_at_generation=4500,
        ),
    )
    result = audit_mandate_editability(
        db, _mandate(closed_at="2026-05-01T10:00:00Z"),
    )
    assert REASON_CLOSED in result["lock_reasons"]
    assert REASON_OPTIMIZER_DIVERGED in result["lock_reasons"]
    assert REASON_RISK_BUDGET_VIOLATED in result["lock_reasons"]
    # Dedupe: keine Duplikate
    assert len(result["lock_reasons"]) == len(set(result["lock_reasons"]))


def test_labels_present_for_every_reason():
    db = _stub_db(optimizer_runs=[_opt_run(status="diverged")])
    result = audit_mandate_editability(db, _mandate())
    for reason in result["lock_reasons"]:
        assert reason in result["lock_reason_labels"]


def test_db_error_returns_editable_degraded():
    """Schema-Mismatch beim OptimizerRun-Query -> kein Crash, kein Lock."""
    db = MagicMock()
    db.query.side_effect = RuntimeError("table missing")
    result = audit_mandate_editability(db, _mandate())
    # Mandate-Felder werden noch gepruefte (deleted/closed/status) — fail-safe.
    assert result["is_editable"] is True


def test_latest_optimizer_status_exposed():
    db = _stub_db(optimizer_runs=[_opt_run(status="converged")])
    result = audit_mandate_editability(db, _mandate())
    assert result["latest_optimizer_status"] == "converged"


def test_fidleg_basis_string_stable():
    db = _stub_db()
    result = audit_mandate_editability(db, _mandate())
    assert result["fidleg_basis"] == "Art. 16 / Art. 11 FIDLEG"


# ---------------------------------------------------------------------------
# Aggregator-Integration (Sektion 22)
# ---------------------------------------------------------------------------

def test_compute_advisory_report_includes_section_22():
    from services.advisory_report import compute_advisory_report
    import inspect
    source = inspect.getsource(compute_advisory_report)
    assert "mandate_lock_status" in source
    assert "Sektion 22" in source


def test_build_mandate_lock_status_degraded_on_error():
    from services.advisory_report import _build_mandate_lock_status
    db = MagicMock()
    db.query.side_effect = RuntimeError("simulated")
    result = _build_mandate_lock_status(db, _mandate())
    assert result["is_editable"] is True
    assert result["fidleg_basis"] == "Art. 16 / Art. 11 FIDLEG"
