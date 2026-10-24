"""Sprint U-37 (Roadmap-Punkt 37, 2026-06-03): MandateReportNotes
Versionierungs-Log Tests.

Pre-U-37
--------
MandateReportNotes hatte nur Audit-Anchor (last_edited_by/_at) plus
AuditLog-Eintrag pro PUT. FINMA-relevant ist WAS zu welchem Zeitpunkt
im Bericht stand — der aktuelle Stand alleine erfuellt das nicht.

Post-U-37
---------
- previous_versions_json Spalte (TEXT) idempotent ergaenzt via
  ensure_runtime_columns
- snapshot_to_history / compute_changes / load_history Helper in
  services/notes_versioning
- put_report_notes wired: snapshot vor Update bei jeder Aenderung
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.notes_versioning import (  # noqa: E402
    NOTES_VERSIONED_FIELDS,
    _normalize,
    _parse_history,
    compute_changes,
    load_history,
    snapshot_to_history,
)


def _notes_stub(**overrides):
    """SimpleNamespace mit allen versionierten Feldern + history."""
    base = {f: None for f in NOTES_VERSIONED_FIELDS}
    base["previous_versions_json"] = None
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# NOTES_VERSIONED_FIELDS Constant
# ---------------------------------------------------------------------------

def test_versioned_fields_include_all_text_overrides():
    """Wenn jemand ein Feld zur Tabelle hinzufuegt aber nicht zur
    Konstanten -> History wird inkonsistent."""
    assert "aa_anmerkungen" in NOTES_VERSIONED_FIELDS
    assert "waehrungen_erklaerung" in NOTES_VERSIONED_FIELDS
    assert "branchen_analyse" in NOTES_VERSIONED_FIELDS
    assert "vorgehen_block_optimierungen" in NOTES_VERSIONED_FIELDS
    assert "vorgehen_block_zielstrategie" in NOTES_VERSIONED_FIELDS
    assert "vorgehen_offene_fragen_json" in NOTES_VERSIONED_FIELDS
    assert "vorgehen_naechster_termin" in NOTES_VERSIONED_FIELDS
    assert "vorgehen_todos_json" in NOTES_VERSIONED_FIELDS
    assert "vorgehen_dokumente_json" in NOTES_VERSIONED_FIELDS


def test_versioned_fields_excludes_audit_anchors():
    """last_edited_*, updated_at sind Meta — KEINE Versionierung."""
    assert "last_edited_by" not in NOTES_VERSIONED_FIELDS
    assert "last_edited_at" not in NOTES_VERSIONED_FIELDS
    assert "updated_at" not in NOTES_VERSIONED_FIELDS
    assert "created_at" not in NOTES_VERSIONED_FIELDS


# ---------------------------------------------------------------------------
# _normalize + _parse_history
# ---------------------------------------------------------------------------

def test_normalize_none_and_empty_equivalent():
    """None == "" == "   " als 'leer' behandelt."""
    assert _normalize(None) == _normalize("")
    assert _normalize("") == _normalize("   ")


def test_normalize_preserves_real_content():
    assert _normalize("hello") == "hello"


def test_parse_history_handles_none():
    assert _parse_history(None) == []


def test_parse_history_handles_empty_string():
    assert _parse_history("") == []


def test_parse_history_handles_valid_json():
    raw = '[{"edited_at": "2026-06-03T10:00:00Z", "edited_by": "u1"}]'
    parsed = _parse_history(raw)
    assert len(parsed) == 1
    assert parsed[0]["edited_by"] == "u1"


def test_parse_history_invalid_json_returns_empty():
    assert _parse_history("not json") == []


def test_parse_history_non_list_returns_empty():
    """Wenn jemand ein Dict in das Feld schreibt: defensive []."""
    assert _parse_history('{"key": "value"}') == []


# ---------------------------------------------------------------------------
# compute_changes
# ---------------------------------------------------------------------------

def test_compute_changes_no_diff():
    old = {"aa_anmerkungen": "same"}
    new = {"aa_anmerkungen": "same"}
    assert compute_changes(old, new) == {}


def test_compute_changes_single_field():
    old = {"aa_anmerkungen": "old text"}
    new = {"aa_anmerkungen": "new text"}
    changes = compute_changes(old, new)
    assert changes == {"aa_anmerkungen": {"old": "old text", "new": "new text"}}


def test_compute_changes_multiple_fields():
    old = {f: None for f in NOTES_VERSIONED_FIELDS}
    new = {
        "aa_anmerkungen": "a",
        "branchen_analyse": "b",
    }
    changes = compute_changes(old, new)
    assert "aa_anmerkungen" in changes
    assert "branchen_analyse" in changes
    assert len(changes) == 2


def test_compute_changes_none_to_empty_string_no_change():
    """None -> "" zaehlt nicht als Aenderung (semantisch leer)."""
    old = {"aa_anmerkungen": None}
    new = {"aa_anmerkungen": ""}
    assert compute_changes(old, new) == {}


def test_compute_changes_field_missing_from_new_no_change():
    """Wenn new dict ein Feld nicht enthaelt -> kein Change Eintrag."""
    old = {"aa_anmerkungen": "x", "branchen_analyse": "y"}
    new = {"aa_anmerkungen": "x"}  # branchen_analyse fehlt
    changes = compute_changes(old, new)
    assert changes == {}


# ---------------------------------------------------------------------------
# snapshot_to_history
# ---------------------------------------------------------------------------

def test_snapshot_no_change_returns_none():
    """No-op Update -> kein History-Eintrag (idempotent)."""
    notes = _notes_stub(aa_anmerkungen="same")
    entry = snapshot_to_history(
        notes,
        new_values={"aa_anmerkungen": "same"},
        edited_by="u1",
    )
    assert entry is None
    assert notes.previous_versions_json is None


def test_snapshot_first_edit_initializes_history():
    notes = _notes_stub(aa_anmerkungen="old")
    entry = snapshot_to_history(
        notes,
        new_values={"aa_anmerkungen": "new"},
        edited_by="u1",
        edited_at="2026-06-03T10:00:00Z",
    )
    assert entry is not None
    history = json.loads(notes.previous_versions_json)
    assert len(history) == 1
    assert history[0]["edited_by"] == "u1"
    assert history[0]["edited_at"] == "2026-06-03T10:00:00Z"
    assert history[0]["changes"]["aa_anmerkungen"]["old"] == "old"
    assert history[0]["changes"]["aa_anmerkungen"]["new"] == "new"


def test_snapshot_prepends_newest_first():
    """Mehrfache Edits: neueste ist Index 0 (chronologisch DESC)."""
    notes = _notes_stub(aa_anmerkungen="v1")
    snapshot_to_history(
        notes, new_values={"aa_anmerkungen": "v2"},
        edited_by="u1", edited_at="2026-06-01T10:00:00Z",
    )
    notes.aa_anmerkungen = "v2"  # Simulate Update
    snapshot_to_history(
        notes, new_values={"aa_anmerkungen": "v3"},
        edited_by="u2", edited_at="2026-06-02T10:00:00Z",
    )
    history = json.loads(notes.previous_versions_json)
    assert len(history) == 2
    assert history[0]["edited_at"] == "2026-06-02T10:00:00Z"
    assert history[1]["edited_at"] == "2026-06-01T10:00:00Z"


def test_snapshot_captures_multiple_field_changes():
    notes = _notes_stub(
        aa_anmerkungen="old_aa",
        branchen_analyse="old_branchen",
    )
    snapshot_to_history(
        notes,
        new_values={
            "aa_anmerkungen": "new_aa",
            "branchen_analyse": "new_branchen",
        },
        edited_by="u1",
    )
    history = json.loads(notes.previous_versions_json)
    changes = history[0]["changes"]
    assert "aa_anmerkungen" in changes
    assert "branchen_analyse" in changes


def test_snapshot_ignores_unchanged_fields():
    notes = _notes_stub(
        aa_anmerkungen="kept",
        branchen_analyse="old",
    )
    snapshot_to_history(
        notes,
        new_values={
            "aa_anmerkungen": "kept",  # gleich
            "branchen_analyse": "new",  # geaendert
        },
        edited_by="u1",
    )
    history = json.loads(notes.previous_versions_json)
    changes = history[0]["changes"]
    assert "aa_anmerkungen" not in changes
    assert "branchen_analyse" in changes


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------

def test_load_history_empty_state():
    notes = _notes_stub()
    assert load_history(notes) == []


def test_load_history_round_trip():
    notes = _notes_stub(aa_anmerkungen="old")
    snapshot_to_history(
        notes, new_values={"aa_anmerkungen": "new"},
        edited_by="u1", edited_at="2026-06-03T10:00:00Z",
    )
    history = load_history(notes)
    assert len(history) == 1
    assert history[0]["edited_by"] == "u1"


# ---------------------------------------------------------------------------
# Schema-Integration: previous_versions_json in MandateReportNotes
# ---------------------------------------------------------------------------

def test_model_has_previous_versions_json_column():
    from models.review import MandateReportNotes
    cols = {c.name for c in MandateReportNotes.__table__.columns}
    assert "previous_versions_json" in cols


def test_ensure_runtime_columns_includes_notes_versioning():
    """database.py ensure_runtime_columns deklariert die Spalte
    fuer idempotenten Runtime-Add (Drift-Schutz)."""
    import inspect
    from database import ensure_runtime_columns
    source = inspect.getsource(ensure_runtime_columns)
    assert "mandate_report_notes" in source
    assert "previous_versions_json" in source
