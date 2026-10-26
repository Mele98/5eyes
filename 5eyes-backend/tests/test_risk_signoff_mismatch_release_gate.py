"""RISK-SIGNOFF-MISMATCH-RELEASE-GATE (CIO-Entscheid 2026-10-24).

Ein Risikoprofil-Signoff im Zustand ``integrity_mismatch`` (Zeile oder
fachliche Bindung passt nicht mehr zum Assessment, siehe
``services/risk_profile_signoff.verify_signoff_binding``) wurde bisher in
Kundendokumenten nur als "nicht gueltig" ausgewiesen -- das Dokument wurde
trotzdem erzeugt, signiert bzw. weitergeleitet.

Jetzt sperrt das zentrale Release-Gate
(``services/recommendation_release_gate.assert_risk_signoff_release_eligible``)
fail-closed mit 409 + Reason-Code, BEVOR der Kanal eine Wirkung hat:

* Kunden-PDFs: Anlagestrategie, Risikoprofil, Beratungsprotokoll,
  Beratungsentscheid (Kundensignatur), Kostenausweis -- kein Render, kein
  Archiv-Eintrag;
* E-Signing der gebundenen Dokumenttypen -- keine Signatur;
* Handoff -- kein Snapshot, keine Persistierung.

Gegenproben: gueltige Signatur und Legacy-Zustaende (unsigniert,
Altsignatur ohne Signoff) gehen wie bisher durch; nicht gebundene
Dokumenttypen und der interne Advisory-Report werden nicht gesperrt.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from models.mandates import Mandate
from models.portfolio_handoff import PortfolioHandoff
from models.profiling import RiskAssessment
from models.review import ContractDocument
from routers import pdf_reports
from routers import portfolio_handoff as handoff_router
from routers import profiling as profiling_router
from routers.review import sign_document
from schemas.portfolio_handoff import PortfolioHandoffCreate
from schemas.review import ContractDocumentSign
from services.recommendation_release_gate import (
    CHANNEL_ADVISORY_PDF,
    CHANNEL_CLIENT_PDF,
    CHANNEL_HANDOFF,
    CHANNEL_SIGNATURE,
    RISK_PROFILE_SIGNOFF_MISMATCH,
    SIGNOFF_BOUND_DOCUMENT_TYPES,
    assert_recommendation_release_eligible,
    assert_risk_signoff_release_eligible,
)
from services.risk_profile_signoff import STATE_INTEGRITY_MISMATCH, build_signoff_view
from tests.test_risk_capacity_plausibility import (
    NOW,
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401 - pytest fixture re-export
)
from tests.test_risk_override_current_gate_decision_log import _assessment

_SIGNATURE = "data:image/png;base64,iVBORw0KGgo="
_MID = "m-rcp"

_CLIENT_DOCUMENT_TYPES = (
    "Anlagestrategie",
    "Risikoprofilierung",
    "Beratungsprotokoll",
    "Eignungsprüfung",
    "Override-Zustimmung",
    "Kostenausweis",
    "Anlagerezept",
)


@pytest.fixture
def seeded(session_factory):  # noqa: F811
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        yield session, advisor


def _sign_profile(session, advisor) -> None:
    profiling_router.sign_risk_profile(
        mandate_id=_MID, request=_FakeRequest(), body=None, db=session, current_user=advisor,
    )


def _tamper(session) -> None:
    """Profil nach der Signatur veraendert -> Bindung bricht."""
    session.execute(text(
        "UPDATE risk_assessments SET final_profile = 'Aktien' WHERE id = 'ra-current'"
    ))
    session.commit()
    session.expire_all()
    view = build_signoff_view(session, session.get(RiskAssessment, "ra-current"))
    assert view["state"] == STATE_INTEGRITY_MISMATCH


@pytest.fixture
def mismatch(seeded):
    session, advisor = seeded
    _sign_profile(session, advisor)
    _tamper(session)
    return session, advisor


def _mandate(session) -> Mandate:
    return session.get(Mandate, _MID)


def _assert_blocked(exc_info, channel: str) -> None:
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["reason_code"] == RISK_PROFILE_SIGNOFF_MISMATCH
    assert detail["channel"] == channel
    assert "Risikoprofil-Signatur passt nicht mehr" in detail["message"]
    assert "neu signieren" in detail["message"]
    assert "final_profile" in detail["integrity_mismatches"]


def _document_count(session) -> int:
    return session.query(ContractDocument).filter(ContractDocument.mandate_id == _MID).count()


def _add_document(session, advisor, document_type: str) -> str:
    doc_id = f"doc-{abs(hash(document_type)) % 10_000_000}"
    session.add(ContractDocument(
        id=doc_id, mandate_id=_MID, document_type=document_type, title=document_type,
        status="Entwurf", signed_by_advisor=0, signed_by_client=0, version=1,
        created_by=advisor.id, created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    return doc_id


def _sign_doc(session, advisor, doc_id):
    return sign_document(
        mandate_id=_MID, doc_id=doc_id,
        body=ContractDocumentSign(
            signed_by_client=True, signature_image=_SIGNATURE, signer_name="Kunde",
        ),
        request=_FakeRequest(), db=session, current_user=advisor,
    )


# ── Dokumenttyp-Liste ─────────────────────────────────────────────────────


def test_bound_document_types_match_cio_list():
    assert set(_CLIENT_DOCUMENT_TYPES) <= SIGNOFF_BOUND_DOCUMENT_TYPES


# ── Kunden-PDFs ───────────────────────────────────────────────────────────


def _no_render(monkeypatch) -> list:
    """Jeder Render-/Archivpfad wird protokolliert -- muss leer bleiben."""
    calls: list = []
    renderer = pdf_reports.ReportLabRenderer
    for name in dir(renderer):
        if name.startswith("render_"):
            monkeypatch.setattr(
                renderer, name, lambda *a, _n=name, **k: calls.append(_n) or b"%PDF",
            )
    monkeypatch.setattr(
        pdf_reports, "archive_generated_pdf", lambda *a, **k: calls.append("archive"),
    )
    return calls


_PDF_ROUTES = {
    "anlagestrategie": lambda db, user: pdf_reports.get_anlagestrategie_pdf(
        mandate_id=_MID, request=_FakeRequest(), db=db, current_user=user,
        expected_allocation_id=None,
    ),
    "risikoprofil": lambda db, user: pdf_reports.get_risikoprofil_pdf(
        mandate_id=_MID, request=_FakeRequest(), db=db, current_user=user,
    ),
    "protokoll": lambda db, user: pdf_reports.get_protokoll_pdf(
        mandate_id=_MID, request=_FakeRequest(), db=db, current_user=user,
    ),
    "contract_signoff": lambda db, user: pdf_reports.get_contract_signoff_pdf(
        mandate_id=_MID, db=db, current_user=user,
    ),
    "cost_disclosure": lambda db, user: pdf_reports.get_cost_disclosure_pdf(
        mandate_id=_MID, request=_FakeRequest(), db=db, current_user=user,
    ),
    "portfolio": lambda db, user: pdf_reports.get_portfolio_pdf(
        mandate_id=_MID, request=_FakeRequest(), db=db, current_user=user,
    ),
}


@pytest.mark.parametrize("route", sorted(_PDF_ROUTES))
def test_client_pdf_blocked_on_signoff_mismatch(mismatch, monkeypatch, route):
    session, advisor = mismatch
    calls = _no_render(monkeypatch)
    before = _document_count(session)
    with pytest.raises(HTTPException) as exc:
        _PDF_ROUTES[route](session, advisor)
    _assert_blocked(exc, CHANNEL_CLIENT_PDF)
    assert calls == [], f"{route}: kein Render/Archiv bei gesperrtem Gate"
    assert _document_count(session) == before


def test_risikoprofil_pdf_renders_with_valid_signoff(seeded, monkeypatch):
    session, advisor = seeded
    _sign_profile(session, advisor)
    calls = _no_render(monkeypatch)
    response = _PDF_ROUTES["risikoprofil"](session, advisor)
    assert response.status_code == 200
    assert "render_risikoprofil" in calls


def test_portfolio_pdf_with_valid_signoff_passes_signoff_gate(seeded, monkeypatch):
    """Gegenprobe: das Signoff-Gate laesst durch; die Fixture hat keine
    Soll-Allokation, also greift erst der bestehende Allokations-Fehler."""
    session, advisor = seeded
    _sign_profile(session, advisor)
    _no_render(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _PDF_ROUTES["portfolio"](session, advisor)
    assert "Soll-Allokation" in str(exc.value.detail)
    assert RISK_PROFILE_SIGNOFF_MISMATCH not in str(exc.value.detail)


@pytest.mark.parametrize("legacy", ["unsigned", "legacy_unbound"])
def test_risikoprofil_pdf_legacy_unchanged(seeded, monkeypatch, legacy):
    session, advisor = seeded
    if legacy == "legacy_unbound":
        session.execute(text(
            "UPDATE risk_assessments SET client_signed_at = :ts, "
            "client_signed_method = 'advisor_recorded' WHERE id = 'ra-current'"
        ), {"ts": NOW})
        session.commit()
    calls = _no_render(monkeypatch)
    response = _PDF_ROUTES["risikoprofil"](session, advisor)
    assert response.status_code == 200
    assert "render_risikoprofil" in calls


# ── E-Signing ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("document_type", _CLIENT_DOCUMENT_TYPES)
def test_signing_bound_document_blocked_without_mutation(mismatch, document_type):
    session, advisor = mismatch
    doc_id = _add_document(session, advisor, document_type)
    with pytest.raises(HTTPException) as exc:
        _sign_doc(session, advisor, doc_id)
    _assert_blocked(exc, CHANNEL_SIGNATURE)
    session.expire_all()
    doc = session.get(ContractDocument, doc_id)
    assert doc.signed_by_client == 0
    assert doc.signature_client_image is None
    assert doc.signed_at is None
    assert doc.status == "Entwurf"


def test_signing_unbound_document_not_gated_by_signoff(mismatch):
    session, advisor = mismatch
    doc_id = _add_document(session, advisor, "Beratungsvertrag")
    doc = _sign_doc(session, advisor, doc_id)
    assert doc.signed_by_client == 1


def test_signing_risk_profile_document_with_valid_signoff(seeded):
    session, advisor = seeded
    _sign_profile(session, advisor)
    doc_id = _add_document(session, advisor, "Risikoprofilierung")
    doc = _sign_doc(session, advisor, doc_id)
    assert doc.signed_by_client == 1


def test_signing_risk_profile_document_legacy_unsigned(seeded):
    session, advisor = seeded
    doc_id = _add_document(session, advisor, "Risikoprofilierung")
    doc = _sign_doc(session, advisor, doc_id)
    assert doc.signed_by_client == 1


# ── Handoff ───────────────────────────────────────────────────────────────


def _handoff(session, advisor, monkeypatch):
    session.execute(text(
        "UPDATE mandates SET mandate_type = 'Vermögensverwaltung' WHERE id = :m"
    ), {"m": _MID})
    session.commit()
    # SIGN-ELIGIBILITY-001: weiterleitbar ist nur ein finalisierter Run.
    run = SimpleNamespace(id="run-x", mandate_id=_MID, target_allocation_id=None, result_status="Final")
    monkeypatch.setattr(handoff_router, "_get_recommendation_run_or_404", lambda *a, **k: run)
    snapshots: list = []
    monkeypatch.setattr(
        handoff_router, "snapshot_handoff_trades",
        lambda *a, **k: snapshots.append(1) or ([{"isin": "X"}], 1),
    )
    with pytest.raises(HTTPException) as exc:
        handoff_router.create_portfolio_handoff(
            mandate_id=_MID, run_id="run-x",
            body=PortfolioHandoffCreate(recipient_name="AM"),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
    return exc, snapshots


def test_handoff_blocked_on_signoff_mismatch(mismatch, monkeypatch):
    session, advisor = mismatch
    exc, snapshots = _handoff(session, advisor, monkeypatch)
    _assert_blocked(exc, CHANNEL_HANDOFF)
    assert snapshots == []
    assert session.query(PortfolioHandoff).count() == 0


def test_handoff_with_valid_signoff_reaches_allocation_gate(seeded, monkeypatch):
    """Gegenprobe: das Signoff-Gate laesst durch; es greift erst das
    bestehende Allokations-Gate (der Fake-Run hat keine Allokation)."""
    session, advisor = seeded
    _sign_profile(session, advisor)
    exc, _snapshots = _handoff(session, advisor, monkeypatch)
    assert exc.value.detail["reason_code"] == "RELEASE_ALLOCATION_MISSING"


# ── Gate direkt ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("channel", [CHANNEL_CLIENT_PDF, CHANNEL_SIGNATURE, CHANNEL_HANDOFF])
def test_gate_passes_valid_and_legacy(seeded, channel):
    session, advisor = seeded
    assert_risk_signoff_release_eligible(session, _mandate(session), channel=channel)
    _sign_profile(session, advisor)
    assert_risk_signoff_release_eligible(session, _mandate(session), channel=channel)


def test_gate_without_assessment_is_noop(session_factory):  # noqa: F811
    with session_factory() as session:
        _seed(session)
        assert_risk_signoff_release_eligible(
            session, session.get(Mandate, _MID), channel=CHANNEL_CLIENT_PDF,
        )


def test_internal_advisory_report_not_blocked_by_signoff(mismatch):
    """Interner Advisory-Report zeigt den Zustand weiter an, ohne Sperre."""
    session, _advisor = mismatch
    assert_recommendation_release_eligible(
        session, _mandate(session), channel=CHANNEL_ADVISORY_PDF,
    )


# ── Kundenportal ──────────────────────────────────────────────────────────


def _portal(session, monkeypatch):
    from models.clients import Client
    from models.users import User
    from routers import client_portal

    client_user = User(
        id="usr-client", username="kunde", password_hash="hash", full_name="Max Muster",
        role="client", is_active=1, created_at=NOW, updated_at=NOW,
    )
    session.add(client_user)
    session.commit()
    client = session.get(Client, "cl-rcp")
    monkeypatch.setattr(client_portal, "get_linked_client_for_user_or_404", lambda *a, **k: client)
    computed: list = []
    monkeypatch.setattr(
        client_portal, "compute_advisory_report",
        lambda *a, **k: computed.append(k) or {"ok": True},
    )

    def call():
        return client_portal.client_portal_mandate_report(
            mandate_id=_MID, db=session, current_user=client_user,
        )

    return call, computed


def _portal_audit_rows(session):
    from models.review import AuditLog

    return session.query(AuditLog).filter(
        AuditLog.record_id == _MID, AuditLog.field_name == "client_portal_report_blocked",
    ).all()


def test_client_portal_report_blocked_with_neutral_message(mismatch, monkeypatch):
    session, _advisor = mismatch
    call, computed = _portal(session, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, str)
    assert "Ihr Bericht wird derzeit aktualisiert" in detail
    assert "Beraterin oder Ihren Berater" in detail
    for internal in (RISK_PROFILE_SIGNOFF_MISMATCH, "Signatur", "final_profile", "signoff"):
        assert internal not in detail
    assert computed == [], "kein Report-Aggregat bei gesperrtem Gate"
    session.expire_all()
    rows = _portal_audit_rows(session)
    assert len(rows) == 1
    assert rows[0].new_value == RISK_PROFILE_SIGNOFF_MISMATCH


def test_client_portal_report_with_valid_signoff(seeded, monkeypatch):
    session, advisor = seeded
    _sign_profile(session, advisor)
    call, computed = _portal(session, monkeypatch)
    assert call() == {"ok": True}
    assert computed == [{"client_facing": True}]
    assert _portal_audit_rows(session) == []


def test_client_portal_report_legacy_unsigned(seeded, monkeypatch):
    session, _advisor = seeded
    call, computed = _portal(session, monkeypatch)
    assert call() == {"ok": True}
    assert len(computed) == 1
