"""C-890-01 Nachtrag 5 (Delta-Pruefung 352852c8, N-897-10/-16/-17).

- N-897-17: Entwurfsfassungen (ohne KYC-Bestaetigung) werden nie archiviert
  und sind nie signierbar; der Markierungszustand ist Teil des Archiv-Hashes;
  nach der KYC-Bestaetigung entsteht eine finale Fassung ohne ENTWURF.
- N-897-16: Kompromittierung hoechstens 30 Tage rueckdatierbar, nie vor der
  Aktivierung; Benachrichtigung per Mail; deutlicher Satz im Nachweis.
- N-897-10: Maske/Antwort melden "per Mail" nur bei echtem Versand; lokale IP
  ist kein Indiz.
"""
from __future__ import annotations

import base64
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_c890_01_compliance_reviewer_role import (  # noqa: E402,F401
    NOW, PW, TENANT, _auth, client, session_factory,
)

from core.reason_codes import DomainError  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog, ContractDocument  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402

from client_onboarding_fixture import satisfy_client_onboarding  # noqa: E402


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


# ---------------------------------------------------------------------------
# N-897-17
# ---------------------------------------------------------------------------


def test_draft_is_never_archived_final_version_after_kyc_is_archived_and_signable(client, session_factory):
    from services.signature_artifact import assert_signable_artifact

    adv = _auth(client, "adv-1")
    draft = client.get("/mandates/m-1/reports/risikoprofil.pdf", headers=adv)
    assert draft.status_code == 200, draft.text[:300]
    assert "vor Vertragsabschluss" in _pdf_text(draft.content)
    with session_factory() as db:
        assert db.query(ContractDocument).filter(ContractDocument.mandate_id == "m-1").count() == 0
        satisfy_client_onboarding(db, db.get(Mandate, "m-1"), actor_id="adv-1")
        db.commit()
    final = client.get("/mandates/m-1/reports/risikoprofil.pdf", headers=adv)
    assert final.status_code == 200
    text_final = _pdf_text(final.content)
    assert "vor Vertragsabschluss" not in text_final and "ENTWURF" not in text_final
    with session_factory() as db:
        docs = db.query(ContractDocument).filter(ContractDocument.mandate_id == "m-1",
                                                 ContractDocument.document_type == "Risikoprofilierung").all()
        assert len(docs) == 1
        assert base64.b64decode(docs[0].pdf_base64) == final.content
        assert_signable_artifact(docs[0])  # finale Fassung: signierbar


def test_draft_artifact_cannot_be_signed():
    from services.signature_artifact import SIGNATURE_ARTIFACT_DRAFT, assert_signable_artifact

    pdf = b"%PDF-1.4 TEST-C890 Entwurf"
    import hashlib

    doc = ContractDocument(
        id="d", mandate_id="m-1", document_type="Anlagestrategie", title="x", status="Archiviert",
        content_json='{"watermark_mode": "vorvertrag"}', pdf_base64=base64.b64encode(pdf).decode(),
        checksum_sha256=hashlib.sha256(pdf).hexdigest(), content_hash="h", version=1,
        signed_by_advisor=0, signed_by_client=0, created_by="adv-1", created_at=NOW, updated_at=NOW)
    with pytest.raises(DomainError) as exc:
        assert_signable_artifact(doc)
    assert exc.value.reason_code == SIGNATURE_ARTIFACT_DRAFT and exc.value.http_status == 409


def test_archive_hash_includes_the_marking_and_draft_never_archives():
    from routers.pdf_reports import _archive_content_hash, _archive_final
    from services.pdf.base import PDFContext

    from datetime import date
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Data:
        value: int = 1

    ctx = PDFContext(mandate_name="M", advisor_name="A", report_date=date(2026, 11, 13))
    draft_ctx = PDFContext(mandate_name="M", advisor_name="A", report_date=date(2026, 11, 13),
                           watermark_mode="vorvertrag")
    assert _archive_content_hash(_Data(), ctx) != _archive_content_hash(_Data(), draft_ctx)

    class _NoDb:
        def __getattr__(self, name):  # jede DB-Nutzung waere ein Fehler
            raise AssertionError(f"Entwurf darf nicht archivieren ({name})")

    assert _archive_final(draft_ctx, _NoDb(), mandate_id="m-1") is None


