"""K-2b: strukturierte Service-Fehler byte-gleich vor/nach DomainError.

Bis K-2b werfen ``recommendation_release_gate``, ``cma_valuation_hold``,
``signature_artifact``, ``portfolio_data_release_gate`` und
``risk_profile_signoff._conflict`` ``fastapi.HTTPException`` mit
strukturiertem ``detail`` (``reason_code`` ...). Seit K-2b werfen sie
``core.reason_codes.DomainError``; der zentrale Handler erzeugt die Antwort.

Teil 1 (``main.app``, Middleware-Stack, ohne Lifespan, eigene SQLite-Datei):
jeder Gate-Pfad ueber einen echten Endpunkt -- Berater-Signatur
(``POST /mandates/{id}/documents/{doc}/sign``), Kundenportal-Bericht (faengt
den Gate-Fehler und antwortet neutral) und Vor-Ort-Signatur (faengt den
Archiv-Gate-Fehler und meldet ``DOCUMENT_NOT_SIGNABLE``). Fachzustaende, die
ohne komplette Allokations-Pipeline nicht entstehen (Risikobudget, KGV-Hold,
Signoff-Bindung, Depot-Policy), werden an den Datenquellen der Gates
gepatcht (``_current_allocation``, ``_load_cma``, ``resolve_signoff_binding``
...); die Gate-Funktion selbst, der Router, die Fehlerabbildung und die
Middleware laufen echt.

Teil 2 (Mini-App mit demselben Handler, Direktaufruf der Service-Funktion):
Pfade ohne leicht erreichbaren Endpunkt -- Handoff-Run ohne Allokation
(``RELEASE_ALLOCATION_MISSING``) und ``risk_profile_signoff._conflict`` mit
den Kontext-Formen seiner Aufrufer.

Je Pfad: Status, SHA-256 der rohen Body-Bytes, SHA-256 aller Header (ohne
``X-Process-Time-Ms``). ``tests/fixtures/service_domain_error_responses.json``
wurde auf dem Stand VOR der Umstellung erzeugt und bleibt unveraendert.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.middleware import install_exception_handlers  # noqa: E402
from models.review import ContractDocument  # noqa: E402
from onsite_signature_fakes import FakeClock, FakePhone, approved_test_policy  # noqa: E402
from services.onsite_signature.providers import NullQesProvider  # noqa: E402
from services.onsite_signature.runtime import OnsiteSignatureRuntime  # noqa: E402
from test_onsite_signature_http_error_parity import (  # noqa: E402
    MID,
    REQUEST_ID,
    _Harness,
    _logins,
    _open_body,
)
from test_onsite_signature_workflow import NOW, _doc, db  # noqa: E402,F401

GOLDEN = TESTS_ROOT / "fixtures" / "service_domain_error_responses.json"
_SIGN_BODY = {"signed_by_advisor": True, "signature_image": "data:image/png;base64,AAAA",
              "signer_name": "Berater Test"}


def _doc_without_pdf(db, doc_id: str, document_type: str = "Sonstiges"):
    doc = ContractDocument(
        id=doc_id, mandate_id=MID, document_type=document_type, title=document_type,
        status="Entwurf", signed_by_advisor=0, signed_by_client=0, version=1,
        created_by="adv-1", created_at=NOW, updated_at=NOW,
    )
    db.add(doc)
    db.commit()
    return doc


def _alloc(budget=5000, realized=4000, cma=None):
    return SimpleNamespace(
        id="ta-1", risk_budget_bps_at_generation=budget, risky_fraction_bps_at_generation=realized,
        capital_market_assumptions_id=cma,
    )


def _patch_allocation(monkeypatch, allocation):
    import services.recommendation_release_gate as gate

    monkeypatch.setattr(gate, "_current_allocation", lambda db, mandate: allocation)


def _patch_kgv_hold(monkeypatch):
    import services.cma_valuation_hold as hold

    monkeypatch.setattr(hold, "_load_cma", lambda db, cma_id: SimpleNamespace(id=cma_id))
    monkeypatch.setattr(hold, "adr12a_hold_finding",
                        lambda cma: ("CMA_ADR12A_HOLD", "KGV-Bewertungsanpassung ungeklaert."))
    monkeypatch.setattr(hold, "kgv_adjustment_representation", lambda cma: "embedded")


def _patch_signoff_mismatch(monkeypatch):
    import services.portfolio_engine as engine
    import services.risk_profile_signoff as signoff

    assessment = SimpleNamespace(id="ra-1", signoff_id="so-1")
    monkeypatch.setattr(engine, "_current_risk_assessment_or_none", lambda db, mid: assessment)
    monkeypatch.setattr(signoff, "signoff_state", lambda ra: signoff.STATUS_SIGNED)
    monkeypatch.setattr(signoff, "resolve_signoff_binding", lambda db, ra: SimpleNamespace(
        verified=False, row_verified=False, mismatches=("final_score_x10",)))


def _patch_portfolio_policy(monkeypatch):
    import services.portfolio_data_release_gate as pdg

    policy = SimpleNamespace(is_active=True, version="PD-TEST-1")
    monkeypatch.setattr(pdg, "load_policy_state", lambda: (policy, None))
    monkeypatch.setattr(pdg, "assess_mandate_portfolio_data", lambda db, mandate, policy_state=None: {
        "gates": {a: {"blocked": True, "reasons": ["depot_stale", "fx_missing"]} for a in pdg.GATE_ACTIONS},
        "freshness_error": None,
    })


def _capture_main_app(db, monkeypatch) -> dict[str, dict]:
    _logins(db)
    out: dict[str, dict] = {}
    h = _Harness(db, OnsiteSignatureRuntime(
        policy=approved_test_policy(), time_source=FakeClock(),
        qes_provider=NullQesProvider(), channel=FakePhone(),
    ))
    sign = f"/mandates/{MID}/documents/{{}}/sign"
    try:
        # signature_artifact
        _doc_without_pdf(db, "doc-nopdf")
        out["sign_artifact_missing"] = h.record(h.call("POST", sign.format("doc-nopdf"), _SIGN_BODY))
        bad = _doc(db, doc_id="doc-badhash")
        bad.checksum_sha256 = "0" * 64
        db.commit()
        out["sign_artifact_hash_mismatch"] = h.record(h.call("POST", sign.format("doc-badhash"), _SIGN_BODY))
        # Vor-Ort-Signatur faengt den Archiv-Gate-Fehler (DOCUMENT_NOT_SIGNABLE)
        _doc_without_pdf(db, "doc-onsite-nopdf")
        out["onsite_open_artifact_missing"] = h.record(h.call(
            "POST", f"/mandates/{MID}/documents/doc-onsite-nopdf/onsite-signature", _open_body("a" * 64)))

        # recommendation_release_gate + cma_valuation_hold (Empfehlungsdokument)
        _doc(db, "Anlagerezept", doc_id="doc-rec")
        with monkeypatch.context() as m:
            _patch_allocation(m, _alloc(budget=None))
            out["sign_risk_budget_evidence_missing"] = h.record(h.call("POST", sign.format("doc-rec"), _SIGN_BODY))
        with monkeypatch.context() as m:
            _patch_allocation(m, _alloc(budget=4000, realized=5123))
            out["sign_risk_budget_violated"] = h.record(h.call("POST", sign.format("doc-rec"), _SIGN_BODY))
        with monkeypatch.context() as m:
            _patch_allocation(m, _alloc(cma="cma-kgv"))
            _patch_kgv_hold(m)
            out["sign_cma_adr12a_hold"] = h.record(h.call("POST", sign.format("doc-rec"), _SIGN_BODY))
        # portfolio_data_release_gate
        with monkeypatch.context() as m:
            _patch_allocation(m, _alloc())
            _patch_portfolio_policy(m)
            out["sign_portfolio_data_not_releasable"] = h.record(h.call("POST", sign.format("doc-rec"), _SIGN_BODY))
        # Signoff-Bindung (signoff-gebundenes Dokument)
        _doc(db, "Anlagestrategie", doc_id="doc-strat")
        with monkeypatch.context() as m:
            _patch_signoff_mismatch(m)
            out["sign_risk_profile_signoff_mismatch"] = h.record(h.call("POST", sign.format("doc-strat"), _SIGN_BODY))

        # Kundenportal faengt Gate-Fehler -> neutrale 409 (Code nur in Log/Audit)
        portal = f"/client-portal/mandates/{MID}/report"
        h.as_user("cust-user-1")
        with monkeypatch.context() as m:
            _patch_signoff_mismatch(m)
            out["portal_report_signoff_mismatch"] = h.record(h.call("GET", portal))
        with monkeypatch.context() as m:
            _patch_allocation(m, _alloc(cma="cma-kgv"))
            _patch_kgv_hold(m)
            out["portal_report_cma_adr12a_hold"] = h.record(h.call("GET", portal))
        h.as_user("adv-1")
    finally:
        h.close()
    return out


def _mini_record(app: FastAPI, path: str) -> dict:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(path, headers={"X-Request-ID": REQUEST_ID})
    import hashlib

    try:
        detail = json.loads(resp.content).get("detail")
    except (ValueError, AttributeError):
        detail = None
    return {
        "status": resp.status_code,
        "reason_code": detail.get("reason_code") if isinstance(detail, dict) else None,
        "body_sha256": hashlib.sha256(resp.content).hexdigest(),
        "body_len": len(resp.content),
        "headers_sha256": hashlib.sha256(json.dumps(
            [[k.decode("latin-1").lower(), v.decode("latin-1")] for k, v in resp.headers.raw]
        ).encode()).hexdigest(),
    }


def _capture_direct(monkeypatch) -> dict[str, dict]:
    import services.recommendation_release_gate as gate
    from services import risk_profile_signoff as signoff

    app = FastAPI()
    install_exception_handlers(app)
    mandate = SimpleNamespace(id=MID)

    @app.get("/handoff-run-without-allocation")
    def handoff_run_without_allocation():
        gate.assert_recommendation_release_eligible(
            None, mandate, channel=gate.CHANNEL_HANDOFF, run=SimpleNamespace(target_allocation_id=None))

    @app.get("/signoff-conflict-plain")
    def signoff_conflict_plain():
        signoff._conflict("RISK_ASSESSMENT_VERSION_CONFLICT", "Version passt nicht.")

    @app.get("/signoff-conflict-context")
    def signoff_conflict_context():
        signoff._conflict(
            "RISK_PROFILE_SIGNOFF_CONFLICT", "Bereits signiert – Ä/ö/ü.",
            current_version=3, expected_version=2, signoff_id=None, mismatches=["a", "b"],
        )

    out = {name: _mini_record(app, f"/{name}") for name in (
        "handoff-run-without-allocation", "signoff-conflict-plain", "signoff-conflict-context")}
    return {f"direct_{k.replace('-', '_')}": v for k, v in out.items()}


def capture_responses(db, monkeypatch) -> dict[str, dict]:
    out = _capture_main_app(db, monkeypatch)
    out.update(_capture_direct(monkeypatch))
    return out


def test_service_error_responses_are_byte_identical(db, monkeypatch):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = capture_responses(db, monkeypatch)
    assert sorted(actual) == sorted(expected)
    diffs = {k: (expected[k], actual[k]) for k in expected if expected[k] != actual[k]}
    assert not diffs, json.dumps(diffs, indent=2)


def test_golden_covers_every_migrated_raise_site():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    codes = {v["reason_code"] for v in expected.values()}
    assert {
        "SIGNATURE_ARTIFACT_MISSING", "SIGNATURE_ARTIFACT_HASH_MISMATCH",   # signature_artifact._blocked
        "RISK_BUDGET_EVIDENCE_MISSING", "RISK_BUDGET_VIOLATED",            # release gate (Budget)
        "RELEASE_ALLOCATION_MISSING",                                      # release gate (Run)
        "RISK_PROFILE_SIGNOFF_MISMATCH",                                   # release gate (Signoff)
        "CMA_ADR12A_HOLD",                                                 # cma_valuation_hold
        "PORTFOLIO_DATA_NOT_RELEASABLE",                                   # portfolio_data_release_gate
        "RISK_ASSESSMENT_VERSION_CONFLICT", "RISK_PROFILE_SIGNOFF_CONFLICT",  # risk_profile_signoff._conflict
        "DOCUMENT_NOT_SIGNABLE",                                           # Fangstelle Vor-Ort-Signatur
    } <= codes
    # Fangstelle Kundenportal: neutrale Text-Antwort, kein Code im Body.
    assert expected["portal_report_signoff_mismatch"]["status"] == 409
    assert expected["portal_report_signoff_mismatch"]["reason_code"] is None
    assert expected["portal_report_cma_adr12a_hold"]["body_sha256"] == \
        expected["portal_report_signoff_mismatch"]["body_sha256"]


@pytest.mark.parametrize("name", ["sign_risk_budget_violated", "sign_artifact_missing"])
def test_golden_gate_entries_are_409(name):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert expected[name]["status"] == 409
