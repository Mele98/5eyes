"""Testdoubles fuer die Vor-Ort-Signatur (SIGN-001).

Nur fuer Tests -- kein echter QES-Anbieter, kein echter SMS-/Mail-Versand.
Die Policy hier ist eine TEST-Policy mit Platzhaltertexten; sie ist keine
Freigabe und keine fachliche Vorgabe.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from services.onsite_signature.policy import policy_from_mapping
from services.onsite_signature.providers import DeliveryResult, QesVerification, TimeReading

TEST_TIME_SOURCE = "test_trusted_clock"
TEST_ID_METHOD = "test_in_person_official_id"
TEST_CONSENT_TEXT = "TEST-Einwilligungstext (Platzhalter, keine Freigabe)"
TEST_WITNESS_TEXT = "TEST-Zeugenerklaerung (Platzhalter, keine Freigabe)"


def approved_test_policy(**overrides) -> object:
    data = {
        "policy_version": "TEST-SIGN-001",
        "status": "APPROVED",
        "production_activation": "ENABLED",
        "approval": {"approved_by": "test-owner", "approved_at": "2026-10-27", "approval_reference": "TEST"},
        "document_classes": {
            "Sonstiges": "EVIDENCE_SIGNATURE_SUFFICIENT",
            "Anlagestrategie": "POLICY_REQUIRES_QES",
            "Beratungsvertrag": "FORM_REQUIRED_QES_OR_WET_INK",
            "Kostenausweis": None,
        },
        "customer_factor": {"kind": "document_bound_one_time_code", "code_digits": 6, "challenge_ttl_seconds": 300},
        "consent_texts": {"de": {"version": "TEST-C1", "text": TEST_CONSENT_TEXT}},
        "witness_statement": {"version": "TEST-W1", "text": TEST_WITNESS_TEXT},
        "accepted_identity_check_methods": [TEST_ID_METHOD],
        "accepted_time_sources": [TEST_TIME_SOURCE],
        "qes": {"provider": None},
    }
    data.update(overrides)
    return policy_from_mapping(data)


class FakeClock:
    def __init__(self, start: datetime | None = None, *, reliable: bool = True,
                 source: str = TEST_TIME_SOURCE) -> None:
        self.instant = start or datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
        self.reliable = reliable
        self.source = source

    def advance(self, seconds: float) -> None:
        self.instant = self.instant + timedelta(seconds=seconds)

    def now(self) -> TimeReading:
        self.instant = self.instant + timedelta(milliseconds=1)
        return TimeReading(self.instant, self.source, "Europe/Zurich", self.reliable)


class FakePhone:
    """Kundeneigenes Telefon: empfaengt Code und Kopie; der Test spielt den Kunden."""

    name = "test_customer_phone"

    def __init__(self, *, deliver_codes: bool = True, deliver_copies: bool = True) -> None:
        self.deliver_codes = deliver_codes
        self.deliver_copies = deliver_copies
        self.codes: dict[str, str] = {}
        self.copies: list[dict] = []

    def send_challenge_code(self, *, client_id, transaction_id, challenge_id, code,
                            document_hash, expires_at) -> DeliveryResult:
        if not self.deliver_codes:
            return DeliveryResult(False, self.name, reason_code="TEST_UNREACHABLE")
        self.codes[challenge_id] = code
        return DeliveryResult(True, self.name, reference=f"sms-{challenge_id[:8]}")

    def send_signed_copy(self, *, client_id, transaction_id, document_id, document_hash,
                         evidence_hash) -> DeliveryResult:
        if not self.deliver_copies:
            return DeliveryResult(False, self.name, reason_code="TEST_UNDELIVERABLE")
        self.copies.append({"transaction_id": transaction_id, "evidence_hash": evidence_hash})
        return DeliveryResult(True, self.name, reference=f"copy-{transaction_id[:8]}")


_FAKE_QES_KEY = b"test-qes-key"


class FakeQesProvider:
    name = "test_qes"
    configured = True

    def __init__(self, key: bytes = _FAKE_QES_KEY) -> None:
        self.key = key

    @staticmethod
    def _material(receipt: dict) -> bytes:
        body = {k: v for k, v in receipt.items() if k != "signature"}
        return json.dumps(body, sort_keys=True).encode("utf-8")

    def issue_receipt(self, *, document_hash, customer_id, transaction_id) -> dict:
        receipt = {
            "document_hash": document_hash, "customer_id": customer_id,
            "transaction_id": transaction_id, "certificate_chain": "TEST-CHAIN",
            "qualified_timestamp": "2026-10-27T09:00:05.000Z",
        }
        receipt["signature"] = hmac.new(self.key, self._material(receipt), hashlib.sha256).hexdigest()
        return receipt

    def verify_receipt(self, receipt, *, document_hash, customer_id, transaction_id) -> QesVerification:
        if not receipt or "signature" not in receipt:
            return QesVerification(False, self.name, reason_code="QES_RECEIPT_MISSING")
        expected = hmac.new(_FAKE_QES_KEY, self._material(receipt), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(receipt["signature"])):
            return QesVerification(False, self.name, reason_code="QES_SIGNATURE_INVALID")
        if (receipt.get("document_hash") != document_hash or receipt.get("customer_id") != customer_id
                or receipt.get("transaction_id") != transaction_id):
            return QesVerification(False, self.name, reason_code="QES_BINDING_MISMATCH")
        return QesVerification(
            True, self.name,
            receipt_hash=hashlib.sha256(self._material(receipt) + receipt["signature"].encode()).hexdigest(),
            certificate_chain_hash=hashlib.sha256(receipt["certificate_chain"].encode()).hexdigest(),
            qualified_timestamp=receipt["qualified_timestamp"],
            validation_result="TEST_VALID",
        )
