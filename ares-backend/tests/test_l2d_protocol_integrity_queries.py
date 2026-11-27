"""L2d: N-938-02 (Abfragezahl), N-938-03 (PUT ohne Aenderung), N-938-04 (kein
Neu-Siegeln eines veraenderten Vorgaengers). Vertraege der externen Abnahme
vom 24.11.2026, dazu Gegenproben."""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import pytest  # noqa: E402
from sqlalchemy import event, text  # noqa: E402

from h8_support import NOW, Req, mandate, sf, user  # noqa: E402,F401
from models.review import MandateReportNotes  # noqa: E402
from routers import allocation as allocation_api  # noqa: E402
from routers import review as review_api  # noqa: E402
from schemas.review import AdvisoryLogUpdate, ConflictDisclosureCreate, ReportNotesUpdate  # noqa: E402
from services import advisory_log_service as advisory  # noqa: E402
from services import pii_vault  # noqa: E402
from services.advisory_report import _load_report_notes  # noqa: E402
from tests.test_l2c_dsg_protocol_texts import _erase, _log  # noqa: E402


def _select_counter(db):
    count = {"selects": 0}

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            count["selects"] += 1

    event.listen(db.get_bind(), "before_cursor_execute", before_cursor_execute)
    return count, before_cursor_execute


def _stop_counter(db, callback):
    event.remove(db.get_bind(), "before_cursor_execute", callback)


def _put_notes(db, **fields):
    return allocation_api.put_report_notes(
        mandate_id="m-1",
        body=ReportNotesUpdate(**fields),
        request=Req(),
        db=db,
        current_user=user(db, "adv-1"),
    )


def test_n938_03_same_value_put_never_erases_unmigrated_head(sf):
    """An old plaintext head without versions must first become version 1.

    Current L2c/L2d salvage behavior returns ``None`` for "unchanged" and then
    clears the plaintext head, losing the only copy.
    """
    with sf() as db:
        db.add(MandateReportNotes(
            id="notes-legacy-same",
            mandate_id="m-1",
            aa_anmerkungen="NADEL-SAME",
            last_edited_by="adv-1",
            last_edited_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        ))
        db.commit()
        _put_notes(db, aa_anmerkungen="NADEL-SAME")
        view = advisory.report_notes_view(db, "m-1", client_id="c-1")
        versions = db.execute(text(
            "SELECT COUNT(*) FROM mandate_report_note_versions WHERE mandate_id = 'm-1'"
        )).scalar()
        assert view.aa_anmerkungen == "NADEL-SAME"
        assert versions == 1


def test_n938_03_empty_put_never_erases_unmigrated_head(sf):
    """An empty patch is a no-op, never an implicit deletion."""
    with sf() as db:
        db.add(MandateReportNotes(
            id="notes-legacy-empty",
            mandate_id="m-1",
            aa_anmerkungen="NADEL-EMPTY",
            last_edited_by="adv-1",
            last_edited_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        ))
        db.commit()
        _put_notes(db)
        view = advisory.report_notes_view(db, "m-1", client_id="c-1")
        assert view.aa_anmerkungen == "NADEL-EMPTY"


def test_n938_04_tampered_legacy_entry_cannot_be_superseded_clean(sf):
    """A bad predecessor must remain blocked; supersede must not wash it."""
    with sf() as db:
        entry = _log(db)
        db.execute(text("UPDATE advisory_log SET title = 'MANIPULIERT' WHERE id = :id"), {"id": entry.id})
        db.commit()
        db.expire_all()
        with pytest.raises(Exception) as exc:
            review_api.update_advisory_log_entry(
                mandate_id="m-1",
                log_id=entry.id,
                body=AdvisoryLogUpdate(
                    description="Neue saubere Fassung mit ausreichend langem Begründungstext"
                ),
                request=Req(),
                db=db,
                current_user=user(db, "adv-1"),
            )
        assert getattr(exc.value, "status_code", None) == 409
        detail = getattr(exc.value, "detail", {})
        assert isinstance(detail, dict) and detail.get("reason_code") == "ADVISORY_LOG_INTEGRITY_FAILED"
        assert db.execute(text("SELECT COUNT(*) FROM advisory_log")).scalar() == 1


def test_n938_02_advisory_log_decryption_queries_are_constant(sf):
    """Twenty sealed entries may not cause per-entry key/mandate SELECTs."""
    with sf() as db:
        _log(db, title="Eintrag 1")
        db.commit()
        counter1, callback1 = _select_counter(db)
        one = review_api.list_advisory_log("m-1", db=db, current_user=user(db, "adv-1"))
        _stop_counter(db, callback1)
        assert len(one) == 1
        baseline = counter1["selects"]

        for index in range(2, 21):
            _log(db, title=f"Eintrag {index}")
        db.commit()
        counter20, callback20 = _select_counter(db)
        twenty = review_api.list_advisory_log("m-1", db=db, current_user=user(db, "adv-1"))
        _stop_counter(db, callback20)
        assert len(twenty) == 20
        assert counter20["selects"] <= baseline + 5, (baseline, counter20["selects"])


def test_n938_02_report_reads_only_current_note_version(sf):
    """Report rendering must not decrypt the complete append-only history."""
    with sf() as db:
        _put_notes(db, aa_anmerkungen="Fassung 1")
        counter1, callback1 = _select_counter(db)
        first = _load_report_notes(db, mandate(db))
        _stop_counter(db, callback1)
        assert first.aa_anmerkungen == "Fassung 1"
        baseline = counter1["selects"]

        for index in range(2, 21):
            _put_notes(db, aa_anmerkungen=f"Fassung {index}")
        counter20, callback20 = _select_counter(db)
        latest = _load_report_notes(db, mandate(db))
        _stop_counter(db, callback20)
        assert latest.aa_anmerkungen == "Fassung 20"
        assert counter20["selects"] <= baseline + 5, (baseline, counter20["selects"])


