"""RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefunde A + B (Codex-Closure-Review
zu PR #646, docs/audits/2026-10-19-risk-override-write-boundary-pr646-
closure-review.md).

A) Current-Gate: nur das aktuelle, nicht geloeschte Assessment des Mandats
   darf uebersteuert werden (historisch -> 409 mit Reason-Code, geloescht/
   fremd -> 404). Optimistic Concurrency ueber optionale Erwartungswerte im
   Request und einen Compare-and-Swap-UPDATE, der is_current und den
   bisherigen Decision-Pointer unmittelbar beim Schreiben erneut prueft.
B) Append-only RiskOverrideDecisionV1: jeder Override/Re-Override schreibt
   eine unveraenderliche, gehashte Decision-Zeile; das Assessment traegt nur
   den Pointer (ID + Hash); Audit-Log, PDF und Strategie-Meldung zeigen ihn.

Die beiden Restvertraege aus dem Codex-Reproducer
(docs/audits/reproducers/test_2026_10_19_pr646_risk_override_closure_
adversarial.py, dort xfail-strict) sind hier ohne xfail uebernommen; die
einzige Abweichung: die Audit-Zeilen werden zusaetzlich ueber die atomare
audit_log.sequence sortiert, damit zwei Eintraege derselben Millisekunde
nicht ueber die zufaellige UUID-Reihenfolge flaky werden.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from models.profiling import RiskAssessment, RiskOverrideDecision
from models.review import AuditLog
from routers import profiling as profiling_router
from schemas.profiling import RiskAssessmentOverride
from services.risk_assessment_semantics import OVERRIDE_DOCUMENTATION_RULES_VERSION
from services.risk_override_decision import (
    compute_decision_hash,
    verify_decision,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    derive_current_risk_fields,
)
from tests.test_risk_capacity_plausibility import (
    NOW,
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401  (pytest fixture)
)


VALID_REASON = (
    "Kunde wuenscht eine dokumentierte Anpassung nach gemeinsamer "
    "Besprechung der Risikofaehigkeit und der Anlageziele."
)

REQUIRED_SNAPSHOT_KEYS = {
    "assessment_id",
    "basis_final_score_x10",
    "basis_capacity_score_x10",
    "requested_score_x10",
    "requested_profile",
    "reason",
    "client_confirmed",
    "warning_delivered",
    "actor_id",
    "decided_at",
    "rules_version",
    "decision_hash",
}


def _risk_fields() -> dict:
    return derive_current_risk_fields(
        q_income_points=3,
        q_obligations_points=3,
        q_savings_points=9,
        q_wealth_points=9,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )


def _assessment(assessment_id, advisor_id, *, version, is_current, deleted_at=None):
    return RiskAssessment(
        id=assessment_id,
        mandate_id="m-rcp",
        version=version,
        is_current=is_current,
        valid_from="2026-10-18",
        valid_to=None if is_current else "2026-10-18",
        supersedes_id=None,
        **_risk_fields(),
        is_overridden=0,
        **CURRENT_RISK_SCHEMA_MARKERS,
        assessed_at=NOW,
        assessed_by=advisor_id,
        created_at=NOW,
        updated_at=NOW,
        deleted_at=deleted_at,
    )


def _assert_pristine(session, assessment_id: str) -> None:
    session.expire_all()
    assessment = session.get(RiskAssessment, assessment_id)
    assert int(assessment.is_overridden or 0) == 0
    assert assessment.override_score_x10 is None
    assert assessment.override_profile is None
    assert not str(assessment.override_reason or "").strip()
    assert int(assessment.override_client_confirmed or 0) == 0
    assert int(assessment.override_warning_delivered or 0) == 0
    assert assessment.override_decision_id is None
    assert assessment.override_decision_hash is None


def _override(session, advisor, ra_id, *, score=60, profile="Ausgewogen", mandate_id="m-rcp", **extra):
    return profiling_router.override_risk_assessment(
        mandate_id=mandate_id,
        ra_id=ra_id,
        body=RiskAssessmentOverride(
            override_score_x10=score,
            override_profile=profile,
            override_reason=VALID_REASON,
            **extra,
        ),
        request=_FakeRequest(),
        db=session,
        current_user=advisor,
    )


def _spy_side_effects(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(profiling_router, "log", lambda *a, **k: calls.append("log"))
    monkeypatch.setattr(
        profiling_router, "invalidate_advisory_cache", lambda *a, **k: calls.append("cache"),
    )
    return calls


def _override_audit_rows(session, ra_id):
    return (
        session.query(AuditLog)
        .filter(
            AuditLog.table_name == "risk_assessments",
            AuditLog.record_id == ra_id,
            AuditLog.field_name == "override",
        )
        .order_by(AuditLog.sequence.asc(), AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )


def _decisions(session, ra_id):
    return (
        session.query(RiskOverrideDecision)
        .filter(RiskOverrideDecision.assessment_id == ra_id)
        .order_by(RiskOverrideDecision.sequence_no.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Restbefund A -- Current-Gate (Codex-Reproducer, ohne xfail)
# ---------------------------------------------------------------------------


def test_historical_noncurrent_assessment_cannot_be_overridden(session_factory, monkeypatch):
    with session_factory() as session:
        advisor = _seed(session)
        session.add_all([
            _assessment("ra-old", advisor.id, version=1, is_current=0),
            _assessment("ra-current", advisor.id, version=2, is_current=1),
        ])
        session.commit()
        calls = _spy_side_effects(monkeypatch)

        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-old")

        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "RISK_ASSESSMENT_NOT_CURRENT"
        assert exc.value.detail["current_assessment_id"] == "ra-current"
        _assert_pristine(session, "ra-old")
        _assert_pristine(session, "ra-current")
        assert _decisions(session, "ra-old") == []
        assert calls == []


def test_soft_deleted_assessment_cannot_be_overridden(session_factory, monkeypatch):
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-del", advisor.id, version=1, is_current=1, deleted_at=NOW))
        session.commit()
        calls = _spy_side_effects(monkeypatch)

        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-del")

        assert exc.value.status_code == 404
        _assert_pristine(session, "ra-del")
        assert calls == []


def test_assessment_of_other_mandate_cannot_be_overridden(session_factory, monkeypatch):
    from models.mandates import Mandate

    with session_factory() as session:
        advisor = _seed(session)
        session.add(Mandate(
            id="m-other", client_id="cl-rcp", mandate_number="M-OTHER",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-01-01", created_at=NOW, updated_at=NOW,
        ))
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        calls = _spy_side_effects(monkeypatch)

        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-current", mandate_id="m-other")

        assert exc.value.status_code == 404
        _assert_pristine(session, "ra-current")
        assert calls == []


# ---------------------------------------------------------------------------
# Restbefund A -- Optimistic Concurrency
# ---------------------------------------------------------------------------


def test_stale_expected_assessment_version_is_rejected(session_factory, monkeypatch):
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=2, is_current=1))
        session.commit()
        calls = _spy_side_effects(monkeypatch)

        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-current", expected_assessment_version=1)

        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "RISK_ASSESSMENT_VERSION_CONFLICT"
        _assert_pristine(session, "ra-current")
        assert calls == []


def test_stale_expected_override_decision_is_rejected(session_factory, monkeypatch):
    """Zwei Berater sehen denselben Stand; der zweite Re-Override darf den
    ersten nicht still ueberschreiben (kein Last-Write-Wins)."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()

        # Beide Clients haben "noch kein Override" gesehen (explizit null).
        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen",
                  expected_override_decision_id=None)
        first = session.get(RiskAssessment, "ra-current").override_decision_id
        assert first

        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-current", score=40, profile="Defensiv",
                      expected_override_decision_id=None)

        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "RISK_OVERRIDE_DECISION_CONFLICT"
        assert exc.value.detail["current_override_decision_id"] == first
        session.expire_all()
        ra = session.get(RiskAssessment, "ra-current")
        assert ra.override_score_x10 == 60
        assert ra.override_decision_id == first
        assert len(_decisions(session, "ra-current")) == 1

        # Mit dem korrekten Erwartungswert ist der Re-Override erlaubt.
        _override(session, advisor, "ra-current", score=40, profile="Defensiv",
                  expected_override_decision_id=first)
        assert len(_decisions(session, "ra-current")) == 2


