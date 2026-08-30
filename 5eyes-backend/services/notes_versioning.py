"""Sprint U-37 (2026-06-03): Notes-Versionierungs-Log.

Hintergrund
-----------
MandateReportNotes hatte pre-U-37 nur einen Audit-Anchor (last_edited_by
+ last_edited_at) plus AuditLog-Eintrag pro PUT. FINMA-relevant ist
aber WAS zu welchem Zeitpunkt im Bericht stand — der aktuelle Stand
allein erfuellt das nicht.

U-37 ergaenzt previous_versions_json als append-only JSON-Array:
  [{
    'edited_at': ISO-UTC,
    'edited_by': user_id,
    'changes': {
       'aa_anmerkungen': {'old': str|null, 'new': str|null},
       ...
    }
  }, ...]

Bei jedem PUT report-notes wird VOR dem Update ein Snapshot der
betroffenen Felder angelegt. Lese-Pfad: aggregator/endpoint kann
JSON parsen + chronologisch anzeigen.

Pattern-Begrenzung
------------------
Append-only ohne Compaction. Bei Notes mit hunderten Edits wird
das JSON gross. Compaction (z.B. nur letzte N Versionen behalten)
ist Folge-Sprint. Default: alle Versionen.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

# Felder von MandateReportNotes die versioniert werden.
# Audit-Anchor (last_edited_*, updated_at) NICHT enthalten — die sind
# triviale Metadata.
NOTES_VERSIONED_FIELDS = (
    "aa_anmerkungen",
    "waehrungen_erklaerung",
    "branchen_analyse",
    "vorgehen_block_optimierungen",
    "vorgehen_block_zielstrategie",
    "vorgehen_offene_fragen_json",
    "vorgehen_naechster_termin",
    "vorgehen_todos_json",
    "vorgehen_dokumente_json",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_history(raw: Any) -> list[dict]:
    """Liest previous_versions_json defensiv. Bei Schema-Drift -> []."""
    if raw in (None, "", b""):
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


def compute_changes(
    old_values: dict[str, Any],
    new_values: dict[str, Any],
    *,
    fields: Iterable[str] = NOTES_VERSIONED_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Liefert Dict {field: {old, new}} fuer Felder die sich aendern.

    None == "" werden als equal behandelt (Triggert keine Change-Entry)
    weil PUT mit "" das Feld leerraeumt — alter Wert war NULL == kein
    Berater-Text == leer.
    """
    changes: dict[str, dict[str, Any]] = {}
    for field in fields:
        old = old_values.get(field)
        new = new_values.get(field, old)  # wenn nicht im new-Dict: kein Change
        if _normalize(old) != _normalize(new):
            changes[field] = {"old": old, "new": new}
    return changes


def _normalize(v: Any) -> Any:
    """Treat None and empty-string as same for diff-purposes."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s == "" else v


def snapshot_to_history(
    notes_obj: Any,
    *,
    new_values: dict[str, Any],
    edited_by: str,
    edited_at: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Mutiert notes_obj.previous_versions_json: prepended snapshot der
    OLD-Werte fuer Felder die sich aendern.

    Returns die snapshot-Entry oder None wenn nichts sich aendert
    (idempotent — kein Eintrag bei No-Op-PUT).
    """
    old_values = {
        f: getattr(notes_obj, f, None) for f in NOTES_VERSIONED_FIELDS
    }
    changes = compute_changes(old_values, new_values)
    if not changes:
        return None
    entry = {
        "edited_at": edited_at or _now_iso(),
        "edited_by": edited_by,
        "changes": changes,
    }
    history = _parse_history(getattr(notes_obj, "previous_versions_json", None))
    history.insert(0, entry)  # neueste vorn (chronologisch DESC)
    notes_obj.previous_versions_json = json.dumps(history)
    return entry


def load_history(notes_obj: Any) -> list[dict[str, Any]]:
    """Liest die History eines Notes-Objects."""
    return _parse_history(getattr(notes_obj, "previous_versions_json", None))


# RESOURCE-002 Teil 2 (Codex-Audit 2026-08-27): "Append-only ohne Compaction"
# (siehe Modul-Docstring) bedeutet die Historie waechst unbegrenzt -- GET/PUT
# lieferten bisher IMMER die volle Liste aus, was bei Mandaten mit vielen
# Edits wiederholte O(Historiengroesse) Response-/Parse-Arbeit verursacht.
# load_history_page() paginiert (neueste zuerst, wie load_history()), OHNE
# etwas aus der DB zu loeschen oder unerreichbar zu machen -- die volle
# Historie bleibt ueber offset weiterhin abrufbar (kein stilles Abschneiden
# von Beweisdaten, siehe Fixvertrag Punkt 4).
def load_history_page(
    notes_obj: Any, *, limit: int = 20, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Liest eine Seite der History. Gibt (page, total) zurueck."""
    history = _parse_history(getattr(notes_obj, "previous_versions_json", None))
    total = len(history)
    return history[offset:offset + limit], total
