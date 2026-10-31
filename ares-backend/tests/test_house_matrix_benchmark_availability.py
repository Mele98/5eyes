"""SUITABILITY-DETECTOR-AVAILABILITY-001 (Nachtrag CIO-Abnahme #678):
HouseMatrix-Referenz in Depotcheck (API + PDF) und Performance-Attribution
mit ausgewiesenem Status statt stiller Auslassung / ``.first()``.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = BACKEND_ROOT / "tests"
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from database import get_db  # noqa: E402
from main import app  # noqa: E402
from models.allocation import HouseMatrix, TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from routers.pdf_reports import (  # noqa: E402
    _build_depotcheck_performance,
    _depotcheck_data_quality_warnings,
    _depotcheck_house_matrix_benchmark_with_status,
)
from services.advisory_report import _build_performance_attribution  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.house_matrix_benchmark import (  # noqa: E402
    REASON_TARGET_ALLOCATION_MISSING,
    UNAVAILABLE_NOTE_PREFIX,
    resolve_depotcheck_benchmark,
)
from services.pdf.base import DepotCheckData, PDFContext  # noqa: E402
from services.pdf.reportlab_renderer import ReportLabRenderer  # noqa: E402
from services.risk_matrix import score_bucket_from_assessment  # noqa: E402
from services.suitability_cap_check import (  # noqa: E402
    REASON_RISK_PROFILE_MISSING,
    REASON_SCORE_BUCKET_AMBIGUOUS,
    REASON_SCORE_BUCKET_MISSING,
)
from test_advisory_log_aggregator import _seed, session_factory  # noqa: E402,F401
from test_suitability_detector_score_scale import (  # noqa: E402
    _seed_mandate_with_production_matrix,
    _seed_valid_ra,
)


def _bucket_rows(s, mandate, policy):
    ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate.id).one()
    bucket = score_bucket_from_assessment(ra)
    return bucket, s.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= bucket,
        HouseMatrix.score_to >= bucket,
    )


def _make_missing(s, mandate, policy):
    _bucket, q = _bucket_rows(s, mandate, policy)
    q.delete(synchronize_session=False)
    s.commit()


def _make_ambiguous(s, mandate, policy):
    _bucket, q = _bucket_rows(s, mandate, policy)
    row = q.one()
    clone = HouseMatrix(**{
        c.name: getattr(row, c.name)
        for c in HouseMatrix.__table__.columns if c.name != "id"
    })
    clone.id = str(uuid.uuid4())
    clone.equity_target_bps = 9999
    s.add(clone)
    s.commit()


def _mandate(s, mandate):
    return s.query(Mandate).filter(Mandate.id == mandate.id).one()


# ---------------------------------------------------------------------------
# Depotcheck: Aufloesung
# ---------------------------------------------------------------------------

def test_depotcheck_benchmark_available_positive_control(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _bucket, q = _bucket_rows(s, mandate, policy)
        row = q.one()
        weights, status = _depotcheck_house_matrix_benchmark_with_status(_mandate(s, mandate), s)
        expected_equity = int(row.equity_target_bps)
    assert status["status"] == "available"
    assert status["reason_code"] is None and status["note"] is None
    assert weights["equities"] == expected_equity
    assert sum(weights.values()) > 0


def test_depotcheck_benchmark_missing_bucket_is_reported(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _make_missing(s, mandate, policy)
        weights, status = _depotcheck_house_matrix_benchmark_with_status(_mandate(s, mandate), s)
    assert weights == {}
    assert status["status"] == "unavailable"
    assert status["reason_code"] == REASON_SCORE_BUCKET_MISSING
    assert status["note"].startswith(UNAVAILABLE_NOTE_PREFIX)


def test_depotcheck_benchmark_ambiguous_bucket_not_first_row(session_factory):
    """Vorher ``order_by(score_from desc).first()`` -> still eine Zeile."""
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _make_ambiguous(s, mandate, policy)
        weights, status = _depotcheck_house_matrix_benchmark_with_status(_mandate(s, mandate), s)
    assert weights == {}
    assert status["reason_code"] == REASON_SCORE_BUCKET_AMBIGUOUS


def test_depotcheck_benchmark_missing_risk_profile(session_factory):
    with session_factory() as s:
        _advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        weights, status = _depotcheck_house_matrix_benchmark_with_status(_mandate(s, mandate), s)
    assert weights == {}
    assert status["reason_code"] == REASON_RISK_PROFILE_MISSING


def test_depotcheck_benchmark_without_target_allocation(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        status = resolve_depotcheck_benchmark(s, _mandate(s, mandate)).public()
    assert status["status"] == "unavailable"
    assert status["reason_code"] == REASON_TARGET_ALLOCATION_MISSING


# ---------------------------------------------------------------------------
# Depotcheck: Performance-Block + Warnungen (Weg ins PDF)
# ---------------------------------------------------------------------------

def test_depotcheck_performance_carries_status_and_warning(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _make_missing(s, mandate, policy)
        performance = _build_depotcheck_performance(_mandate(s, mandate), s)
    status = performance["house_matrix_benchmark"]
    assert status["status"] == "unavailable"
    assert status["reason_code"] == REASON_SCORE_BUCKET_MISSING
    merged = _depotcheck_data_quality_warnings({"warnings": []}, performance)
    assert any(w.startswith(UNAVAILABLE_NOTE_PREFIX) for w in merged), merged


def test_depotcheck_performance_available_has_no_benchmark_warning(session_factory):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        performance = _build_depotcheck_performance(_mandate(s, mandate), s)
    assert performance["house_matrix_benchmark"]["status"] == "available"
    assert not any(
        str(w).startswith(UNAVAILABLE_NOTE_PREFIX)
        for w in performance.get("warnings") or []
    )


def _pdf_text(data: DepotCheckData) -> str:
    ctx = PDFContext(
        mandate_name="Muster Mandat", advisor_name="Anna Beratung",
        advisor_org="Beratungshaus", report_date=date(2026, 10, 21),
        audit_hash="hm-benchmark-test",
    )
    pdf = ReportLabRenderer().render_depotcheck(ctx, data)
    reader = PdfReader(BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_depotcheck_pdf_shows_unavailable_house_matrix_note():
    note = f"{UNAVAILABLE_NOTE_PREFIX} (SCORE_BUCKET_MISSING)."
    text = _pdf_text(DepotCheckData(
        mandate_number="M-HM",
        performance={
            "data_pending": True,
            "note": "Daten ausstehend.",
            "house_matrix_benchmark": {
                "status": "unavailable",
                "reason_code": "SCORE_BUCKET_MISSING",
                "note": note,
            },
        },
        cost_disclosure={"data_pending": True, "note": "Daten ausstehend."},
    ))
    flat = " ".join(text.split())
    assert "Vergleich mit der Hausmatrix nicht" in flat
    assert "SCORE_BUCKET_MISSING" in flat


def test_depotcheck_pdf_no_note_when_available():
    text = _pdf_text(DepotCheckData(
        mandate_number="M-HM-OK",
        performance={
            "data_pending": True,
            "note": "Daten ausstehend.",
            "house_matrix_benchmark": {"status": "available"},
        },
        cost_disclosure={"data_pending": True, "note": "Daten ausstehend."},
    ))
    assert "Vergleich mit der Hausmatrix" not in " ".join(text.split())


# ---------------------------------------------------------------------------
# Depotcheck-API
# ---------------------------------------------------------------------------

def test_depot_check_api_exposes_house_matrix_status(session_factory):
    session = session_factory()
    try:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(session, risky_bps=7000)
        _seed_valid_ra(session, mandate, advisor, final_score_x10=75)
        _make_missing(session, mandate, policy)

        def _db_dep():
            yield session

        app.dependency_overrides[get_db] = _db_dep
        app.dependency_overrides[get_current_user] = lambda: advisor
        try:
            resp = TestClient(app).get(f"/mandates/{mandate.id}/depot-check")
        finally:
            app.dependency_overrides.clear()
    finally:
        session.close()
    assert resp.status_code == 200, resp.text
    block = resp.json()["house_matrix_benchmark"]
    assert block["status"] == "unavailable"
    assert block["reason_code"] == REASON_SCORE_BUCKET_MISSING
    assert block["note"].startswith(UNAVAILABLE_NOTE_PREFIX)


# ---------------------------------------------------------------------------
# Performance-Attribution
# ---------------------------------------------------------------------------

def test_performance_attribution_ambiguous_bucket_is_reported(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _make_ambiguous(s, mandate, policy)
        result = _build_performance_attribution(s, _mandate(s, mandate))
    assert "error" in result, result
    assert result.get("reason_code") == REASON_SCORE_BUCKET_AMBIGUOUS


def test_performance_attribution_missing_bucket_is_reported(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _make_missing(s, mandate, policy)
        result = _build_performance_attribution(s, _mandate(s, mandate))
    assert "error" in result, result
    assert result.get("reason_code") == REASON_SCORE_BUCKET_MISSING


def test_performance_attribution_missing_risk_profile_is_gated(session_factory):
    """Ohne Risikoprofil greift schon das Projektions-Gate (MC-CONTEXT-001)
    und weist den Grund aus -- nie eine Attribution ohne Referenz."""
    with session_factory() as s:
        _advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        result = _build_performance_attribution(s, _mandate(s, mandate))
    assert "Kein aktuelles Risikoprofil" in result["error"], result
    assert result["buckets"] == []


def test_performance_attribution_positive_control_unique_bucket(session_factory):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        result = _build_performance_attribution(s, _mandate(s, mandate))
    assert "reason_code" not in result, result
    assert "error" not in result, result
    assert result["method"] == "brinson_fachler_hood_1986"


def test_target_allocation_fixture_has_policy(session_factory):
    """Praemisse: die Depotcheck-Referenz folgt TargetAllocation.policy_id."""
    with session_factory() as s:
        _advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        ta = s.query(TargetAllocation).filter(TargetAllocation.mandate_id == mandate.id).one()
    assert ta.policy_id == policy.id