def test_assessment_superseded_between_load_and_write_is_conflict(session_factory, monkeypatch):
    """Race: zwischen Validierung und Schreiben wird eine neue Assessment-
    Version aktuell. Der Compare-and-Swap-UPDATE prueft is_current erneut
    -> 409 statt Mutation der alten Basis."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        calls = _spy_side_effects(monkeypatch)

        real_requirements = profiling_router.override_documentation_requirements

        def _supersede_then_validate(**kwargs):
            session.execute(text(
                "UPDATE risk_assessments SET is_current = 0, valid_to = '2026-10-19' "
                "WHERE id = 'ra-current'"
            ))
            return real_requirements(**kwargs)

        monkeypatch.setattr(
            profiling_router, "override_documentation_requirements", _supersede_then_validate,
        )
        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-current")

        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "RISK_OVERRIDE_CONCURRENT_MODIFICATION"
        _assert_pristine(session, "ra-current")
        assert _decisions(session, "ra-current") == []
        assert calls == []


def test_parallel_reoverride_between_load_and_write_is_conflict(session_factory, monkeypatch):
    """Race: ein paralleler Re-Override setzt den Decision-Pointer, nachdem
    dieser Request geladen hat. Der CAS auf den alten Pointer verliert."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")
        calls = _spy_side_effects(monkeypatch)

        real_requirements = profiling_router.override_documentation_requirements

        def _foreign_pointer_then_validate(**kwargs):
            session.execute(text(
                "UPDATE risk_assessments SET override_decision_id = 'rod-foreign' "
                "WHERE id = 'ra-current'"
            ))
            return real_requirements(**kwargs)

        monkeypatch.setattr(
            profiling_router, "override_documentation_requirements", _foreign_pointer_then_validate,
        )
        with pytest.raises(HTTPException) as exc:
            _override(session, advisor, "ra-current", score=40, profile="Defensiv")

        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "RISK_OVERRIDE_CONCURRENT_MODIFICATION"
        assert len(_decisions(session, "ra-current")) == 1
        assert calls == []


