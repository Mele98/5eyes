"""FIDLEG-Eignungspruefungs-Audit (Sprint U-66; Art.-12-Umstellung 2026-07-19).

Hintergrund
-----------
FIDLEG Art. 10 (Pruefpflicht) + Art. 12 (Eignungspruefung): Wer portfolio-
bezogene Anlageberatung oder Vermoegensverwaltung erbringt — 5eyes tut das —
muss eine Eignungspruefung durchfuehren und REGELMAESSIG aktualisieren.

Umstellung (Option A): Der Audit prueft auf MANDATSEBENE, ob ein AKTUELLES
Risikoprofil (RiskAssessment = 5eyes-Eignungspruefung) existiert. Der fruehere
Per-Log-Ansatz las AdvisoryLog.duty_type/.suitability_check_id — Spalten, die es
auf AdvisoryLog gar nicht gibt -> der Audit war blind (immer 'compliant').

Diese Suite verifiziert services/suitability_audit.py und seine Integration in
compute_advisory_report (Sektion 19).

Test-Strategie: Pure-Unit mit MagicMock-DB, deterministische Frische ueber
_days_ago(...) relativ zu now (keine hartkodierten Kalenderdaten -> nicht flaky).
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

def _risk_assessment(**overrides):
    """Synthetisches RiskAssessment (= 5eyes-Eignungspruefung). Default: heute
    erstellt (frisch). assessed_at via _days_ago fuer deterministische Frische."""
    base = {
        "id": "ra-001",
        "mandate_id": "MX-TEST",
        "version": 1,
        "is_current": 1,
        "valid_from": _days_ago(30)[:10],
        "assessed_at": _days_ago(30),
        "final_profile": "Ausgewogen",
    }
    base.update(overrides)
    return MagicMock(**base)


def _days_ago(days: int) -> str:
    """ISO-Timestamp 'days' Tage vor jetzt (deterministisch relativ zu now)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _stub_mandate(mid: str = "MX-TEST", mandate_type: str = "Anlageberatung"):
    m = MagicMock()
    m.id = mid
    m.mandate_type = mandate_type
    return m


def _stub_db(ra=None, *, advisory_log_count: int = 0, raise_on: str | None = None):
    """Stub-DB: AdvisoryLog.count() -> advisory_log_count, RiskAssessment.first()
    -> ra. raise_on='risk' laesst die RiskAssessment-Query werfen (Infra-Fehler);
    raise_on='all' laesst jede Query werfen."""
    db = MagicMock()

    log_query = MagicMock()
    log_query.filter.return_value = log_query
    log_query.count.return_value = advisory_log_count

    ra_query = MagicMock()
    ra_query.filter.return_value = ra_query
    ra_query.order_by.return_value = ra_query
    if raise_on in ("risk", "all"):
        ra_query.first.side_effect = RuntimeError("table missing")
    else:
        ra_query.first.return_value = ra

    def query_router(model):
        if raise_on == "all":
            raise RuntimeError("db down")
        name = getattr(model, "__name__", str(model))
        if "AdvisoryLog" in name:
            return log_query
        if "RiskAssessment" in name:
            return ra_query
        return MagicMock()
    db.query.side_effect = query_router
    return db


# ---------------------------------------------------------------------------
# audit_mandate_suitability — Szenarien
# ---------------------------------------------------------------------------

def test_audit_execution_only_mandate_exempt():
    """Execution-only-Mandat (Art. 13) verlangt keine Eignungspruefung -> konform."""
    db = _stub_db(ra=None, advisory_log_count=2)
    result = audit_mandate_suitability(db, _stub_mandate(mandate_type="execution_only"))
    assert result["requires_suitability"] is False
    assert result["suitability_basis"] == "execution_only_exempt"
    assert result["is_compliant"] is True


def test_audit_no_risk_assessment_flags_violation():
    """Anlageberatung ohne aktuelle Eignungspruefung (Risikoprofil) -> Verstoss."""
    db = _stub_db(ra=None, advisory_log_count=1)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["requires_suitability"] is True
    assert result["logs_requiring_suitability"] == 1
    assert len(result["logs_without_suitability"]) == 1
    assert result["logs_without_suitability"][0]["reason"] == "no_current_risk_assessment"
    assert result["is_compliant"] is False


def test_audit_fresh_risk_assessment_compliant():
    """Frisches Risikoprofil (< 365 Tage) -> konform."""
    db = _stub_db(ra=_risk_assessment(assessed_at=_days_ago(30)))
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["logs_with_suitability"] == 1
    assert result["freshness_issues"] == []
    assert result["is_compliant"] is True


def test_audit_stale_risk_assessment_flags_freshness():
    """Veraltetes Risikoprofil (> 365 Tage) -> Frische-Verstoss (Art. 12
    'regelmaessig aktualisieren')."""
    db = _stub_db(ra=_risk_assessment(assessed_at=_days_ago(400)))
    result = audit_mandate_suitability(db, _stub_mandate())
    assert len(result["freshness_issues"]) == 1
    assert result["freshness_issues"][0]["reason"] == "stale"
    assert result["is_compliant"] is False


def test_audit_populates_risk_assessment_summary_fields():
    """Fuer die Zusammenfassung 'wann/welches Profil': id/version/datum/profil
    werden ausgewiesen."""
    ra = _risk_assessment(id="ra-xy", version=3, final_profile="Wachstumsorientiert",
                          assessed_at=_days_ago(10))
    db = _stub_db(ra=ra)
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["risk_assessment_id"] == "ra-xy"
    assert result["risk_assessment_version"] == 3
    assert result["risk_assessment_profile"] == "Wachstumsorientiert"
    assert result["risk_assessment_date"] is not None
    assert result["risk_assessment_age_days"] is not None


def test_audit_db_error_returns_degraded_fail_closed():
    """Infra-/Schema-Fehler beim Laden des Risikoprofils -> degraded, NICHT
    faelschlich compliant (fail-closed, konsistent zu Welle 1.2)."""
    db = _stub_db(raise_on="risk")
    result = audit_mandate_suitability(db, _stub_mandate())
    assert result["audit_degraded"] is True
    assert result["is_compliant"] is None
    assert result["fidleg_basis"] == "Art. 10 / Art. 12 FIDLEG"


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
    """Wrapper darf nicht crashen — bei Service-Error fail-closed (is_compliant
    None + audit_degraded), NIE faelschlich compliant."""
    from services.advisory_report import _build_suitability_compliance
    db = MagicMock()
    db.query.side_effect = RuntimeError("simulated")
    mandate = _stub_mandate()
    result = _build_suitability_compliance(db, mandate)
    assert result["is_compliant"] is None
    assert result.get("audit_degraded") is True
