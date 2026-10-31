"""RISK-PROFILE-SIGNOFF-001 (Codex-Closure-Review zu PR #657, docs/audits/
2026-10-20-risk-override-signoff-pr657-closure-review.md).

A) Eine vorhandene Signatur des Risikoprofils ueberlebte einen spaeteren
   Override, obwohl sich das wirksame Profil danach geaendert hatte.
B) Eine neue Signatur pruefte die aktuelle Override-Decision nicht
   fail-closed und band weder Decision-ID noch -Hash in Response/Audit.

Die beiden Codex-Restvertraege (docs/audits/reproducers/test_2026_10_20_
pr657_risk_override_signoff_adversarial.py, dort xfail-strict) sind hier
ohne xfail uebernommen (die ersten zwei Tests), gefolgt von den
Pflichtregressionen aus Abschnitt 7 des Reviews.
"""
from __future__ import annotations

import json

import pytest
from core.reason_codes import DomainError  # noqa: E402  K-2b: Gates werfen DomainError
from sqlalchemy import text

import models.client_login  # noqa: F401  (Tabelle fuer den Portal-Test registrieren)
from models.profiling import RiskAssessment, RiskOverrideDecision, RiskProfileSignoff
from models.review import AdvisoryLog, AuditLog
from routers import profiling as profiling_router
from routers.profiling import RiskProfileSignRequest
from services import risk_profile_signoff as signoff_service
from services.risk_override_decision import resolve_assessment_decision
from services.risk_profile_signoff import (
    build_signoff_view,
    signoff_view_lines,
    verify_signoff,
)
from tests.test_risk_capacity_plausibility import (
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401 - pytest fixture re-export
)
from tests.test_risk_override_current_gate_decision_log import (
    _assessment,
    _override,
)


def _sign(session, advisor, body=None):
    return profiling_router.sign_risk_profile(
        mandate_id="m-rcp",
        request=_FakeRequest(),
        body=body,
        db=session,
        current_user=advisor,
    )


def _signoffs(session, ra_id="ra-current"):
    return (
        session.query(RiskProfileSignoff)
        .filter(RiskProfileSignoff.assessment_id == ra_id)
        .order_by(RiskProfileSignoff.sequence_no.asc())
        .all()
    )


def _audit(session, field, ra_id="ra-current"):
    return (
        session.query(AuditLog)
        .filter(AuditLog.record_id == ra_id, AuditLog.field_name == field)
        .order_by(AuditLog.sequence.asc(), AuditLog.created_at.asc())
        .all()
    )