def test_decision_sequence_is_unique_per_assessment(session_factory):
    """DB-Ebene: zwei Decisions mit derselben Sequenz fuer dasselbe
    Assessment (paralleles Append) scheitern am Unique-Index."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")
        existing = _decisions(session, "ra-current")[0]

        clone = RiskOverrideDecision(**{
            c.name: getattr(existing, c.name) for c in RiskOverrideDecision.__table__.columns
        })
        clone.id = "rod-dup"
        session.add(clone)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ---------------------------------------------------------------------------
# Restbefund B -- replaybare Decision-Evidence (Codex-Reproducer, ohne xfail)
# ---------------------------------------------------------------------------


def test_reoverride_appends_complete_immutable_decision_snapshots(session_factory):
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()

        for score, profile in [(60, "Ausgewogen"), (40, "Defensiv")]:
            _override(session, advisor, "ra-current", score=score, profile=profile)

        rows = _override_audit_rows(session, "ra-current")
        assert len(rows) == 2
        snapshots = [json.loads(row.new_value) for row in rows]
        assert all(REQUIRED_SNAPSHOT_KEYS <= set(snapshot) for snapshot in snapshots)
        assert [snapshot["requested_score_x10"] for snapshot in snapshots] == [60, 40]
        assert snapshots[0]["decision_hash"] != snapshots[1]["decision_hash"]


def test_decision_rows_bind_basis_rules_and_chain(session_factory):
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        ra = session.get(RiskAssessment, "ra-current")
        basis_final = ra.final_score_x10
        basis_capacity = ra.risk_capacity_score_x10
        basis_willingness = ra.risk_willingness_score_x10

        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")
        _override(session, advisor, "ra-current", score=40, profile="Defensiv")

        decisions = _decisions(session, "ra-current")
        assert [d.sequence_no for d in decisions] == [1, 2]
        assert [d.requested_score_x10 for d in decisions] == [60, 40]
        assert decisions[0].previous_decision_id is None
        assert decisions[1].previous_decision_id == decisions[0].id
        for decision in decisions:
            # PG-002 (PR #662): V2 bindet zusaetzlich den Mandanten.
            assert decision.schema_version == "RiskOverrideDecisionV2"
            assert decision.mandate_id == "m-rcp"
            assert decision.assessment_version == 1
            assert decision.basis_final_score_x10 == basis_final
            assert decision.basis_capacity_score_x10 == basis_capacity
            assert decision.basis_willingness_score_x10 == basis_willingness
            # DSG-ERASURE-APPEND-ONLY-001: Begruendung nur versiegelt in der
            # append-only Zeile (Crypto-Shredding), lesbar ueber den Vault.
            from services.pii_vault import is_sealed, reveal

            assert is_sealed(decision.reason)
            assert reveal(session, decision.reason) == VALID_REASON
            assert decision.actor_id == advisor.id
            assert decision.rules_version == OVERRIDE_DOCUMENTATION_RULES_VERSION
            assert decision.decision_hash == compute_decision_hash(decision)
            assert verify_decision(decision)

        session.expire_all()
        ra = session.get(RiskAssessment, "ra-current")
        assert ra.override_decision_id == decisions[1].id
        assert ra.override_decision_hash == decisions[1].decision_hash
        # Die Basis selbst bleibt unveraendert -- nur der Pointer wandert.
        assert ra.final_score_x10 == basis_final

        rows = _override_audit_rows(session, "ra-current")
        snapshots = [json.loads(row.new_value) for row in rows]
        assert [s["decision_id"] for s in snapshots] == [d.id for d in decisions]
        assert [s["decision_hash"] for s in snapshots] == [d.decision_hash for d in decisions]


def test_decision_records_effective_requirements(session_factory):
    """Aufwaerts innerhalb Capacity: Bestaetigung Pflicht, Warnung nicht --
    die Decision haelt die damals geltenden Requirements fest, damit ein
    spaeterer Policywechsel alte Entscheidungen nicht umdeutet."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        ra = session.get(RiskAssessment, "ra-current")
        upward = min(ra.final_score_x10 + 5, ra.risk_capacity_score_x10)
        assert upward > ra.final_score_x10
        from services.risk_scoring import profile_for_score_x10

        _override(session, advisor, "ra-current", score=upward,
                  profile=profile_for_score_x10(upward), override_client_confirmed=True)
        decision = _decisions(session, "ra-current")[0]
        assert decision.required_client_confirmation == 1
        assert decision.client_confirmed == 1

        _override(session, advisor, "ra-current", score=30, profile="Defensiv")
        downward = _decisions(session, "ra-current")[1]
        assert downward.required_client_confirmation == 0
        assert downward.required_warning == 0


