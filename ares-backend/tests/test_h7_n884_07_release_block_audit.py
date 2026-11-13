"""H7 N-884-04/07: Freigabe-Sperren werden im Audit-Log festgehalten.

Geprueft wird der echte ``AuditLog``-Eintrag (nicht der Quelltext) fuer
- Signatur eines Empfehlungsdokuments (``review.sign_document``),
- Weiterleitung an das Asset Management (``create_portfolio_handoff``),
- Vor-Ort-Signatur (``open`` und ``finalize``; bei ``finalize`` zusaetzlich
  das Abbruch-Ereignis mit dem Gate-Reason-Code in der Ereigniskette).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.reason_codes import DomainError  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.onsite_signature import OnsiteSignatureEvent  # noqa: E402
from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.review import AuditLog, ContractDocument, Product, RecommendationPosition, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from routers import onsite_signature as api  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from routers.review import sign_document  # noqa: E402
from schemas.portfolio_handoff import PortfolioHandoffCreate  # noqa: E402
from schemas.review import ContractDocumentSign  # noqa: E402
from test_risk_budget_release_gate_channels import (  # noqa: E402,F401
    _SIGNATURE,
    _FakeRequest,
    _add_document,
    _add_full_position,
    _allocation_policy_and_cma,
    _make_run,
    _setup,
    session_factory,
)

RETRO_UNAVAILABLE = "RETROCESSION_EVIDENCE_UNAVAILABLE"


def _final_run_without_retro_evidence(session_factory, suffix, *, vv=False):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, suffix, mode="ok")
    if vv:
        with session_factory() as db:
            db.query(Mandate).filter(Mandate.id == mid).update({"mandate_type": "Vermögensverwaltung"})
            db.commit()
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma, result_status="Final")
    _add_full_position(session_factory, run_id)
    with session_factory() as db:
        # Altlauf (vor H7 finalisiert): kein eingefrorener Nachweis, Retro unbekannt.
        db.get(RecommendationRun, run_id).cost_disclosure_snapshot_json = None
        position = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).one()
        db.get(Product, position.product_id).retrocession_bps = None
        db.commit()
    return advisor_id, mid, run_id


def _blocked_entries(session_factory, mid, field_name):
    with session_factory() as db:
        return [
            (row.field_name, row.new_value, row.record_id, row.user_id)
            for row in db.query(AuditLog).filter(AuditLog.mandate_id == mid, AuditLog.field_name == field_name)
        ]


def test_signature_block_writes_audit_entry(session_factory):
    advisor_id, mid, run_id = _final_run_without_retro_evidence(session_factory, "n7-sign")
    doc_id = _add_document(session_factory, mid, advisor_id, "Anlagestrategie")
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(DomainError) as exc:
            sign_document(
                mandate_id=mid, doc_id=doc_id,
                body=ContractDocumentSign(signed_by_advisor=True, signature_image=_SIGNATURE, signer_name="Berater"),
                request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == RETRO_UNAVAILABLE
    assert _blocked_entries(session_factory, mid, "signature_blocked") == [
        ("signature_blocked", RETRO_UNAVAILABLE, run_id, advisor_id),
    ]
    with session_factory() as db:
        assert db.get(ContractDocument, doc_id).signed_by_advisor == 0


def test_handoff_block_writes_audit_entry(session_factory, monkeypatch):
    advisor_id, mid, run_id = _final_run_without_retro_evidence(session_factory, "n7-ho", vv=True)
    import routers.portfolio_handoff as ho

    monkeypatch.setattr(ho, "snapshot_handoff", lambda *a, **k: pytest.fail("Snapshot trotz Sperre"))
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(DomainError) as exc:
            create_portfolio_handoff(
                mandate_id=mid, run_id=run_id, body=PortfolioHandoffCreate(recipient_name="AM"),
                request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc.value.detail["reason_code"] == RETRO_UNAVAILABLE
    assert _blocked_entries(session_factory, mid, "handoff_blocked") == [
        ("handoff_blocked", RETRO_UNAVAILABLE, run_id, advisor_id),
    ]
    with session_factory() as db:
        assert db.query(PortfolioHandoff).filter(PortfolioHandoff.mandate_id == mid).count() == 0


# ---------------------------------------------------------------------------
# Vor-Ort-Signatur
# ---------------------------------------------------------------------------

from test_onsite_signature_api import MID, _open, _runtime, _users  # noqa: E402
from test_onsite_signature_workflow import _doc, db  # noqa: E402,F401
from onsite_signature_fakes import TEST_CONSENT_TEXT, TEST_ID_METHOD, TEST_WITNESS_TEXT  # noqa: E402
from services.onsite_signature.policy import text_hash  # noqa: E402


def _gate_raising(code):
    def _gate(*_args, **_kwargs):
        raise DomainError(code, "Gesperrt (Test).", http_status=409)
    return _gate


def _onsite_entries(db):
    db.expire_all()
    return [
        (row.field_name, row.new_value)
        for row in db.query(AuditLog).filter(AuditLog.field_name == "onsite_signature_blocked")
    ]


@pytest.mark.parametrize("gate", [
    "assert_risk_signoff_release_eligible",
    "assert_recommendation_release_eligible",
    "assert_retrocession_release_eligible",
])
def test_onsite_open_block_of_every_gate_is_audited(db, monkeypatch, gate):
    advisor, _, _ = _users(db)
    doc = _doc(db, "Anlagestrategie")
    monkeypatch.setattr(api, gate, _gate_raising(f"TEST_{gate.upper()}"))
    with pytest.raises(DomainError):
        _open(db, advisor, _runtime(), doc)
    assert _onsite_entries(db) == [("onsite_signature_blocked", f"TEST_{gate.upper()}")]
    assert db.query(OnsiteSignatureEvent).count() == 0


def test_onsite_finalize_block_is_audited_and_closes_the_transaction(db, monkeypatch):
    advisor, customer, _ = _users(db)
    runtime = _runtime()
    doc = _doc(db)  # Testpolicy: "Sonstiges" ohne QES-Pflicht
    tx_id = _open(db, advisor, runtime, doc)["transaction_id"]
    api.onsite_identity_check(
        mandate_id=MID, transaction_id=tx_id,
        body=api.IdentityCheckRequest(method=TEST_ID_METHOD, result="verified", id_document_kind="passport",
                                      id_document_country="CH", id_document_valid=True),
        db=db, runtime=runtime, current_user=advisor,
    )
    challenge = api.onsite_issue_challenge(mandate_id=MID, transaction_id=tx_id, db=db,
                                           runtime=runtime, current_user=advisor)
    api.client_confirm_onsite_signature(
        transaction_id=tx_id,
        body=api.CustomerConfirmRequest(challenge_id=challenge["challenge_id"],
                                        code=runtime.channel.codes[challenge["challenge_id"]],
                                        displayed_document_hash=doc.checksum_sha256,
                                        consent_text_hash=text_hash(TEST_CONSENT_TEXT)),
        db=db, runtime=runtime, current_user=customer,
    )
    api.onsite_witness(
        mandate_id=MID, transaction_id=tx_id,
        body=api.WitnessRequest(statement_version="TEST-W1", statement_hash=text_hash(TEST_WITNESS_TEXT),
                                confirmed=True),
        db=db, runtime=runtime, current_user=advisor,
    )
    # Das Dokument verkoerpert jetzt die Empfehlung -> Retro-Gate greift.
    db.get(ContractDocument, doc.id).document_type = "Anlagestrategie"
    db.commit()
    monkeypatch.setattr(api, "assert_retrocession_release_eligible", _gate_raising(RETRO_UNAVAILABLE))
    with pytest.raises(DomainError) as exc:
        api.onsite_finalize(mandate_id=MID, transaction_id=tx_id, body=api.FinalizeRequest(),
                            db=db, runtime=runtime, current_user=advisor)
    assert exc.value.detail["reason_code"] == RETRO_UNAVAILABLE
    assert _onsite_entries(db) == [("onsite_signature_blocked", RETRO_UNAVAILABLE)]
    last = (
        db.query(OnsiteSignatureEvent).filter(OnsiteSignatureEvent.transaction_id == tx_id)
        .order_by(OnsiteSignatureEvent.sequence_no.desc()).first()
    )
    assert last.event_type == "ABORTED" or last.state == "ABORTED"
    assert last.reason_code == RETRO_UNAVAILABLE