def _spy(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(signoff_service, "log", lambda *a, **k: calls.append("log"))
    monkeypatch.setattr(
        profiling_router, "invalidate_advisory_cache", lambda *a, **k: calls.append("cache"),
    )
    return calls


def _fresh(session, ra_id="ra-current") -> RiskAssessment:
    session.expire_all()
    return session.get(RiskAssessment, ra_id)


@pytest.fixture
def seeded(session_factory):  # noqa: F811
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        yield session, advisor


# ---------------------------------------------------------------------------
# Codex-Reproducer (ohne xfail)
# ---------------------------------------------------------------------------


def test_override_invalidates_signature_of_previous_effective_profile(session_factory):  # noqa: F811
    """A signature cannot survive a later change of the effective risk profile."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()

        profiling_router.sign_risk_profile(
            mandate_id="m-rcp",
            request=_FakeRequest(),
            body=None,
            db=session,
            current_user=advisor,
        )
        signed = session.get(RiskAssessment, "ra-current")
        assert signed.client_signed_at

        _override(session, advisor, "ra-current", score=40, profile="Defensiv")
        session.expire_all()
        changed = session.get(RiskAssessment, "ra-current")

        assert changed.override_decision_id
        assert changed.client_signed_at is None
        assert changed.client_signed_method is None
        assert changed.client_signed_ref is None


def test_signoff_binds_verified_override_decision_id_and_hash(session_factory):  # noqa: F811
    """Signoff response and audit event must identify the exact decision."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _override(session, advisor, "ra-current", score=40, profile="Defensiv")

        assessment = session.get(RiskAssessment, "ra-current")
        decision_id, decision_hash, verified = resolve_assessment_decision(
            session, assessment,
        )
        assert verified is True

        response = profiling_router.sign_risk_profile(
            mandate_id="m-rcp",
            request=_FakeRequest(),
            body=None,
            db=session,
            current_user=advisor,
        )
        assert response.get("override_decision_id") == decision_id
        assert response.get("override_decision_hash") == decision_hash

        row = (
            session.query(AuditLog)
            .filter(
                AuditLog.record_id == "ra-current",
                AuditLog.field_name == "client_signed",
            )
            .order_by(AuditLog.sequence.desc())
            .first()
        )
        payload = json.loads(row.new_value)
        assert payload["override_decision_id"] == decision_id
        assert payload["override_decision_hash"] == decision_hash
        assert payload["override_decision_verified"] is True


# ---------------------------------------------------------------------------
# Restbefund A -- Invalidierung, Historie bleibt
# ---------------------------------------------------------------------------


def test_override_sets_signature_required_and_keeps_old_signoff_as_history(seeded):
    session, advisor = seeded
    first = _sign(session, advisor)
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")

    ra = _fresh(session)
    assert ra.signoff_status == "signature_required"
    assert ra.signoff_id is None and ra.signoff_hash is None
    assert ra.signoff_state == "signature_required"
    rows = _signoffs(session)
    assert [r.id for r in rows] == [first["signoff_id"]]
    assert verify_signoff(rows[0])
    assert rows[0].override_binding == "no_override"
    # Invalidierung ist replaybar im Audit-Log (inkl. bisheriger Signatur).
    inv = _audit(session, "client_signed_invalidated")
    assert len(inv) == 1
    payload = json.loads(inv[0].new_value)
    assert payload["invalidated_signoff_id"] == first["signoff_id"]
    assert payload["override_decision_id"] == ra.override_decision_id
    assert payload["signoff_status"] == "signature_required"


def test_reoverride_of_signed_override_forces_new_signature_bound_to_new_decision(seeded):
    session, advisor = seeded
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    first = _sign(session, advisor)
    first_decision = first["override_decision_id"]

    _override(session, advisor, "ra-current", score=30, profile="Defensiv")
    ra = _fresh(session)
    assert ra.signoff_state == "signature_required"
    assert ra.client_signed_at is None
    assert ra.override_decision_id != first_decision

    second = _sign(session, advisor)
    assert second["override_decision_id"] == ra.override_decision_id
    assert second["override_decision_hash"] == ra.override_decision_hash
    assert second["previous_signoff_id"] is None  # Pointer war invalidiert
    rows = _signoffs(session)
    assert [r.sequence_no for r in rows] == [1, 2]
    assert rows[0].override_decision_id == first_decision
    assert rows[1].override_decision_id == ra.override_decision_id
    assert all(verify_signoff(r) for r in rows)


def test_resign_chains_previous_signoff(seeded):
    session, advisor = seeded
    first = _sign(session, advisor)
    second = _sign(session, advisor, RiskProfileSignRequest(
        note="erneuert", expected_signoff_id=first["signoff_id"],
    ))
    assert second["previous_signoff_id"] == first["signoff_id"]
    ra = _fresh(session)
    assert ra.signoff_id == second["signoff_id"]
    assert ra.client_signed_ref == "erneuert"


# ---------------------------------------------------------------------------
# Restbefund B -- Bindung + fail-closed
# ---------------------------------------------------------------------------


def test_unoverridden_profile_binds_explicit_no_override_and_assessment_version(seeded):
    session, advisor = seeded
    res = _sign(session, advisor)
    assert res["override_binding"] == "no_override"
    assert res["override_decision_id"] is None
    assert res["override_decision_verified"] is None
    assert res["assessment_version"] == 1
    row = session.get(RiskProfileSignoff, res["signoff_id"])
    assert row.assessment_version == 1
    assert row.effective_profile == row.final_profile
    assert row.effective_score_x10 == row.final_score_x10
    assert row.assessment_input_hash and len(row.assessment_input_hash) == 64
    assert row.signoff_hash == res["signoff_hash"] and verify_signoff(row)
    ra = _fresh(session)
    assert ra.signoff_id == row.id and ra.signoff_hash == row.signoff_hash
    assert ra.signoff_status == "signed"


def test_signoff_snapshot_binds_exact_verified_decision(seeded):
    session, advisor = seeded
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    ra = _fresh(session)
    res = _sign(session, advisor)
    row = session.get(RiskProfileSignoff, res["signoff_id"])
    assert row.override_binding == "decision"
    assert row.override_decision_id == ra.override_decision_id
    assert row.override_decision_hash == ra.override_decision_hash
    assert row.effective_score_x10 == 40 and row.effective_profile == "Defensiv"
    assert row.is_overridden == 1
    assert row.override_rules_version
    audit = json.loads(_audit(session, "client_signed")[-1].new_value)
    assert audit["signoff_id"] == row.id
    assert audit["signoff_hash"] == row.signoff_hash


def _tamper_missing(session):
    session.execute(text(
        "UPDATE risk_assessments SET override_decision_id = 'rod-missing' WHERE id = 'ra-current'"
    ))


def _tamper_hash(session):
    session.execute(text(
        "UPDATE risk_assessments SET override_decision_hash = 'ff' WHERE id = 'ra-current'"
    ))


def _tamper_projection(session):
    session.execute(text(
        "UPDATE risk_assessments SET override_score_x10 = 90, override_profile = 'Aktien' "
        "WHERE id = 'ra-current'"
    ))


def _tamper_foreign(session):
    # Decision eines anderen Assessments (Trigger verhindert Aenderung der
    # Zeile selbst; der Pointer wird auf eine fremde Decision gebogen).
    advisor_id = session.execute(text("SELECT id FROM users LIMIT 1")).scalar()
    session.add(_assessment("ra-other", advisor_id, version=1, is_current=0))
    session.commit()
    other = session.query(RiskOverrideDecision).first()
    session.execute(text(
        "UPDATE risk_assessments SET is_current = 0 WHERE id = 'ra-current'"
    ))
    session.execute(text(
        "UPDATE risk_assessments SET is_current = 1, is_overridden = 1, "
        "override_score_x10 = :s, override_profile = :p, override_reason = :r, "
        "override_decision_id = :d, override_decision_hash = :h WHERE id = 'ra-other'"
    ), {"s": other.requested_score_x10, "p": other.requested_profile,
        "r": other.reason, "d": other.id, "h": other.decision_hash})


@pytest.mark.parametrize("tamper", [
    _tamper_missing, _tamper_hash, _tamper_projection, _tamper_foreign,
], ids=["missing_row", "hash_tamper", "projection_drift", "foreign_assessment"])
def test_unverifiable_decision_is_409_before_any_effect(seeded, monkeypatch, tamper):
    session, advisor = seeded
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    tamper(session)
    session.commit()
    before_logs = session.query(AdvisoryLog).count()
    calls = _spy(monkeypatch)

    with pytest.raises(DomainError) as exc:
        _sign(session, advisor)

    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "RISK_OVERRIDE_DECISION_UNVERIFIABLE"
    assert calls == []
    assert session.query(RiskProfileSignoff).count() == 0
    assert session.query(AdvisoryLog).count() == before_logs
    session.expire_all()
    assert all(
        ra.client_signed_at is None and ra.signoff_id is None
        for ra in session.query(RiskAssessment).all()
    )


def test_legacy_override_without_decision_requires_remediation(seeded, monkeypatch):
    session, advisor = seeded
    session.execute(text(
        "UPDATE risk_assessments SET is_overridden = 1, override_score_x10 = 40, "
        "override_profile = 'Defensiv', override_reason = 'Altbestand-Override ohne Decision' "
        "WHERE id = 'ra-current'"
    ))
    session.commit()
    assert _fresh(session).signoff_state == "remediation_required"
    calls = _spy(monkeypatch)
    with pytest.raises(DomainError) as exc:
        _sign(session, advisor)
    assert exc.value.status_code == 409
    assert exc.value.detail["signoff_state"] == "remediation_required"
    assert calls == []
    assert session.query(RiskProfileSignoff).count() == 0


@pytest.mark.parametrize("body,code", [
    (RiskProfileSignRequest(expected_assessment_version=2), "RISK_ASSESSMENT_VERSION_CONFLICT"),
    (RiskProfileSignRequest(expected_override_decision_id="rod-stale"), "RISK_OVERRIDE_DECISION_CONFLICT"),
    (RiskProfileSignRequest(expected_signoff_id="rps-stale"), "RISK_PROFILE_SIGNOFF_CONFLICT"),
])
def test_stale_expectations_are_409_before_any_effect(seeded, monkeypatch, body, code):
    session, advisor = seeded
    calls = _spy(monkeypatch)
    with pytest.raises(DomainError) as exc:
        _sign(session, advisor, body)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == code
    assert calls == []
    assert session.query(RiskProfileSignoff).count() == 0


# ---------------------------------------------------------------------------
# Race-Vertraege (beide Commit-Reihenfolgen)
# ---------------------------------------------------------------------------


def test_override_between_sign_load_and_write_is_conflict(seeded, monkeypatch):
    """sign laedt -> paralleler Override schreibt -> sign-CAS verliert."""
    session, advisor = seeded
    calls = _spy(monkeypatch)
    real_hash = signoff_service.assessment_input_hash

    def _override_then_hash(db, assessment):
        session.execute(text(
            "UPDATE risk_assessments SET is_overridden = 1, override_score_x10 = 40, "
            "override_profile = 'Defensiv', override_reason = 'parallel', "
            "override_decision_id = 'rod-parallel', override_decision_hash = 'aa' "
            "WHERE id = 'ra-current'"
        ))
        return real_hash(db, assessment)

    monkeypatch.setattr(signoff_service, "assessment_input_hash", _override_then_hash)
    with pytest.raises(DomainError) as exc:
        _sign(session, advisor)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "RISK_PROFILE_SIGNOFF_CONCURRENT_MODIFICATION"
    assert calls == []
    assert session.query(RiskProfileSignoff).count() == 0
    assert _fresh(session).client_signed_at is None


def test_sign_between_override_load_and_write_is_invalidated_by_override(seeded, monkeypatch):
    """override laedt -> parallele Signatur committet -> Override-CAS gewinnt
    und setzt die (fuer das alte Profil erfasste) Signatur zurueck."""
    session, advisor = seeded
    real_requirements = profiling_router.override_documentation_requirements
    state = {"signed": None}

    def _sign_then_validate(**kwargs):
        if state["signed"] is None:
            state["signed"] = _sign(session, advisor)
        return real_requirements(**kwargs)

    monkeypatch.setattr(
        profiling_router, "override_documentation_requirements", _sign_then_validate,
    )
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    ra = _fresh(session)
    assert state["signed"]["signoff_id"]
    assert ra.override_decision_id
    assert ra.signoff_state == "signature_required"
    assert ra.client_signed_at is None and ra.signoff_id is None
    # Der parallele Signoff bleibt historisch und ist an no_override gebunden.
    assert [r.override_binding for r in _signoffs(session)] == ["no_override"]


def test_signoff_sequence_is_unique_per_assessment(seeded):
    session, advisor = seeded
    _sign(session, advisor)
    row = _signoffs(session)[0]
    clone = RiskProfileSignoff(**{
        c.name: getattr(row, c.name) for c in RiskProfileSignoff.__table__.columns
    })
    clone.id = "rps-dup"
    session.add(clone)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_signoff_table_is_append_only(seeded):
    session, advisor = seeded
    _sign(session, advisor)
    with pytest.raises(Exception, match="immutable"):
        session.execute(text("UPDATE risk_profile_signoffs SET note = 'x'"))
    session.rollback()
    with pytest.raises(Exception, match="immutable"):
        session.execute(text("DELETE FROM risk_profile_signoffs"))
    session.rollback()
    assert len(_signoffs(session)) == 1


# ---------------------------------------------------------------------------
# Altbestand
# ---------------------------------------------------------------------------


def test_legacy_signature_without_snapshot_is_marked_unbound(seeded):
    session, _ = seeded
    session.execute(text(
        "UPDATE risk_assessments SET client_signed_at = '2026-07-19T10:00:00.000Z', "
        "client_signed_method = 'advisor_recorded' WHERE id = 'ra-current'"
    ))
    session.commit()
    ra = _fresh(session)
    assert ra.signoff_state == "legacy_unbound"
    view = build_signoff_view(session, ra)
    joined = " ".join(t for _, t in signoff_view_lines(view))
    assert "Altsignatur" in joined
    assert "nicht an eine Override-Decision gebunden" in joined
    from schemas.profiling import RiskAssessmentResponse

    payload = RiskAssessmentResponse.model_validate(ra).model_dump()
    assert payload["signoff_state"] == "legacy_unbound"
    assert payload["client_signed_at"] == "2026-07-19T10:00:00.000Z"


# ---------------------------------------------------------------------------
# Eine Referenz: API, Audit, AdvisoryLog, Strategie, PDFs
# ---------------------------------------------------------------------------


def test_api_audit_advisory_log_strategy_and_pdfs_share_one_reference(seeded):
    from services.allocation_messages import WARN_OVERRIDE, classify_messages
    from services.pdf.base import ProtokollData, RisikoprofilData
    from services.pdf.documents.protokoll import build_protokoll_flowables
    from services.pdf.documents.risikoprofil import build_risikoprofil_flowables
    from routers.pdf_reports import _risk_signoff_view
    from schemas.profiling import RiskAssessmentResponse

    session, advisor = seeded
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    res = _sign(session, advisor)
    ra = _fresh(session)
    sid, shash = res["signoff_id"], res["signoff_hash"]
    did, dhash = res["override_decision_id"], res["override_decision_hash"]

    api = RiskAssessmentResponse.model_validate(ra).model_dump()
    assert (api["signoff_id"], api["signoff_hash"], api["signoff_state"]) == (sid, shash, "signed")
    assert (api["override_decision_id"], api["override_decision_hash"]) == (did, dhash)

    audit = json.loads(_audit(session, "client_signed")[-1].new_value)
    assert (audit["signoff_id"], audit["signoff_hash"]) == (sid, shash)

    # CIO-Abnahme #662: eine Berater-Signatur ist kein Beratungsgespraech ->
    # KEIN AdvisoryLog-Eintrag; Audit-Log + Signoff-Tabelle sind der Nachweis.
    assert res["advisory_log_id"] is None
    assert session.query(AdvisoryLog).count() == 0
    assert res["evidence_level"] == "advisor_attested"

    msg = [m for m in classify_messages(None, [], "optimal", None, ra) if m["code"] == WARN_OVERRIDE][0]
    assert (msg["signoff_id"], msg["signoff_hash"], msg["signoff_state"]) == (sid, shash, "signed")
    assert sid in msg["body_advisor"]

    view = _risk_signoff_view(session, ra)
    assert view["signoff_verified"] is True
    joined = " ".join(t for _, t in view["lines"])
    assert sid in joined and shash in joined and did in joined and dhash in joined
    assert "Hash verifiziert" in joined
    risk_texts = _render_texts(build_risikoprofil_flowables, RisikoprofilData(
        risk_profile_label="Defensiv", risk_capacity_score=50, risk_tolerance_score=50,
        signoff_state=view["state"], signoff_id=view["signoff_id"],
        signoff_hash=view["signoff_hash"], signoff_lines=view["lines"],
    ))
    proto_texts = _render_texts(build_protokoll_flowables, ProtokollData(
        risk_signoff_state=view["state"], risk_signoff_id=view["signoff_id"],
        risk_signoff_hash=view["signoff_hash"], risk_signoff_lines=view["lines"],
    ))
    for texts in (risk_texts, proto_texts):
        assert sid in texts and shash in texts and did in texts and dhash in texts


def test_signature_required_is_visible_in_strategy_and_pdf_lines(seeded):
    from services.allocation_messages import WARN_OVERRIDE, classify_messages
    from routers.pdf_reports import _risk_signoff_view

    session, advisor = seeded
    _sign(session, advisor)
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    ra = _fresh(session)
    msg = [m for m in classify_messages(None, [], "optimal", None, ra) if m["code"] == WARN_OVERRIDE][0]
    assert msg["signoff_state"] == "signature_required"
    assert msg["signoff_id"] is None
    assert "Neue Signatur des Risikoprofils erforderlich" in msg["body_advisor"]
    joined = " ".join(t for _, t in _risk_signoff_view(session, ra)["lines"])
    assert "Neue Signatur erforderlich" in joined
    assert ra.override_decision_id in joined


def test_tampered_signoff_row_is_flagged_in_pdf_view(seeded):
    from routers.pdf_reports import _risk_signoff_view

    session, advisor = seeded
    _sign(session, advisor)
    session.execute(text("UPDATE risk_assessments SET signoff_hash = 'ee' WHERE id = 'ra-current'"))
    session.commit()
    view = _risk_signoff_view(session, _fresh(session))
    assert view["signoff_verified"] is False
    assert "NICHT verifiziert" in " ".join(t for _, t in view["lines"])


def test_portal_signoff_binds_decision_and_counts_as_client_signature(session_factory):  # noqa: F811
    from models.client_login import ClientLogin
    from models.users import User
    from routers.client_portal import client_portal_sign_risk_profile
    from tests.test_risk_capacity_plausibility import NOW

    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        cu = User(id="cu-rcp", username="cu-rcp", password_hash="h", full_name="Kunde",
                  role="client", is_active=1, created_at=NOW, updated_at=NOW)
        session.add(cu)
        session.add(ClientLogin(id="lnk-rcp", user_id="cu-rcp", client_id="cl-rcp",
                                is_active=1, created_by=advisor.id, created_at=NOW))
        session.commit()
        _override(session, advisor, "ra-current", score=40, profile="Defensiv")
        ra = _fresh(session)
        res = client_portal_sign_risk_profile(
            mandate_id="m-rcp", request=_FakeRequest(), db=session, current_user=cu,
        )
        assert res["client_signed_method"] == "portal"
        assert res["evidence_level"] == "client_portal"
        assert res["override_decision_id"] == ra.override_decision_id
        entry = session.get(AdvisoryLog, res["advisory_log_id"])
        assert entry.client_signed == 1 and entry.client_signed_at
        assert entry.advisor_id == advisor.id
        # Kennzeichnung als Signoff-Ereignis + dieselbe Referenz.
        assert entry.system_event == "risk_profile_signoff"
        assert entry.entry_type == "Eignungsprüfung"
        assert entry.duration_minutes is None
        assert res["signoff_id"] in entry.description and res["signoff_hash"] in entry.description
        assert res["override_decision_id"] in entry.description
        assert res["override_decision_hash"] in entry.description
        assert _fresh(session).client_signed_ref == "cu-rcp"


def test_signoffs_never_become_the_last_advisory_appointment(session_factory):  # noqa: F811
    """CIO-Abnahme #662: nach Berater- UND Portal-Signatur bleibt der
    "letzte Termin" im Report der echte letzte Beratungstermin."""
    from models.client_login import ClientLogin
    from models.mandates import Mandate
    from models.users import User
    from routers.client_portal import client_portal_sign_risk_profile
    from services.advisory_log_service import create_advisory_log, get_latest_active_entry
    from tests.test_risk_capacity_plausibility import NOW
    from types import SimpleNamespace

    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        cu = User(id="cu-rcp", username="cu-rcp", password_hash="h", full_name="Kunde",
                  role="client", is_active=1, created_at=NOW, updated_at=NOW)
        session.add(cu)
        session.add(ClientLogin(id="lnk-rcp", user_id="cu-rcp", client_id="cl-rcp",
                                is_active=1, created_by=advisor.id, created_at=NOW))
        session.commit()
        meeting = create_advisory_log(session, mandate_id="m-rcp", advisor=advisor, payload=SimpleNamespace(
            entry_type="Jahresreview", title="Jahresgespraech 2026",
            description="Echtes Beratungsgespraech mit dem Kunden zum Jahresreview.",
            decision=None, trigger_id=None, recommendation_run_id=None, status="Empfohlen",
            client_signed=False, client_signed_at=None, document_id=None, entry_date=None,
            entry_datetime="2026-01-15T10:00:00.000Z", duration_minutes=60,
            communication_channel="persoenlich", language="de", location=None,
            participants=[], topics=["Jahresreview"], risk_warnings_given=[],
            cost_disclosure_given=False, conflict_disclosure_ids=[], suitability_check_id=None,
        ))
        session.commit()

        _sign(session, advisor)
        assert get_latest_active_entry(session, mandate_id="m-rcp").id == meeting.id
        client_portal_sign_risk_profile(
            mandate_id="m-rcp", request=_FakeRequest(), db=session, current_user=cu,
        )
        assert session.query(AdvisoryLog).count() == 2
        assert get_latest_active_entry(session, mandate_id="m-rcp").id == meeting.id

        from services.advisory_report import _build_beratungsprotokoll

        mandate = session.get(Mandate, "m-rcp")
        section = _build_beratungsprotokoll(session, mandate)
        assert section["latest_entry"]["id"] == meeting.id
        assert section["last_review_date"] == "2026-01-15"


def _render_texts(builder, data) -> str:
    from datetime import date

    from reportlab.platypus import Paragraph, Table

    from services.pdf.base import PDFContext

    ctx = PDFContext(mandate_name="Max Muster", advisor_name="Advisor", report_date=date(2026, 10, 20))
    out: list[str] = []

    def walk(item):
        if isinstance(item, Paragraph):
            out.append(item.getPlainText())
        elif isinstance(item, Table):
            for row in item._cellvalues:
                for cell in row:
                    for c in (cell if isinstance(cell, (list, tuple)) else [cell]):
                        walk(c)
        elif isinstance(item, str):
            out.append(item)

    for flowable in builder(ctx, data):
        walk(flowable)
    return " ".join(out)
