"""L2b (H-190): DSG-Loeschpfad fuer ``advice_rationales`` (P-1, Art. 15 FIDLEG).

Muster der uebrigen append-only Freitexte (services/pii_vault.py,
``SEALED_FREE_TEXT`` / ``CRYPTO_SHRED``):

* Beduerfnisse und Gruende werden VOR dem Siegeln mit dem Kundenschluessel
  versiegelt; weder Zeile noch audit_log enthalten Klartext.
* Das Zeilensiegel ``rationale_hash`` bindet den Umschlag und wird beim Lesen
  nachgerechnet. Nach der Schluesselvernichtung bleibt es gueltig: Anzeige
  «Gelöscht (DSG)», keine Manipulation, keine KN9a-Sperre, kein
  ``ADVICE_RATIONALE_MISSING``.
* Nur ein nicht passendes Siegel heisst «verändert»: Protokoll-PDF 409
  (gleiche Regel wie KN9a), Finalisierung gesperrt.
* Eine loeschende Disposition endet fuer ``advice_rationales`` mit APPLIED
  statt ``METHOD_NOT_IMPLEMENTED``.

An der Basis 842dd37f rot: Klartext in der Zeile, kein Siegel-Nachrechnen,
Inventar ``FREE_TEXT`` ohne Methode.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, Req, mandate, sf, user  # noqa: E402,F401

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

from routers import review as api  # noqa: E402
from schemas.review import AdviceRationaleCreate  # noqa: E402
from services import pii_vault  # noqa: E402
from services import privacy_erasure_inventory as inv  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402
from services.recommendation_release_gate import CHANNEL_FINALIZATION  # noqa: E402

NEEDS = "Altersvorsorge Eva Muster, Erbschaft der Tante (fiktiv)"
REASONS = "Horizont 12 Jahre, Profil ausgewogen, Gesundheit stabil (fiktiv)"


def _run(db, run_id="run-1"):
    from models.review import RecommendationRun

    db.add(RecommendationRun(id=run_id, mandate_id="m-1", client_id="c-1", run_type="Initial", policy_id="pol-l2b",
                             result_status="Draft", created_by="adv-1", created_at=NOW, updated_at=NOW))
    db.flush()


def _record(db, run_id="run-1", needs=NEEDS, reasons=REASONS):
    return api.create_advice_rationale(
        mandate_id="m-1", run_id=run_id,
        body=AdviceRationaleCreate(client_needs=needs, recommendation_reasons=reasons),
        request=Req(), db=db, current_user=user(db, "adv-1"),
    )


def _codes(db, run_id="run-1"):
    return [f["reason_code"] for f in gate.contract_layer_findings(db, mandate(db), channel=CHANNEL_FINALIZATION,
                                                                   run_id=run_id)]


def _all_text(db):
    tables = [r[0] for r in db.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).all()]
    for table in tables:
        for row in db.execute(text(f'SELECT * FROM "{table}"')).all():
            for value in row:
                if isinstance(value, str):
                    yield table, value


def _protocol_sections(db, monkeypatch, run_id="run-1"):
    from routers import pdf_reports

    monkeypatch.setattr(pdf_reports, "resolve_current_recommendation_run",
                        lambda *_a, **_k: SimpleNamespace(id=run_id))
    return pdf_reports._protocol_advice_sections(db, mandate(db), None)


def test_rationale_is_sealed_no_plaintext_in_row_or_audit_and_seal_verifies(sf):
    with sf() as db:
        _run(db)
        response = _record(db)
        # Die API antwortet mit dem erfassten Text, gespeichert ist nur der Umschlag.
        assert response["client_needs"] == NEEDS and response["sealed"] is True
        row = db.execute(text("SELECT * FROM advice_rationales")).mappings().one()
        assert pii_vault.is_sealed(row["client_needs"]) and pii_vault.is_sealed(row["recommendation_reasons"])
        hits = [(t, v) for t, v in _all_text(db) if "Eva Muster" in v and t != "clients" or "Tante" in v]
        assert hits == [], hits
        view = gate.latest_advice_rationale(db, "m-1", "run-1")
        assert view["state"] == gate.ADVICE_RATIONALE_OK and view["integrity_verified"] is True
        assert (view["client_needs"], view["recommendation_reasons"]) == (NEEDS, REASONS)
        assert "ADVICE_RATIONALE_MISSING" not in _codes(db)


def test_after_crypto_shred_seal_still_verifies_shows_deleted_dsg_and_does_not_block(sf, monkeypatch):
    with sf() as db:
        _run(db)
        _record(db)
        before = db.execute(text("SELECT rationale_hash, client_needs FROM advice_rationales")).one()
        # L2c (N-936-04): «gelöscht» nur mit belegter Loeschung -> echte
        # Loeschung (Alt-Pfad erase_client_personal_data: erased_at + Shred).
        from services.client_erasure import erase_client_personal_data

        assert erase_client_personal_data(db, "c-1", reason="L2b-Test")["pii_keys_shredded"] == 1
        after = db.execute(text("SELECT rationale_hash, client_needs FROM advice_rationales")).one()
        assert tuple(after) == tuple(before)  # Zeile unveraendert (append-only)
        view = gate.latest_advice_rationale(db, "m-1", "run-1")
        assert view["state"] == gate.ADVICE_RATIONALE_ERASED
        assert view["integrity_verified"] is True  # keine Manipulation
        assert view["client_needs"] is None and view["recommendation_reasons"] is None
        assert "ADVICE_RATIONALE_MISSING" not in _codes(db)
        sections = _protocol_sections(db, monkeypatch)
        assert sections["client_needs"] == "Gelöscht (DSG)."
        assert sections["recommendation_reasons"] == "Gelöscht (DSG)."


def test_after_shred_new_rationale_is_refused_and_nothing_is_stored(sf):
    with sf() as db:
        _run(db)
        _run(db, "run-2")
        _record(db)
        pii_vault.shred_client_keys(db, "c-1")
        with pytest.raises(HTTPException) as exc:
            _record(db, "run-2")
        assert exc.value.status_code == 409 and "DSG" in str(exc.value.detail)
        assert db.execute(text("SELECT COUNT(*) FROM advice_rationales WHERE recommendation_run_id='run-2'")).scalar() == 0
        assert not [v for _t, v in _all_text(db) if "Tante" in v]


def _forged(db, run_id="run-1", **override):
    """Zeile mit gesiegeltem Umschlag, danach ein Feld veraendert (direkt
    geschrieben; die API kann das nicht)."""
    from models.review import AdviceRationale
    from database import new_uuid

    record = AdviceRationale(
        id=new_uuid(), tenant_id="t-h8", mandate_id="m-1", client_id="c-1", recommendation_run_id=run_id,
        client_needs=pii_vault.seal_for_client(db, "c-1", NEEDS),
        recommendation_reasons=pii_vault.seal_for_client(db, "c-1", REASONS),
        recorded_by="adv-1", recorded_at=NOW,
    )
    record.rationale_hash = gate.row_seal({c.name: getattr(record, c.name) for c in record.__table__.columns},
                                          "rationale_hash")
    for key, value in override.items():
        setattr(record, key, value)
    db.add(record)
    db.flush()
    return record


def test_changed_text_breaks_the_seal_blocks_finalization_and_protocol_pdf(sf, monkeypatch):
    from routers.pdf_reports import AdviceRationaleIntegrityFailed

    with sf() as db:
        _run(db)
        _forged(db, client_needs=pii_vault.seal_for_client(db, "c-1", "untergeschoben"))
        view = gate.latest_advice_rationale(db, "m-1", "run-1")
        assert view["state"] == gate.ADVICE_RATIONALE_TAMPERED and view["integrity_verified"] is False
        findings = gate.contract_layer_findings(db, mandate(db), channel=CHANNEL_FINALIZATION, run_id="run-1")
        rationale = [f for f in findings if f["reason_code"] == "ADVICE_RATIONALE_MISSING"]
        assert rationale and "Prüfsumme" in rationale[0]["message"]
        with pytest.raises(AdviceRationaleIntegrityFailed) as exc:
            _protocol_sections(db, monkeypatch)
        assert "Prüfsumme" in str(exc.value) and "Gründe der Empfehlung" in str(exc.value)


def test_cross_check_shredding_another_client_or_tampering_another_run_changes_nothing(sf):
    """Querschnitt: Loeschung eines anderen Kunden und ein veraenderter
    Eintrag eines anderen Laufs lassen diesen Eintrag lesbar und gueltig."""
    from models.clients import Client

    with sf() as db:
        db.add(Client(id="c-2", tenant_id="t-h8", client_number="K-2", first_name="Andere", last_name="Person",
                      advisor_id="adv-1", created_at=NOW, updated_at=NOW))
        _run(db)
        _run(db, "run-x")
        _record(db)
        pii_vault.seal_for_client(db, "c-2", "Text eines anderen Kunden")
        pii_vault.shred_client_keys(db, "c-2")
        _forged(db, "run-x", recommendation_reasons=pii_vault.seal_for_client(db, "c-1", "anders"))
        view = gate.latest_advice_rationale(db, "m-1", "run-1")
        assert view["state"] == gate.ADVICE_RATIONALE_OK and view["client_needs"] == NEEDS
        assert gate.latest_advice_rationale(db, "m-1", "run-x")["state"] == gate.ADVICE_RATIONALE_TAMPERED


def test_legacy_plaintext_row_stays_readable_and_is_reported_by_the_erasure(sf):
    """Gegenprobe Altbestand (vor L2b im Klartext gesiegelt): lesbar, gueltig,
    von ``count_unsealed_rows`` gemeldet (Owner-/Legal-Entscheid, nie still)."""
    from models.review import AdviceRationale
    from database import new_uuid

    with sf() as db:
        _run(db)
        record = AdviceRationale(id=new_uuid(), tenant_id="t-h8", mandate_id="m-1", client_id="c-1",
                                 recommendation_run_id="run-1", client_needs="alt", recommendation_reasons="alt",
                                 recorded_by="adv-1", recorded_at=NOW)
        record.rationale_hash = gate.row_seal({c.name: getattr(record, c.name) for c in record.__table__.columns},
                                              "rationale_hash")
        db.add(record)
        db.flush()
        view = gate.latest_advice_rationale(db, "m-1", "run-1")
        assert view["state"] == gate.ADVICE_RATIONALE_OK and view["sealed"] is False
        assert pii_vault.count_unsealed_rows(db, "c-1", ["m-1"]) == {"advice_rationales": 1}


def test_inventory_marks_advice_rationales_sealed_with_crypto_shred_and_registry_covers_it():
    entry = inv.PERSONAL_DATA_INVENTORY["advice_rationales"]
    sealed = [c for c in entry.categories if c.name == inv.SEALED_FREE_TEXT]
    assert sealed and sealed[0].method == inv.CRYPTO_SHRED
    assert set(sealed[0].columns) == {"client_needs", "recommendation_reasons"}
    assert not [c for c in entry.categories if c.name == inv.FREE_TEXT]
    assert {("advice_rationales", "client_needs"), ("advice_rationales", "recommendation_reasons")} <= set(
        pii_vault.SEALED_APPEND_ONLY_COLUMNS)


def test_processing_register_names_the_sealed_rationale():
    import json

    raw = json.loads((Path(__file__).resolve().parents[1] / "config" / "processing_activities.json")
                     .read_text(encoding="utf-8"))
    pa05 = next(a for a in raw["activities"] if a["id"] == "PA-05")
    assert "advice_rationales" in pa05["tables"]
    assert "Gruende der Empfehlung" in pa05["purpose"] and "versiegelt" in pa05["purpose"]


# --- Loeschvorgang (PRIVACY-001) ---------------------------------------------

from test_privacy_erasure_workflow import (  # noqa: E402,F401
    CLIENT, NOW as ERASURE_NOW, _approve, _lines, _retain_evidence_erase_identity, db_path, session,
)


def test_erasing_disposition_applies_crypto_shred_instead_of_method_not_implemented(session):
    from database import new_uuid
    from models.review import AdviceRationale
    from services import privacy_erasure as pe

    needs, reasons = gate.seal_advice_rationale_texts(session, CLIENT, NEEDS, REASONS)
    record = AdviceRationale(id=new_uuid(), mandate_id="m-rcp", client_id=CLIENT, recommendation_run_id="run-rcp",
                             client_needs=needs, recommendation_reasons=reasons, recorded_by="adv-rcp",
                             recorded_at=NOW)
    record.rationale_hash = gate.row_seal({c.name: getattr(record, c.name) for c in record.__table__.columns},
                                          "rationale_hash")
    session.add(record)
    session.commit()
    _retain_evidence_erase_identity(session)
    # Geteilter Kundenschluessel: alle versiegelten Kategorien loeschen.
    for evidence_type, name in sorted({(c.evidence_type, c.name) for e in inv.PERSONAL_DATA_INVENTORY.values()
                                       for c in e.categories if c.method == inv.CRYPTO_SHRED}):
        _approve(session, evidence_type, name, inv.DELETE)
    session.commit()
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=ERASURE_NOW)
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=ERASURE_NOW)
    session.commit()

    line = _lines(session, case.id)[("advice_rationales", inv.SEALED_FREE_TEXT)]
    assert line.row_count == 1 and line.disposition == inv.DELETE
    assert line.decision_status == "APPLIED" and line.failure_code is None
    view = gate.latest_advice_rationale(session, "m-rcp", "run-rcp")
    assert view["state"] == gate.ADVICE_RATIONALE_ERASED and view["integrity_verified"] is True
    assert not [v for _t, v in _all_text(session) if "Tante" in v]


# --- Owner-Content-Admin: wo erscheint der Text? (L2b Punkt 4) ---------------


def test_every_catalog_key_names_document_and_section_and_the_form_shows_it():
    entries = list(gate.owner_content_catalog()) + [gate.owner_catalog_entry("depotbank_zuwendung.testbank")]
    for entry in entries:
        assert "(PDF)" in entry.visible_in and ("Abschnitt" in entry.visible_in or "Titel" in entry.visible_in), entry
    vv = gate.owner_catalog_entry("vertrag.vv.rechenschaft")
    assert "Klausel «Rechenschaft»" in vv.visible_in and "Vermögensverwaltung" in vv.visible_in
    js = (Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "owner-content.js").read_text(encoding="utf-8")
    assert 'id="oc-key-hint"' in js and "onchange=\"ownerContentKeyHint()\"" in js and "Erscheint in:" in js


def test_catalog_wording_is_not_part_of_the_template_hash(sf, monkeypatch):
    """Querschnitt-Freshness: eine geaenderte Anzeige «Erscheint in» laesst den
    Vorlagen-Pruefwert stehen (sie ist kein Vertragsinhalt)."""
    import dataclasses

    from h8_support import TENANT
    from client_onboarding_fixture import ensure_test_owner_content

    with sf() as db:
        for clause in gate.CONTRACT_CLAUSE_KEYS:
            ensure_test_owner_content(db, TENANT, actor_id="adm-1", key=gate.contract_clause_key("gemeinsam", clause),
                                      body_text=f"Testwert {clause}", approve=True)
        before = gate.contract_template_state(db, mandate(db))["template_hash"]
        assert before
        original = gate.owner_content_catalog
        monkeypatch.setattr(gate, "owner_content_catalog",
                            lambda: tuple(dataclasses.replace(e, visible_in="anders") for e in original()))
        assert gate.contract_template_state(db, mandate(db))["template_hash"] == before
