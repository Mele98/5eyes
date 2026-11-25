"""L2c (H-192): DSG-Vollstaendigkeit der Protokoll-Freitexte.

* advisory_log, mandate_report_notes (Versionen), conflict_of_interest_disclosures:
  Freitexte mit dem Kundenschluessel versiegelt (pii_vault-Muster wie L2b);
  das Siegel rechnet ueber den Umschlag und bleibt nach Crypto-Shred pruefbar.
  «gelöscht» != «manipuliert»; manipulierter Ciphertext bleibt «verändert»
  und sperrt alle Kundenkanaele (409 ADVISORY_LOG_INTEGRITY_FAILED).
* N-936-04: «Gelöscht (DSG)» nur mit belegter, ausgefuehrter Loeschung.
* N-936-05: Schluessel eines anderen Kunden -> «verändert».
* N-936-01: bleiben unversiegelte Altzeilen, meldet die Loeschquittung FAILED.
* N-936-06: 409 mit neutralem ``entry_id``/``entry_kind``.
* Auskunft (Art. 25 DSG): alle Personendaten inkl. versiegelter Freitexte.
* Migration: Altzeilen versiegeln (Up/Down/Up, Downgrade fail-closed).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, alembic_cfg, mandate, sf, user  # noqa: E402,F401

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

from routers import allocation as alloc_api  # noqa: E402
from routers import review as api  # noqa: E402
from schemas.review import (  # noqa: E402
    AdvisoryLogCreate, ConflictDisclosureCreate, ConflictMitigateRequest, ReportNotesUpdate,
)
from services import advisory_log_service as als  # noqa: E402
from services import pii_vault  # noqa: E402
from services import privacy_erasure_inventory as inv  # noqa: E402

NEEDLE = "Erbschaft Tante Verena (fiktiv)"
PERSON = "Eva Muster und Ehemann (fiktiv)"


def _log(db, *, description=NEEDLE, title="Jahresgespraech (fiktiv)"):
    payload = AdvisoryLogCreate(
        entry_type="Jahresreview", title=title, description=description + " " + "x" * 30,
        entry_datetime="2026-11-20T10:00:00.000Z", duration_minutes=45, communication_channel="persoenlich",
        language="de", location="Zuerich (fiktiv)", participants=[{"role": "client", "name": PERSON}],
        topics=["Risikoprofil"], risk_warnings_given=["Marktrisiko"], cost_disclosure_given=False,
    )
    entry = als.create_advisory_log(db, mandate_id="m-1", advisor=user(db, "adv-1"), payload=payload,
                                    mandate=mandate(db))
    db.flush()
    return entry


def _all_text(db):
    tables = [r[0] for r in db.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).all()]
    for table in tables:
        for row in db.execute(text(f'SELECT * FROM "{table}"')).all():
            for value in row:
                if isinstance(value, str):
                    yield table, value


def _erase(db, client_id="c-1"):
    from services.client_erasure import erase_client_personal_data

    return erase_client_personal_data(db, client_id, reason="L2c-Test")


# --- advisory_log ------------------------------------------------------------

def test_advisory_log_is_sealed_hash_binds_envelope_and_reads_back(sf):
    with sf() as db:
        entry = _log(db)
        row = db.execute(text("SELECT * FROM advisory_log")).mappings().one()
        for field in als.ADVISORY_LOG_SEALED_FIELDS:
            assert row[field] is None or pii_vault.is_sealed(row[field]), field
        assert all(pii_vault.is_sealed(row[f]) for f in als.ADVISORY_LOG_SEALED_FIELDS)
        assert "decision" not in als.ADVISORY_LOG_SEALED_FIELDS  # Kategorie (CHECK-Liste), kein Freitext
        assert not [t for t, v in _all_text(db) if NEEDLE in v or PERSON in v]
        assert als.verify_entry_integrity(entry) is True
        view = als.serialize_response(entry, db)
        assert NEEDLE in view["description"] and view["participants"][0]["name"] == PERSON
        assert view["location"] == "Zuerich (fiktiv)" and view["integrity_verified"] is True
        assert not any(pii_vault.is_sealed(v) for v in view.values() if isinstance(v, str))
        als.assert_shown_entries_intact([entry], document="Beratungsprotokoll")
        assert NEEDLE in als.customer_protocol_entry(entry)["description"]


def test_after_executed_erasure_seal_still_verifies_and_shows_deleted_not_tampered(sf):
    with sf() as db:
        entry = _log(db)
        stored = db.execute(text("SELECT description, integrity_hash FROM advisory_log")).one()
        _erase(db)
        assert tuple(db.execute(text("SELECT description, integrity_hash FROM advisory_log")).one()) == tuple(stored)
        db.expire_all()
        view = als.serialize_response(entry, db)
        assert view["integrity_verified"] is True  # geloescht, nicht manipuliert
        assert view["title"] == als.ERASED_TEXT and view["description"] == als.ERASED_TEXT
        assert view["participants"] == [] and view["location"] is None
        als.assert_shown_entries_intact([entry], document="Beratungsprotokoll")
        assert als.customer_protocol_entry(entry)["description"] == als.ERASED_TEXT


def test_n936_04_tombstone_without_executed_erasure_counts_as_tampered(sf):
    """Schluessel direkt vernichtet (kein Loeschvorgang): «verändert», Sperre."""
    with sf() as db:
        entry = _log(db)
        pii_vault.shred_client_keys(db, "c-1")
        db.expire_all()
        view = als.serialize_response(entry, db)
        assert view["integrity_verified"] is False and view["description"] is None
        with pytest.raises(als.AdvisoryLogIntegrityFailed):
            als.assert_shown_entries_intact([entry], document="Beratungsprotokoll")


def test_manipulated_ciphertext_stays_tampered_also_after_erasure(sf):
    from services.advisory_log_integrity import compute_integrity_hash

    with sf() as db:
        entry = _log(db)
        forged = pii_vault.seal_for_client(db, "c-1", "untergeschoben " + "y" * 30)
        db.execute(text("UPDATE advisory_log SET description = :d"), {"d": forged})
        db.expire_all()
        assert als.serialize_response(entry, db)["integrity_verified"] is False
        # Siegel neu gerechnet, aber Umschlag mit fremdem Kundenschluessel (N-936-05).
        from models.clients import Client

        db.add(Client(id="c-2", tenant_id=TENANT, client_number="K-2", first_name="Andere", last_name="Person",
                      advisor_id="adv-1", created_at=NOW, updated_at=NOW))
        db.flush()
        foreign = pii_vault.seal_for_client(db, "c-2", "fremd " + "z" * 30)
        db.execute(text("UPDATE advisory_log SET description = :d"), {"d": foreign})
        db.expire_all()
        entry = db.get(type(entry), entry.id)
        db.execute(text("UPDATE advisory_log SET integrity_hash = :h"),
                   {"h": compute_integrity_hash(payload=als.build_hash_payload(entry))})
        db.expire_all()
        entry = db.get(type(entry), entry.id)
        assert als.verify_entry_integrity(entry) is True  # Siegel passt ...
        assert als.serialize_response(entry, db)["integrity_verified"] is False  # ... Schluessel nicht
        # Nach echter Loeschung des fremden Kunden: weiterhin verändert, nie «gelöscht».
        _erase(db, "c-2")
        db.expire_all()
        assert als.serialize_response(db.get(type(entry), entry.id), db)["integrity_verified"] is False


def test_protocol_pdf_route_returns_409_with_neutral_fields(sf):
    from routers import pdf_reports

    with sf() as db:
        _log(db)
        db.execute(text("UPDATE advisory_log SET title = :t"),
                   {"t": pii_vault.seal_for_client(db, "c-1", "anders")})
        with pytest.raises(als.AdvisoryLogIntegrityFailed) as exc:
            pdf_reports._build_protokoll_data(mandate(db), db)
        detail = pdf_reports._advisory_log_integrity_409(exc.value).detail
        assert detail["reason_code"] == "ADVISORY_LOG_INTEGRITY_FAILED"
        assert detail["entry_kind"] == "advisory_log" and detail["entry_id"] == detail["advisory_log_id"]
        assert "pii-sealed" not in detail["message"]


def test_n936_06_rationale_409_has_no_advisory_log_id():
    from routers.pdf_reports import AdviceRationaleIntegrityFailed, _advisory_log_integrity_409

    detail = _advisory_log_integrity_409(AdviceRationaleIntegrityFailed("rat-1")).detail
    assert detail["entry_kind"] == "advice_rationale" and detail["entry_id"] == "rat-1"
    assert "advisory_log_id" not in detail and "Gründe der Empfehlung" in detail["message"]


def test_new_entry_after_erasure_is_refused_never_plaintext(sf):
    with sf() as db:
        _log(db)
        _erase(db)
        with pytest.raises(als.ProtocolTextSealError):
            _log(db, description="neu nach Loeschung")
        db.rollback()
        assert not [t for t, v in _all_text(db) if "neu nach Loeschung" in v]


# --- Interessenkonflikte -------------------------------------------------------

def _conflict(db, description=NEEDLE):
    return api.create_conflict(
        mandate_id="m-1",
        body=ConflictDisclosureCreate(conflict_type="Sonstiger Interessenkonflikt", description=description,
                                      reimbursed_to_client=False),
        request=Req(), db=db, current_user=user(db, "adv-1"),
    )


def test_conflict_texts_sealed_audit_log_without_plaintext_and_views_reveal(sf):
    from services.advisory_report import _build_conflict_disclosures

    with sf() as db:
        created = _conflict(db)
        assert created["description"] == NEEDLE and "text_seal" not in created
        api.mitigate_conflict(mandate_id="m-1", conflict_id=created["id"],
                              body=ConflictMitigateRequest(mitigation_action="Strukturelle Massnahme"),
                              request=Req(), db=db, current_user=user(db, "adv-1"))
        row = db.execute(text("SELECT description, mitigation_action, text_seal FROM conflict_of_interest_disclosures")).one()
        # Beschreibung versiegelt; die Massnahme ist eine Kategorie (CHECK-Liste im Desktop-Schema).
        assert pii_vault.is_sealed(row[0]) and row[1] == "Strukturelle Massnahme" and row[2]
        assert not [t for t, v in _all_text(db) if NEEDLE in v]
        listed = api.list_conflicts(mandate_id="m-1", db=db, current_user=user(db, "adv-1"))
        assert listed[0]["description"] == NEEDLE and listed[0]["mitigation_action"] == "Strukturelle Massnahme"
        section = _build_conflict_disclosures(db, mandate(db))
        assert section["entries"][0]["description"] == NEEDLE and "integrity_failed_ids" not in section


def test_tampered_conflict_blocks_advisory_report_and_kundeninformation(sf):
    from routers import pdf_reports
    from services.advisory_report import (
        _build_conflict_disclosures, _protocol_text_failures, assert_report_advisory_log_integrity,
    )

    with sf() as db:
        created = _conflict(db)
        db.execute(text("UPDATE conflict_of_interest_disclosures SET description = :d"),
                   {"d": pii_vault.seal_for_client(db, "c-1", "untergeschoben")})
        db.expire_all()
        section = _build_conflict_disclosures(db, mandate(db))
        assert section["integrity_failed_ids"] == [created["id"]] and section["entries"][0]["description"] == ""
        payload = {"protocol_text_integrity_failures": _protocol_text_failures(None, section)}
        with pytest.raises(als.AdvisoryLogIntegrityFailed) as exc:
            assert_report_advisory_log_integrity(payload, document="Advisory-Report")
        assert exc.value.entry_kind == "conflict_disclosure"
        with pytest.raises(als.AdvisoryLogIntegrityFailed):
            pdf_reports._kundeninformation_ties_and_offer(db, mandate(db), TENANT)


# --- Berichtsnotizen: Versionierung statt Ueberschreiben ------------------------

def _put_notes(db, **fields):
    return alloc_api.put_report_notes(mandate_id="m-1", body=ReportNotesUpdate(**fields), request=Req(), db=db,
                                      current_user=user(db, "adv-1"))


def test_report_notes_are_versioned_append_only_and_sealed(sf):
    with sf() as db:
        _put_notes(db, aa_anmerkungen="Erste Fassung: " + NEEDLE)
        second = _put_notes(db, aa_anmerkungen="Zweite Fassung", vorgehen_todos=["Termin mit " + PERSON])
        versions = db.execute(text(
            "SELECT version, aa_anmerkungen, vorgehen_todos_json FROM mandate_report_note_versions ORDER BY version"
        )).all()
        assert [v[0] for v in versions] == [1, 2]
        assert all(pii_vault.is_sealed(v[1]) for v in versions) and pii_vault.is_sealed(versions[1][2])
        head = db.execute(text("SELECT aa_anmerkungen, previous_versions_json FROM mandate_report_notes")).one()
        assert head[0] is None and head[1] is None  # kein Ueberschreiben, kein Klartext in der Kopfzeile
        assert not [t for t, v in _all_text(db) if NEEDLE in v or PERSON in v]
        assert second.aa_anmerkungen == "Zweite Fassung" and second.vorgehen_todos == ["Termin mit " + PERSON]
        assert second.previous_versions_total == 2
        assert second.previous_versions[0].changes["aa_anmerkungen"]["old"].startswith("Erste Fassung")
        with pytest.raises(Exception):  # append-only (Trigger)
            db.execute(text("UPDATE mandate_report_note_versions SET aa_anmerkungen = 'x'"))
        db.rollback()


def test_report_notes_erased_vs_tampered(sf):
    from services.advisory_report import _load_report_notes, _protocol_text_failures

    with sf() as db:
        _put_notes(db, aa_anmerkungen=NEEDLE)
        _erase(db)
        view = _load_report_notes(db, mandate(db))
        assert view.text_state == als.PROTOCOL_TEXT_ERASED and view.aa_anmerkungen == als.ERASED_TEXT
        assert _protocol_text_failures(view, {}) == []
        with pytest.raises(HTTPException) as exc:  # Kunde geloescht: Mandat nicht mehr erreichbar
            _put_notes(db, aa_anmerkungen="neu")
        assert exc.value.status_code in (404, 409)
        with pytest.raises(als.ProtocolTextSealError):  # und nie Klartext
            als.append_report_note_version(db, mandate_id="m-1", client_id="c-1", values={"aa_anmerkungen": "neu"},
                                           edited_by="adv-1", edited_at=NOW)


def test_tampered_report_note_version_blocks_put_and_customer_channel(sf):
    from services.advisory_report import _load_report_notes, _protocol_text_failures

    with sf() as db:
        _put_notes(db, aa_anmerkungen=NEEDLE)
        db.execute(text("DROP TRIGGER trg_mandate_report_note_versions_no_update"))
        db.execute(text("UPDATE mandate_report_note_versions SET aa_anmerkungen = :x"),
                   {"x": pii_vault.seal_for_client(db, "c-1", "untergeschoben")})
        view = _load_report_notes(db, mandate(db))
        assert view.text_state == als.PROTOCOL_TEXT_TAMPERED and view.aa_anmerkungen is None
        assert _protocol_text_failures(view, {})[0]["entry_kind"] == "report_notes"
        with pytest.raises(HTTPException) as exc:
            _put_notes(db, aa_anmerkungen="drueber")
        assert exc.value.status_code == 409 and exc.value.detail["reason_code"] == "ADVISORY_LOG_INTEGRITY_FAILED"


# --- Querschnitt (Freshness/Integritaet) ---------------------------------------

def test_cross_section_other_client_erasure_and_other_mandate_tamper_change_nothing(sf):
    from models.clients import Client
    from models.mandates import Mandate
    from services.advisory_report import _build_conflict_disclosures, _load_report_notes

    with sf() as db:
        entry = _log(db)
        _conflict(db)
        _put_notes(db, aa_anmerkungen=NEEDLE)
        db.add(Client(id="c-2", tenant_id=TENANT, client_number="K-2", first_name="Andere", last_name="Person",
                      advisor_id="adv-1", created_at=NOW, updated_at=NOW))
        db.add(Mandate(id="m-2", tenant_id=TENANT, client_id="c-2", mandate_number="M-2",
                       mandate_type="Anlageberatung", opened_at=NOW, created_at=NOW, updated_at=NOW))
        db.flush()
        other = api.create_conflict(
            mandate_id="m-2", body=ConflictDisclosureCreate(conflict_type="Sonstiger Interessenkonflikt",
                                                            description="anderer Kunde", reimbursed_to_client=False),
            request=Req(), db=db, current_user=user(db, "adv-1"))
        db.execute(text("UPDATE conflict_of_interest_disclosures SET description = 'kaputt' WHERE id = :i"),
                   {"i": other["id"]})
        _erase(db, "c-2")
        db.expire_all()
        assert als.serialize_response(db.get(type(entry), entry.id), db)["integrity_verified"] is True
        section = _build_conflict_disclosures(db, mandate(db))
        assert section["entries"][0]["description"] == NEEDLE and "integrity_failed_ids" not in section
        assert _load_report_notes(db, mandate(db)).aa_anmerkungen == NEEDLE


# --- Auskunft (Art. 25 DSG) ----------------------------------------------------

def test_access_export_contains_all_sealed_texts_decrypted_and_erased_marked(sf):
    from services import data_export

    with sf() as db:
        _log(db)
        _conflict(db)
        _put_notes(db, aa_anmerkungen="Notiz " + NEEDLE)
        db.commit()
        export = data_export.export_client_data(db, "c-1")
        dump = json.dumps(export, ensure_ascii=False)
        assert "pii-sealed" not in dump
        assert NEEDLE in json.dumps(export["sections"]["advisory_log"], ensure_ascii=False)
        assert PERSON in json.dumps(export["sections"]["advisory_log"], ensure_ascii=False)
        assert export["sections"]["conflict_of_interest_disclosure"][0]["description"] == NEEDLE
        assert export["sections"]["mandate_report_note_versions"][0]["aa_anmerkungen"] == "Notiz " + NEEDLE
        assert "advice_rationales" in export["sections"] and export["complete"] is True
        _erase(db)
        db.commit()
        after = data_export.export_client_data(db, "c-1")
        assert "pii-sealed" not in json.dumps(after, ensure_ascii=False)
        assert after["sections"]["advisory_log"][0]["description"] == "Gelöscht (DSG)."
        assert NEEDLE not in json.dumps(after, ensure_ascii=False)


def test_export_sections_list_matches_subject_request_export():
    from services.privacy_subject_requests import EXPORT_SECTIONS

    from services import data_export

    expected = {"advice_rationales", "mandate_report_note_versions", *data_export._SEALED_EVIDENCE_SECTIONS}
    assert expected <= set(EXPORT_SECTIONS) and expected <= set(data_export.RETENTION_NOTES)


# --- Loeschvorgang: N-936-01 ---------------------------------------------------

from test_privacy_erasure_workflow import (  # noqa: E402,F401
    CLIENT, NOW as ERASURE_NOW, _approve, _lines, _retain_evidence_erase_identity, db_path, session,
)


def _legacy_plain_log(session):
    from models.review import AdvisoryLog
    from services.advisory_log_integrity import compute_integrity_hash

    row = AdvisoryLog(id="log-legacy", mandate_id="m-rcp", entry_type="Jahresreview", title="Alt " + NEEDLE,
                      description="Klartext " + NEEDLE, status="Empfohlen", advisor_id="adv-rcp", client_signed=0,
                      entry_date="2026-01-01", entry_datetime="2026-01-01T10:00:00.000Z", cost_disclosure_given=0,
                      version=1, created_at="2026-01-01", updated_at="2026-01-01")
    row.integrity_hash = compute_integrity_hash(payload=als.build_hash_payload(row))
    session.add(row)
    session.commit()


def _erase_all_crypto(session):
    from services import privacy_erasure as pe

    _retain_evidence_erase_identity(session)
    for evidence_type, name in sorted({(c.evidence_type, c.name) for e in inv.PERSONAL_DATA_INVENTORY.values()
                                       for c in e.categories if c.method == inv.CRYPTO_SHRED}):
        _approve(session, evidence_type, name, inv.DELETE)
    session.commit()
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=ERASURE_NOW)
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=ERASURE_NOW)
    session.commit()
    return case


def test_n936_01_unsealed_legacy_rows_make_the_receipt_failed_with_count(session):
    _legacy_plain_log(session)
    case = _erase_all_crypto(session)
    line = _lines(session, case.id)[("advisory_log", inv.SEALED_FREE_TEXT)]
    assert line.decision_status == "FAILED" and line.failure_code == "UNSEALED_LEGACY_ROWS"
    assert case.status == "PARTIALLY_EXECUTED"
    receipt = json.loads(case.receipt_json)
    assert receipt["unsealed_legacy_rows"]["advisory_log"] == 1


def test_n936_01_counter_check_after_legacy_sealing_the_line_is_applied_and_text_erased(session):
    from services.advisory_log_integrity import seal_legacy_protocol_texts

    _legacy_plain_log(session)
    counts = seal_legacy_protocol_texts(session.connection())
    session.commit()
    assert counts["advisory_log_sealed"] == 1
    case = _erase_all_crypto(session)
    line = _lines(session, case.id)[("advisory_log", inv.SEALED_FREE_TEXT)]
    assert line.decision_status == "APPLIED" and line.failure_code is None
    assert "unsealed_legacy_rows" not in json.loads(case.receipt_json)
    from models.review import AdvisoryLog

    entry = session.get(AdvisoryLog, "log-legacy")
    view = als.serialize_response(entry, session)
    assert view["integrity_verified"] is True and view["description"] == als.ERASED_TEXT
    assert not [v for _t, v in _all_text(session) if "Klartext " + NEEDLE in v]


def test_inventory_and_register_cover_the_sealed_protocol_tables():
    for table in ("advisory_log", "mandate_report_notes", "mandate_report_note_versions",
                  "conflict_of_interest_disclosures"):
        cats = inv.PERSONAL_DATA_INVENTORY[table].categories
        sealed = [c for c in cats if c.name == inv.SEALED_FREE_TEXT]
        assert sealed and sealed[0].method == inv.CRYPTO_SHRED, table
        assert not [c for c in cats if c.name == inv.FREE_TEXT], table
    assert inv.INVENTORY_VERSION == "2026-11-22.1"
    raw = json.loads((Path(__file__).resolve().parents[1] / "config" / "processing_activities.json")
                     .read_text(encoding="utf-8"))
    pa05 = next(a for a in raw["activities"] if a["id"] == "PA-05")
    assert "mandate_report_note_versions" in pa05["tables"] and "versioniert" in pa05["purpose"]


# --- Migration ------------------------------------------------------------------

def test_legacy_sealing_seals_valid_rows_skips_tampered_and_is_idempotent(sf):
    from models.review import AdvisoryLog, ConflictOfInterestDisclosure, MandateReportNotes
    from services.advisory_log_integrity import compute_integrity_hash, seal_legacy_protocol_texts

    with sf() as db:
        good = AdvisoryLog(id="log-good", mandate_id="m-1", entry_type="Jahresreview", title="Alt gut",
                           description=NEEDLE, status="Empfohlen", advisor_id="adv-1", client_signed=0,
                           entry_date="2026-01-01", cost_disclosure_given=0, version=1,
                           created_at=NOW, updated_at=NOW)
        good.integrity_hash = compute_integrity_hash(payload=als.build_hash_payload(good))
        bad = AdvisoryLog(id="log-bad", mandate_id="m-1", entry_type="Jahresreview", title="Alt manipuliert",
                          description="vorher", status="Empfohlen", advisor_id="adv-1", client_signed=0,
                          entry_date="2026-01-01", cost_disclosure_given=0, version=1,
                          created_at=NOW, updated_at=NOW)
        bad.integrity_hash = compute_integrity_hash(payload=als.build_hash_payload(bad))
        bad.description = "nachher veraendert"
        db.add_all([good, bad, ConflictOfInterestDisclosure(
            id="coi-old", mandate_id="m-1", conflict_type="Sonstiger Interessenkonflikt", description=NEEDLE,
            disclosed_by="adv-1", created_at=NOW, updated_at=NOW), MandateReportNotes(
            id="mrn-old", mandate_id="m-1", aa_anmerkungen=NEEDLE, previous_versions_json=json.dumps(
                [{"edited_at": NOW, "edited_by": "adv-1", "changes": {"aa_anmerkungen": {"old": PERSON, "new": NEEDLE}}}]),
            last_edited_by="adv-1", last_edited_at=NOW, created_at=NOW, updated_at=NOW)])
        db.commit()
        counts = seal_legacy_protocol_texts(db.connection())
        db.commit()
        assert counts["advisory_log_sealed"] == 1 and counts["advisory_log_skipped_tampered"] == 1
        assert counts["conflicts_sealed"] == 1 and counts["report_notes_versioned"] == 1
        assert counts["report_history_sealed"] == 1
        db.expire_all()
        g = db.get(AdvisoryLog, "log-good")
        assert pii_vault.is_sealed(g.description) and pii_vault.reveal(db, g.description) == NEEDLE
        assert als.serialize_response(g, db)["integrity_verified"] is True
        b = db.get(AdvisoryLog, "log-bad")
        assert b.description == "nachher veraendert"  # bleibt Klartext und verändert
        assert als.serialize_response(b, db)["integrity_verified"] is False
        assert pii_vault.count_unsealed_rows(db, "c-1", ["m-1"]) == {"advisory_log": 1}
        notes = als.report_notes_view(db, "m-1")
        assert notes.aa_anmerkungen == NEEDLE and notes.history[-1]["changes"]["aa_anmerkungen"]["old"] == PERSON
        coi = api.list_conflicts(mandate_id="m-1", db=db, current_user=user(db, "adv-1"))
        assert coi[0]["description"] == NEEDLE
        assert not [t for t, v in _all_text(db) if NEEDLE in v or PERSON in v]
        again = seal_legacy_protocol_texts(db.connection())
        assert again["advisory_log_sealed"] == again["conflicts_sealed"] == again["report_notes_versioned"] == 0


def test_alembic_l2c_up_down_up_and_downgrade_fail_closed(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path / 'l2c.db'}"
    script = ScriptDirectory.from_config(alembic_cfg(url))
    assert script.get_heads() == ["d3b7e1f9a5c2"]  # K3 haengt an L2d
    assert script.get_revision("e2b7c4d9a1f3").down_revision == "c7e1a9d3f5b2"
    command.upgrade(alembic_cfg(url), "e2b7c4d9a1f3")
    engine = create_engine(url)

    def _state():
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(conflict_of_interest_disclosures)"))}
            triggers = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
        return tables, cols, triggers

    try:
        tables, cols, triggers = _state()
        assert "mandate_report_note_versions" in tables and "text_seal" in cols
        assert {"trg_mandate_report_note_versions_no_update", "trg_mandate_report_note_versions_tenant_guard"} <= triggers
        command.downgrade(alembic_cfg(url), "c7e1a9d3f5b2")  # leer -> erlaubt
        tables, cols, _ = _state()
        assert "mandate_report_note_versions" not in tables and "text_seal" not in cols
        command.upgrade(alembic_cfg(url), "e2b7c4d9a1f3")
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO advisory_log (id, mandate_id, entry_type, title, status, advisor_id, client_signed, "
                "entry_date, created_at, updated_at, cost_disclosure_given, version) VALUES "
                "('l1', 'm', 'Jahresreview', 'pii-sealed:v1:k:t', 'Empfohlen', 'u', 0, '2026-01-01', 'x', 'x', 0, 1)"
            ))
        with pytest.raises(RuntimeError, match="fail-closed"):
            command.downgrade(alembic_cfg(url), "c7e1a9d3f5b2")
        assert "mandate_report_note_versions" in _state()[0]
    finally:
        engine.dispose()


def test_alembic_postgres_offline_sql_creates_guard_and_rls_ready_table():
    import io

    from alembic import command

    buf = io.StringIO()
    command.upgrade(alembic_cfg("postgresql://u:p@localhost/db", buf), "c7e1a9d3f5b2:e2b7c4d9a1f3", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE mandate_report_note_versions" in sql
    assert "trg_mandate_report_note_versions_tenant_guard" in sql and "mandate_evidence_tenant_from_mandate" in sql
    assert "ADD COLUMN text_seal" in sql


def test_envelope_from_migration_opens_with_pii_vault(sf):
    from services.advisory_log_integrity import _LegacySealer

    with sf() as db:
        envelope = _LegacySealer(db.connection()).seal("c-1", "Text")
        assert pii_vault.reveal(db, envelope) == "Text"
        assert pii_vault.reveal_state(db, envelope, client_id="c-1") == ("Text", pii_vault.REVEAL_OPEN)
        assert pii_vault.reveal_state(db, envelope, client_id="c-x")[1] == pii_vault.REVEAL_UNREADABLE


def test_documents_list_names_the_source_draft_of_an_archived_contract(sf):
    from models.review import ContractDocument

    with sf() as db:
        for doc_id, content, pdf in (("d-draft", json.dumps({"ort_unterzeichnung": "Bern"}), None),
                                     ("d-arch", json.dumps({"source_document_id": "d-draft"}), "JVBERi0=")):
            db.add(ContractDocument(id=doc_id, mandate_id="m-1", document_type="Beratungsvertrag", title="BV",
                                    status="Entwurf", content_json=content, pdf_base64=pdf, version=1,
                                    created_by="adv-1", created_at=NOW, updated_at=NOW))
        db.commit()
        docs = {d.id: d for d in api.list_documents(mandate_id="m-1", db=db, current_user=user(db, "adv-1"))}
        assert docs["d-arch"].source_document_id == "d-draft" and docs["d-draft"].source_document_id is None


def test_damaged_envelope_with_appended_text_is_tampered_not_a_server_error(sf):
    """Wie der KN3-B-Waechter: an den Umschlag angehaengter Text (Umlaut) ist
    «verändert» (Sperre), kein 500 aus dem Fernet-Decoder."""
    with sf() as db:
        entry = _log(db)
        db.execute(text("UPDATE advisory_log SET description = description || ' Nachträglich geändert'"))
        db.expire_all()
        view = als.serialize_response(db.get(type(entry), entry.id), db)
        assert view["integrity_verified"] is False and view["description"] is None
        listed = api.list_advisory_log(mandate_id="m-1", db=db, current_user=user(db, "adv-1"))
        assert listed[0]["integrity_verified"] is False


def test_kundeninformation_ties_text_is_unchanged_for_sealed_description(sf):
    """Der Kundentext der Kundeninformation ist fuer dieselben Daten gleich,
    ob die Beschreibung versiegelt (neu) oder Klartext (Altbestand) ist --
    deshalb keine neue Vorlagenversion (Pin ARES-KI-FIDLEG-4 nachgefuehrt)."""
    from models.review import ConflictOfInterestDisclosure
    from routers import pdf_reports

    with sf() as db:
        _conflict(db, description="Retrozession Fonds A (fiktiv)")
        sealed_ties, _ = pdf_reports._kundeninformation_ties_and_offer(db, mandate(db), TENANT)
        db.execute(text("DELETE FROM conflict_of_interest_disclosures"))
        db.add(ConflictOfInterestDisclosure(id="coi-plain", mandate_id="m-1",
                                            conflict_type="Sonstiger Interessenkonflikt",
                                            description="Retrozession Fonds A (fiktiv)", disclosed_by="adv-1",
                                            created_at=NOW, updated_at=NOW))
        db.flush()
        plain_ties, _ = pdf_reports._kundeninformation_ties_and_offer(db, mandate(db), TENANT)
        assert sealed_ties == plain_ties == ("Sonstiger Interessenkonflikt: Retrozession Fonds A (fiktiv)",) or (
            list(sealed_ties) == list(plain_ties) and "Retrozession Fonds A (fiktiv)" in sealed_ties[0])


def test_access_export_stays_blocked_for_readonly():
    """CTO-Nachtrag: die Auskunft schreibt (Exportsiegel am Fall) -- fuer
    «Lesend» bleibt sie zentral gesperrt (READONLY_SCOPE); ausgefuehrt wird sie
    nur mit der bestehenden Datenschutz-Rollenpruefung."""
    from services.auth import readonly_may_call

    assert readonly_may_call("POST", "/privacy/subject-requests/x/export") is False
    assert readonly_may_call("POST", "/api/privacy/subject-requests/x/export") is False
