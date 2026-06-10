"""Sprint U-69 (Roadmap-Punkt 69, 2026-06-03): Recommendation-Run-
Methodology Audit.

Hintergrund
-----------
OptimizerRun-Tabelle persistiert method/mode/status/seed/n_paths/
iterations seit Sprint U-P9+. Im Berater-UI fehlte aber ein Hinweis
welche Methode den aktuellen Run produziert hat (stochastic vs
fallback). U-69 schafft Sichtbarkeit via Aggregator-Sektion 21.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.recommendation_audit import (  # noqa: E402
    ACCEPTABLE_STATUSES,
    STATUS_LABELS,
    _is_acceptable,
    _label_for_status,
    _safe_json,
    audit_recommendation_methodology,
    summarize_optimizer_run,
)


def _run(**overrides):
    base = {
        "id": "run-001",
        "mandate_id": "MX-TEST",
        "run_at": "2026-06-01T10:00:00Z",
        "optimizer_mode": "shadow_stochastic",
        "role": "shadow",
        "method": "stochastic",
        "status": "converged",
        "seed": 42,
        "n_paths": 1000,
        "n_iterations": 250,
        "n_starts_attempted": 3,
        "objective_value_milli": 1234,
        "constraint_violations_json": None,
        "reasoning_json": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _stub_mandate(mid: str = "MX-TEST"):
    m = MagicMock()
    m.id = mid
    return m


def _stub_db(runs):
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.all.return_value = runs
    db.query.return_value = query_chain
    return db


# ---------------------------------------------------------------------------
# Status-Labels + Acceptable-Logik
# ---------------------------------------------------------------------------

def test_status_labels_cover_known_states():
    expected = {
        "converged", "converged_robustified",
        "diverged", "diverged_infeasible", "fallback_house_matrix",
    }
    assert expected == set(STATUS_LABELS.keys())


def test_label_for_status_unknown_falls_back_to_raw():
    assert _label_for_status("brand_new_state") == "brand_new_state"


def test_label_for_status_none_returns_placeholder():
    assert _label_for_status(None) == "(kein Status)"


def test_acceptable_statuses_include_fallback():
    """fallback_house_matrix ist FINMA-akzeptabel (produktiver Default)."""
    assert "fallback_house_matrix" in ACCEPTABLE_STATUSES
    assert "converged" in ACCEPTABLE_STATUSES
    assert "converged_robustified" in ACCEPTABLE_STATUSES


def test_diverged_not_acceptable():
    assert _is_acceptable("diverged") is False
    assert _is_acceptable("diverged_infeasible") is False
    assert _is_acceptable(None) is False


# ---------------------------------------------------------------------------
# _safe_json
# ---------------------------------------------------------------------------

def test_safe_json_handles_none_and_empty():
    assert _safe_json(None) is None
    assert _safe_json("") is None
    assert _safe_json(b"") is None


def test_safe_json_passthrough_dict():
    assert _safe_json({"a": 1}) == {"a": 1}


def test_safe_json_parses_valid_string():
    assert _safe_json('{"a": 1}') == {"a": 1}
    assert _safe_json('["x", "y"]') == ["x", "y"]


def test_safe_json_returns_none_on_invalid():
    assert _safe_json("not json") is None


# ---------------------------------------------------------------------------
# summarize_optimizer_run
# ---------------------------------------------------------------------------

def test_summarize_includes_full_payload():
    run = _run(
        constraint_violations_json='["risk_budget_exceeded"]',
        reasoning_json='["Solver converged after 3 starts"]',
    )
    summary = summarize_optimizer_run(run)
    assert summary["run_id"] == "run-001"
    assert summary["status_label"] == "konvergiert"
    assert summary["is_acceptable"] is True
    assert summary["constraint_violations"] == ["risk_budget_exceeded"]
    assert summary["reasoning"] == ["Solver converged after 3 starts"]


def test_summarize_handles_null_json_fields():
    run = _run(constraint_violations_json=None, reasoning_json=None)
    summary = summarize_optimizer_run(run)
    assert summary["constraint_violations"] == []
    assert summary["reasoning"] == []


def test_summarize_diverged_run_not_acceptable():
    run = _run(status="diverged")
    summary = summarize_optimizer_run(run)
    assert summary["status_label"] == "divergiert"
    assert summary["is_acceptable"] is False


# ---------------------------------------------------------------------------
# audit_recommendation_methodology
# ---------------------------------------------------------------------------

def test_audit_empty_mandate_returns_empty():
    db = _stub_db([])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["total_runs"] == 0
    assert result["latest_run"] is None
    assert result["latest_active_run"] is None
    assert result["is_compliant"] is True


def test_audit_only_shadow_runs_is_compliant():
    """Shadow-only ist Stage-8-Pre-Production -> kein aktiver Run, OK."""
    db = _stub_db([
        _run(role="shadow", status="converged"),
        _run(id="r2", role="shadow", status="diverged"),
    ])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["total_runs"] == 2
    assert result["shadow_count"] == 2
    assert result["active_count"] == 0
    assert result["latest_active_run"] is None
    assert result["is_compliant"] is True


def test_audit_active_converged_is_compliant():
    db = _stub_db([
        _run(role="active", status="converged"),
    ])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["active_count"] == 1
    assert result["latest_active_run"]["status"] == "converged"
    assert result["is_compliant"] is True


def test_audit_active_diverged_is_NOT_compliant():
    """Aktiver Run divergiert -> Compliance-Verstoss (Berater muss reagieren)."""
    db = _stub_db([
        _run(role="active", status="diverged"),
    ])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["is_compliant"] is False


def test_audit_active_fallback_house_matrix_is_compliant():
    """Fallback HouseMatrix-Mid ist als Default akzeptabel."""
    db = _stub_db([
        _run(role="active", status="fallback_house_matrix",
             method="fallback_house_matrix"),
    ])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["fallback_count"] == 1
    assert result["is_compliant"] is True


def test_audit_picks_latest_by_order():
    """Liste ist DESC sortiert -> erstes Element ist jungster."""
    db = _stub_db([
        _run(id="r-newest", role="active", run_at="2026-06-01T15:00:00Z"),
        _run(id="r-older", role="active", run_at="2026-05-01T15:00:00Z"),
    ])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["latest_run"]["run_id"] == "r-newest"
    assert result["latest_active_run"]["run_id"] == "r-newest"


def test_audit_counts_methods_correctly():
    db = _stub_db([
        _run(id="r1", role="active", method="stochastic"),
        _run(id="r2", role="shadow", method="stochastic"),
        _run(id="r3", role="shadow", method="fallback_house_matrix"),
    ])
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["total_runs"] == 3
    assert result["active_count"] == 1
    assert result["shadow_count"] == 2
    assert result["fallback_count"] == 1


def test_audit_db_error_returns_degraded():
    db = MagicMock()
    db.query.side_effect = RuntimeError("table missing")
    result = audit_recommendation_methodology(db, _stub_mandate())
    assert result["total_runs"] == 0
    assert result["is_compliant"] is True
    assert result["fidleg_basis"] == "Art. 16 FIDLEG"


# ---------------------------------------------------------------------------
# Aggregator-Integration (Sektion 21)
# ---------------------------------------------------------------------------

def test_compute_advisory_report_includes_section_21():
    # Seit PR #110 liegt die Sektions-Verdrahtung in _compute_advisory_report_inner.
    from services.advisory_report import _compute_advisory_report_inner
    import inspect
    source = inspect.getsource(_compute_advisory_report_inner)
    assert "recommendation_methodology" in source
    assert "Sektion 21" in source


def test_build_recommendation_methodology_degraded_on_error():
    from services.advisory_report import _build_recommendation_methodology
    db = MagicMock()
    db.query.side_effect = RuntimeError("simulated")
    result = _build_recommendation_methodology(db, _stub_mandate())
    assert result["total_runs"] == 0
    assert result["is_compliant"] is True