class _ArchivedDoc:
    """Archivierte finale Fassung mit identischem Fachinhalt (Render-once-Kandidat)."""
    id, version, content_hash, pdf_base64 = "doc-1", 1, "hash-1", base64.b64encode(b"ARCHIVIERT").decode()
    bound_preference_decision_hash = bound_target_allocation_id = bound_preferences_sha256 = None
    checksum_sha256 = "sha-1"


class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def first(self):
        return self.result


def _cost_pdf(monkeypatch, *, watermark, archived, db_queries):
    """H11 (N-897-19): Verhaltenstest statt Quelltextvergleich -- die echte
    Route get_cost_disclosure_pdf, nur Gates/Daten/Renderer ersetzt."""
    from types import SimpleNamespace

    import services.cost_disclosure as cost_service
    from routers import pdf_reports

    rendered, archived_calls = [], []
    for gate in ("_assert_client_pdf_kyc_review", "_assert_client_pdf_signoff", "_assert_client_pdf_cma_hold",
                 "_assert_client_pdf_sustainability_floor"):
        monkeypatch.setattr(pdf_reports, gate, lambda *a, **k: None)
    mandate = SimpleNamespace(id="m-1", mandate_number="M-1")
    monkeypatch.setattr(pdf_reports, "get_mandate_for_user_or_404", lambda *a: mandate)
    monkeypatch.setattr(cost_service, "build_cost_disclosure", lambda *a: {"advisory_wealth_rappen": 100})
    monkeypatch.setattr(pdf_reports, "_build_pdf_context", lambda *a: SimpleNamespace(watermark_mode=watermark))
    monkeypatch.setattr(pdf_reports, "_attach_provisional_notice", lambda ctx, *a: ctx)
    monkeypatch.setattr(pdf_reports, "_archive_content_hash", lambda *a: "hash-1")
    monkeypatch.setattr(pdf_reports, "_document_binding", lambda *a: {})
    monkeypatch.setattr(pdf_reports, "current_preference_binding", lambda *a: None)
    monkeypatch.setattr(pdf_reports, "_extract_client_ip", lambda *a: "127.0.0.1")
    monkeypatch.setattr(pdf_reports, "ReportLabRenderer", lambda: SimpleNamespace(
        render_cost_disclosure=lambda ctx, data: rendered.append(ctx.watermark_mode) or b"FRISCH"))
    monkeypatch.setattr(pdf_reports, "archive_generated_pdf",
                        lambda db, **kw: archived_calls.append(kw["content_hash"]) or _ArchivedDoc())

    class _Db:
        def query(self, *_a):
            db_queries.append("query")
            return _Query(archived)

    response = pdf_reports.get_cost_disclosure_pdf("m-1", request=None, db=_Db(), current_user=None)
    return response, rendered, archived_calls


def test_cost_disclosure_draft_never_reuses_or_creates_an_archive(monkeypatch):
    """Entwurf (vor KYC-Bestaetigung): auch wenn eine finale Fassung mit
    identischem Inhalt archiviert ist, wird frisch mit Entwurfsmarkierung
    gerendert, nichts archiviert und das Archiv nicht einmal gelesen."""
    queries: list[str] = []
    response, rendered, archived = _cost_pdf(monkeypatch, watermark="vorvertrag", archived=_ArchivedDoc(),
                                             db_queries=queries)
    assert response.body == b"FRISCH" and rendered == ["vorvertrag"]
    assert archived == [] and queries == []
    assert response.headers["X-Ares-Draft"] == "vorvertrag"
    assert "X-Cost-Disclosure-Document-Id" not in response.headers


def test_cost_disclosure_final_renders_once_from_the_archive(monkeypatch):
    queries: list[str] = []
    response, rendered, archived = _cost_pdf(monkeypatch, watermark="none", archived=_ArchivedDoc(),
                                             db_queries=queries)
    assert response.body == b"ARCHIVIERT" and rendered == [] and archived == []
    assert response.headers["X-Cost-Disclosure-Document-Id"] == "doc-1"


def test_cost_disclosure_final_without_archive_renders_and_archives(monkeypatch):
    queries: list[str] = []
    response, rendered, archived = _cost_pdf(monkeypatch, watermark="none", archived=None, db_queries=queries)
    assert response.body == b"FRISCH" and rendered == ["none"] and archived == ["hash-1"]
    assert "X-Ares-Draft" not in response.headers


