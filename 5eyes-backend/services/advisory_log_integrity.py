"""Sprint U-FINMA-2.1 — Integritäts-Hash + Aufbewahrungs-Logik für AdvisoryLog.

FINMA / FIDLEG verlangt:
- Nachvollziehbares Audit-Log jedes Beratungsgesprächs.
- Manipulations-Schutz über kryptographischen Hash.
- Aufbewahrung 10 Jahre nach Termin.

Zentrales Modul, damit die Hash-Berechnung deterministisch und an genau
**einer Stelle** gepflegt wird (vermeidet Hash-Drift zwischen verschiedenen
Code-Pfaden).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

# Aufbewahrungs-Pflicht in Jahren (FIDLEG Art. 17)
RETENTION_YEARS: int = 10


def compute_integrity_hash(*, payload: dict) -> str:
    """SHA256 über die FINMA-relevanten Eintragsfelder.

    Die Felder-Auswahl ist die **Inhaltsfingerprint** — Änderungen an
    `description` / `decision` / `risk_warnings_given_json` etc. erzeugen
    einen neuen Hash. Felder wie `id`, `created_at`, `updated_at`,
    `last_read_at` sind NICHT Teil des Hash (Metadaten, nicht Inhalt).

    Parameter
    ---------
    payload
        Dict mit allen unten gelisteten Schlüsseln. Fehlende Schlüssel
        werden als leerer String behandelt.
    """
    # Fester Feld-Order — Reihenfolge ist Teil des Hash-Vertrags und darf
    # NIE geändert werden ohne Hash-Migrations-Strategie.
    fields = [
        "mandate_id",
        "advisor_id",
        "entry_type",
        "entry_datetime",
        "duration_minutes",
        "communication_channel",
        "language",
        "location",
        "title",
        "description",
        "decision",
        "status",
        "participants_json",
        "topics_json",
        "risk_warnings_given_json",
        "cost_disclosure_given",
        "conflict_disclosure_ids_json",
        "suitability_check_id",
        "recommendation_run_id",
        "client_signed",
        "client_signed_at",
        "version",
    ]
    parts = []
    for key in fields:
        value = payload.get(key)
        if value is None:
            parts.append("")
        elif isinstance(value, bool):
            parts.append("1" if value else "0")
        else:
            parts.append(str(value))
    text = "\x1f".join(parts)  # Unit-Separator zwischen Feldern
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_retain_until(entry_datetime_iso: str) -> str:
    """`entry_datetime` + 10 Jahre als ISO-Date (YYYY-MM-DD).

    Robust gegen Formate mit und ohne Z-Suffix. Bei ungültigem Input wird
    `today + 10 Jahre` zurückgegeben (defensiver Fallback statt Crash).
    """
    if not entry_datetime_iso:
        base = datetime.now(timezone.utc)
    else:
        normalized = str(entry_datetime_iso).replace("Z", "+00:00")
        try:
            base = datetime.fromisoformat(normalized)
        except ValueError:
            base = datetime.now(timezone.utc)
    # Für 10 Jahre: naive Jahr-Addition reicht (kein Schaltjahr-Issue, weil
    # wir nur Date-Teil persistieren).
    target_year = base.year + RETENTION_YEARS
    # Bei 29. Feb in Schaltjahr → fällt auf 28. Feb des Zieljahrs
    try:
        retain = base.replace(year=target_year)
    except ValueError:
        retain = base.replace(year=target_year, day=28)
    return retain.date().isoformat()


def verify_integrity_hash(*, payload: dict, expected_hash: str) -> bool:
    """True wenn der Hash des Payload identisch ist zum gespeicherten Hash.

    Wird beim Read genutzt um Manipulation zu erkennen (FINMA-Audit).
    """
    actual = compute_integrity_hash(payload=payload)
    # Konstante-Zeit-Vergleich gegen Timing-Attacks (überschießend hier,
    # aber gute Hygiene)
    return _constant_time_eq(actual, str(expected_hash or ""))


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0
