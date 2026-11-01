"""K-2: Fehlerantworten der Vor-Ort-Signatur byte-gleich vor/nach DomainError.

Bis K-2 hat ``routers/onsite_signature.py`` jede ``OnsiteSignatureError`` per
``try/except`` in ``HTTPException(status_code=exc.http_status,
detail=exc.as_detail())`` umgewandelt. Seit K-2 ist ``OnsiteSignatureError``
ein ``core.reason_codes.DomainError`` und der zentrale Handler
(``core/middleware.py``) erzeugt die Antwort.

Dieser Test faehrt jeden Fehlerpfad der Router ueber die ECHTE App
(``main.app``, Middleware-Stack inkl. Security-Header, ohne Lifespan, eigene
SQLite-Datei) und vergleicht pro Pfad Status, rohe Body-Bytes und alle
Antwort-Header (ohne ``X-Process-Time-Ms``) mit
``tests/fixtures/onsite_signature_error_responses.json``. Die Datei wurde auf
dem Stand VOR der Umstellung (Parent-Commit, alter Router mit try/except)
mit ``capture_responses`` erzeugt und ist seither unveraendert; der Test ist
damit der Vorher/Nachher-Nachweis. Kontrollen: ein Router-``HTTPException``-
Pfad (Dokument fehlt) und ein 422-Validierungsfehler laufen nicht ueber den
neuen Handler und muessen ebenfalls unveraendert bleiben.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient  # noqa: E402

from database import get_db  # noqa: E402
from models.client_login import ClientLogin  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.onsite_signature.policy import text_hash  # noqa: E402
from services.onsite_signature.providers import NullQesProvider  # noqa: E402
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

GOLDEN = TESTS_ROOT / "fixtures" / "onsite_signature_error_responses.json"
MID = "mandate-1"
REQUEST_ID = "k2-parity-request"
_VOLATILE_HEADERS = {"x-process-time-ms"}


class _Harness:
    """Echte App mit ueberschriebenen Abhaengigkeiten (DB, Login, Runtime)."""

    def __init__(self, db, runtime):
        from main import app

        self.app = app
        self.db = db
        self.runtime = runtime
        self.user: User = db.get(User, "adv-1")
        self.tx_ids: list[str] = []
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_onsite_signature_runtime] = lambda: self.runtime
        # Ohne ``with``: kein Lifespan (kein init_db, keine Scheduler).
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        for dep in (get_db, get_current_user, get_onsite_signature_runtime):
            self.app.dependency_overrides.pop(dep, None)

    def as_user(self, uid: str) -> "_Harness":
        self.user = self.db.get(User, uid)
        return self

    def call(self, method: str, path: str, json_body=None):
        return self.client.request(method, path, json=json_body, headers={"X-Request-ID": REQUEST_ID})

    def record(self, response) -> dict:
        body = response.content
        for i, tx in enumerate(self.tx_ids):  # Vorgangs-IDs sind UUIDs
            body = body.replace(tx.encode(), f"<TX{i}>".encode())
        headers = [
            [k.decode("latin-1").lower(), v.decode("latin-1")]
            for k, v in response.headers.raw
            if k.decode("latin-1").lower() not in _VOLATILE_HEADERS
        ]
        try:
            detail = json.loads(response.content).get("detail")
        except (ValueError, AttributeError):
            detail = None
        return {
            "status": response.status_code,
            "reason_code": detail.get("reason_code") if isinstance(detail, dict) else None,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_len": len(response.content),
            "headers_sha256": hashlib.sha256(json.dumps(headers).encode()).hexdigest(),
        }


def _approved_runtime() -> OnsiteSignatureRuntime:
    return OnsiteSignatureRuntime(
        policy=approved_test_policy(), time_source=FakeClock(),
        qes_provider=NullQesProvider(), channel=FakePhone(),
    )


def _logins(db) -> None:
    db.add_all([
        ClientLogin(id="cl-1", user_id="cust-user-1", client_id="client-1", created_by="adv-1",
                    created_at=NOW, is_active=1),
        ClientLogin(id="cl-2", user_id="cust-user-2", client_id="client-2", created_by="adv-1",
                    created_at=NOW, is_active=1),
    ])
    db.commit()


def _open_body(doc_hash: str, **over) -> dict:
    body = {"displayed_document_hash": doc_hash, "language": "de", "device_app_version": "test-app/1.0"}
    body.update(over)
    return body


def _identity(result="verified") -> dict:
    return {"method": TEST_ID_METHOD, "result": result, "id_document_kind": "passport",
            "id_document_country": "CH", "id_document_valid": True}


def _witness(confirmed=True, statement_hash=None) -> dict:
    return {"statement_version": "TEST-W1", "statement_hash": statement_hash or text_hash(TEST_WITNESS_TEXT),
            "confirmed": confirmed}


def capture_responses(db) -> dict[str, dict]:
    """Faehrt alle Fehlerpfade und liefert je Pfad den Antwort-Fingerabdruck."""
    _logins(db)
    out: dict[str, dict] = {}
    doc = _doc(db)
    doc2 = _doc(db, doc_id="doc-2")
    base = f"/mandates/{MID}/onsite-signature"

    # 1) Ausgelieferte Runtime: ehrlich "nicht freigegeben" (409 + details).
    shipped = get_onsite_signature_runtime()
    h = _Harness(db, shipped)
    try:
        out["open_not_released"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/{doc.id}/onsite-signature", _open_body(doc.checksum_sha256)))
        h.runtime = _approved_runtime()
        # Kontrolle: Router-HTTPException (kein DomainError).
        out["control_open_document_missing"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/nope/onsite-signature", _open_body(doc.checksum_sha256)))
        # Kontrolle: 422 Pydantic.
        out["control_open_validation_422"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/{doc.id}/onsite-signature", _open_body("zz")))
        out["open_hash_mismatch"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/{doc.id}/onsite-signature", _open_body("a" * 64)))
        out["open_input_missing"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/{doc.id}/onsite-signature",
            _open_body(doc.checksum_sha256, device_app_version=" ")))
        out["open_language_not_supported"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/{doc.id}/onsite-signature",
            _open_body(doc.checksum_sha256, language="xx")))
        out["get_not_found"] = h.record(h.call("GET", f"{base}/nope"))
        out["identity_not_found"] = h.record(h.call("POST", f"{base}/nope/identity-check", _identity()))
        out["challenge_not_found"] = h.record(h.call("POST", f"{base}/nope/challenge"))
        out["witness_not_found"] = h.record(h.call("POST", f"{base}/nope/witness", _witness()))
        out["finalize_not_found"] = h.record(h.call("POST", f"{base}/nope/finalize", {}))
        out["deliver_not_found"] = h.record(h.call("POST", f"{base}/nope/deliver"))
        out["abort_not_found"] = h.record(h.call("POST", f"{base}/nope/abort", {"reason_code": "OFFLINE_ABORT"}))

        opened = h.call("POST", f"/mandates/{MID}/documents/{doc.id}/onsite-signature",
                        _open_body(doc.checksum_sha256))
        assert opened.status_code == 201, opened.text
        tx = opened.json()["transaction_id"]
        h.tx_ids.append(tx)
        # Kontrolle: unbekanntes Mandat -> HTTPException aus services.auth.
        out["control_get_unknown_mandate"] = h.record(h.call("GET", f"/mandates/mandate-x/onsite-signature/{tx}"))
        out["challenge_invalid_state"] = h.record(h.call("POST", f"{base}/{tx}/challenge"))
        out["witness_invalid_state"] = h.record(h.call("POST", f"{base}/{tx}/witness", _witness()))
        out["finalize_invalid_state"] = h.record(h.call("POST", f"{base}/{tx}/finalize", {}))
        out["deliver_invalid_state"] = h.record(h.call("POST", f"{base}/{tx}/deliver"))
        out["identity_method_not_accepted"] = h.record(h.call(
            "POST", f"{base}/{tx}/identity-check", {**_identity(), "method": "unknown-method"}))
        assert h.call("POST", f"{base}/{tx}/identity-check", _identity()).status_code == 200
        challenge = h.call("POST", f"{base}/{tx}/challenge")
        assert challenge.status_code == 200, challenge.text
        challenge_id = challenge.json()["challenge_id"]
        h.tx_ids.append(challenge_id)
        code = h.runtime.channel.codes[challenge_id]
        confirm = {"challenge_id": challenge_id, "code": code,
                   "displayed_document_hash": doc.checksum_sha256,
                   "consent_text_hash": text_hash(TEST_CONSENT_TEXT)}
        portal = f"/client-portal/onsite-signature/{tx}/confirm"
        out["control_confirm_advisor_forbidden"] = h.record(h.call("POST", portal, confirm))
        h.as_user("cust-user-2")
        out["confirm_foreign_customer_not_found"] = h.record(h.call("POST", portal, confirm))
        h.as_user("cust-user-1")
        out["confirm_unknown_tx_not_found"] = h.record(h.call(
            "POST", "/client-portal/onsite-signature/nope/confirm", confirm))
        out["confirm_unknown_challenge"] = h.record(h.call("POST", portal, {**confirm, "challenge_id": "nope"}))
        out["confirm_consent_mismatch"] = h.record(h.call(
            "POST", portal, {**confirm, "consent_text_hash": "b" * 64}))
        out["confirm_wrong_code"] = h.record(h.call("POST", portal, {**confirm, "code": "000000x"}))
        h.as_user("adv-1")
        out["witness_before_factor_invalid_state"] = h.record(h.call("POST", f"{base}/{tx}/witness", _witness()))

        # Abbruch und Folgeaktion auf abgebrochenem Vorgang.
        opened2 = h.call("POST", f"/mandates/{MID}/documents/{doc2.id}/onsite-signature",
                         _open_body(doc2.checksum_sha256))
        assert opened2.status_code == 201, opened2.text
        tx2 = opened2.json()["transaction_id"]
        h.tx_ids.append(tx2)
        assert h.call("POST", f"{base}/{tx2}/abort", {"reason_code": "CUSTOMER_DECLINED"}).status_code == 200
        out["abort_twice_invalid_state"] = h.record(h.call(
            "POST", f"{base}/{tx2}/abort", {"reason_code": "OFFLINE_ABORT"}))
        out["identity_after_abort_invalid_state"] = h.record(h.call(
            "POST", f"{base}/{tx2}/identity-check", _identity()))
    finally:
        h.close()
    return out


def test_onsite_signature_error_responses_are_byte_identical(db):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = capture_responses(db)
    assert sorted(actual) == sorted(expected)
    diffs = {k: (expected[k], actual[k]) for k in expected if expected[k] != actual[k]}
    assert not diffs, json.dumps(diffs, indent=2)


def test_golden_covers_every_router_endpoint_and_controls():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    domain = {k: v for k, v in expected.items() if not k.startswith("control_")}
    # Jeder fachliche Pfad liefert ein strukturiertes Detail mit Reason-Code.
    assert all(v["reason_code"] for v in domain.values())
    for prefix in ("open_", "get_", "identity_", "challenge_", "witness_", "finalize_",
                   "deliver_", "abort_", "confirm_"):
        assert any(k.startswith(prefix) for k in domain), prefix
    assert expected["control_open_validation_422"]["status"] == 422
    assert expected["control_open_document_missing"]["status"] == 404


@pytest.mark.parametrize("name", ["open_not_released", "get_not_found", "challenge_invalid_state"])
def test_golden_entries_are_structured_onsite_details(name):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert expected[name]["status"] in {404, 409}
    assert expected[name]["reason_code"].startswith(("ONSITE_SIGNATURE_",))
