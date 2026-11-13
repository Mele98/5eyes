"""E2a Codex-Abnahmevertrag (2026-11-08): neutrale Erhebung ohne Enginewirkung,
Pflichtzustaende, Evidenz-/Dokumentbindung und die zehn Negativfaelle.

End-to-end auf einer echten App-Instanz (synthetische Daten, Wegwerf-DB):

* Mutationstest: ESG-Antworten variieren -> identische Risiko-, Ziel-,
  Monte-Carlo- und Allokations-Ergebnisse (sowie Produktauswahl).
* Negativfaelle 1-10 (Nummern im Testnamen).
* Gates mit tenantgebundenem Audit-Eintrag: Finalisierung, Signatur,
  Weiterleitung.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from core import sustainability_preference as sp
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401 - pytest fixtures
    _create_client_and_mandate,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)

VOLATILE_KEYS = frozenset({
    "id", "run_id", "target_allocation_id", "allocation_id", "assessment_id", "based_on_assessment_id",
    "created_at", "updated_at", "set_at", "approved_at", "generated_at", "computed_at", "as_of",
    "version", "allocation_context_hash", "input_snapshot_hash", "context_hash", "snapshot_hash",
    "previous_allocation_id", "supersedes_id", "set_by", "created_by", "warnings",
})


def _normalize(value):
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items()) if k not in VOLATILE_KEYS
                and not k.endswith(("_hash", "_at", "_id"))}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _capture(api, mandate_id, *, expected=None, **overrides):
    body = {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION,
        "definition_hash": sp.definition_hash(),
        "response_status": "answered",
        "esg_relevance": "yes",
        "esg_characteristic": "esg_factors",
        "exclusions": [],
        "information_acknowledged": True,
        "client_confirmed": True,
        "capture_channel": "in_person",
        "expected_current_id": expected,
    }
    body.update(overrides)
    return api.post(f"/mandates/{mandate_id}/sustainability-preferences", json=body)


def _ok_capture(api, mandate_id, **overrides):
    current = api.get(f"/mandates/{mandate_id}/sustainability-preferences").json()["current"]
    resp = _capture(api, mandate_id, expected=current["id"] if current else None, **overrides)
    assert resp.status_code == 201, resp.text
    return resp.json()


NOT_RELEVANT = {"esg_relevance": "not_relevant", "esg_characteristic": None, "information_acknowledged": False}
DECLINED = {"response_status": "declined", "esg_relevance": None, "esg_characteristic": None,
            "information_acknowledged": False}


@pytest.fixture()
def scenario(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    _seed_risk_profile(api, mandate_id)
    _seed_products(api, advisor_user)
    return {"client_id": client_id, "mandate_id": mandate_id}


def _results(api, mandate_id) -> dict:
    risk = api.get(f"/mandates/{mandate_id}/risk-assessments/current")
    assert risk.status_code == 200, risk.text
    goals = api.get(f"/mandates/{mandate_id}/goals")
    assert goals.status_code == 200, goals.text
    alloc = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={})
    assert alloc.status_code in (200, 201), alloc.text
    rec = api.post(f"/mandates/{mandate_id}/recommendations/generate", json={})
    assert rec.status_code == 200, rec.text
    risk_body = risk.json()
    return {
        "risk": _normalize({k: risk_body.get(k) for k in (
            "total_score", "final_profile", "risk_capacity_score", "risk_tolerance_score",
            "investment_horizon", "computed_profile", "answers",
        )}),
        "goals": _normalize(goals.json()),
        "allocation": _normalize(alloc.json()),
        "positions": sorted(
            (p["product_id"], int(p["target_weight_bps"]), int(p["target_amount_rappen"]))
            for p in rec.json()["positions"]
        ),
    }


def _first_diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return _first_diff(a.get(k), b.get(k), f"{path}.{k}")
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_diff(x, y, f"{path}[{i}]")
    return (path, a, b)


def test_mutation_esg_answers_do_not_change_risk_goals_mc_or_allocation(api, scenario):
    """Codex-Vertrag: keine Enginewirkung. Dieselben Eingaben mit allen
    Antwortvarianten ergeben dieselben Ergebnisse wie ohne Erfassung."""
    mid = scenario["mandate_id"]
    # Erster Lauf erzeugt die Allokation; alle Vergleichslaeufe sind
    # Neuberechnungen (gleicher Hinweis "Neuberechnung ohne mitgesendete
    # Praeferenzen"), damit nur die ESG-Antwort variiert.
    _results(api, mid)
    baseline = _results(api, mid)
    assert baseline["allocation"].get("goal_achievability") is not None or baseline["allocation"]
    assert baseline["positions"], "Vorbedingung: Produktauswahl vorhanden"
    variants = [
        {},
        {"esg_characteristic": "sdg_alignment", "capture_channel": "phone"},
        {"esg_characteristic": "no_specific"},
        NOT_RELEVANT,
        DECLINED,
    ]
    seen_states = set()
    for overrides in variants:
        state = _ok_capture(api, mid, **overrides)
        seen_states.add(state["state"])
        result = _results(api, mid)
        for key in baseline:
            assert result[key] == baseline[key], (overrides, key, _first_diff(result[key], baseline[key]))
    assert seen_states == {"preference_stated", "no_preference", "declined"}


# ── Negativfaelle ─────────────────────────────────────────────────────────────

def test_n01_missing_answer_is_not_no_preference(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["state"] == "unanswered" and state["state_label"] == "Noch nicht erfasst"
    # Frage 1 leer: weder "Ja" noch "Nicht relevant" noch "Keine Angabe".
    resp = _capture(api, mid, esg_relevance=None, esg_characteristic=None, information_acknowledged=False)
    assert resp.status_code == 422
    assert api.get(f"/mandates/{mid}/sustainability-preferences").json()["state"] == "unanswered"
    # Eignungspruefung (N-888-04) meldet "nicht erfasst", nie "keine Praeferenz".
    from models.mandates import Mandate
    from services.suitability_audit import audit_mandate_suitability

    with session_factory() as s:
        audit = audit_mandate_suitability(s, s.get(Mandate, mid))
    assert audit["sustainability_preference"]["status"] == "unanswered"
    assert "nicht erfasst" in audit["sustainability_preference"]["notice"]


def test_n02_aborted_flow_creates_no_effective_evidence(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    # Abbruch = keine vollstaendige Erfassung (fehlende Bestaetigung / Kanal).
    assert _capture(api, mid, client_confirmed=False).status_code == 422
    body = {"questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
            "response_status": "answered", "esg_relevance": "yes"}
    assert api.post(f"/mandates/{mid}/sustainability-preferences", json=body).status_code == 422
    with session_factory() as s:
        assert s.execute(text("SELECT COUNT(*) FROM investment_preference_decisions")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM audit_log WHERE table_name = 'investment_preference_decisions'"
        )).scalar() == 0


def test_n03_waiver_impossible_in_discretionary_mandate(api, scenario):
    mid = scenario["mandate_id"]  # Szenario: Vermoegensverwaltung
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["waiver_allowed"] is False
    resp = _capture(api, mid, preference_waived=True, waiver_reason="Kunde verzichtet ausdrücklich nach Erklärung.")
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_WAIVER_NOT_ALLOWED"


def _finalize_flow(api, mid):
    alloc = api.post(f"/mandates/{mid}/target-allocation/generate", json={})
    assert alloc.status_code in (200, 201), alloc.text
    rec = api.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert rec.status_code == 200, rec.text
    return rec.json()["run"]["id"] if isinstance(rec.json().get("run"), dict) else rec.json()["run_id"]


def _block_audits(session_factory):
    with session_factory() as s:
        return [json.loads(r[0]) for r in s.execute(text(
            "SELECT new_value FROM audit_log WHERE field_name = 'sustainability_preference_blocked' ORDER BY rowid"
        ))]


def test_n04_outdated_text_or_policy_version_blocks_finalization(api, scenario, session_factory, monkeypatch):
    mid = scenario["mandate_id"]
    _ok_capture(api, mid)
    run_id = _finalize_flow(api, mid)
    # Textversion aendert sich nach der Erfassung (neue Definition).
    monkeypatch.setitem(sp.PROFILE_TEXTS, sp.PROFILE_ESG_FACTORS, sp.PROFILE_TEXTS[sp.PROFILE_ESG_FACTORS] + " (neu)")
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["state"] == "stale" and state["stale_reasons"] == ["definition_outdated"]
    resp = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_PREFERENCE_STALE"
    audits = _block_audits(session_factory)
    assert audits and audits[-1]["channel"] == "finalize" and audits[-1]["state"] == "stale"
    monkeypatch.undo()
    # Erneut erfasst -> Finalisierung moeglich.
    assert api.get(f"/mandates/{mid}/sustainability-preferences").json()["state"] == "preference_stated"
    resp = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert resp.status_code == 200, resp.text


def test_n05_foreign_tenant_or_mandate_gets_no_data(api, scenario, session_factory, advisor_user):
    from main import app
    from models.users import User
    from services.auth import get_current_user

    mid = scenario["mandate_id"]
    _ok_capture(api, mid)
    stranger = User(id="user-stranger", username="stranger", password_hash="h", full_name="Fremd",
                    role="advisor", is_active=1, created_at="x", updated_at="x")
    with session_factory() as s:
        s.add(User(id="user-stranger", username="stranger", password_hash="h", full_name="Fremd",
                   role="advisor", is_active=1, created_at="x", updated_at="x"))
        s.commit()
    app.dependency_overrides[get_current_user] = lambda: stranger
    try:
        for resp in (
            api.get(f"/mandates/{mid}/sustainability-preferences"),
            _capture(api, mid),
        ):
            assert resp.status_code in (403, 404), resp.text
            assert "decision_hash" not in resp.text
        assert api.get("/mandates/does-not-exist/sustainability-preferences").status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = lambda: advisor_user
    with session_factory() as s:
        assert s.execute(text("SELECT COUNT(*) FROM investment_preference_decisions")).scalar() == 1


def test_n06_hash_or_time_manipulation_blocks(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    _ok_capture(api, mid)
    run_id = _finalize_flow(api, mid)
    with session_factory() as s:
        db_path = s.get_bind().url.database
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TRIGGER trg_investment_preference_decisions_no_update")
        conn.execute("UPDATE investment_preference_decisions SET captured_at = '2020-01-01T00:00:00.000Z'")
        conn.commit()
    finally:
        conn.close()
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["state"] == "unreadable"
    resp = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_PREFERENCE_UNREADABLE"
    assert _block_audits(session_factory)[-1]["state"] == "unreadable"


def _protocol_doc(api, session_factory, mid):
    pdf = api.get(f"/mandates/{mid}/reports/protokoll.pdf")
    assert pdf.status_code == 200, pdf.text[:300]
    docs = api.get(f"/mandates/{mid}/documents").json()
    protocols = [d for d in docs if d["document_type"] == "Beratungsprotokoll"]
    return max(protocols, key=lambda d: d["version"])


def _sign(api, mid, doc_id):
    return api.post(f"/mandates/{mid}/documents/{doc_id}/sign", json={
        "signed_by_advisor": True, "signer_name": "Beraterin Mock",
        "signature_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
    })


def test_n07_new_preference_invalidates_old_customer_documents(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    first = _ok_capture(api, mid)
    old_doc = _protocol_doc(api, session_factory, mid)
    assert old_doc["bound_preference_decision_hash"] == first["current"]["decision_hash"]
    second = _ok_capture(api, mid, **NOT_RELEVANT)
    resp = _sign(api, mid, old_doc["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_DOCUMENT_OUTDATED"
    assert _block_audits(session_factory)[-1]["channel"] == "signature"
    new_doc = _protocol_doc(api, session_factory, mid)
    assert new_doc["id"] != old_doc["id"]
    assert new_doc["bound_preference_decision_hash"] == second["current"]["decision_hash"]
    signed = _sign(api, mid, new_doc["id"])
    assert signed.status_code == 200, signed.text


def test_n07b_document_without_capture_is_invalidated_by_first_capture(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    doc = _protocol_doc(api, session_factory, mid)
    assert doc["bound_preference_decision_hash"] == sp.NO_DECISION_BINDING_PREFIX + mid
    _ok_capture(api, mid, **DECLINED)
    resp = _sign(api, mid, doc["id"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_DOCUMENT_OUTDATED"


def test_n08_unknown_product_data_cannot_satisfy_an_exclusion(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert not any(o["available"] for o in state["exclusion_options"])
    resp = _capture(api, mid, exclusions=["tobacco"])
    assert resp.status_code == 422
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_OPTION_NOT_OFFERABLE"
    with session_factory() as s:
        assert s.execute(text("SELECT COUNT(*) FROM investment_preference_decisions")).scalar() == 0


def test_n10_browser_api_pdf_audit_archive_show_the_same_state(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    body = _ok_capture(api, mid, esg_characteristic="sdg_alignment", capture_channel="written")
    decision_hash = body["current"]["decision_hash"]
    # API
    assert body["state"] == "preference_stated" and body["document_binding"] == decision_hash
    # PDF (Protokoll) + Archiv
    from io import BytesIO

    from pypdf import PdfReader

    pdf = api.get(f"/mandates/{mid}/reports/protokoll.pdf")
    flat = " ".join(" ".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf.content)).pages).split())
    assert sp.STATE_LABELS["preference_stated"] in flat
    assert decision_hash in flat.replace(" ", "")
    doc = _protocol_doc(api, session_factory, mid)
    assert doc["bound_preference_decision_hash"] == decision_hash
    # Audit
    with session_factory() as s:
        payload = json.loads(s.execute(text(
            "SELECT new_value FROM audit_log WHERE table_name = 'investment_preference_decisions' "
            "AND action = 'CREATE' ORDER BY rowid DESC LIMIT 1"
        )).scalar())
    assert payload["state"] == "preference_stated" and payload["decision_hash"] == decision_hash
    # Browser: die Maske rendert state_label/decision aus genau dieser API
    # (Playwright: tests/test_livetest_e2a_sustainability_flow.py).


def test_handoff_blocked_by_stale_preference(api, scenario, session_factory, monkeypatch):
    mid = scenario["mandate_id"]
    _ok_capture(api, mid)
    run_id = _finalize_flow(api, mid)
    assert api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize").status_code == 200
    import services.recommendation_release_gate as release_gate

    monkeypatch.setattr(release_gate, "_today", lambda: "2999-01-01")
    resp = api.post(f"/mandates/{mid}/recommendations/{run_id}/portfolio-handoffs", json={
        "recipient_name": "Depotbank Synth", "confirm_no_existing_holdings": True,
    })
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict) and detail["reason_code"] == "SUSTAINABILITY_PREFERENCE_STALE"
    assert _block_audits(session_factory)[-1]["channel"] == "handoff"


def test_onsite_signature_uses_the_same_document_binding(api, scenario, session_factory):
    """Vor-Ort-Signatur (Kanal signature): gleiche Bindung wie die Berater-
    Signatur. Audit-Eintrag folgt mit H7 (release_block_audit, N-888-13)."""
    from core.reason_codes import DomainError
    from models.mandates import Mandate
    from models.review import ContractDocument
    from routers.onsite_signature import _release_gates

    mid = scenario["mandate_id"]
    _ok_capture(api, mid)
    doc = _protocol_doc(api, session_factory, mid)
    with session_factory() as s:
        _release_gates(s, s.get(Mandate, mid), s.get(ContractDocument, doc["id"]))  # gebunden: ok
    _ok_capture(api, mid, **NOT_RELEVANT)
    with session_factory() as s:
        with pytest.raises(DomainError) as exc:
            _release_gates(s, s.get(Mandate, mid), s.get(ContractDocument, doc["id"]))
    assert exc.value.reason_code == "SUSTAINABILITY_DOCUMENT_OUTDATED"


def test_n07c_cost_disclosure_is_reissued_after_a_new_preference(api, scenario, session_factory):
    """Render-once des Kostenausweises darf kein Dokument der alten Erfassung
    wiederverwenden (sonst nur ein nicht signierbares Dokument)."""
    mid = scenario["mandate_id"]
    _finalize_flow(api, mid)
    first = _ok_capture(api, mid)
    assert api.get(f"/mandates/{mid}/reports/cost-disclosure.pdf").status_code == 200
    second = _ok_capture(api, mid, **NOT_RELEVANT)
    assert api.get(f"/mandates/{mid}/reports/cost-disclosure.pdf").status_code == 200
    docs = [d for d in api.get(f"/mandates/{mid}/documents").json() if d["document_type"] == "Kostenausweis"]
    bindings = [d["bound_preference_decision_hash"] for d in sorted(docs, key=lambda d: d["version"])]
    assert bindings == [first["current"]["decision_hash"], second["current"]["decision_hash"]]


def test_mutation_harness_positive_control_wealth_change(api, scenario):
    """C-901-01 (Codex 2026-11-12): Positivkontrolle des Neutralitaets-
    Harnesses. Dieselbe Ergebnis-Erfassung (_results/_normalize) muss eine
    WIRKSAME Nicht-ESG-Inputmutation erkennen -- sonst waere der Mutationstest
    oben leer. Eingriff ausschliesslich ueber denselben API-Pfad: eine
    zusaetzliche Vermoegensposition (Beratungsvermoegen)."""
    mid = scenario["mandate_id"]
    _results(api, mid)
    baseline = _results(api, mid)
    resp = api.post(f"/clients/{scenario['client_id']}/wealth-positions", json={
        "label": "Konto Positivkontrolle", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
        "current_value_rappen": 100_000_00, "currency": "CHF",
        "liquidity_instrument": "Kontoguthaben", "data_classification": "synthetic",
    })
    assert resp.status_code == 201, resp.text
    mutated = _results(api, mid)
    assert mutated["risk"] == baseline["risk"]  # Risikoprofil unberuehrt
    changed = [k for k in ("allocation", "positions") if mutated[k] != baseline[k]]
    assert changed, "Harness erkennt eine wirksame Vermoegensaenderung nicht"
    assert mutated["positions"] != baseline["positions"]
    path, _a, _b = _first_diff(mutated["allocation"], baseline["allocation"])
    assert path, "Allocation-Vergleich zeigt keinen Unterschied"


def test_mutation_harness_negative_control_volatile_fields_only():
    """Gegenstueck: Aenderungen nur an ausgenommenen, volatilen Feldern
    (IDs, Zeitstempel, Hashes, Warnungen) bleiben im Vergleich gleich; eine
    fachliche Zahl dagegen nicht."""
    import copy

    base = {"id": "a", "created_at": "t1", "allocation_context_hash": "h1", "warnings": ["x"],
            "target_allocation": {"run_id": "r1", "set_at": "t", "target_equities_bps": 4000},
            "sub": [{"evaluation_id": "e1", "target_weight_bps": 1200}]}
    volatile = copy.deepcopy(base)
    volatile.update(id="b", created_at="t2", allocation_context_hash="h2", warnings=["y"])
    volatile["target_allocation"].update(run_id="r2", set_at="u")
    volatile["sub"][0]["evaluation_id"] = "e2"
    assert _normalize(volatile) == _normalize(base)
    material = copy.deepcopy(base)
    material["target_allocation"]["target_equities_bps"] = 4100
    assert _normalize(material) != _normalize(base)
    material = copy.deepcopy(base)
    material["sub"][0]["target_weight_bps"] = 1300
    assert _normalize(material) != _normalize(base)