def test_tampered_decision_fails_hash_verification(session_factory):
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")
        decision = _decisions(session, "ra-current")[0]
        assert verify_decision(decision)
        decision.requested_score_x10 = 100  # nur im Speicher, nie committed
        assert not verify_decision(decision)
        session.rollback()


def test_decision_table_is_append_only(session_factory):
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")

        with pytest.raises(Exception, match="immutable"):
            session.execute(text("UPDATE risk_override_decisions SET reason = 'x'"))
        session.rollback()
        with pytest.raises(Exception, match="immutable"):
            session.execute(text("DELETE FROM risk_override_decisions"))
        session.rollback()
        assert len(_decisions(session, "ra-current")) == 1


# ---------------------------------------------------------------------------
# Konsumenten: Strategie-Meldung + Risikoprofil-PDF zeigen ID/Hash
# ---------------------------------------------------------------------------


def test_strategy_override_message_references_decision(session_factory):
    from services.allocation_messages import WARN_OVERRIDE, classify_messages

    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")
        ra = session.get(RiskAssessment, "ra-current")

        messages = classify_messages(None, [], "optimal", None, ra)
        override_msgs = [m for m in messages if m["code"] == WARN_OVERRIDE]
        assert len(override_msgs) == 1
        message = override_msgs[0]
        assert message["override_decision_id"] == ra.override_decision_id
        assert message["override_decision_hash"] == ra.override_decision_hash
        assert ra.override_decision_id in message["body_advisor"]
        assert ra.override_decision_hash[:12] in message["body_advisor"]


def test_legacy_override_message_without_decision_is_marked():
    from types import SimpleNamespace

    from services.allocation_messages import WARN_OVERRIDE, classify_messages

    legacy = SimpleNamespace(
        is_overridden=1, override_score_x10=60, override_profile="Ausgewogen",
        override_reason=VALID_REASON, override_decision_id=None, override_decision_hash=None,
    )
    message = [m for m in classify_messages(None, [], "optimal", None, legacy)
               if m["code"] == WARN_OVERRIDE][0]
    assert message["override_decision_id"] is None
    assert "ohne Decision-Nachweis" in message["body_advisor"]


def test_risikoprofil_pdf_override_table_shows_decision_reference():
    from reportlab.platypus import Paragraph

    from services.pdf.base import RisikoprofilData
    from services.pdf.documents.risikoprofil import _override_documentation
    from services.pdf.styles import make_paragraph_styles

    data = RisikoprofilData(
        risk_profile_label="Ausgewogen", risk_capacity_score=8, risk_tolerance_score=5,
        is_overridden=True, override_reason=VALID_REASON,
        override_client_confirmed=True, override_warning_delivered=False,
        override_decision_id="rod-123", override_decision_hash="ab" * 32,
        override_decision_verified=True,
    )
    table = _override_documentation(data, make_paragraph_styles())
    texts = [
        cell.getPlainText() if isinstance(cell, Paragraph) else str(cell)
        for row in table._cellvalues for cell in row
    ]
    joined = " ".join(texts)
    assert "rod-123" in joined
    assert ("ab" * 32) in joined
    assert "verifiziert" in joined


def test_risikoprofil_pdf_flags_unverified_decision_hash():
    from reportlab.platypus import Paragraph

    from services.pdf.base import RisikoprofilData
    from services.pdf.documents.risikoprofil import _override_documentation
    from services.pdf.styles import make_paragraph_styles

    data = RisikoprofilData(
        risk_profile_label="Ausgewogen", risk_capacity_score=8, risk_tolerance_score=5,
        is_overridden=True, override_reason=VALID_REASON,
        override_decision_id="rod-123", override_decision_hash="cd" * 32,
        override_decision_verified=False,
    )
    table = _override_documentation(data, make_paragraph_styles())
    joined = " ".join(
        cell.getPlainText() if isinstance(cell, Paragraph) else str(cell)
        for row in table._cellvalues for cell in row
    )
    assert "NICHT verifiziert" in joined
