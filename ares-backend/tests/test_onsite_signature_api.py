"""SIGN-001 Endpunkte: produktiv ehrlich "nicht freigegeben", Kundenfaktor nur
ueber den Kunden-Login, dieselben Freigabe-Gates wie die bestehende Signatur.

Router-Funktionen werden direkt aufgerufen (kein App-Lifespan, keine DB
ausser der Test-SQLite-Datei).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.client_login import ClientLogin  # noqa: E402
from models.onsite_signature import OnsiteSignatureEvent, OnsiteSignatureEvidence  # noqa: E402
from models.users import User  # noqa: E402
from routers import onsite_signature as api  # noqa: E402
from services.auth import require_client  # noqa: E402
from services.onsite_signature import service as svc  # noqa: E402
from services.onsite_signature.policy import text_hash  # noqa: E402
from services.onsite_signature.runtime import OnsiteSignatureRuntime, get_onsite_signature_runtime  # noqa: E402
from onsite_signature_fakes import (  # noqa: E402
    TEST_CONSENT_TEXT,
    TEST_ID_METHOD,
    TEST_WITNESS_TEXT,
    FakeClock,
    FakePhone,
    approved_test_policy,
)
from test_onsite_signature_workflow import NOW, _doc, db  # noqa: E402,F401
from services.onsite_signature.providers import NullQesProvider  # noqa: E402

MID = "mandate-1"


def _users(db):
    advisor = db.get(User, "adv-1")
    customer = db.get(User, "cust-user-1")
    other = db.get(User, "cust-user-2")
    db.add_all([
        ClientLogin(id="cl-1", user_id="cust-user-1", client_id="client-1", created_by="adv-1",
                    created_at=NOW, is_active=1),
        ClientLogin(id="cl-2", user_id="cust-user-2", client_id="client-2", created_by="adv-1",
                    created_at=NOW, is_active=1),
    ])
    db.commit()
    return advisor, customer, other


def _runtime():
    return OnsiteSignatureRuntime(
        policy=approved_test_policy(), time_source=FakeClock(),
        qes_provider=NullQesProvider(), channel=FakePhone(),
    )


def _open(db, advisor, runtime, doc):
    return api.open_onsite_signature(
        mandate_id=MID, doc_id=doc.id,
        body=api.OpenRequest(displayed_document_hash=doc.checksum_sha256, language="de",
                             device_app_version="test-app/1.0"),
        db=db, runtime=runtime, current_user=advisor,
    )


def test_route_map_and_client_only_confirm():
    from main import app

    routes = {(r.path, tuple(sorted(r.methods or []))): r for r in app.routes if hasattr(r, "methods")}
    assert ("/onsite-signature/policy", ("GET",)) in routes
    assert ("/mandates/{mandate_id}/documents/{doc_id}/onsite-signature", ("POST",)) in routes
    confirm = routes[("/client-portal/onsite-signature/{transaction_id}/confirm", ("POST",))]
    dependencies = {d.call for d in confirm.dependant.dependencies}
    assert require_client in dependencies


def test_require_client_rejects_advisor_login(db):
    advisor, _, _ = _users(db)
    with pytest.raises(HTTPException) as exc:
        require_client(advisor)
    assert exc.value.status_code == 403


def test_policy_endpoint_reports_not_released_by_default(db):
    advisor, _, _ = _users(db)
    view = api.get_onsite_signature_policy(runtime=get_onsite_signature_runtime(), current_user=advisor)
    assert view["released"] is False
    assert view["status"] == "PROPOSED" and view["production_activation"] == "BLOCKED"
    assert "nicht freigegeben" in view["message"]
    assert view["qes_provider_configured"] is False
    assert view["customer_channel"] == "none"


def test_open_with_shipped_runtime_is_honestly_blocked(db):
    advisor, _, _ = _users(db)
    doc = _doc(db)
    with pytest.raises(HTTPException) as exc:
        _open(db, advisor, get_onsite_signature_runtime(), doc)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == svc.NOT_RELEASED
    assert exc.value.detail["details"]["release_problems"]
    assert db.query(OnsiteSignatureEvent).count() == 0


def test_open_runs_the_existing_release_gates(db, monkeypatch):
    advisor, _, _ = _users(db)
    doc = _doc(db, "Anlagestrategie")
    calls = []

    def _gate(*_args, **kwargs):
        calls.append(kwargs.get("channel"))
        raise HTTPException(status_code=409, detail={"reason_code": "GATE"})

    monkeypatch.setattr(api, "assert_risk_signoff_release_eligible", _gate)
    with pytest.raises(HTTPException) as exc:
        _open(db, advisor, _runtime(), doc)
    assert exc.value.detail == {"reason_code": "GATE"}
    assert calls == ["signature"]
    assert db.query(OnsiteSignatureEvent).count() == 0


def test_full_flow_over_the_endpoints(db):
    advisor, customer, _ = _users(db)
    runtime = _runtime()
    doc = _doc(db)
    view = _open(db, advisor, runtime, doc)
    tx_id = view["transaction_id"]
    assert view["state"] == "OPEN" and view["consent_text_hash"] == text_hash(TEST_CONSENT_TEXT)
    api.onsite_identity_check(
        mandate_id=MID, transaction_id=tx_id,
        body=api.IdentityCheckRequest(method=TEST_ID_METHOD, result="verified", id_document_kind="passport",
                                      id_document_country="CH", id_document_valid=True),
        db=db, runtime=runtime, current_user=advisor,
    )
    challenge = api.onsite_issue_challenge(mandate_id=MID, transaction_id=tx_id, db=db,
                                           runtime=runtime, current_user=advisor)
    code = runtime.channel.codes[challenge["challenge_id"]]
    assert "code" not in challenge
    confirmed = api.client_confirm_onsite_signature(
        transaction_id=tx_id,
        body=api.CustomerConfirmRequest(challenge_id=challenge["challenge_id"], code=code,
                                        displayed_document_hash=doc.checksum_sha256,
                                        consent_text_hash=text_hash(TEST_CONSENT_TEXT)),
        db=db, runtime=runtime, current_user=customer,
    )
    assert confirmed["state"] == "FACTOR_VERIFIED"
    api.onsite_witness(
        mandate_id=MID, transaction_id=tx_id,
        body=api.WitnessRequest(statement_version="TEST-W1", statement_hash=text_hash(TEST_WITNESS_TEXT),
                                confirmed=True),
        db=db, runtime=runtime, current_user=advisor,
    )
    signed = api.onsite_finalize(mandate_id=MID, transaction_id=tx_id, body=api.FinalizeRequest(),
                                 db=db, runtime=runtime, current_user=advisor)
    assert signed["state"] == "SIGNED" and signed["followup_allowed"] is False
    assert signed["evidence_hash"] == db.query(OnsiteSignatureEvidence).one().evidence_hash
    delivered = api.onsite_deliver_copy(mandate_id=MID, transaction_id=tx_id, db=db,
                                        runtime=runtime, current_user=advisor)
    assert delivered["state"] == "DELIVERED" and delivered["followup_allowed"] is True


def test_foreign_customer_sees_404_and_cannot_burn_the_code(db):
    advisor, customer, other = _users(db)
    runtime = _runtime()
    doc = _doc(db)
    tx_id = _open(db, advisor, runtime, doc)["transaction_id"]
    api.onsite_identity_check(
        mandate_id=MID, transaction_id=tx_id,
        body=api.IdentityCheckRequest(method=TEST_ID_METHOD, result="verified", id_document_kind="passport",
                                      id_document_country="CH", id_document_valid=True),
        db=db, runtime=runtime, current_user=advisor,
    )
    challenge = api.onsite_issue_challenge(mandate_id=MID, transaction_id=tx_id, db=db,
                                           runtime=runtime, current_user=advisor)
    body = api.CustomerConfirmRequest(
        challenge_id=challenge["challenge_id"], code=runtime.channel.codes[challenge["challenge_id"]],
        displayed_document_hash=doc.checksum_sha256, consent_text_hash=text_hash(TEST_CONSENT_TEXT),
    )
    with pytest.raises(HTTPException) as exc:
        api.client_confirm_onsite_signature(transaction_id=tx_id, body=body, db=db,
                                            runtime=runtime, current_user=other)
    assert exc.value.status_code == 404
    confirmed = api.client_confirm_onsite_signature(transaction_id=tx_id, body=body, db=db,
                                                    runtime=runtime, current_user=customer)
    assert confirmed["state"] == "FACTOR_VERIFIED"


def test_transaction_of_other_mandate_is_not_found(db):
    advisor, _, _ = _users(db)
    with pytest.raises(HTTPException) as exc:
        api.get_onsite_signature(mandate_id=MID, transaction_id="nope", db=db, current_user=advisor)
    assert exc.value.status_code == 404
