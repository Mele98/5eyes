"""SIGN-001: Vor-Ort-Signatur mit kundeneigenem Faktor -- Zustandsmaschine,
Evidence-Paket und die Fail-closed-Faelle aus dem Entscheiddokument
(ARES_OPEN_DECISIONS_RECOMMENDATION_2026-10-27, Abschnitt 2 "Zukunftsziel und
Tests"): Dokumentaenderung nach Anzeige, falscher Kunde, abgelaufener Code,
Berater gibt Kundencode ein, Offline-Abbruch, Doppelklick, Wiederholung,
Zeitfehler, unzustellbare Kundenkopie, manipuliertes Receipt, ungueltige QES.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from services.postgres_rls import import_tenant_models  # noqa: E402

import_tenant_models()

from database import Base  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.onsite_signature import (  # noqa: E402
    OnsiteSignatureChallenge,
    OnsiteSignatureEvent,
    OnsiteSignatureEvidence,
)
from models.review import ContractDocument  # noqa: E402
from models.users import User  # noqa: E402
from services.onsite_signature import service as svc  # noqa: E402
from services.onsite_signature import state_machine as sm  # noqa: E402
from services.onsite_signature.policy import load_policy, text_hash  # noqa: E402
from services.onsite_signature.providers import (  # noqa: E402
    NullCustomerChannel,
    NullQesProvider,
    SystemTimeSource,
)
from signable_document_fixture import archived_pdf_fields  # noqa: E402
from onsite_signature_fakes import (  # noqa: E402
    TEST_CONSENT_TEXT,
    TEST_ID_METHOD,
    TEST_WITNESS_TEXT,
    FakeClock,
    FakePhone,
    FakeQesProvider,
    approved_test_policy,
)

NOW = "2026-10-27T08:00:00.000Z"
ADVISOR = svc.AdvisorActor(user_id="adv-1", role="advisor", totp_enabled=True)
OTHER_ADVISOR = svc.AdvisorActor(user_id="adv-2", role="advisor", totp_enabled=True)
CUSTOMER = svc.CustomerActor(user_id="cust-user-1", role="client", linked_client_id="client-1")
OTHER_CUSTOMER = svc.CustomerActor(user_id="cust-user-2", role="client", linked_client_id="client-2")
ADVISOR_AS_CUSTOMER = svc.CustomerActor(user_id="adv-1", role="advisor", linked_client_id=None)
CONSENT_HASH = text_hash(TEST_CONSENT_TEXT)


def _user(uid, role, totp=1):
    return User(id=uid, username=uid, password_hash="x", full_name=uid, role=role,
                is_active=1, totp_enabled=totp, created_at=NOW, updated_at=NOW)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'onsite.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    session = factory()
    session.add_all([_user("adv-1", "advisor"), _user("adv-2", "advisor"),
                     _user("cust-user-1", "client", 0), _user("cust-user-2", "client", 0)])
    for cid in ("client-1", "client-2"):
        session.add(Client(
            id=cid, client_number=f"C-{cid}", first_name="Test", last_name=cid,
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="adv-1", created_at=NOW, updated_at=NOW,
        ))
    session.add(Mandate(
        id="mandate-1", client_id="client-1", mandate_number="M-1", mandate_type="Anlageberatung",
        status="Aktiv", base_currency="CHF", advisory_language="DE", opened_at="2026-01-01",
        created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _doc(db, document_type="Sonstiges", doc_id="doc-1"):
    doc = ContractDocument(
        id=doc_id, mandate_id="mandate-1", document_type=document_type, title=document_type,
        status="Entwurf", signed_by_advisor=0, signed_by_client=0, version=1,
        created_by="adv-1", created_at=NOW, updated_at=NOW, **archived_pdf_fields(),
    )
    db.add(doc)
    db.commit()
    return doc


class Ctx:
    def __init__(self, db, policy=None, qes=None):
        self.db = db
        self.policy = policy or approved_test_policy()
        self.clock = FakeClock()
        self.phone = FakePhone()
        self.qes = qes or NullQesProvider()

    def kw(self):
        return {"policy": self.policy, "time_source": self.clock}

    def open(self, doc, displayed=None, advisor=ADVISOR):
        return svc.open_transaction(
            self.db, **self.kw(), qes_provider=self.qes, advisor=advisor,
            mandate=self.db.get(Mandate, "mandate-1"), document=doc,
            displayed_document_hash=displayed or doc.checksum_sha256, language="de",
            device_app_version="test-app/1.0",
        )

    def identify(self, tx, result="verified", valid=True):
        return svc.record_identity_check(
            self.db, **self.kw(), advisor=ADVISOR, transaction_id=tx.transaction_id,
            method=TEST_ID_METHOD, result=result, id_document_kind="passport",
            id_document_country="ch", id_document_valid=valid,
        )

    def challenge(self, tx):
        return svc.issue_customer_challenge(
            self.db, **self.kw(), channel=self.phone, advisor=ADVISOR,
            transaction_id=tx.transaction_id,
        )

    def verify(self, tx, challenge, actor=CUSTOMER, code=None, displayed=None, consent=CONSENT_HASH):
        return svc.verify_customer_factor(
            self.db, **self.kw(), actor=actor, transaction_id=tx.transaction_id,
            challenge_id=challenge["challenge_id"],
            code=self.phone.codes[challenge["challenge_id"]] if code is None else code,
            displayed_document_hash=displayed or tx.document_hash, consent_text_hash=consent,
        )

    def witness(self, tx):
        return svc.record_witness_statement(
            self.db, **self.kw(), advisor=ADVISOR, transaction_id=tx.transaction_id,
            statement_version="TEST-W1", statement_hash=text_hash(TEST_WITNESS_TEXT), confirmed=True,
        )

    def finalize(self, tx, receipt=None):
        return svc.finalize_signature(
            self.db, **self.kw(), qes_provider=self.qes, advisor=ADVISOR,
            transaction_id=tx.transaction_id, qes_receipt=receipt,
        )

    def deliver(self, tx, channel=None):
        return svc.deliver_customer_copy(
            self.db, **self.kw(), channel=channel or self.phone, advisor=ADVISOR,
            transaction_id=tx.transaction_id,
        )

    def up_to_witness(self, doc):
        tx = self.open(doc)
        self.identify(tx)
        challenge = self.challenge(tx)
        self.verify(tx, challenge)
        return self.witness(tx)


def _count(db, model):
    return db.query(model).count()


def _block(exc_info, reason):
    assert exc_info.value.reason_code == reason, exc_info.value.as_detail()


# ── Produktivaktivierung: standardmaessig AUS ───────────────────────────────


def test_shipped_policy_is_proposed_blocked_and_classifies_nothing():
    policy = load_policy()
    assert policy.status == "PROPOSED"
    assert policy.production_activation == "BLOCKED"
    assert not policy.released
    problems = policy.release_problems()
    assert "policy_status:PROPOSED" in problems
    assert "production_activation:BLOCKED" in problems
    view = policy.public_view()
    assert view["released"] is False
    assert view["document_classes"] and all(v is None for v in view["document_classes"].values())


def test_shipped_policy_blocks_every_step_without_writing(db):
    doc = _doc(db)
    ctx = Ctx(db, policy=load_policy())
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.open(doc)
    _block(exc, svc.NOT_RELEASED)
    assert exc.value.details["release_problems"]
    assert _count(db, OnsiteSignatureEvent) == 0


def test_unreadable_policy_file_is_blocked(tmp_path):
    missing = load_policy(tmp_path / "nope.json")
    assert not missing.released
    assert missing.release_problems() == ["policy_unreadable:FileNotFoundError"]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"status": "APPROVED", "document_classes": {"Sonstiges": "WHATEVER"}}))
    assert load_policy(broken).release_problems() == ["policy_unreadable:ValueError"]


def test_approved_status_without_documented_approval_stays_blocked(db):
    policy = approved_test_policy(approval={"approved_by": None, "approved_at": None, "approval_reference": None})
    assert "approval_missing:approved_by" in policy.release_problems()
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db, policy=policy).open(_doc(db))
    _block(exc, svc.NOT_RELEASED)


# ── Dokumentklassen ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("document_type", ["Kostenausweis", "Risikoprofilierung"])
def test_unclassified_document_type_blocks(db, document_type):
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db).open(_doc(db, document_type))
    _block(exc, svc.DOCUMENT_CLASS_UNCLASSIFIED)
    assert _count(db, OnsiteSignatureEvent) == 0


def test_form_required_class_without_qes_is_always_blocked(db):
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db).open(_doc(db, "Beratungsvertrag"))
    _block(exc, svc.FORM_REQUIRES_QES_OR_WET_INK)


def test_policy_requires_qes_without_provider_is_blocked(db):
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db).open(_doc(db, "Anlagestrategie"))
    _block(exc, svc.QES_REQUIRED_NOT_AVAILABLE)


def test_unarchived_document_is_not_signable(db):
    doc = _doc(db)
    doc.pdf_base64 = None
    db.commit()
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db).open(doc)
    _block(exc, svc.DOCUMENT_NOT_SIGNABLE)


# ── Gluecklicher Pfad + Evidence ────────────────────────────────────────────


def test_full_flow_writes_atomic_evidence_and_blocks_followup_until_delivered(db):
    doc = _doc(db)
    ctx = Ctx(db)
    tx = ctx.open(doc)
    assert tx.state == sm.OPEN
    assert ctx.identify(tx).state == sm.IDENTITY_VERIFIED
    challenge = ctx.challenge(tx)
    code = ctx.phone.codes[challenge["challenge_id"]]
    # Der Code erscheint nie in der Antwort an den Berater und nie in der DB.
    assert set(challenge) == {"transaction_id", "challenge_id", "expires_at", "channel", "binding_hash"}
    assert code not in json.dumps(challenge)
    row = db.get(OnsiteSignatureChallenge, challenge["challenge_id"])
    assert all(code != str(getattr(row, c.name)) for c in OnsiteSignatureChallenge.__table__.columns)
    assert ctx.verify(tx, challenge).state == sm.FACTOR_VERIFIED
    assert ctx.witness(tx).state == sm.WITNESSED
    evidence = ctx.finalize(tx)

    assert evidence.displayed_document_hash == evidence.final_document_hash == doc.checksum_sha256
    assert evidence.document_class == "EVIDENCE_SIGNATURE_SUFFICIENT"
    assert evidence.client_id == "client-1" and evidence.mandate_id == "mandate-1"
    assert evidence.signer_role == "client"
    assert evidence.consent_text_hash == CONSENT_HASH
    assert evidence.customer_factor_actor_id == CUSTOMER.user_id
    assert evidence.customer_factor_challenge_id == challenge["challenge_id"]
    assert evidence.customer_factor_binding_hash == challenge["binding_hash"]
    assert evidence.advisor_id == ADVISOR.user_id
    assert evidence.advisor_auth_method == "password+totp"
    assert evidence.witness_statement_hash == text_hash(TEST_WITNESS_TEXT)
    assert evidence.time_source == "test_trusted_clock" and evidence.timezone == "Europe/Zurich"
    assert evidence.id_document_kind == "passport" and evidence.id_document_country == "CH"
    assert evidence.template_version is None  # Vorlagen sind heute nicht versioniert
    assert evidence.qes_provider is None
    assert evidence.evidence_hash == svc.compute_evidence_hash(evidence)
    signed = db.query(OnsiteSignatureEvent).filter_by(event_type=sm.EV_SIGNED).one()
    assert evidence.signed_event_hash == signed.event_hash
    # Keine Stift-Biometrie, keine Ausweiskopie, kein Unterschriftsbild.
    columns = {c.name for c in OnsiteSignatureEvidence.__table__.columns}
    assert not {name for name in columns if any(w in name for w in ("image", "pressure", "stroke", "copy"))}

    # Folgeprozess gesperrt bis DELIVERED.
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        svc.assert_followup_allowed(db, doc.id)
    _block(exc, svc.FOLLOWUP_BLOCKED_DELIVERY_PENDING)
    assert ctx.deliver(tx).state == sm.DELIVERED
    assert ctx.phone.copies == [{"transaction_id": tx.transaction_id, "evidence_hash": evidence.evidence_hash}]
    svc.assert_followup_allowed(db, doc.id)
    assert svc.verify_event_chain(db, tx.transaction_id) == []
    states = [e.state for e in db.query(OnsiteSignatureEvent).order_by(OnsiteSignatureEvent.sequence_no)]
    assert states == [sm.OPEN, sm.IDENTITY_VERIFIED, sm.CHALLENGE_ISSUED, sm.FACTOR_VERIFIED,
                      sm.WITNESSED, sm.SIGNED, sm.DELIVERY_PENDING, sm.DELIVERED]


def test_existing_contract_document_is_not_mutated(db):
    doc = _doc(db)
    ctx = Ctx(db)
    tx = ctx.up_to_witness(doc)
    ctx.finalize(tx)
    db.expire_all()
    stored = db.get(ContractDocument, doc.id)
    assert stored.signed_by_client == 0 and stored.status == "Entwurf"


# ── Fail-closed laut Entscheiddokument ──────────────────────────────────────


def test_document_change_after_display_aborts_without_evidence(db):
    doc = _doc(db)
    ctx = Ctx(db)
    tx = ctx.up_to_witness(doc)
    other = b"%PDF-1.4\n% changed after display\n%%EOF\n"
    doc.pdf_base64 = base64.b64encode(other).decode("ascii")
    doc.checksum_sha256 = hashlib.sha256(other).hexdigest()
    db.commit()
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.finalize(tx)
    _block(exc, svc.DOCUMENT_CHANGED_AFTER_DISPLAY)
    assert svc.load_transaction(db, tx.transaction_id).state == sm.ABORTED
    assert _count(db, OnsiteSignatureEvidence) == 0


def test_displayed_hash_differs_from_archived_document_blocks_open(db):
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db).open(_doc(db), displayed="0" * 64)
    _block(exc, svc.DOCUMENT_HASH_MISMATCH)


def test_customer_displayed_hash_mismatch_burns_challenge(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge, displayed="f" * 64)
    _block(exc, svc.DOCUMENT_HASH_MISMATCH)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.CHALLENGE_ALREADY_USED)


def test_wrong_customer_is_rejected_and_code_is_consumed(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge, actor=OTHER_CUSTOMER)
    _block(exc, svc.WRONG_CUSTOMER)
    assert exc.value.http_status == 403
    assert svc.load_transaction(db, tx.transaction_id).state == sm.IDENTITY_VERIFIED
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.CHALLENGE_ALREADY_USED)


def test_expired_code_is_rejected(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    ctx.clock.advance(301)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.CHALLENGE_EXPIRED)
    assert _count(db, OnsiteSignatureEvidence) == 0


def test_advisor_entering_customer_code_is_rejected_and_code_burned(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge, actor=ADVISOR_AS_CUSTOMER)
    _block(exc, svc.ADVISOR_CANNOT_ENTER_CUSTOMER_FACTOR)
    assert exc.value.http_status == 403
    rejected = db.query(OnsiteSignatureEvent).filter_by(event_type=sm.EV_FACTOR_REJECTED).one()
    assert rejected.actor_id == "adv-1" and rejected.reason_code == svc.ADVISOR_CANNOT_ENTER_CUSTOMER_FACTOR
    # Auch der echte Kunde kann den vom Berater "gesehenen" Code nicht mehr nutzen.
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.CHALLENGE_ALREADY_USED)


def test_wrong_code_is_single_attempt(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    real = ctx.phone.codes[challenge["challenge_id"]]
    wrong = "0" * len(real) if real != "0" * len(real) else "1" * len(real)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge, code=wrong)
    _block(exc, svc.CHALLENGE_CODE_INVALID)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.CHALLENGE_ALREADY_USED)


def test_consent_must_match_approved_text(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge, consent=text_hash("anderer Text"))
    _block(exc, svc.CONSENT_MISMATCH)


def test_superseded_challenge_is_rejected(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    first = ctx.challenge(tx)
    ctx.challenge(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, first)
    _block(exc, svc.CHALLENGE_SUPERSEDED)


def test_replay_of_a_used_code_is_rejected(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    ctx.verify(tx, challenge)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.CHALLENGE_ALREADY_USED)


def test_challenge_is_bound_to_document_transaction_customer(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    row = db.get(OnsiteSignatureChallenge, challenge["challenge_id"])
    expected = svc.challenge_binding_hash(
        document_hash=tx.document_hash, transaction_id=tx.transaction_id, customer_id="client-1",
        purpose=svc.CHALLENGE_PURPOSE, nonce=row.nonce, expires_at=row.expires_at,
        mandate_id="mandate-1", consent_text_hash=CONSENT_HASH, policy_version="TEST-SIGN-001",
    )
    assert row.binding_hash == expected == challenge["binding_hash"]
    other_customer = svc.challenge_binding_hash(
        document_hash=tx.document_hash, transaction_id=tx.transaction_id, customer_id="client-2",
        purpose=svc.CHALLENGE_PURPOSE, nonce=row.nonce, expires_at=row.expires_at,
        mandate_id="mandate-1", consent_text_hash=CONSENT_HASH, policy_version="TEST-SIGN-001",
    )
    assert other_customer != expected


def test_undeliverable_challenge_code_keeps_transaction_waiting(db):
    ctx = Ctx(db)
    ctx.phone = FakePhone(deliver_codes=False)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.challenge(tx)
    _block(exc, "TEST_UNREACHABLE")
    assert svc.load_transaction(db, tx.transaction_id).state == sm.IDENTITY_VERIFIED


def test_null_channel_never_delivers(db):
    ctx = Ctx(db)
    ctx.phone = NullCustomerChannel()
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.challenge(tx)
    _block(exc, "CUSTOMER_CHANNEL_NOT_CONFIGURED")


def test_double_click_on_finalize_signs_once(db):
    ctx = Ctx(db)
    tx = ctx.up_to_witness(_doc(db))
    ctx.finalize(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.finalize(tx)
    _block(exc, svc.INVALID_STATE)
    assert _count(db, OnsiteSignatureEvidence) == 1


def test_concurrent_transitions_from_the_same_state_only_one_wins(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    reading = ctx.clock.now()
    first = svc._new_event(tx, event_type=sm.EV_ABORTED, actor_id="adv-1", actor_role="advisor",
                           reading=reading, payload={}, reason_code="OFFLINE_ABORT")
    second = svc._new_event(tx, event_type=sm.EV_IDENTITY_VERIFIED, actor_id="adv-1",
                            actor_role="advisor", reading=reading, payload={})
    svc._commit(db, first)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        svc._commit(db, second)
    _block(exc, svc.CONCURRENT_TRANSITION)
    assert svc.load_transaction(db, tx.transaction_id).state == sm.ABORTED


def test_offline_abort_is_terminal(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    challenge = ctx.challenge(tx)
    aborted = svc.abort_transaction(db, **ctx.kw(), advisor=ADVISOR,
                                    transaction_id=tx.transaction_id, reason_code="OFFLINE_ABORT")
    assert aborted.state == sm.ABORTED
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.verify(tx, challenge)
    _block(exc, svc.INVALID_STATE)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.witness(tx)
    _block(exc, svc.INVALID_STATE)


def test_unreliable_time_source_blocks(db):
    ctx = Ctx(db)
    ctx.clock = FakeClock(reliable=False)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.open(_doc(db))
    _block(exc, svc.TIME_SOURCE_UNRELIABLE)


def test_system_clock_is_not_a_reliable_time_source(db):
    ctx = Ctx(db)
    ctx.clock = SystemTimeSource()
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.open(_doc(db))
    _block(exc, svc.TIME_SOURCE_UNRELIABLE)


def test_clock_going_backwards_blocks(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.clock.advance(-3600)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.identify(tx)
    _block(exc, svc.TIME_NOT_MONOTONIC)
    assert svc.load_transaction(db, tx.transaction_id).state == sm.OPEN


def test_undeliverable_customer_copy_keeps_followup_blocked_until_retry(db):
    doc = _doc(db)
    ctx = Ctx(db)
    tx = ctx.up_to_witness(doc)
    ctx.finalize(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.deliver(tx, channel=FakePhone(deliver_copies=False))
    _block(exc, "TEST_UNDELIVERABLE")
    assert svc.load_transaction(db, tx.transaction_id).state == sm.DELIVERY_PENDING
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        svc.assert_followup_allowed(db, doc.id)
    _block(exc, svc.FOLLOWUP_BLOCKED_DELIVERY_PENDING)
    # Signatur bleibt wirksam (Evidence unveraendert), Zustellung wird nachgeholt.
    assert _count(db, OnsiteSignatureEvidence) == 1
    assert ctx.deliver(tx).state == sm.DELIVERED
    svc.assert_followup_allowed(db, doc.id)


def test_delivery_without_proof_reference_is_not_delivered(db):
    class NoProof(FakePhone):
        def send_signed_copy(self, **kwargs):
            from services.onsite_signature.providers import DeliveryResult
            return DeliveryResult(True, self.name, reference=None)

    ctx = Ctx(db)
    tx = ctx.up_to_witness(_doc(db))
    ctx.finalize(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.deliver(tx, channel=NoProof())
    _block(exc, svc.DELIVERY_PROOF_MISSING)


def _qes_ctx(db):
    policy = approved_test_policy(qes={"provider": "test_qes"})
    return Ctx(db, policy=policy, qes=FakeQesProvider())


def test_qes_class_signs_only_with_valid_bound_receipt(db):
    ctx = _qes_ctx(db)
    tx = ctx.up_to_witness(_doc(db, "Anlagestrategie"))
    receipt = ctx.qes.issue_receipt(document_hash=tx.document_hash, customer_id="client-1",
                                    transaction_id=tx.transaction_id)
    evidence = ctx.finalize(tx, receipt)
    assert evidence.document_class == "POLICY_REQUIRES_QES"
    assert evidence.qes_provider == "test_qes" and evidence.qes_receipt_hash
    assert evidence.qes_certificate_chain_hash and evidence.qes_timestamp


def test_manipulated_qes_receipt_is_rejected(db):
    ctx = _qes_ctx(db)
    tx = ctx.up_to_witness(_doc(db, "Anlagestrategie"))
    receipt = ctx.qes.issue_receipt(document_hash=tx.document_hash, customer_id="client-1",
                                    transaction_id=tx.transaction_id)
    receipt["customer_id"] = "client-2"
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.finalize(tx, receipt)
    _block(exc, svc.QES_INVALID)
    assert exc.value.details["provider_reason"] == "QES_SIGNATURE_INVALID"
    assert _count(db, OnsiteSignatureEvidence) == 0


@pytest.mark.parametrize("variant", ["foreign_key", "other_document", "missing"])
def test_invalid_qes_is_rejected(db, variant):
    ctx = _qes_ctx(db)
    tx = ctx.up_to_witness(_doc(db, "Anlagestrategie"))
    if variant == "foreign_key":
        receipt = FakeQesProvider(key=b"untrusted").issue_receipt(
            document_hash=tx.document_hash, customer_id="client-1", transaction_id=tx.transaction_id)
    elif variant == "other_document":
        receipt = ctx.qes.issue_receipt(document_hash="a" * 64, customer_id="client-1",
                                        transaction_id=tx.transaction_id)
    else:
        receipt = None
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.finalize(tx, receipt)
    _block(exc, svc.QES_INVALID)
    assert svc.load_transaction(db, tx.transaction_id).state == sm.WITNESSED
    assert _count(db, OnsiteSignatureEvidence) == 0


# ── Rollen / Berater ────────────────────────────────────────────────────────


def test_advisor_without_strong_auth_cannot_open(db):
    weak = svc.AdvisorActor(user_id="adv-1", role="advisor", totp_enabled=False)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        Ctx(db).open(_doc(db), advisor=weak)
    _block(exc, svc.ADVISOR_STRONG_AUTH_REQUIRED)


def test_other_advisor_cannot_continue_transaction(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        svc.record_identity_check(
            db, **ctx.kw(), advisor=OTHER_ADVISOR, transaction_id=tx.transaction_id,
            method=TEST_ID_METHOD, result="verified", id_document_kind="passport",
            id_document_country="CH", id_document_valid=True,
        )
    _block(exc, svc.ADVISOR_NOT_OWNER)


def test_failed_identity_check_aborts(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.identify(tx, valid=False)
    _block(exc, svc.IDENTITY_CHECK_FAILED)
    assert svc.load_transaction(db, tx.transaction_id).state == sm.ABORTED


def test_witness_statement_must_match_approved_text(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    ctx.verify(tx, ctx.challenge(tx))
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        svc.record_witness_statement(
            db, **ctx.kw(), advisor=ADVISOR, transaction_id=tx.transaction_id,
            statement_version="TEST-W1", statement_hash=text_hash("frei formuliert"), confirmed=True,
        )
    _block(exc, svc.WITNESS_STATEMENT_MISMATCH)


def test_witness_requires_customer_factor_first(db):
    ctx = Ctx(db)
    tx = ctx.open(_doc(db))
    ctx.identify(tx)
    with pytest.raises(svc.OnsiteSignatureError) as exc:
        ctx.witness(tx)
    _block(exc, svc.INVALID_STATE)


def test_state_machine_has_no_shortcut_to_signed():
    for event_type, (allowed_from, _target) in sm.TRANSITIONS.items():
        if event_type == sm.EV_SIGNED:
            assert allowed_from == (sm.WITNESSED,)
    assert sm.next_state(sm.SIGNED, sm.EV_ABORTED) is None
    assert sm.next_state(sm.DELIVERY_PENDING, sm.EV_ABORTED) is None
    assert sm.next_state(sm.CHALLENGE_ISSUED, sm.EV_SIGNED) is None


def test_full_flow_binds_every_row_to_the_mandate_tenant(db):
    """PG-002 (Red-Team 2026-10-28, Befund 6): Ereignisse, Challenge und
    Evidence tragen den Mandanten des Mandats direkt (RLS-Plan)."""
    from models.tenant import Tenant

    db.add(Tenant(id="t-1", display_name="t-1", slug="t-1", created_at=NOW, updated_at=NOW))
    db.flush()
    db.get(Mandate, "mandate-1").tenant_id = "t-1"
    db.commit()
    doc = _doc(db)
    ctx = Ctx(db)
    tx = ctx.up_to_witness(doc)
    evidence = ctx.finalize(tx)
    ctx.deliver(tx)
    assert evidence.tenant_id == "t-1"
    for model in (OnsiteSignatureEvent, OnsiteSignatureChallenge, OnsiteSignatureEvidence):
        assert {row.tenant_id for row in db.query(model).all()} == {"t-1"}, model.__tablename__
    # Mandant ist nicht Teil der Hashes: Kette und Evidence-Hash bleiben gueltig.
    assert svc.verify_event_chain(db, tx.transaction_id) == []
    assert evidence.evidence_hash == svc.compute_evidence_hash(evidence)
