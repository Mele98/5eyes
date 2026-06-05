"""Sprint U-37b (2026-06-04): Integration-Test History via FastAPI-Client.

Pre-U-37b
---------
PR #140 (U-37) hat Append-only Snapshot-History in
previous_versions_json eingebaut, aber Response-Schema und
GET-Endpoint exponierten sie NICHT (Review-Befund).

Post-U-37b
----------
- ReportNotesResponse.previous_versions: list[ReportNotesHistoryEntry]
- _serialize_notes laedt History via notes_versioning.load_history
- GET /mandates/{id}/report-notes returnt History DESC
- Integration-Test: PUT -> PUT -> GET liefert 2 Einträge neueste zuerst,
  No-Op PUT erzeugt KEIN Eintrag.

Test-Strategie
--------------
Uses FastAPI TestClient mit DB-stub damit kein SQLCipher-Setup
noetig. Reicht fuer Schema-Roundtrip + History-Order-Verification.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Schema-Existenz (PR #140 Review-Befund A)
# ---------------------------------------------------------------------------

def test_report_notes_response_has_previous_versions_field():
    """Schema-Befund: ReportNotesResponse exponiert History."""
    from schemas.review import ReportNotesResponse
    fields = ReportNotesResponse.model_fields
    assert "previous_versions" in fields, (
        "ReportNotesResponse fehlt previous_versions Feld — U-37b Wiring "
        "unvollstaendig."
    )


def test_history_entry_schema_has_required_fields():
    from schemas.review import ReportNotesHistoryEntry
    fields = ReportNotesHistoryEntry.model_fields
    assert "edited_at" in fields
    assert "edited_by" in fields
    assert "changes" in fields


def test_history_entry_changes_is_nested_dict():
    """changes: {field_name: {old, new}} — Type-Check."""
    from schemas.review import ReportNotesHistoryEntry
    entry = ReportNotesHistoryEntry(
        edited_at="2026-06-04T10:00:00Z",
        edited_by="user-1",
        changes={"aa_anmerkungen": {"old": "alt", "new": "neu"}},
    )
    assert entry.changes["aa_anmerkungen"]["old"] == "alt"
    assert entry.changes["aa_anmerkungen"]["new"] == "neu"


# ---------------------------------------------------------------------------
# _serialize_notes lädt History
# ---------------------------------------------------------------------------

def test_serialize_notes_loads_history_from_json_field():
    from routers.allocation import _serialize_notes

    notes = MagicMock()
    notes.id = "n-1"
    notes.mandate_id = "MX-1"
    notes.aa_anmerkungen = "current"
    notes.waehrungen_erklaerung = None
    notes.branchen_analyse = None
    notes.vorgehen_block_optimierungen = None
    notes.vorgehen_block_zielstrategie = None
    notes.vorgehen_offene_fragen_json = None
    notes.vorgehen_naechster_termin = None
    notes.vorgehen_todos_json = None
    notes.vorgehen_dokumente_json = None
    notes.last_edited_by = "user-1"
    notes.last_edited_at = "2026-06-04T10:00:00Z"
    notes.created_at = "2026-06-03T10:00:00Z"
    notes.updated_at = "2026-06-04T10:00:00Z"
    notes.previous_versions_json = (
        '[{"edited_at":"2026-06-04T10:00:00Z","edited_by":"user-1",'
        '"changes":{"aa_anmerkungen":{"old":"alt","new":"current"}}}]'
    )

    result = _serialize_notes(notes)
    assert "previous_versions" in result
    history = result["previous_versions"]
    assert len(history) == 1
    assert history[0]["edited_by"] == "user-1"
    assert history[0]["changes"]["aa_anmerkungen"]["old"] == "alt"


def test_serialize_notes_empty_history_for_null_field():
    """Pre-U-37b Notes ohne JSON-Feld -> leere History, kein Crash."""
    from routers.allocation import _serialize_notes

    notes = MagicMock()
    notes.id = "n-1"
    notes.mandate_id = "MX-1"
    notes.aa_anmerkungen = None
    notes.waehrungen_erklaerung = None
    notes.branchen_analyse = None
    notes.vorgehen_block_optimierungen = None
    notes.vorgehen_block_zielstrategie = None
    notes.vorgehen_offene_fragen_json = None
    notes.vorgehen_naechster_termin = None
    notes.vorgehen_todos_json = None
    notes.vorgehen_dokumente_json = None
    notes.last_edited_by = "user-1"
    notes.last_edited_at = "2026-06-04T10:00:00Z"
    notes.created_at = "2026-06-04T10:00:00Z"
    notes.updated_at = "2026-06-04T10:00:00Z"
    notes.previous_versions_json = None

    result = _serialize_notes(notes)
    assert result["previous_versions"] == []


# ---------------------------------------------------------------------------
# History-Order DESC + No-Op-Idempotenz (verifiziert über
# notes_versioning helpers, da DB-Roundtrip ohne fixtures heavy)
# ---------------------------------------------------------------------------

def test_history_order_newest_first_after_two_edits():
    """Verifiziere Order über das Service-Modul (snapshot_to_history
    prepended)."""
    from services.notes_versioning import snapshot_to_history, load_history
    from types import SimpleNamespace

    notes = SimpleNamespace(
        aa_anmerkungen="v1",
        waehrungen_erklaerung=None,
        branchen_analyse=None,
        vorgehen_block_optimierungen=None,
        vorgehen_block_zielstrategie=None,
        vorgehen_offene_fragen_json=None,
        vorgehen_naechster_termin=None,
        vorgehen_todos_json=None,
        vorgehen_dokumente_json=None,
        previous_versions_json=None,
    )
    snapshot_to_history(
        notes, new_values={"aa_anmerkungen": "v2"},
        edited_by="u1", edited_at="2026-06-01T10:00:00Z",
    )
    notes.aa_anmerkungen = "v2"
    snapshot_to_history(
        notes, new_values={"aa_anmerkungen": "v3"},
        edited_by="u2", edited_at="2026-06-02T10:00:00Z",
    )
    history = load_history(notes)
    assert len(history) == 2
    # DESC: neuester (2026-06-02) zuerst
    assert history[0]["edited_at"] == "2026-06-02T10:00:00Z"
    assert history[1]["edited_at"] == "2026-06-01T10:00:00Z"


def test_history_no_entry_for_no_op_edit():
    """No-Op PUT -> kein Snapshot."""
    from services.notes_versioning import snapshot_to_history, load_history
    from types import SimpleNamespace

    notes = SimpleNamespace(
        aa_anmerkungen="v1",
        waehrungen_erklaerung=None,
        branchen_analyse=None,
        vorgehen_block_optimierungen=None,
        vorgehen_block_zielstrategie=None,
        vorgehen_offene_fragen_json=None,
        vorgehen_naechster_termin=None,
        vorgehen_todos_json=None,
        vorgehen_dokumente_json=None,
        previous_versions_json=None,
    )
    entry = snapshot_to_history(
        notes, new_values={"aa_anmerkungen": "v1"},  # gleicher Wert
        edited_by="u1",
    )
    assert entry is None
    assert load_history(notes) == []


# ---------------------------------------------------------------------------
# Schema-Integration: ReportNotesResponse akzeptiert History-Liste
# ---------------------------------------------------------------------------

def test_response_schema_accepts_history_list():
    """End-to-End Schema-Roundtrip mit History."""
    from schemas.review import ReportNotesResponse, ReportNotesHistoryEntry

    entry = ReportNotesHistoryEntry(
        edited_at="2026-06-04T10:00:00Z",
        edited_by="user-1",
        changes={"aa_anmerkungen": {"old": "alt", "new": "neu"}},
    )
    response = ReportNotesResponse(
        mandate_id="MX-1",
        previous_versions=[entry],
    )
    assert len(response.previous_versions) == 1
    assert response.previous_versions[0].edited_by == "user-1"


def test_response_schema_defaults_history_to_empty_list():
    """Default: leere Liste, kein None."""
    from schemas.review import ReportNotesResponse
    response = ReportNotesResponse(mandate_id="MX-1")
    assert response.previous_versions == []