def _legacy_head(db, value="NADEL-ALT"):
    db.add(MandateReportNotes(
        id="notes-legacy", mandate_id="m-1", aa_anmerkungen=value, last_edited_by="adv-1",
        last_edited_at=NOW, created_at=NOW, updated_at=NOW,
    ))
    db.commit()


def test_n938_03_changed_put_keeps_legacy_text_as_version_one(sf):
    with sf() as db:
        _legacy_head(db)
        _put_notes(db, aa_anmerkungen="NEU")
        view = advisory.report_notes_view(db, "m-1", client_id="c-1")
        assert (view.aa_anmerkungen, view.current_version) == ("NEU", 2)
        assert view.history[0]["changes"]["aa_anmerkungen"] == {"old": "NADEL-ALT", "new": "NEU"}
        assert view.history[1]["edited_at"] == NOW
        assert "NADEL" not in str(db.execute(text("SELECT * FROM mandate_report_notes")).all())
        assert "NADEL" not in str(db.execute(text("SELECT * FROM mandate_report_note_versions")).all())


def test_n938_03_explicit_clear_empties_the_current_text_only(sf):
    with sf() as db:
        _legacy_head(db)
        _put_notes(db, aa_anmerkungen="")
        view = advisory.report_notes_view(db, "m-1", client_id="c-1")
        assert view.aa_anmerkungen is None
        assert view.history[0]["changes"]["aa_anmerkungen"]["old"] == "NADEL-ALT"


def test_n938_04_untouched_entry_can_still_be_superseded(sf):
    with sf() as db:
        entry = _log(db)
        db.commit()
        result = review_api.update_advisory_log_entry(
            mandate_id="m-1", log_id=entry.id, request=Req(), db=db, current_user=user(db, "adv-1"),
            body=AdvisoryLogUpdate(description="Neue saubere Fassung mit ausreichend langem Text"),
        )
        assert result["version"] == 2 and result["integrity_verified"] is True


def test_n938_02_protocol_pdf_and_conflict_list_queries_are_constant(sf):
    from models.review import AdvisoryLog

    def _count(db, call):
        counter, callback = _select_counter(db)
        call()
        _stop_counter(db, callback)
        return counter["selects"]

    def _conflict(db, i):
        review_api.create_conflict(
            mandate_id="m-1", request=Req(), db=db, current_user=user(db, "adv-1"),
            body=ConflictDisclosureCreate(conflict_type="Retrozession / Inducement", description=f"Offenlegung {i} " + "x" * 30),
        )

    with sf() as db:
        def protocol():
            rows = db.query(AdvisoryLog).filter(AdvisoryLog.mandate_id == "m-1").all()
            advisory.assert_shown_entries_intact(rows, document="Beratungsprotokoll")
            reader = advisory.ProtocolReader(db)
            assert all(advisory.customer_protocol_entry(r, reader)["title"] for r in rows)

        def conflicts():
            review_api.list_conflicts("m-1", db=db, current_user=user(db, "adv-1"))

        _log(db)
        _conflict(db, 0)
        db.commit()
        base = _count(db, protocol), _count(db, conflicts)
        for i in range(1, 15):
            _log(db, title=f"Eintrag {i}")
            _conflict(db, i)
        db.commit()
        many = _count(db, protocol), _count(db, conflicts)
        assert many[0] <= base[0] + 2 and many[1] <= base[1] + 2, (base, many)


def test_key_reader_does_not_survive_the_call_after_erasure(sf):
    """Der Lesekontext gilt je Aufruf: nach der Loeschung ist nichts mehr lesbar."""
    with sf() as db:
        _log(db)
        db.commit()
        user_ = user(db, "adv-1")
        assert review_api.list_advisory_log("m-1", db=db, current_user=user_)[0]["title"].startswith("Jahres")
        _erase(db)
        db.commit()
        db.expire_all()
        entry = advisory.serialize_entries(db.query(review_api.AdvisoryLog).all(), db)[0]
        assert entry["title"] == advisory.ERASED_TEXT
        assert pii_vault.KeyReader(db).key("unbekannt") is None


def test_n938_02_report_opens_exactly_one_version(sf, monkeypatch):
    with sf() as db:
        for index in range(1, 4):
            _put_notes(db, aa_anmerkungen=f"Fassung {index}")
        opened = []
        original = advisory._reveal_note_version

        def _spy(db_, row, *args):
            opened.append(row["version"])
            return original(db_, row, *args)

        monkeypatch.setattr(advisory, "_reveal_note_version", _spy)
        assert _load_report_notes(db, mandate(db)).aa_anmerkungen == "Fassung 3"
        assert opened == [3]


def test_n938_03_head_without_version_is_never_emptied(sf):
    """Versiegelte Kopfzeile eines geloeschten Kunden: nichts zu uebernehmen,
    der Umschlag (Nachweis) bleibt stehen."""
    from services import notes_versioning

    with sf() as db:
        envelope = pii_vault.seal_for_client(db, "c-1", "NADEL")
        _legacy_head(db, envelope)
        _erase(db)
        db.commit()
        db.expire_all()
        head = db.query(MandateReportNotes).one()
        before = head.aa_anmerkungen
        assert notes_versioning.save_report_notes_version(
            db, head, client_id="c-1", values={}, edited_by="adv-1", edited_at=NOW,
        ) is None
        assert head.aa_anmerkungen == before == envelope