# ---------------------------------------------------------------------------
# N-897-16
# ---------------------------------------------------------------------------


def test_compromise_backdating_is_limited_and_notified(client, session_factory, monkeypatch):
    import routers.auth as auth_router

    sent: list[tuple] = []
    monkeypatch.setattr(auth_router, "send_compromise_notice_email", lambda *a: sent.append(a) or True)
    admin = _auth(client, "adm-1")
    too_old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    r = client.post("/users/rev-1/compromise", headers=admin,
                    json={"reason": "Verdacht auf Missbrauch (Test)", "compromised_since": too_old})
    assert r.status_code == 422 and r.json()["detail"]["reason_code"] == "COMPROMISE_BACKDATE_INVALID"
    with session_factory() as db:
        db.execute(text("UPDATE users SET activated_at = :a WHERE id = 'rev-1'"),
                   {"a": (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")})
        db.commit()
    before_activation = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    r = client.post("/users/rev-1/compromise", headers=admin,
                    json={"reason": "Verdacht auf Missbrauch (Test)", "compromised_since": before_activation})
    assert r.status_code == 422 and r.json()["detail"]["reason_code"] == "COMPROMISE_BACKDATE_INVALID"
    ok_since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post("/users/rev-1/compromise", headers=admin,
                    json={"reason": "Geraet verloren (Test)", "compromised_since": ok_since})
    assert r.status_code == 200, r.text
    assert len(sent) == 1 and sent[0][3] == "ADM-1"
    with session_factory() as db:
        audit = db.query(AuditLog).filter(AuditLog.action == "COMPROMISE").one()
        assert "rueckwirkend 1 Tage" in audit.new_value
        account = gate.kyc_approver_account(db, "rev-1")
    assert account["compromise_notice"].startswith("durch Admin ADM-1 am ")
    assert "als kompromittiert gemeldet, wirksam ab " in account["compromise_notice"]


# ---------------------------------------------------------------------------
# N-897-10
# ---------------------------------------------------------------------------


def test_failed_mail_shows_the_link_with_mail_failure_flag(client, monkeypatch):
    import routers.auth as auth_router

    monkeypatch.setattr(auth_router, "mail_configured", lambda: True)
    monkeypatch.setattr(auth_router, "send_invite_email", lambda *a, **k: False)
    r = client.post("/users/invite", headers=_auth(client, "adm-1"), json={
        "username": "ext-5", "full_name": "Externe 5", "email": "ext5@testfirma.ch",
        "role": "compliance_reviewer", "reviewer_organisation": "TEST-C890 AG", "reviewer_reference": "TEST-C890 M5"})
    body = r.json()
    assert body["invite_token"] and body["email_sent"] is False and body["link_delivery"] == "anzeige_mailfehler"


def test_local_ip_is_not_an_indicator(session_factory):
    from services.audit import log

    with session_factory() as db:
        db.execute(text("UPDATE users SET invited_at = :i, activated_at = :a WHERE id = 'rev-1'"),
                   {"i": "2026-11-12T09:00:00.000Z", "a": "2026-11-12T09:05:00.000Z"})
        log(db, user_id="adm-1", user_name="ADM-1", table_name="users", record_id="rev-1", action="INVITE",
            field_name="role", new_value="compliance_reviewer; ua=Browser A", ip_address="127.0.0.1")
        log(db, user_id="rev-1", user_name="REV-1", table_name="users", record_id="rev-1", action="INVITE_ACCEPT",
            field_name="user_agent", new_value="Browser B", ip_address="127.0.0.1")
        db.commit()
        account = gate.kyc_approver_account(db, "rev-1")
    assert account["same_ip_as_inviter"] is None and account["same_device_as_inviter"] is False
    assert "nicht aussagekraeftig (lokale Installation)" in account["origin_hint"]
    assert account["accepted_after_minutes"] == 5


def test_mask_reports_mail_only_when_really_sent():
    source = (Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "kyc-review-policy.js").read_text(
        encoding="utf-8")
    assert "E-Mail konnte nicht gesendet werden – Link bitte sicher übergeben" in source
    assert "inv.link_delivery === 'anzeige_mailfehler'" in source
