"""RISK-OVERRIDE-LEGACY-REMEDIATION-001.

Seit #657/#662 gibt es append-only RiskOverrideDecisionV1 und
RiskProfileSignoffV1. Ein Override aus dem Altbestand (is_overridden=1 ohne
override_decision_id, signoff_state=remediation_required) blockiert den
Signoff mit 409 -- bisher ohne klaren Weg heraus.

Remediation-Pfad: derselbe NORMALE Override-Endpunkt mit
``remediation="legacy_remediation"`` erzeugt eine Decision fuer den
bestehenden Override

* mit allen Pflichtpruefungen (Begruendungsqualitaet, Kundenwunsch,
  Warnhinweis, FZK-Cap, Current-Gate, CAS);
* ohne Rueckdatierung (decided_at = jetzt, nicht das alte override_at);
* nur fuer echten Altbestand (sonst 409) und nur fuer denselben Score
  (Aenderung = normaler Override, sonst 422);
* Audit: Snapshot traegt audit_reason=legacy_remediation, zusaetzlich ein
  Audit-Eintrag ``legacy_remediation`` mit den Altwerten (replaybar).

Danach ist der Signoff moeglich. Das Strategie-Gate bleibt fuer Legacy
nicht-blockierend, die Strategie-Meldung zeigt aber den Hinweis.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from core.reason_codes import DomainError  # noqa: E402  K-2b: Gates werfen DomainError
from pydantic import ValidationError
from sqlalchemy import text

from models.profiling import RiskAssessment, RiskOverrideDecision, RiskProfileSignoff
from models.review import AuditLog
from routers import profiling as profiling_router
from schemas.profiling import RiskAssessmentOverride
from services.risk_override_decision import resolve_assessment_decision, verify_decision
from services.risk_scoring import profile_for_score_x10
from tests.test_risk_capacity_plausibility import (
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401  (pytest fixture)
)
from tests.test_risk_override_current_gate_decision_log import (
    VALID_REASON,
    _assessment,
    _override,
)

LEGACY_AT = "2025-01-15T09:00:00.000Z"
LEGACY_REASON = "Kurz"  # Altbestand: erfuellt die heutige Qualitaetsregel NICHT


def _make_legacy(session, *, score=40, confirmed=0, warned=0, reason=LEGACY_REASON):
    session.execute(text(
        "UPDATE risk_assessments SET is_overridden = 1, override_score_x10 = :s, "
        "override_profile = :p, override_reason = :r, override_at = :at, "
        "override_client_confirmed = :c, override_warning_delivered = :w "
        "WHERE id = 'ra-current'"
    ), {"s": score, "p": profile_for_score_x10(score), "r": reason, "at": LEGACY_AT,
        "c": confirmed, "w": warned})
    session.commit()


def _fresh(session) -> RiskAssessment:
    session.expire_all()
    return session.get(RiskAssessment, "ra-current")


def _remediate(session, advisor, *, score=40, **extra):
    return _override(
        session, advisor, "ra-current", score=score, profile=profile_for_score_x10(score),
        remediation="legacy_remediation", expected_override_decision_id=None, **extra,
    )


def _sign(session, advisor):
    return profiling_router.sign_risk_profile(
        mandate_id="m-rcp", request=_FakeRequest(), body=None, db=session, current_user=advisor,
    )


def _audit(session, field):
    return (
        session.query(AuditLog)
        .filter(AuditLog.record_id == "ra-current", AuditLog.field_name == field)
        .order_by(AuditLog.sequence.asc())
        .all()
    )


@pytest.fixture
def seeded(session_factory):  # noqa: F811
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        yield session, advisor


def test_legacy_remediation_creates_decision_and_unblocks_signoff(seeded):
    session, advisor = seeded
    _make_legacy(session)
    assert _fresh(session).signoff_state == "remediation_required"
    with pytest.raises(DomainError) as exc:
        _sign(session, advisor)
    assert exc.value.status_code == 409

    _remediate(session, advisor)
    ra = _fresh(session)
    decisions = session.query(RiskOverrideDecision).filter_by(assessment_id="ra-current").all()
    assert len(decisions) == 1
    decision = decisions[0]
    assert verify_decision(decision)
    assert resolve_assessment_decision(session, ra)[2] is True
    assert decision.previous_decision_id is None
    assert decision.requested_score_x10 == 40
    # Keine Rueckdatierung: Zeitstempel = jetzt, nicht das alte override_at.
    assert decision.decided_at != LEGACY_AT and decision.decided_at > LEGACY_AT
    assert ra.override_at == decision.decided_at
    assert ra.signoff_state == "signature_required"

    snap = json.loads(_audit(session, "override")[-1].new_value)
    assert snap["audit_reason"] == "legacy_remediation"
    assert snap["decision_id"] == decision.id
    legacy_rows = _audit(session, "legacy_remediation")
    assert len(legacy_rows) == 1
    legacy = json.loads(legacy_rows[0].new_value)
    assert legacy["audit_reason"] == "legacy_remediation"
    assert legacy["legacy_override_at"] == LEGACY_AT
    assert legacy["legacy_override_reason"] == LEGACY_REASON
    assert legacy["legacy_override_score_x10"] == 40
    assert legacy["decision_id"] == decision.id

    result = _sign(session, advisor)
    assert result
    signoffs = session.query(RiskProfileSignoff).filter_by(assessment_id="ra-current").all()
    assert len(signoffs) == 1
    assert signoffs[0].override_decision_id == decision.id
    assert _fresh(session).signoff_state == "signed"


def test_remediation_only_for_legacy_without_decision(seeded):
    session, advisor = seeded
    # Kein Override -> nichts zu remediieren.
    with pytest.raises(HTTPException) as exc:
        _remediate(session, advisor)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "RISK_OVERRIDE_NOT_LEGACY"
    assert session.query(RiskOverrideDecision).count() == 0

    # Override mit Decision -> ebenfalls kein Altbestand.
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    with pytest.raises(HTTPException) as exc:
        _override(session, advisor, "ra-current", score=40, profile="Defensiv",
                  remediation="legacy_remediation")
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "RISK_OVERRIDE_NOT_LEGACY"
    assert session.query(RiskOverrideDecision).count() == 1
    assert _audit(session, "legacy_remediation") == []


def test_remediation_cannot_change_the_legacy_score(seeded):
    session, advisor = seeded
    _make_legacy(session, score=40)
    with pytest.raises(HTTPException) as exc:
        _remediate(session, advisor, score=60)
    assert exc.value.status_code == 422
    assert session.query(RiskOverrideDecision).count() == 0
    assert _fresh(session).signoff_state == "remediation_required"


def test_remediation_enforces_mandatory_documentation_checks(seeded):
    session, advisor = seeded
    # Override nach oben (Basis 70 -> 80): Kundenwunsch ist Pflicht -- auch
    # wenn der Altbestand ihn als bestaetigt fuehrt, muss ihn der Request
    # erneut bestaetigen.
    _make_legacy(session, score=80, confirmed=1)
    with pytest.raises(HTTPException) as exc:
        _remediate(session, advisor, score=80)
    assert exc.value.status_code == 422
    assert session.query(RiskOverrideDecision).count() == 0
    assert _audit(session, "legacy_remediation") == []

    _remediate(session, advisor, score=80, override_client_confirmed=True)
    decision = session.query(RiskOverrideDecision).one()
    assert decision.required_client_confirmation == 1
    assert decision.client_confirmed == 1


def test_remediation_applies_reason_quality_rule():
    # Die Alt-Begruendung wird vorbelegt, muss aber die heutige Regel erfuellen.
    with pytest.raises(ValidationError):
        RiskAssessmentOverride(
            override_score_x10=40, override_profile="Defensiv",
            override_reason=LEGACY_REASON, remediation="legacy_remediation",
        )
    with pytest.raises(ValidationError):
        RiskAssessmentOverride(
            override_score_x10=40, override_profile="Defensiv",
            override_reason=VALID_REASON, remediation="backdate",
        )


def test_strategy_gate_stays_non_blocking_but_shows_legacy_hint(seeded):
    from services.allocation_messages import WARN_OVERRIDE, classify_messages
    from services.portfolio_engine import risk_assessment_ready_for_strategy

    session, advisor = seeded
    _make_legacy(session, reason=VALID_REASON)
    ra = _fresh(session)
    assert risk_assessment_ready_for_strategy(ra) is True
    msg = [m for m in classify_messages(None, [], "optimal", None, ra) if m["code"] == WARN_OVERRIDE][0]
    assert msg["legacy_remediation_required"] is True
    assert "Override aus Altbestand" in msg["body_advisor"]
    assert "bitte bestaetigen" in msg["body_advisor"]

    _remediate(session, advisor)
    ra = _fresh(session)
    msg = [m for m in classify_messages(None, [], "optimal", None, ra) if m["code"] == WARN_OVERRIDE][0]
    assert msg["legacy_remediation_required"] is False
    assert "Override aus Altbestand" not in msg["body_advisor"]


def test_monolith_offers_legacy_remediation_action():
    html = (
        Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"
    ).read_text(encoding="utf-8")
    assert "function openLegacyOverrideRemediation(" in html
    assert "Override aus Altbestand" in html
    assert "ovPayload.remediation='legacy_remediation'" in html
    # Kein Browser-Dialog (Electron) -- bestehende Modal-Komponente.
    start = html.index("function openLegacyOverrideRemediation(")
    body = html[start:start + 4000]
    assert "om('m-overr')" in body or "openOverrideModal(" in body
    assert "window.confirm" not in body and "prompt(" not in body


def test_signoff_lines_and_409_point_to_legacy_confirmation(seeded):
    from services.risk_profile_signoff import build_signoff_view, signoff_view_lines

    session, advisor = seeded
    _make_legacy(session)
    ra = _fresh(session)
    joined = " ".join(t for _, t in signoff_view_lines(build_signoff_view(session, ra)))
    assert "Override aus Altbestand" in joined and "bitte bestaetigen" in joined
    with pytest.raises(DomainError) as exc:
        _sign(session, advisor)
    assert "legacy_remediation" in exc.value.detail["message"]
