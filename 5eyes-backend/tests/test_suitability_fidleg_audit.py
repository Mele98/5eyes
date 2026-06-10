"""Sprint U-66 (Roadmap-Punkt 66, 2026-06-03): FIDLEG-Suitability-Audit.

Hintergrund
-----------
FIDLEG Art. 11-13 verlangt Geeignetheitspruefung VOR Anlageempfehlung.
Modelle (SuitabilityCheck + AdvisoryLog.suitability_check_id) gibt es
schon, aber kein Code-Pfad pruefte Compliance.

Diese Suite verifiziert services/suitability_audit.py und seine
Integration in compute_advisory_report (Sektion 19).

Test-Strategie: Pure-Unit mit MagicMock-DB (kein echtes SQLAlchemy
brauchen) — schnell, deterministisch.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.suitability_audit import (  # noqa: E402
    DUTY_TYPES_REQUIRING_SUITABILITY,
    SUITABILITY_FRESHNESS_MAX_DAYS,
    _parse_iso,
    audit_mandate_suitability,
    evaluate_suitability_freshness,
)


# ---------------------------------------------------------------------------
# ISO-Parser
# ---------------------------------------------------------------------------

def test_parse_iso_handles_z_suffix():
    dt = _parse_iso("2026-06-03T10:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 6 and dt.day == 3


def test_parse_iso_handles_offset():
    dt = _parse_iso("2026-06-03T10:00:00+02:00")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_iso_naive_input_becomes_utc_aware():
    dt = _parse_iso("2026-06-03T10:00:00")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_iso_invalid_returns_none():
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None
    assert _parse_iso(12345) is None


# ---------------------------------------------------------------------------
# Freshness-Evaluator
# ---------------------------------------------------------------------------

def test_freshness_check_is_fresh_recent():
    ref = datetime(2026, 6, 3, tzinfo=timezone.utc)
    chk = ref - timedelta(days=30)
    result = evaluate_suitability_freshness(chk, ref)
    assert result["fresh"] is True
    assert result["reason"] == "ok"
    assert result["age_days"] == 30


def test_freshness_check_missing_dt_not_fresh():
    ref = datetime(2026, 6, 3, tzinfo=timezone.utc)
    result = evaluate_suitability_freshness(None, ref)
    assert result["fresh"] is False
    assert result["reason"] == "missing_checked_at"
    assert result["age_days"] is None


def test_freshness_check_after_advisory_not_fresh():
    """Geeignetheitspruefung NACH der Beratung -> Verstoss."""
    ref = datetime(2026, 6, 3, tzinfo=timezone.utc)
    chk = ref + timedelta(days=5)
    result = evaluate_suitability_freshness(chk, ref)
    assert result["fresh"] is False
    assert result["reason"] == "check_after_advisory"


def test_freshness_stale_over_365_days():
    ref = datetime(2026, 6, 3, tzinfo=timezone.utc)
    chk = ref - timedelta(days=400)
    result = evaluate_suitability_freshness(chk, ref)
    assert result["fresh"] is False
    assert result["reason"] == "stale"
    assert result["age_days"] == 400


def test_freshness_at_exactly_365_days_is_fresh():
    ref = datetime(2026, 6, 3, tzinfo=timezone.utc)
    chk = ref - timedelta(days=SUITABILITY_FRESHNESS_MAX_DAYS)
    result = evaluate_suitability_freshness(chk, ref)
    assert result["fresh"] is True


def test_freshness_custom_max_age_override():
    """Custom max_age_days respektiert (z.B. 180 fuer striktere Praxis)."""
    ref = datetime(2026, 6, 3, tzinfo=timezone.utc)
    chk = ref - timedelta(days=200)
    result = evaluate_suitability_freshness(chk, ref, max_age_days=180)
    assert result["fresh"] is False


# ---------------------------------------------------------------------------
# DUTY_TYPES Konstante
# ---------------------------------------------------------------------------

def test_duty_types_include_full_advisory():
    assert "advisory_individual" in DUTY_TYPES_REQUIRING_SUITABILITY
    assert "advisory_portfolio" in DUTY_TYPES_REQUIRING_SUITABILITY
    assert "portfolio_management" in DUTY_TYPES_REQUIRING_SUITABILITY


def test_duty_types_exclude_execution_only():
    """FIDLEG Art. 13 Abs. 3: Execution-Only braucht keine Pruefung."""
    assert "execution_only" not in DUTY_TYPES_REQUIRING_SUITABILITY
    assert "no_advice" not in DUTY_TYPES_REQUIRING_SUITABILITY


# ---------------------------------------------------------------------------
# audit_mandate_suitability — Helpers
# ---------------------------------------------------------------------------

def _log(**overrides):
    base = {
        "id": "log-001",
        "mandate_id": "MX-TEST",
        "duty_type": "advisory_individual",
        "entry_datetime": "2026-06-01T10:00:00Z",
        "entry_date": "2026-06-01",
        "suitability_check_id": "chk-001",
    }
    base.update(overrides)
    return MagicMock(**base)


def _check(**overrides):
    base = {
        "id": "chk-001",
        "mandate_id": "MX-TEST",
        "checked_at": "2026-05-01T10:00:00Z",
        "result": "geeignet",
        "client_proceeding_despite": 0,
    }
    base.update(overrides)
    return MagicMock(**base)


def _stub_mandate(mid: str = "MX-TEST"):
    m = MagicMock()
    m.id = mid
    return m


def _stub_db(logs, checks):
    """Stub-DB: liefert je nach Model-Klasse die richtigen Rows."""
    db = MagicMock()
    log_query = MagicMock()
    log_query.filter.return_value = log_query
    log_query.all.return_value = logs

    check_query = MagicMock()
    check_query.filter.return_value = check_query
    check_query.all.return_value = checks

    def query_router(model):
        name = getattr(model, "__name__", str(model))
        if "AdvisoryLog" in name:
            return log_query
        if "SuitabilityCheck" in name:
            return check_query
        return MagicMock()
    db.query.side_effect = query_router
    return db


# ---------------------------------------------------------------------------
# audit_mandate_suitability — Szenarien
# ---------------------------------------------------------------------------

def test_audit_empty_mandate_compliant():
    db = _stub_db([], [])
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["total_advisory_logs"] == 0
    assert result["is_compliant"] is True


def test_audit_execution_only_no_check_required():
    """execution_only-Logs werden nicht in logs_requiring_suitability gezaehlt."""
    logs = [_log(duty_type="execution_only", suitability_check_id=None)]
    db = _stub_db(logs, [])
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["total_advisory_logs"] == 1
    assert result["logs_requiring_suitability"] == 0
    assert result["is_compliant"] is True


def test_audit_missing_suitability_check_flags_violation():
    """advisory_individual ohne suitability_check_id -> Verstoss."""
    logs = [_log(suitability_check_id=None)]
    db = _stub_db(logs, [])
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["logs_requiring_suitability"] == 1
    assert len(result["logs_without_suitability"]) == 1
    assert result["logs_without_suitability"][0]["reason"] == "no_suitability_check_linked"
    assert result["is_compliant"] is False


def test_audit_dangling_suitability_check_id_flags_violation():
    """suitability_check_id zeigt auf nicht-existierende Pruefung."""
    logs = [_log(suitability_check_id="chk-nonexistent")]
    db = _stub_db(logs, [_check(id="chk-other")])  # Andere ID
    result = audit_mandate_suitability(db, _stub_mandate())
    assert len(result["logs_without_suitability"]) == 1
    assert result["logs_without_suitability"][0]["reason"] == "suitability_check_id_dangling"
    assert result["is_compliant"] is False


def test_audit_fresh_compliant_check_passes():
    logs = [_log(entry_datetime="2026-06-01T10:00:00Z")]
    checks = [_check(checked_at="2026-05-15T10:00:00Z")]
    db = _stub_db(logs, checks)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["logs_with_suitability"] == 1
    assert result["freshness_issues"] == []
    assert result["result_issues"] == []
    assert result["is_compliant"] is True


def test_audit_stale_check_flags_freshness_issue():
    logs = [_log(entry_datetime="2026-06-01T10:00:00Z")]
    checks = [_check(checked_at="2024-01-01T10:00:00Z")]  # > 1 Jahr alt
    db = _stub_db(logs, checks)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert len(result["freshness_issues"]) == 1
    assert result["freshness_issues"][0]["reason"] == "stale"
    assert result["is_compliant"] is False


def test_audit_check_after_advisory_flags_issue():
    """Pruefung NACH Beratung -> Verstoss."""
    logs = [_log(entry_datetime="2026-05-01T10:00:00Z")]
    checks = [_check(checked_at="2026-06-01T10:00:00Z")]
    db = _stub_db(logs, checks)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert len(result["freshness_issues"]) == 1
    assert result["freshness_issues"][0]["reason"] == "check_after_advisory"
    assert result["is_compliant"] is False


def test_audit_unsuitable_without_consent_flags_result_issue():
    """Check=nicht_geeignet + client_proceeding=0 -> Verstoss."""
    logs = [_log()]
    checks = [_check(result="nicht_geeignet", client_proceeding_despite=0)]
    db = _stub_db(logs, checks)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert len(result["result_issues"]) == 1
    assert result["result_issues"][0]["result"] == "nicht_geeignet"
    assert result["is_compliant"] is False


def test_audit_unsuitable_with_client_consent_compliant():
    """Check=nicht_geeignet + client_proceeding=1 -> dokumentiert, OK."""
    logs = [_log()]
    checks = [_check(result="nicht_geeignet", client_proceeding_despite=1)]
    db = _stub_db(logs, checks)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["result_issues"] == []
    # Freshness ist trotzdem ok (Mai check vor Juni log)
    assert result["is_compliant"] is True


def test_audit_db_error_returns_degraded_compliant():
    """Schema-Mismatch -> degraded leeres Schema, nicht crashen."""
    db = MagicMock()
    db.query.side_effect = RuntimeError("table missing")
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["total_advisory_logs"] == 0
    assert result["is_compliant"] is True
    assert result["fidleg_basis"] == "Art. 11/13/16 FIDLEG"


# ---------------------------------------------------------------------------
# Integration in compute_advisory_report (Sektion 19)
# ---------------------------------------------------------------------------

def test_compute_advisory_report_includes_section_19():
    # Seit PR #110 liegt die Sektions-Verdrahtung in _compute_advisory_report_inner.
    from services.advisory_report import _compute_advisory_report_inner
    import inspect
    source = inspect.getsource(_compute_advisory_report_inner)
    assert "suitability_compliance" in source
    assert "Sektion 19" in source


def test_build_suitability_compliance_degraded_on_error():
    """Wrapper darf nicht crashen — bei Service-Error degraded payload."""
    from services.advisory_report import _build_suitability_compliance
    db = MagicMock()
    db.query.side_effect = RuntimeError("simulated")
    mandate = _stub_mandate()
    result = _build_suitability_compliance(db, mandate)
    assert result["is_compliant"] is True
    assert result["fidleg_basis"] == "Art. 11/13/16 FIDLEG"
