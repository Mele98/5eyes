"""SUITABILITY-DETECTOR-AVAILABILITY-001: der HouseMatrix-Cap-Check im
Suitability-Detektor darf bei fehlender Grundlage nicht still "geeignet"
liefern (fail-open), sondern meldet Status ``unavailable`` mit Reason-Code.

Teil 1 uebernimmt die Codex-Reproducer
``test_2026_10_16_suitability_detector_matrix_availability_adversarial.py``
unveraendert in der Aussage (ohne xfail). Teil 2 pinnt Reason-Codes, die
Verbraucher (Advisory-Report Sektion 16, Beratungsprotokoll-Vorlage) und
Positivkontrollen, damit der Fix nicht einfach "immer warnen" ist.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = BACKEND_ROOT / "tests"
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.allocation import HouseMatrix, OptimizerPolicy, TargetAllocation  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from services.advisory_log_service import (  # noqa: E402
    build_auto_log_payload,
    detect_suitability_mismatches,
    evaluate_suitability_mismatches,
)
from services.advisory_report import compute_advisory_report  # noqa: E402
from services.risk_matrix import score_bucket_from_assessment  # noqa: E402
from services.suitability_cap_check import (  # noqa: E402
    REASON_RISK_PROFILE_INCONSISTENT,
    REASON_RISK_PROFILE_MISSING,
    REASON_RISKY_FRACTION_MISSING,
    REASON_SCORE_BUCKET_AMBIGUOUS,
    REASON_SCORE_BUCKET_MISSING,
    REASON_SUITABILITY_POLICY_MISSING,
    STATUS_NOT_APPLICABLE,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    STATUS_VIOLATION,
)
from test_advisory_log_aggregator import _NOW, _seed, session_factory  # noqa: E402,F401
from test_suitability_detector_score_scale import (  # noqa: E402
    _seed_mandate_with_production_matrix,
    _seed_valid_ra,
)


def _assert_cap_check_unavailable(warnings: list[str]) -> None:
    assert any(
        "HouseMatrix-Cap" in warning and "nicht pruefbar" in warning
        for warning in warnings
    ), warnings


def _disable_current_policy(session, policy) -> None:
    policy.is_current = 0
    session.commit()


def _delete_bucket_row(session, mandate, policy) -> None:
    assessment = (
        session.query(RiskAssessment)
        .filter(RiskAssessment.mandate_id == mandate.id)
        .one()
    )
    bucket = score_bucket_from_assessment(assessment)
    (
        session.query(HouseMatrix)
        .filter(
            HouseMatrix.policy_id == policy.id,
            HouseMatrix.score_from <= bucket,
            HouseMatrix.score_to >= bucket,
        )
        .delete(synchronize_session=False)
    )
    session.commit()


# ---------------------------------------------------------------------------
# Teil 1: Codex-Reproducer (ohne xfail)
# ---------------------------------------------------------------------------

def test_missing_current_policy_is_not_silently_treated_as_suitable(
    session_factory,
) -> None:
    """Fail closed when no current policy can supply the cap contract."""
    with session_factory() as session:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(
            session,
            risky_bps=9000,
        )
        _seed_valid_ra(session, mandate, advisor, final_score_x10=75)
        _disable_current_policy(session, policy)

        warnings = detect_suitability_mismatches(session, mandate)

    _assert_cap_check_unavailable(warnings)


def test_missing_score_bucket_is_not_silently_treated_as_suitable(
    session_factory,
) -> None:
    """A partial matrix cannot turn the cap check into a silent no-op."""
    with session_factory() as session:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(
            session,
            risky_bps=9000,
        )
        _seed_valid_ra(session, mandate, advisor, final_score_x10=75)
        _delete_bucket_row(session, mandate, policy)

        warnings = detect_suitability_mismatches(session, mandate)

    _assert_cap_check_unavailable(warnings)


# ---------------------------------------------------------------------------
# Teil 2: Reason-Codes
# ---------------------------------------------------------------------------

def test_policy_missing_reports_reason_code_even_for_low_risk(session_factory):
    """Auch ein niedriger Risiko-Anteil ist ohne Policy nicht "geeignet"."""
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _disable_current_policy(s, policy)
        result = evaluate_suitability_mismatches(s, mandate)
    check = result["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_SUITABILITY_POLICY_MISSING
    assert check.counts_as_suitable is False
    assert any(REASON_SUITABILITY_POLICY_MISSING in w for w in result["warnings"])


def test_score_bucket_missing_reports_reason_code_even_for_low_risk(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _delete_bucket_row(s, mandate, policy)
        result = evaluate_suitability_mismatches(s, mandate)
    check = result["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_SCORE_BUCKET_MISSING
    assert check.score_bucket is not None
    assert check.counts_as_suitable is False
    assert any(REASON_SCORE_BUCKET_MISSING in w for w in result["warnings"])


def test_inactive_bucket_row_counts_as_missing(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate.id).one()
        bucket = score_bucket_from_assessment(ra)
        for row in s.query(HouseMatrix).filter(
            HouseMatrix.policy_id == policy.id,
            HouseMatrix.score_from <= bucket,
            HouseMatrix.score_to >= bucket,
        ):
            row.is_active = 0
        s.commit()
        check = evaluate_suitability_mismatches(s, mandate)["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_SCORE_BUCKET_MISSING


def test_ambiguous_score_bucket_is_unavailable_not_first_row(session_factory):
    """Vorher ``.first()``: bei ueberlappenden Zeilen entschied die
    DB-Reihenfolge ueber das Cap. Jetzt fail-closed."""
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate.id).one()
        bucket = score_bucket_from_assessment(ra)
        row = s.query(HouseMatrix).filter(
            HouseMatrix.policy_id == policy.id,
            HouseMatrix.score_from <= bucket,
            HouseMatrix.score_to >= bucket,
        ).one()
        clone = HouseMatrix(**{
            col.name: getattr(row, col.name)
            for col in HouseMatrix.__table__.columns
            if col.name != "id"
        })
        clone.id = str(uuid.uuid4())
        clone.max_risky_fraction_bps = 10000
        s.add(clone)
        s.commit()
        check = evaluate_suitability_mismatches(s, mandate)["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_SCORE_BUCKET_AMBIGUOUS


def test_missing_risk_profile_with_active_allocation_is_unavailable(session_factory):
    with session_factory() as s:
        _advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        result = evaluate_suitability_mismatches(s, mandate)
    check = result["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_RISK_PROFILE_MISSING
    _assert_cap_check_unavailable(result["warnings"])


def test_inconsistent_risk_profile_reports_reason_code(session_factory):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=9000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate.id).one()
        ra.final_profile = "Ausgewogen"  # passt nicht zu final_score_x10=75
        s.commit()
        result = evaluate_suitability_mismatches(s, mandate)
    assert result["cap_check"].reason_code == REASON_RISK_PROFILE_INCONSISTENT
    cap = [w for w in result["warnings"] if "HouseMatrix-Cap" in w]
    assert len(cap) == 1 and "nicht pruefbar" in cap[0], result["warnings"]


def test_missing_risky_fraction_is_unavailable(session_factory):
    """``risky_fraction_bps`` NULL ist "unbekannt", nicht 0 % (vorher still ok)."""
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        ta = s.query(TargetAllocation).filter(TargetAllocation.mandate_id == mandate.id).one()
        ta.risky_fraction_bps = None
        s.commit()
        check = evaluate_suitability_mismatches(s, mandate)["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_RISKY_FRACTION_MISSING


# ---------------------------------------------------------------------------
# Positivkontrollen: der Fix warnt nicht einfach immer
# ---------------------------------------------------------------------------

def test_positive_control_cap_checked_and_ok(session_factory):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        result = evaluate_suitability_mismatches(s, mandate)
    check = result["cap_check"]
    assert check.status == STATUS_OK
    assert check.reason_code is None
    assert check.counts_as_suitable is True
    assert check.cap_bps == 8000 and check.profile_name == "Wachstumsorientiert"
    assert result["warnings"] == []


def test_positive_control_violation_keeps_cap_text(session_factory):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=9000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        result = evaluate_suitability_mismatches(s, mandate)
    check = result["cap_check"]
    assert check.status == STATUS_VIOLATION
    assert check.counts_as_suitable is False
    assert any(
        "überschreitet HouseMatrix-Cap 80.0 % (Wachstumsorientiert)" in w
        for w in result["warnings"]
    ), result["warnings"]


def test_no_target_allocation_is_not_applicable(session_factory):
    with session_factory() as s:
        _advisor, mandate = _seed(s)
        result = evaluate_suitability_mismatches(s, mandate)
    assert result["warnings"] == []
    assert result["cap_check"].status == STATUS_NOT_APPLICABLE
    assert result["cap_check"].counts_as_suitable is False


def test_unrelated_policy_without_matrix_does_not_count_as_policy(session_factory):
    """Gegenprobe: eine zweite, aktuelle Policy ohne Zeilen ersetzt die
    Produktions-Policy -> SCORE_BUCKET_MISSING statt stillem ok."""
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        policy.is_current = 0
        s.add(OptimizerPolicy(
            id=str(uuid.uuid4()), policy_name="leer", version=99,
            is_current=1, valid_from=_NOW[:10],
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000, max_alternatives_bps=1000,
            min_liquidity_bps=0, allow_other_assets_for_goals=1,
            created_by=advisor.id, created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        check = evaluate_suitability_mismatches(s, mandate)["cap_check"]
    assert check.status == STATUS_UNAVAILABLE
    assert check.reason_code == REASON_SCORE_BUCKET_MISSING


# ---------------------------------------------------------------------------
# Verbraucher: Kundendokument (Report Sektion 16 / PDF) + Protokoll-Vorlage
# ---------------------------------------------------------------------------

def test_advisory_report_section16_flags_unavailable_as_active(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _disable_current_policy(s, policy)
        payload = compute_advisory_report(s, mandate, advisor=advisor)
    bp = payload["beratungsprotokoll"]
    assert bp["has_active_mismatches"] is True
    assert bp["suitability_cap_check"]["status"] == STATUS_UNAVAILABLE
    assert bp["suitability_cap_check"]["reason_code"] == REASON_SUITABILITY_POLICY_MISSING
    assert bp["suitability_cap_check"]["counts_as_suitable"] is False
    _assert_cap_check_unavailable(bp["suitability_mismatches"])


def test_advisory_report_section16_ok_status_for_positive_control(session_factory):
    with session_factory() as s:
        advisor, mandate, _policy = _seed_mandate_with_production_matrix(s, risky_bps=7000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        payload = compute_advisory_report(s, mandate, advisor=advisor)
    bp = payload["beratungsprotokoll"]
    assert bp["suitability_cap_check"]["status"] == STATUS_OK
    assert bp["has_active_mismatches"] is False
    assert bp["suitability_mismatches"] == []


def test_auto_log_payload_carries_unavailable_hint_not_generic_only(session_factory):
    with session_factory() as s:
        advisor, mandate, policy = _seed_mandate_with_production_matrix(s, risky_bps=1000)
        _seed_valid_ra(s, mandate, advisor, final_score_x10=75)
        _delete_bucket_row(s, mandate, policy)
        payload = build_auto_log_payload(
            s, mandate=mandate, advisor=advisor, entry_datetime=_NOW,
        )
    warnings = payload["risk_warnings_given"]
    _assert_cap_check_unavailable(warnings)
    assert any(REASON_SCORE_BUCKET_MISSING in w for w in warnings)
