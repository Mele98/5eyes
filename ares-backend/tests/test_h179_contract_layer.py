"""H-179 L2/L3 Vertragsschicht (Dok. 112 Kap. 4.1/7.1, Dok. 113 E-113-4/5).

Ares erfindet keinen Rechtstext und keinen Owner-Wert. Geprueft wird die
Mechanik: Katalog nur aus Schluesseln/Platzhaltern, Vier-Augen-Freigabe,
fail-closed Gate je fehlendem Owner-Inhalt (typisierter Code, deutsche
Meldung), Vertrags-PDF als Entwurf bzw. final mit Vorlagen-Hash, Kunden-
information mit Datenschutzabschnitt, Zuwendungen der Depotbank, Gruende der
Empfehlung (Art. 15 FIDLEG), W033-Restinhalte und die Querschnitt-Frische
(irrelevante Aenderung laesst den Vorlagen-Hash stehen, relevante macht den
Vertrag veraltet).

An der Basis d1dc3a78 rot: weder Katalog noch Tabellen noch Gate existieren;
``vertrag.py`` setzt den Ort «Zürich» als Vorgabe.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, alembic_cfg, mandate, sf, user  # noqa: E402,F401

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from core.reason_codes import DomainError  # noqa: E402
from database import new_uuid  # noqa: E402
from models.tenant import OwnerContentApproval, OwnerContentVersion  # noqa: E402
from models.review import ContractDocument  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from routers import review as api  # noqa: E402
from routers.review import sign_document  # noqa: E402
from schemas.review import (  # noqa: E402
    AdviceRationaleCreate, OwnerContentApprove, OwnerContentCreate, W033DeclarationCreate,
)
from schemas.review import ContractDocumentSign  # noqa: E402
from services import recommendation_release_gate as layer  # noqa: E402
from services import recommendation_release_gate as oc  # noqa: E402
from services.recommendation_release_gate import CHANNEL_FINALIZATION, CHANNEL_SIGNATURE  # noqa: E402

from client_onboarding_fixture import (  # noqa: E402
    ensure_test_contract_layer_tenant, ensure_test_owner_content, satisfy_client_onboarding,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _codes(db, channel=CHANNEL_SIGNATURE, **kw):
    return [f["reason_code"] for f in layer.contract_layer_findings(db, mandate(db), channel=channel, **kw)]


def _create(db, uid, key, *, body_text=None, value=None):
    return api.create_owner_content(
        body=OwnerContentCreate(content_key=key, body_text=body_text, value=value, source_reference="Beleg 1"),
        request=Req(), db=db, current_user=user(db, uid),
    )


def _approve(db, uid, row_id, content_hash):
    return api.approve_owner_content(
        row_id=row_id, body=OwnerContentApprove(content_hash=content_hash, approval_reference="Freigabe 1"),
        request=Req(), db=db, current_user=user(db, uid),
    )


def _add_risk_assessment(db, horizon_years: int, aid: str = "ra-1"):
    from models.profiling import RiskAssessment

    db.add(RiskAssessment(
        id=aid, mandate_id="m-1", version=1, is_current=1, valid_from=NOW,
        q_income_points=1, q_obligations_points=1, q_savings_points=1, q_wealth_points=1,
        risk_capacity_total=4, risk_capacity_profile="Ausgewogen", investment_horizon_years=horizon_years,
        investment_horizon_label=f"{horizon_years} Jahre", risk_capacity_score_x10=30,
        q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=1,
        risk_willingness_total=3, risk_willingness_profile="Ausgewogen", risk_willingness_score_x10=30,
        final_score_x10=30, final_profile="Ausgewogen", assessed_at=NOW, assessed_by="adv-1",
        created_at=NOW, updated_at=NOW,
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Katalog: nur Schluessel und Platzhalter, nie Text
# ---------------------------------------------------------------------------


def test_catalog_has_the_clause_keys_of_dok_112_and_placeholders_but_no_text():
    assert oc.CONTRACT_CLAUSE_KEYS == (
        "parteien_personalien", "leistung", "bestandteile", "rechenschaft", "kommunikation_zustellung",
        "datenbearbeitung_geheimnisentbindung", "delegation", "ausschluss_steuer_rechtsberatung",
        "segmentierung_kag_qualifikation", "meldepflicht_kunde", "wohnsitzwechsel", "steuerkonformitaet",
        "beendigung", "recht_gerichtsstand",
    )
    assert set(oc.CONTRACT_MANDATE_TYPES) == {"Vermögensverwaltung", "Anlageberatung", "Finanzplanung"}
    entries = oc.owner_content_catalog()
    for entry in entries:
        assert re.fullmatch(r"__OWNER_[A-Z0-9_]+_REQUIRED__", entry.placeholder), entry.key
        assert not hasattr(entry, "body_text")
    keys = {e.key for e in entries}
    assert "vertrag.gemeinsam.rechenschaft" in keys and "vertrag.vv.delegation" in keys
    rechenschaft = next(e for e in entries if e.key == "vertrag.gemeinsam.rechenschaft")
    assert rechenschaft.placeholder == "__OWNER_REPORTING_MODEL_REQUIRED__"  # A-1
    horizon = next(e for e in entries if e.key == oc.W033_MIN_HORIZON_KEY)
    assert horizon.placeholder == "__OWNER_MIN_HORIZON_YEARS_REQUIRED__" and horizon.kind == oc.OWNER_KIND_INTEGER


def test_place_default_zurich_is_gone():
    from services.pdf.base import VertragData

    assert VertragData().ort_unterzeichnung == ""
    for rel in ("routers/pdf_reports.py", "services/pdf/documents/vertrag.py"):
        source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
        assert '"Zürich"' not in source, rel


# ---------------------------------------------------------------------------
# Gate: frische Firma sperrt mit je eigenem Code
# ---------------------------------------------------------------------------


def test_fresh_tenant_blocks_with_typed_codes_and_german_owner_actions(sf):
    with sf() as db:
        m = mandate(db)
        m.mandate_type = "Vermögensverwaltung"
        db.flush()
        findings = layer.contract_layer_findings(db, m, channel=CHANNEL_SIGNATURE)
    codes = [f["reason_code"] for f in findings]
    assert codes == [
        "CONTRACT_TEMPLATE_UNAPPROVED", "CLIENT_INFORMATION_PRIVACY_MISSING", "DEPOT_BANK_INDUCEMENT_MISSING",
    ]
    assert all("Administration" in f["owner_action"] or "Berater" in f["owner_action"] for f in findings)
    assert "Vertragsvorlage" in findings[0]["message"]


def test_gate_raises_contract_layer_incomplete_before_any_effect(sf):
    with sf() as db:
        with pytest.raises(DomainError) as exc:
            layer.assert_contract_layer_release_eligible(db, mandate(db), channel=CHANNEL_FINALIZATION,
                                                         http_status=422)
    assert exc.value.reason_code == "CONTRACT_LAYER_INCOMPLETE"
    assert exc.value.http_status == 422
    assert "CONTRACT_TEMPLATE_UNAPPROVED" in exc.value.extra["finding_codes"]
    assert exc.value.extra["channel"] == CHANNEL_FINALIZATION


def test_signature_gate_ignores_documents_that_do_not_conclude_the_contract(sf):
    with sf() as db:
        doc = ContractDocument(id="d-x", mandate_id="m-1", document_type="Sonstiges", title="X",
                               status="Bereit", version=1, created_by="adv-1", created_at=NOW, updated_at=NOW)
        layer.assert_contract_layer_release_eligible(db, mandate(db), channel=CHANNEL_SIGNATURE, document=doc)


# ---------------------------------------------------------------------------
# Vier-Augen-Freigabe (Muster KYC-Wiedervorlage)
# ---------------------------------------------------------------------------


def test_owner_content_needs_a_second_person_and_the_seen_hash(sf):
    key = "vertrag.gemeinsam.rechenschaft"
    with sf() as db:
        created = _create(db, "adm-1", key, body_text="Text der Firma A")
        assert created["status"] == oc.OWNER_STATUS_UNAPPROVED and created["draft_version"] == 1
        row_id, content_hash = created["created_row_id"], created["draft_content_hash"]
        with pytest.raises(HTTPException) as same:
            _approve(db, "adm-1", row_id, content_hash)
        assert same.value.status_code == 403 and same.value.detail["reason_code"] == "OWNER_CONTENT_SAME_PERSON"
        with pytest.raises(HTTPException) as wrong:
            _approve(db, "adm-2", row_id, "0" * 64)
        assert wrong.value.detail["reason_code"] == "OWNER_CONTENT_HASH_MISMATCH"
        approved = _approve(db, "adm-2", row_id, content_hash)
        assert approved["status"] == oc.OWNER_STATUS_APPROVED and approved["effective_version"] == 1
        with pytest.raises(HTTPException) as again:
            _approve(db, "adm-2", row_id, content_hash)
        assert again.value.detail["reason_code"] == "OWNER_CONTENT_ALREADY_APPROVED"
        # Korrektur = neue Version; bis zur Freigabe bleibt v1 wirksam.
        v2 = _create(db, "adm-1", key, body_text="Text der Firma A, korrigiert")
        assert v2["status"] == oc.OWNER_STATUS_APPROVED and v2["effective_version"] == 1 and v2["draft_version"] == 2


def test_unknown_key_placeholder_text_and_bad_values_are_rejected(sf):
    with sf() as db:
        for key, kwargs, code in (
            ("vertrag.gemeinsam.erfunden", {"body_text": "x"}, "OWNER_CONTENT_KEY_UNKNOWN"),
            ("vertrag.gemeinsam.leistung", {"body_text": "__OWNER_VERTRAG_LEISTUNG_REQUIRED__"},
             "OWNER_CONTENT_VALUE_INVALID"),
            (oc.W033_MIN_HORIZON_KEY, {"value": 0}, "OWNER_CONTENT_VALUE_INVALID"),
            ("depotbank_zuwendung.bank-a", {"value": {"depot_bank": "Bank A", "status": "satz", "rate_bps": 10,
                                                      "evidence_reference": "B", "valid_from": "2026-01-01"}},
             "OWNER_CONTENT_VALUE_INVALID"),  # Basis fehlt
            ("depotbank_zuwendung.bank-a", {"value": {"depot_bank": "Bank B", "status": "keine",
                                                      "evidence_reference": "B", "valid_from": "2026-01-01"}},
             "OWNER_CONTENT_VALUE_INVALID"),  # Bank passt nicht zum Schluessel
            ("depotbank_zuwendung.bank-a", {"value": {"depot_bank": "Bank A", "status": "verzicht",
                                                      "range_min_bps": 30, "range_max_bps": 10,
                                                      "evidence_reference": "B", "valid_from": "2026-01-01"}},
             "OWNER_CONTENT_VALUE_INVALID"),
        ):
            with pytest.raises(HTTPException) as exc:
                _create(db, "adm-1", key, **kwargs)
            assert exc.value.status_code == 422 and exc.value.detail["reason_code"] == code, key


def test_forged_or_self_approved_chain_is_never_effective(sf):
    key = oc.PRIVACY_KEY_PREFIX + "zwecke"
    with sf() as db:
        created = _create(db, "adm-1", key, body_text="Zwecke der Firma")
        forged = OwnerContentApproval(
            id=new_uuid(), tenant_id=TENANT, content_key=key, content_row_id=created["created_row_id"],
            predecessor_approval_id="GENESIS", approved_by="adm-1", approved_at=NOW,
            approval_reference="selbst", content_hash=created["draft_content_hash"], approval_hash="f" * 64,
            approver_role="admin", approver_ready=1, approver_mailbox_digest="", creator_mailbox_digest="",
        )
        db.add(forged)
        db.flush()
        assert oc.resolve_owner_content(db, TENANT, key)["status"] == oc.OWNER_STATUS_INVALID
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE owner_content_approvals SET approved_by = 'adm-2'"))


def test_approval_of_another_firm_does_not_count(sf):
    with sf() as db:
        db.add(Tenant(id="t-andere", display_name="Andere", slug="t-andere", created_at=NOW, updated_at=NOW))
        db.flush()
        ensure_test_contract_layer_tenant(db, "t-andere", actor_id="adv-1")
        assert "CONTRACT_TEMPLATE_UNAPPROVED" in _codes(db)
        assert "CLIENT_INFORMATION_PRIVACY_MISSING" in _codes(db)


# ---------------------------------------------------------------------------
# V-1: Klauseln, Vorrang, Vorlagen-Hash und Querschnitt-Frische
# ---------------------------------------------------------------------------


def test_missing_clause_is_named_and_type_specific_text_wins(sf):
    with sf() as db:
        ensure_test_contract_layer_tenant(db, TENANT, actor_id="adm-1")
        assert "CONTRACT_TEMPLATE_UNAPPROVED" not in _codes(db)
        state = layer.contract_template_state(db, mandate(db))
        assert state["template_hash"] and all(c["key"].startswith("vertrag.gemeinsam.") for c in state["clauses"])
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key="vertrag.anlageberatung.leistung",
                                  body_text="Leistung Anlageberatung (Testwert)")
        state2 = layer.contract_template_state(db, mandate(db))
        leistung = next(c for c in state2["clauses"] if c["clause"] == "leistung")
        assert leistung["key"] == "vertrag.anlageberatung.leistung"
        assert state2["template_hash"] != state["template_hash"]
    with sf() as db:  # nur ein Teil freigegeben -> fehlende Klauseln benannt
        for clause in oc.CONTRACT_CLAUSE_KEYS[:3]:
            ensure_test_owner_content(db, TENANT, actor_id="adm-1",
                                      key=oc.contract_clause_key("gemeinsam", clause), body_text=f"T {clause}")
        finding = next(f for f in layer.contract_layer_findings(db, mandate(db), channel=CHANNEL_SIGNATURE)
                       if f["reason_code"].startswith("CONTRACT_TEMPLATE"))
        assert finding["reason_code"] == "CONTRACT_TEMPLATE_CLAUSE_MISSING"
        assert "rechenschaft" in finding["missing_clauses"] and "Beendigung" in finding["message"]


def test_freshness_cross_check_irrelevant_change_keeps_hash_relevant_change_breaks_it(sf):
    with sf() as db:
        ensure_test_contract_layer_tenant(db, TENANT, actor_id="adm-1")
        before = layer.contract_template_state(db, mandate(db))["template_hash"]
        # irrelevant: Klausel eines ANDEREN Mandatstyps, Entwurf ohne Freigabe,
        # Inhalt einer anderen Firma, Datenschutz-Text.
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key="vertrag.vv.leistung", body_text="VV")
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key="vertrag.gemeinsam.delegation",
                                  body_text="Entwurf", approve=False)
        db.add(Tenant(id="t-x", display_name="X", slug="t-x", created_at=NOW, updated_at=NOW))
        db.flush()
        ensure_test_owner_content(db, "t-x", actor_id="adm-1", key="vertrag.gemeinsam.beendigung", body_text="X")
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.PRIVACY_KEY_PREFIX + "zwecke",
                                  body_text="neu")
        assert layer.contract_template_state(db, mandate(db))["template_hash"] == before
        # relevant: freigegebene neue Version einer Klausel des Typs.
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key="vertrag.gemeinsam.beendigung",
                                  body_text="Beendigung neu")
        assert layer.contract_template_state(db, mandate(db))["template_hash"] != before


def test_p5_binding_is_none_until_approved_and_names_every_clause(sf):
    with sf() as db:
        assert layer.contract_template_binding(db, mandate(db)) is None
        ensure_test_contract_layer_tenant(db, TENANT, actor_id="adm-1")
        binding = layer.contract_template_binding(db, mandate(db))
    assert binding["kind"] == "contract_template" and binding["catalog_version"] == oc.OWNER_CATALOG_VERSION
    assert len(binding["template_hash"]) == 64
    assert [c["clause"] for c in binding["clauses"]] == list(oc.CONTRACT_CLAUSE_KEYS)
    assert all(c["approval_hash"] and c["content_hash"] for c in binding["clauses"])


# ---------------------------------------------------------------------------
# R-1: Zuwendungen der Depotbank
# ---------------------------------------------------------------------------


def test_depot_bank_inducement_missing_expired_and_ok(sf):
    with sf() as db:
        m = mandate(db)
        m.depot_bank = "Bank Ä"
        db.flush()
        assert "DEPOT_BANK_INDUCEMENT_MISSING" in _codes(db)
        key = oc.depot_bank_key("Bank Ä")
        assert key == "depotbank_zuwendung.bank-ae"
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=key, value={
            "depot_bank": "Bank Ä", "status": "satz", "rate_bps": 25, "basis": "verwaltetes Vermögen",
            "evidence_reference": "Vertrag 7", "valid_from": "2020-01-01", "valid_until": "2021-01-01",
        })
        assert "DEPOT_BANK_INDUCEMENT_EXPIRED" in _codes(db)
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=key, value={
            "depot_bank": "Bank Ä", "status": "verzicht", "range_min_bps": 10, "range_max_bps": 40,
            "evidence_reference": "Verzicht 3", "valid_from": "2020-01-01",
        })
        state = layer.depot_bank_inducement_state(db, m)
        assert state["status"] == "ok" and not any(c.startswith("DEPOT_BANK") for c in _codes(db))
        from routers.pdf_reports import _depot_bank_inducement_lines

        (line,) = _depot_bank_inducement_lines(state)
        assert "Bank Ä" in line and "Verzicht" in line and "Verzicht 3" in line


def test_advisory_mandate_without_bank_needs_no_inducement_but_vv_does(sf):
    with sf() as db:
        assert not any(c.startswith("DEPOT_BANK") for c in _codes(db))  # Anlageberatung ohne Bank
        mandate(db).mandate_type = "Vermögensverwaltung"
        db.flush()
        assert "DEPOT_BANK_INDUCEMENT_MISSING" in _codes(db)


# ---------------------------------------------------------------------------
# P-1 und E-1
# ---------------------------------------------------------------------------


def test_advice_rationale_required_at_finalization_for_investment_advice(sf):
    from models.review import RecommendationRun

    with sf() as db:
        db.add(RecommendationRun(id="run-1", mandate_id="m-1", client_id="c-1", run_type="Initial", policy_id="pol-h179",
                                 result_status="Draft", created_by="adv-1", created_at=NOW, updated_at=NOW))
        db.flush()
        assert "ADVICE_RATIONALE_MISSING" in _codes(db, CHANNEL_FINALIZATION, run_id="run-1")
        assert "ADVICE_RATIONALE_MISSING" not in _codes(db, CHANNEL_SIGNATURE)
        api.create_advice_rationale(
            mandate_id="m-1", run_id="run-1",
            body=AdviceRationaleCreate(client_needs="Beduerfnis", recommendation_reasons="Grund"),
            request=Req(), db=db, current_user=user(db, "adv-1"),
        )
        assert "ADVICE_RATIONALE_MISSING" not in _codes(db, CHANNEL_FINALIZATION, run_id="run-1")
        # Finanzplanung: keine Pflicht.
        mandate(db).mandate_type = "Finanzplanung"
        db.flush()
        assert "ADVICE_RATIONALE_MISSING" not in _codes(db, CHANNEL_FINALIZATION, run_id="run-2")


def test_w033_short_horizon_needs_advice_and_confirmation_bound_to_text_version(sf):
    with sf() as db:
        _add_risk_assessment(db, horizon_years=3)
        codes = _codes(db)
        assert "W033_DECLARATION_MISSING" in codes and "W033_MIN_HORIZON_UNAPPROVED" in codes
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.W033_MIN_HORIZON_KEY, value=5)
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.W033_DECLARATION_KEY, body_text="Erkl. v1")
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.W033_HORIZON_ADVICE_KEY, body_text="Abraten")
        assert "W033_HORIZON_ADVICE_UNCONFIRMED" in _codes(db)
        state = layer.w033_state(db, mandate(db))
        for kind, binding in (("angaben_wahr_meldepflicht", state["declaration_binding"]),
                              ("horizont_abraten", state["advice_binding"])):
            api.create_w033_declaration(
                mandate_id="m-1",
                body=W033DeclarationCreate(declaration_kind=kind, capture_channel="persoenlich_papier",
                                           confirmed_at="2026-11-21", content_hash=binding["content_hash"]),
                request=Req(), db=db, current_user=user(db, "adv-1"),
            )
        assert not any(c.startswith("W033") for c in _codes(db))
        # Neue, freigegebene Textversion -> alte Bestaetigung zaehlt nicht mehr.
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.W033_DECLARATION_KEY, body_text="Erkl. v2")
        assert "W033_DECLARATION_MISSING" in _codes(db)


def test_w033_advice_declaration_rejected_when_horizon_is_long_enough(sf):
    with sf() as db:
        _add_risk_assessment(db, horizon_years=10)
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.W033_MIN_HORIZON_KEY, value=5)
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.W033_HORIZON_ADVICE_KEY, body_text="Abraten")
        binding = layer.w033_state(db, mandate(db))["advice_binding"]
        with pytest.raises(HTTPException) as exc:
            api.create_w033_declaration(
                mandate_id="m-1",
                body=W033DeclarationCreate(declaration_kind="horizont_abraten", capture_channel="vor_ort",
                                           confirmed_at="2026-11-21", content_hash=binding["content_hash"]),
                request=Req(), db=db, current_user=user(db, "adv-1"),
            )
        assert exc.value.detail["reason_code"] == "W033_DECLARATION_NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# Kanaele: Signatur, Vertrags-PDF, Kundeninformation
# ---------------------------------------------------------------------------


def _contract_doc(db, doc_id="vertrag-1", content=None):
    db.add(ContractDocument(
        id=doc_id, mandate_id="m-1", document_type="Beratungsvertrag", title="Beratungsvertrag",
        content_json=json.dumps(content if content is not None else {"ort_unterzeichnung": "Bern"}),
        status="Entwurf", signed_by_advisor=0, signed_by_client=0, version=1,
        created_by="adv-1", created_at=NOW, updated_at=NOW,
    ))
    db.flush()


def test_contract_signature_blocked_without_owner_release_and_not_mutated(sf):
    with sf() as db:
        # Alles freigegeben (Testwerte) -- nur der Ort fehlt im Vertrag.
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.commit()
    with sf() as db:
        m = mandate(db)
        _contract_doc(db, content={})
        db.commit()
        layer_codes = _codes(db, document=db.get(ContractDocument, "vertrag-1"))
        assert "CONTRACT_PLACE_MISSING" in layer_codes
        body = ContractDocumentSign(signed_by_advisor=True, signature_image="data:image/png;base64,AAAA",
                                    signer_name="Berater")
        with pytest.raises(DomainError) as exc:
            sign_document(mandate_id=m.id, doc_id="vertrag-1", body=body, request=Req(), db=db,
                          current_user=user(db, "adv-1"))
        assert exc.value.reason_code == "CONTRACT_LAYER_INCOMPLETE"
        assert "CONTRACT_PLACE_MISSING" in exc.value.extra["finding_codes"]
        db.rollback()
        assert db.get(ContractDocument, "vertrag-1").signed_by_advisor == 0


def _doc_codes(db, doc):
    return [f["reason_code"] for f in layer.contract_layer_findings(
        db, mandate(db), channel=CHANNEL_SIGNATURE, document=doc) if f["scope"] == "document"]


def _vertrag_pdf(db, doc_id):
    from routers.pdf_reports import get_vertrag_pdf

    return get_vertrag_pdf(mandate_id="m-1", document_id=doc_id, db=db, current_user=user(db, "adv-1"))


def test_contract_pdf_is_draft_until_released_then_final_with_template_hash(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        _contract_doc(db)
        db.commit()
    with sf() as db:  # Vorlage freigegeben (Fixture), aber Ort fehlt in einem zweiten Vertrag
        _contract_doc(db, "vertrag-ohne-ort", content={})
        db.commit()
        draft = _vertrag_pdf(db, "vertrag-ohne-ort")
        assert draft.headers["X-Ares-Draft"] == "vertragsvorlage"
        assert "CONTRACT_PLACE_MISSING" in draft.headers["X-Ares-Draft-Reasons"]
        assert "X-Ares-Contract-Document-Id" not in draft.headers
    with sf() as db:
        final = _vertrag_pdf(db, "vertrag-1")
        assert "X-Ares-Draft" not in final.headers
        template_hash = final.headers["X-Ares-Contract-Template-Hash"]
        archived = db.get(ContractDocument, final.headers["X-Ares-Contract-Document-Id"])
        assert archived.status == "Archiviert" and archived.pdf_base64
        meta = json.loads(archived.content_json)
        assert meta["contract_template"]["template_hash"] == template_hash and meta["ort_unterzeichnung"] == "Bern"
        assert _doc_codes(db, archived) == []
        # relevante Aenderung: neue freigegebene Klausel -> archivierter Vertrag veraltet.
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key="vertrag.gemeinsam.beendigung",
                                  body_text="Beendigung v2 (Testwert)")
        db.commit()
        assert "CONTRACT_TEMPLATE_OUTDATED" in _doc_codes(db, archived)


def test_contract_pdf_for_mandate_type_without_template_is_a_draft(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        _contract_doc(db)
        mandate(db).mandate_type = "Reporting only"
        db.commit()
        response = _vertrag_pdf(db, "vertrag-1")
        assert response.headers["X-Ares-Draft"] == "vertragsvorlage"
        assert "CONTRACT_TEMPLATE_UNAPPROVED" in response.headers["X-Ares-Draft-Reasons"]
        assert db.query(ContractDocument).filter(ContractDocument.status == "Archiviert",
                                                 ContractDocument.document_type == "Beratungsvertrag").count() == 0


def test_client_information_requires_privacy_section(sf):
    from routers.pdf_reports import get_kundeninformation_pdf

    from client_onboarding_fixture import ensure_test_legal_profile

    with sf() as db:
        ensure_test_legal_profile(db, TENANT)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            get_kundeninformation_pdf(mandate_id="m-1", request=Req(), db=db, current_user=user(db, "adv-1"))
        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "CLIENT_INFORMATION_PRIVACY_MISSING"
        assert "verantwortlicher" in exc.value.detail["missing_sections"]


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_alembic_head_creates_append_only_tables_with_mandate_guard(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'h179.db'}"
    command.upgrade(alembic_cfg(url), "c7e1a9d3f5b2")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            triggers = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
        assert {"owner_content_versions", "owner_content_approvals", "advice_rationales",
                "w033_client_declarations"} <= tables
        for table in ("owner_content_versions", "owner_content_approvals", "advice_rationales",
                      "w033_client_declarations"):
            assert {f"trg_{table}_no_update", f"trg_{table}_no_delete"} <= triggers
        assert {"trg_advice_rationales_tenant_guard", "trg_w033_client_declarations_tenant_guard"} <= triggers
        command.downgrade(alembic_cfg(url), "74e3e973ea09")  # leer -> erlaubt
        command.upgrade(alembic_cfg(url), "c7e1a9d3f5b2")
    finally:
        engine.dispose()


def test_postgres_ddl_has_immutability_and_insert_guard():
    import io

    from alembic import command

    buf = io.StringIO()
    command.upgrade(alembic_cfg("postgresql://u:p@localhost/db", buf), "74e3e973ea09:c7e1a9d3f5b2", sql=True)
    ddl = buf.getvalue()
    for table in ("owner_content_versions", "owner_content_approvals", "advice_rationales",
                  "w033_client_declarations"):
        assert f"CREATE TRIGGER trg_{table}_immutable" in ddl
    assert "trg_advice_rationales_tenant_guard" in ddl and "mandate_evidence_tenant_from_mandate()" in ddl


# ---------------------------------------------------------------------------
# Finalisierung (Ende-zu-Ende ueber den Router)
# ---------------------------------------------------------------------------

from test_optimizer_shadow_mode import session_factory  # noqa: E402,F401


def test_finalization_blocked_without_advice_rationale_then_allowed(session_factory, monkeypatch):
    import client_onboarding_fixture as fixture
    from models.mandates import Mandate
    from models.review import RecommendationRun
    from models.users import User
    from test_finalize_conflict_evidence_gate import _finalize, _ready_run

    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="h179", client_onboarding=False)
    with session_factory() as db:
        m = db.get(Mandate, mandate_id)
        m.mandate_type = "Anlageberatung"
        monkeypatch.setattr(fixture, "record_test_advice_rationale", lambda *a, **k: None)
        satisfy_client_onboarding(db, m)
        db.commit()
    monkeypatch.undo()
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, mandate_id, run_id, advisor_id)
    assert exc.value.reason_code == "CONTRACT_LAYER_INCOMPLETE" and exc.value.http_status == 422
    assert exc.value.extra["finding_codes"] == ["ADVICE_RATIONALE_MISSING"]
    with session_factory() as db:
        assert db.get(RecommendationRun, run_id).result_status == "Draft"
        api.create_advice_rationale(
            mandate_id=mandate_id, run_id=run_id,
            body=AdviceRationaleCreate(client_needs="Altersvorsorge", recommendation_reasons="Horizont, Profil"),
            request=Req(), db=db, current_user=db.get(User, advisor_id),
        )
    assert _finalize(session_factory, mandate_id, run_id, advisor_id).result_status == "Final"


# ---------------------------------------------------------------------------
# N-927-02: die zweite Person wird beim LESEN nachgerechnet
# ---------------------------------------------------------------------------


def _direct_approval(db, key: str, approver_id: str, approved_at: str = NOW):
    """Version durch adm-1, Freigabe direkt in der DB (gueltiges Siegel), mit
    dem Stand des Freigebers eingefroren wie in der API (Rolle, Bereitschaft,
    Postfach-Identitaeten; N-927R-01/N-927S-01)."""
    from models.users import User
    from services.recommendation_release_gate import row_seal

    ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=key, body_text="Text (Testwert)", approve=False)
    version = db.query(OwnerContentVersion).filter(OwnerContentVersion.content_key == key).one()
    approver = db.get(User, approver_id)
    approval_id = new_uuid()
    ready = (int(oc.kyc_reviewer_account_ready({c.name: getattr(approver, c.name) for c in approver.__table__.columns}))
             if approver.role == "compliance_reviewer" else 1)
    approval = OwnerContentApproval(
        id=approval_id, tenant_id=TENANT, content_key=key, content_row_id=version.id,
        predecessor_approval_id="GENESIS", approved_by=approver_id, approved_at=approved_at,
        approval_reference="direkt", content_hash=version.content_hash,
        approver_role=str(approver.role), approver_ready=ready,
        **oc.owner_approval_frozen_identities(db, approval_id, approver_id, version.created_by),
    )
    approval.approval_hash = row_seal({c.name: getattr(approval, c.name) for c in approval.__table__.columns},
                                      "approval_hash")
    db.add(approval)
    db.flush()
    return oc.resolve_owner_content(db, TENANT, key)["status"]


def _user(db, uid, role="admin", tenant=TENANT, **extra):
    from models.users import User

    db.add(User(id=uid, username=uid, password_hash="x", full_name=uid.upper(), role=role, is_active=1,
                tenant_id=tenant, created_at=NOW, updated_at=NOW, **extra))
    db.flush()


def test_approver_of_another_firm_is_never_effective_but_same_firm_is(sf):
    with sf() as db:
        db.add(Tenant(id="t-fremd", display_name="Fremd", slug="t-fremd", created_at=NOW, updated_at=NOW))
        _user(db, "adm-fremd", tenant="t-fremd")
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "zwecke", "adm-fremd") == oc.OWNER_STATUS_UNAPPROVED
        # Gegenprobe: Admin derselben Firma.
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "rechte", "adm-2") == oc.OWNER_STATUS_APPROVED


def test_approver_without_approver_role_is_never_effective(sf):
    with sf() as db:
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "zwecke", "adv-1") == oc.OWNER_STATUS_UNAPPROVED
        _user(db, "rev-1", role="compliance_reviewer", invited_at=NOW, activated_at=NOW,
              credentials_set_by="self", totp_enabled=1, totp_set_by="self")
        # Gegenprobe: bereite externe Pruefperson derselben Firma.
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "rechte", "rev-1") == oc.OWNER_STATUS_APPROVED


def test_alias_mailbox_of_the_creator_is_never_a_second_person(sf):
    from models.users import User

    with sf() as db:
        db.query(User).filter(User.id == "adm-1").update({"email": "chef@firma.example"})
        _user(db, "adm-alias", email="Chef+zweit@Firma.example")
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "zwecke", "adm-alias") == oc.OWNER_STATUS_UNAPPROVED
        _user(db, "adm-anders", email="kollegin@firma.example")
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "rechte", "adm-anders") == oc.OWNER_STATUS_APPROVED


def _api_create(db, uid, key, text):
    return _create(db, uid, key, body_text=text)


def _api_approve(db, uid, created):
    return _approve(db, uid, created["created_row_id"], created["draft_content_hash"])


def test_later_deactivation_keeps_a_valid_approval_but_compromise_revokes_it(sf):
    """Gleiche Regel wie die KYC-Zweitfreigabe: eine spaetere Deaktivierung
    entwertet eine vorher gueltige Freigabe nicht; ein auditierter Widerruf
    wegen Kompromittierung ab dem Widerruf schon -- aber nur dieses Glied
    (N-927R-01: kein Kettenbruch, der Entwurf bleibt freigebbar)."""
    from models.users import User

    with sf() as db:
        key = oc.PRIVACY_KEY_PREFIX + "zwecke"
        assert _direct_approval(db, key, "adm-2") == oc.OWNER_STATUS_APPROVED
        db.query(User).filter(User.id == "adm-2").update({"is_active": 0})
        db.flush()
        assert oc.resolve_owner_content(db, TENANT, key)["status"] == oc.OWNER_STATUS_APPROVED
        db.query(User).filter(User.id == "adm-2").update({"compromised_since": "2000-01-01T00:00:00.000Z"})
        db.flush()
        assert oc.resolve_owner_content(db, TENANT, key)["status"] == oc.OWNER_STATUS_UNAPPROVED
        # Gegenprobe: Widerruf NACH der Freigabe laesst sie wirksam.
        db.query(User).filter(User.id == "adm-2").update({"compromised_since": "2999-01-01T00:00:00.000Z"})
        db.flush()
        assert oc.resolve_owner_content(db, TENANT, key)["status"] == oc.OWNER_STATUS_APPROVED


def test_role_change_of_the_approver_keeps_the_frozen_approval_effective(sf):
    """N-927R-01 (a): Rolle beim Freigeben gesiegelt eingefroren."""
    from models.users import User

    with sf() as db:
        key = oc.PRIVACY_KEY_PREFIX + "zwecke"
        created = _api_create(db, "adm-1", key, "Zwecke v1")
        approved = _api_approve(db, "adm-2", created)
        assert approved["status"] == oc.OWNER_STATUS_APPROVED
        row = db.query(OwnerContentApproval).filter(OwnerContentApproval.content_key == key).one()
        assert (row.approver_role, row.approver_ready) == ("admin", 1)
        db.query(User).filter(User.id == "adm-2").update({"role": "advisor"})
        db.flush()
        assert oc.resolve_owner_content(db, TENANT, key)["status"] == oc.OWNER_STATUS_APPROVED
        # Gegenprobe: eine mit der Rolle Berater eingefrorene Freigabe ist unwirksam.
        assert _direct_approval(db, oc.PRIVACY_KEY_PREFIX + "rechte", "adm-2") == oc.OWNER_STATUS_UNAPPROVED


def test_compromised_approver_then_new_approval_by_another_person_is_effective_again(sf):
    """N-927R-01 (b): nach dem Widerruf ist das Glied unwirksam, die Kette aber
    NICHT gebrochen -- eine neue Version mit neuer Freigabe wird wirksam."""
    from models.users import User

    with sf() as db:
        _user(db, "adm-3")
        key = oc.PRIVACY_KEY_PREFIX + "zwecke"
        _api_approve(db, "adm-2", _api_create(db, "adm-1", key, "Zwecke v1"))
        db.query(User).filter(User.id == "adm-2").update({"compromised_since": "2000-01-01T00:00:00.000Z",
                                                           "is_active": 0})
        db.flush()
        state = oc.resolve_owner_content(db, TENANT, key)
        assert state["status"] == oc.OWNER_STATUS_UNAPPROVED and state["invalid_approvals"] == 1
        assert "CLIENT_INFORMATION_PRIVACY_MISSING" in _codes(db)
        v2 = _api_create(db, "adm-1", key, "Zwecke v2")
        assert v2["draft_version"] == 2
        result = _api_approve(db, "adm-3", v2)
        assert result["status"] == oc.OWNER_STATUS_APPROVED and result["effective_version"] == 2
        # Gegenprobe: die neue Freigabe haengt lueckenlos am entwerteten Glied.
        rows = {r.content_row_id: r for r in db.query(OwnerContentApproval).filter(
            OwnerContentApproval.content_key == key).all()}
        first = next(r for r in rows.values() if r.predecessor_approval_id == "GENESIS")
        assert any(r.predecessor_approval_id == first.id for r in rows.values())
        # Gegenprobe: eine aeltere Version bleibt nicht nachtraeglich freigebbar.
        with pytest.raises(HTTPException) as exc:
            _approve(db, "adm-3", rows[first.content_row_id].content_row_id, first.content_hash)
        assert exc.value.status_code == 409


def test_structural_break_still_locks_the_key(sf):
    """Gegenprobe zu N-927R-01: ein Strukturfehler (gefaelschtes Siegel) bleibt
    kette_ungueltig und sperrt jede weitere Freigabe."""
    key = oc.PRIVACY_KEY_PREFIX + "zwecke"
    with sf() as db:
        created = _api_create(db, "adm-1", key, "Zwecke v1")
        db.add(OwnerContentApproval(
            id=new_uuid(), tenant_id=TENANT, content_key=key, content_row_id=created["created_row_id"],
            predecessor_approval_id="GENESIS", approved_by="adm-2", approved_at=NOW, approval_reference="x",
            content_hash=created["draft_content_hash"], approval_hash="0" * 64,
            approver_role="admin", approver_ready=1, approver_mailbox_digest="", creator_mailbox_digest="",
        ))
        db.flush()
        assert oc.resolve_owner_content(db, TENANT, key)["status"] == oc.OWNER_STATUS_INVALID
        v2 = _api_create(db, "adm-1", key, "Zwecke v2")
        row = db.get(OwnerContentVersion, v2["created_row_id"])
        with pytest.raises(HTTPException) as exc:
            _approve(db, "adm-2", row.id, row.content_hash)
        assert exc.value.detail["reason_code"] == "OWNER_CONTENT_CHAIN_INVALID"


def test_alembic_frozen_approver_columns_folded_into_c7e1_up_down_up(tmp_path):
    """N-927S-02: die eingefrorenen Spalten liegen direkt in c7e1a9d3f5b2
    (e5a9c3d7b1f4 gestrichen); ein Kopf, Up/Down/Up mit Append-only-Triggern."""
    from alembic import command
    from alembic.script import ScriptDirectory

    url = f"sqlite:///{tmp_path / 's02.db'}"
    script = ScriptDirectory.from_config(alembic_cfg(url))
    assert script.get_heads() == ["d3b7e1f9a5c2"]  # K3: neuer Kopf (hinter L2d)
    assert "e5a9c3d7b1f4" not in {r.revision for r in script.walk_revisions()}
    frozen = {"approver_role", "approver_ready", "approver_mailbox_digest", "creator_mailbox_digest"}
    command.upgrade(alembic_cfg(url), "c7e1a9d3f5b2")
    engine = create_engine(url)

    def _state():
        with engine.connect() as conn:
            info = {r[1]: r[3] for r in conn.execute(text("PRAGMA table_info(owner_content_approvals)"))}
            triggers = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
        return info, triggers

    try:
        info, triggers = _state()
        assert frozen <= set(info) and all(info[c] == 1 for c in frozen)  # NOT NULL
        assert "trg_owner_content_approvals_no_update" in triggers
        command.downgrade(alembic_cfg(url), script.get_revision("c7e1a9d3f5b2").down_revision)
        info, triggers = _state()
        assert not info and "trg_owner_content_approvals_no_update" not in triggers
        command.upgrade(alembic_cfg(url), "c7e1a9d3f5b2")
        info, triggers = _state()
        assert frozen <= set(info) and "trg_owner_content_approvals_no_update" in triggers
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# N-927S-01: nur der Kettenkopf wirkt; Postfach-Identitaeten eingefroren
# ---------------------------------------------------------------------------


def _two_approved_versions(db, key):
    """v1: adm-1 erfasst, adm-2 gibt frei. v2: adm-1 erfasst, adm-3 gibt frei."""
    from models.users import User

    db.query(User).filter(User.id == "adm-1").update({"email": "chef@firma.example"})
    db.query(User).filter(User.id == "adm-2").update({"email": "zwei@firma.example"})
    _user(db, "adm-3", email="drei@firma.example")
    _api_approve(db, "adm-2", _api_create(db, "adm-1", key, "Text ALT v1 (Testwert)"))
    result = _api_approve(db, "adm-3", _api_create(db, "adm-1", key, "Text NEU v2 (Testwert)"))
    assert (result["status"], result["effective_version"]) == (oc.OWNER_STATUS_APPROVED, 2)
    db.commit()


def _effective(db, key, tenant=TENANT):
    state = oc.resolve_owner_content(db, tenant, key)
    return state["status"], (state["version"] or {}).get("version")


def test_email_alias_change_of_the_head_approver_changes_nothing(sf):
    """N-927S-01 Weg 1 (Freigeber): ein Admin setzt die E-Mail des v2-Freigebers
    auf einen Alias des Erfassers. An 798642a7: Rueckfall auf v1 (Kippschalter).
    Neu: die Postfach-Identitaet ist eingefroren -> v2 bleibt wirksam, und die
    Aenderung steht mit Feld und maskiertem alt/neu im Audit."""
    from models.review import AuditLog
    from routers.auth import update_user
    from schemas.users import UserUpdate

    key = oc.PRIVACY_KEY_PREFIX + "zwecke"
    with sf() as db:
        _two_approved_versions(db, key)
        update_user(user_id="adm-3", body=UserUpdate(email="chef+x@firma.example"), db=db,
                    current_user=user(db, "adm-2"))
        assert _effective(db, key) == (oc.OWNER_STATUS_APPROVED, 2)
        update_user(user_id="adm-3", body=UserUpdate(email="drei@firma.example"), db=db,
                    current_user=user(db, "adm-2"))
        assert _effective(db, key) == (oc.OWNER_STATUS_APPROVED, 2)
        rows = db.query(AuditLog).filter(AuditLog.table_name == "users", AuditLog.record_id == "adm-3",
                                         AuditLog.field_name == "email").all()
        assert sorted((r.old_value, r.new_value) for r in rows) == sorted([
            ("d***@firma.example", "c***+…@firma.example"), ("c***+…@firma.example", "d***@firma.example"),
        ])


def test_email_alias_change_of_the_creator_changes_nothing(sf):
    """N-927S-01 Weg 1 (Erfasser): E-Mail des Erfassers auf einen Alias des
    v2-Freigebers. An 798642a7: Rueckfall auf v1. Neu: v2 bleibt wirksam."""
    from routers.auth import update_user
    from schemas.users import UserUpdate

    key = oc.PRIVACY_KEY_PREFIX + "zwecke"
    with sf() as db:
        _two_approved_versions(db, key)
        update_user(user_id="adm-1", body=UserUpdate(email="drei+y@firma.example"), db=db,
                    current_user=user(db, "adm-2"))
        assert _effective(db, key) == (oc.OWNER_STATUS_APPROVED, 2)


def test_backdated_revocation_of_the_head_approver_locks_without_rollback_then_new_version_works(sf):
    """N-927S-01 Weg 2: rueckdatierter Widerruf des v2-Freigebers. An 798642a7:
    v1 wieder wirksam. Neu: nicht freigegeben (kein Rueckfall), Gate sperrt.
    Danach v3 durch eine gueltige zweite Person -> wirksam (keine Dauersperre)."""
    from models.users import User

    key = oc.PRIVACY_KEY_PREFIX + "zwecke"
    with sf() as db:
        _two_approved_versions(db, key)
        db.query(User).filter(User.id == "adm-3").update(
            {"compromised_since": "2000-01-01T00:00:00.000Z", "is_active": 0})
        db.flush()
        state = oc.resolve_owner_content(db, TENANT, key)
        assert (state["status"], state["version"], state.get("head_revoked")) == (
            oc.OWNER_STATUS_UNAPPROVED, None, True)
        assert oc.approved_text(state) is None
        assert "CLIENT_INFORMATION_PRIVACY_MISSING" in _codes(db)
        v3 = _api_create(db, "adm-1", key, "Text v3 (Testwert)")
        assert v3["status"] == oc.OWNER_STATUS_UNAPPROVED and v3["draft_version"] == 3  # Entwurf sichtbar
        result = _api_approve(db, "adm-2", v3)
        assert (result["status"], result["effective_version"]) == (oc.OWNER_STATUS_APPROVED, 3)


def test_type_specific_clause_with_revoked_head_does_not_fall_back_to_the_shared_text(sf):
    """N-927S-01 analog: kein Rueckfall vom typspezifischen auf den gemeinsamen
    Klauseltext, wenn der Kopf des typspezifischen entwertet ist. Gegenprobe:
    ein nie freigegebener typspezifischer Entwurf faellt weiter auf den
    gemeinsamen Text zurueck."""
    from models.users import User

    with sf() as db:
        ensure_test_contract_layer_tenant(db, TENANT, actor_id="adv-1")
        m = mandate(db)
        slug = oc.CONTRACT_MANDATE_TYPES[m.mandate_type]
        clause = oc.CONTRACT_CLAUSE_KEYS[0]
        specific = oc.contract_clause_key(slug, clause)
        _user(db, "adm-3")
        _api_approve(db, "adm-3", _api_create(db, "adm-1", specific, "Typspezifisch (Testwert)"))
        state = oc.contract_template_state(db, m)
        assert state["clauses"][0]["key"] == specific and state["template_hash"]
        db.query(User).filter(User.id == "adm-3").update({"compromised_since": "2000-01-01T00:00:00.000Z"})
        db.flush()
        state = oc.contract_template_state(db, m)
        assert state["clauses"][0]["key"] == specific and clause in state["missing"]
        assert state["template_hash"] is None
        other = oc.contract_clause_key(slug, oc.CONTRACT_CLAUSE_KEYS[1])
        _api_create(db, "adm-1", other, "Nur Entwurf (Testwert)")
        entry = next(c for c in oc.contract_template_state(db, m)["clauses"]
                     if c["clause"] == oc.CONTRACT_CLAUSE_KEYS[1])
        assert entry["status"] == oc.OWNER_STATUS_APPROVED and entry["key"] != other


def test_cross_check_revoked_head_of_one_key_or_firm_changes_nothing_elsewhere(sf):
    """Querschnitt: der entwertete Kopf einer anderen Firma bzw. eine E-Mail-
    Aenderung eines Unbeteiligten aendert nichts; ein entwerteter Kopf im
    eigenen Schluessel kippt nur diesen Schluessel, nicht einen anderen."""
    from models.users import User
    from routers.auth import update_user
    from schemas.users import UserUpdate

    key = oc.PRIVACY_KEY_PREFIX + "zwecke"
    other_key = oc.PRIVACY_KEY_PREFIX + "rechte"
    with sf() as db:
        _two_approved_versions(db, key)
        _api_approve(db, "adm-2", _api_create(db, "adm-1", other_key, "Rechte (Testwert)"))
        db.add(Tenant(id="t-andere", display_name="Andere", slug="t-andere", created_at=NOW, updated_at=NOW))
        db.flush()
        _user(db, "adm-x1", tenant="t-andere")
        _user(db, "adm-x2", tenant="t-andere")
        _api_approve(db, "adm-x2", _api_create(db, "adm-x1", key, "Andere Firma (Testwert)"))
        assert _effective(db, key, "t-andere") == (oc.OWNER_STATUS_APPROVED, 1)

        def _snapshot():
            own = oc.resolve_owner_content(db, TENANT, key)
            return _effective(db, key), _effective(db, other_key), own["approval"]["approval_hash"]

        before = _snapshot()
        db.query(User).filter(User.id == "adm-x2").update({"compromised_since": "2000-01-01T00:00:00.000Z"})
        db.flush()
        update_user(user_id="adv-1", body=UserUpdate(email="unbeteiligt@firma.example"), db=db,
                    current_user=user(db, "adm-2"))
        assert _effective(db, key, "t-andere") == (oc.OWNER_STATUS_UNAPPROVED, None)
        assert _snapshot() == before
        db.query(User).filter(User.id == "adm-3").update({"compromised_since": "2000-01-01T00:00:00.000Z"})
        db.flush()
        assert _effective(db, key) == (oc.OWNER_STATUS_UNAPPROVED, None)
        assert _effective(db, other_key) == (oc.OWNER_STATUS_APPROVED, 1)


# ---------------------------------------------------------------------------
# N-927-03 / -06 / -07
# ---------------------------------------------------------------------------


def test_handoff_route_runs_the_contract_layer_gate():
    import inspect

    from routers import portfolio_handoff

    source = inspect.getsource(portfolio_handoff)
    gate_at = source.index("assert_contract_layer_release_eligible(\n        db, mandate, channel=CHANNEL_HANDOFF")
    assert source.index("assert_client_onboarding_release_eligible(\n        db, mandate, channel=CHANNEL_HANDOFF") < gate_at
    assert gate_at < source.index("p5_decision = _assert_run_is_published")


def test_handoff_gate_blocks_without_owner_release(sf):
    from services.recommendation_release_gate import CHANNEL_HANDOFF

    with sf() as db:
        with pytest.raises(DomainError) as exc:
            layer.assert_contract_layer_release_eligible(db, mandate(db), channel=CHANNEL_HANDOFF)
        assert exc.value.reason_code == "CONTRACT_LAYER_INCOMPLETE"
        assert "ADVICE_RATIONALE_MISSING" not in exc.value.extra["finding_codes"]
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        layer.assert_contract_layer_release_eligible(db, mandate(db), channel=CHANNEL_HANDOFF)


def test_bib_hint_only_as_owner_text(sf):
    from routers.pdf_reports import _protocol_advice_sections

    entry = oc.owner_catalog_entry(oc.PROTOCOL_BIB_KEY)
    assert entry is not None and entry.placeholder == "__OWNER_PROTOKOLL_BIB_HINWEIS_REQUIRED__"
    with sf() as db:
        before = _protocol_advice_sections(db, mandate(db), None)["information"]
        assert not any("Basisinformation" in line for line in before)
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.PROTOCOL_BIB_KEY,
                                  body_text="BIB-Hinweis der Firma (Testwert)")
        after = _protocol_advice_sections(db, mandate(db), None)["information"]
        assert "BIB-Hinweis der Firma (Testwert)" in after


def test_archived_contract_names_its_source_document(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        _contract_doc(db)
        db.commit()
        final = _vertrag_pdf(db, "vertrag-1")
        archived = db.get(ContractDocument, final.headers["X-Ares-Contract-Document-Id"])
        assert json.loads(archived.content_json)["source_document_id"] == "vertrag-1"


def test_cost_disclosure_without_depot_bank_inducement_is_a_draft(sf):
    import inspect

    from routers import pdf_reports
    from services.pdf.components import footer, watermark

    assert watermark.DEPOT_BANK_DRAFT_TEXT == footer.DEPOT_BANK_DRAFT_TEXT and "depotbank" in watermark.WATERMARK_MODES
    source = inspect.getsource(pdf_reports.get_cost_disclosure_pdf) if hasattr(
        pdf_reports, "get_cost_disclosure_pdf") else inspect.getsource(pdf_reports)
    assert '_with_draft_reason(ctx, "depotbank")' in source
    with sf() as db:
        m = mandate(db)
        m.depot_bank = "Bank X"
        db.flush()
        assert pdf_reports._depot_bank_inducement_missing(m, layer.depot_bank_inducement_state(db, m))
        ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=oc.depot_bank_key("Bank X"), value={
            "depot_bank": "Bank X", "status": "keine", "evidence_reference": "B", "valid_from": "2000-01-01"})
        assert not pdf_reports._depot_bank_inducement_missing(m, layer.depot_bank_inducement_state(db, m))
        m.depot_bank = None
        db.flush()
        assert not pdf_reports._depot_bank_inducement_missing(m, layer.depot_bank_inducement_state(db, m))
        m.mandate_type = "Vermögensverwaltung"
        db.flush()
        assert pdf_reports._depot_bank_inducement_missing(m, layer.depot_bank_inducement_state(db, m))
