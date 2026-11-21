"""Sprint U-FINMA-2.1 — Integritäts-Hash + Aufbewahrungs-Logik für AdvisoryLog.

FINMA / FIDLEG verlangt:
- Nachvollziehbares Audit-Log jedes Beratungsgesprächs.
- Manipulations-Schutz über kryptographischen Hash.
- Aufbewahrung bis 10 Jahre nach Ende des Mandats (H7 C-6; nie kuerzer
  als 10 Jahre nach dem Eintrag).

Zentrales Modul, damit die Hash-Berechnung deterministisch und an genau
**einer Stelle** gepflegt wird (vermeidet Hash-Drift zwischen verschiedenen
Code-Pfaden).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sa_text

# Aufbewahrungsfrist in Jahren. FIDLEG (Art. 15) verlangt die Dokumentation,
# nennt aber keine Frist; die 10 Jahre folgen aus der Beweissicherung
# (OR 127) bzw. GwG Art. 7 Abs. 3 und laufen ab Mandats-/Beziehungsende.
RETENTION_YEARS: int = 10


class AdvisoryLogDatetimeError(ValueError):
    """ADV-WORKFLOW-003 (Codex-Audit): wird geworfen, wenn `entry_datetime`
    NICHT als gueltiger ISO-Datums-/Zeitstempel interpretiert werden kann,
    oder wenn die daraus abgeleitete Aufbewahrungsfrist ausserhalb des
    darstellbaren Datumsbereichs liegen wuerde. Analog zu
    services.review_engine.ReviewAnchorDataError (REVIEW-STATE-001):
    Aufrufer muessen dies fail-closed behandeln (z.B. auf 409/422 mappen),
    NIE mehr stillschweigend auf `datetime.now()` zurueckfallen -- ein
    Beratungsprotokoll mit kaputtem Zeitstempel wuerde sonst mit einer
    plausibel wirkenden, aber fachlich falschen Aufbewahrungsfrist
    gespeichert. In der Praxis validiert schemas.review.AdvisoryLogCreate.
    entry_datetime bereits am API-Rand -- diese Funktion bleibt trotzdem
    strikt, falls sie je mit einem nicht schema-geprueften Wert aufgerufen
    wird."""


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
        # REC-007 (Codex-Audit 2026-08-25): cost_disclosure_given ist nur ein
        # Bool-Flag ("wurde ein Kostenausweis gezeigt"); die eigentlichen
        # gezeigten Kostenzahlen liegen in cost_disclosure_snapshot_json
        # (Bugfix 2026-08-07, CEO/CFO/CIO-Audit) und waren bislang NICHT im
        # Integritaets-Hash -- eine nachtraegliche Aenderung der ausgewiesenen
        # Kosten haette integrity_hash unveraendert gelassen. Migration fuer
        # bereits gespeicherte Zeilen: database.py::
        # migrate_advisory_log_hash_scheme_cost_disclosure_snapshot().
        "cost_disclosure_snapshot_json",
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

    Robust gegen Formate mit und ohne Z-Suffix. ADV-WORKFLOW-003
    (Codex-Audit): frueher bei jedem leeren oder ungueltigen Input auf
    `datetime.now()` zurueckgefallen (silent fallback) -- dieselbe
    Bugklasse wie services.review_engine._parse_iso_date() vor
    REVIEW-STATE-001. Wirft jetzt fail-closed `AdvisoryLogDatetimeError`
    statt zu raten, auch wenn die resultierende Aufbewahrungsfrist
    ausserhalb des darstellbaren Datumsbereichs liegen wuerde (z.B. bei
    einem entry_datetime im Jahr 9999).
    """
    raw = str(entry_datetime_iso or "").strip()
    if not raw:
        raise AdvisoryLogDatetimeError("entry_datetime darf nicht leer sein")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        base = datetime.fromisoformat(normalized)
    except ValueError:
        raise AdvisoryLogDatetimeError(
            f"entry_datetime ist kein gueltiges ISO-Datum/-Zeitstempel: {entry_datetime_iso!r}"
        ) from None
    # Für 10 Jahre: naive Jahr-Addition reicht (kein Schaltjahr-Issue, weil
    # wir nur Date-Teil persistieren).
    target_year = base.year + RETENTION_YEARS
    # Bei 29. Feb in Schaltjahr → fällt auf 28. Feb des Zieljahrs
    try:
        retain = base.replace(year=target_year)
    except ValueError:
        try:
            retain = base.replace(year=target_year, day=28)
        except ValueError:
            raise AdvisoryLogDatetimeError(
                f"entry_datetime {entry_datetime_iso!r} fuehrt zu einer "
                f"Aufbewahrungsfrist ausserhalb des darstellbaren "
                f"Datumsbereichs (Jahr {target_year})"
            ) from None
    return retain.date().isoformat()


def compute_relationship_retain_until(
    entry_datetime_iso: str, relationship_end_iso: str | None,
) -> str | None:
    """H7 C-6: Aufbewahrungsfrist eines Protokolleintrags ab Mandatsende.

    * Mandat offen (kein bzw. unlesbares Enddatum): ``None`` -- die Frist
      laeuft noch nicht; der Eintrag ist bis Mandatsende + 10 Jahre
      aufzubewahren (nie "abgelaufen").
    * Mandat beendet: spaeteres Datum von Mandatsende + 10 Jahre und
      Eintrag + 10 Jahre (ein Nachtrag nach Mandatsende verkuerzt nie).

    ``entry_datetime`` wird wie bisher fail-closed validiert.
    """
    floor = compute_retain_until(entry_datetime_iso)
    if not str(relationship_end_iso or "").strip():
        return None
    try:
        end = compute_retain_until(str(relationship_end_iso))
    except AdvisoryLogDatetimeError:
        return None
    return max(floor, end)


def extended_retain_until(
    current: str | None, entry_datetime_iso: str | None, relationship_end_iso: str | None,
) -> str | None:
    """Neue Frist bei Aenderung des Mandatsendes -- nie verkuerzend.

    Beendetes Mandat -> Maximum aus bisheriger Frist, Eintrag + 10 Jahre und
    Mandatsende + 10 Jahre. Ein unlesbarer Eintragszeitpunkt (Altdaten)
    zaehlt nicht als Untergrenze, verhindert die Berechnung aber nicht.
    Mandat (wieder) offen oder Ende unlesbar -> bisherige Frist bleibt
    unveraendert stehen (N-884-06: bei Wiedereroeffnung Mindestfrist, nie
    verworfen); ein nie beendetes Mandat behaelt ``None`` (Frist laeuft
    noch nicht).
    """
    kept = str(current).strip()[:10] if str(current or "").strip() else None
    if not str(relationship_end_iso or "").strip():
        return kept
    try:
        end = compute_retain_until(str(relationship_end_iso))
    except AdvisoryLogDatetimeError:
        return kept
    candidates = [end]
    try:
        candidates.append(compute_retain_until(str(entry_datetime_iso or "")))
    except AdvisoryLogDatetimeError:
        pass
    if str(current or "").strip():
        candidates.append(str(current).strip()[:10])
    return max(candidates)


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


# ---------------------------------------------------------------------------
# L2c (H-192): Pruefsummen-Schema der versiegelten Protokoll-Freitexte und
# Versiegelung des Altbestands.
#
# Bewusst ohne Projekt-Importe (wie der Rest dieses Moduls): die Funktion
# ``seal_legacy_protocol_texts`` laeuft im SQLite-Startpfad (database.py) und
# in Alembic ``e2b7c4d9a1f3``. Der Umschlag ist exakt das Format von
# ``services/pii_vault.py`` (``pii-sealed:v1:<key_id>:<Fernet-Token>``, ein
# Schluessel je Kunde in ``client_pii_keys``); ein Test prueft, dass
# ``pii_vault.reveal`` ihn oeffnet.
# ---------------------------------------------------------------------------
# ``decision`` und ``conflict_of_interest_disclosures.mitigation_action`` sind
# Kategorien (CHECK-Liste im Desktop-Schema ares_schema.sql), kein Freitext.
ADVISORY_LOG_SEALED_FIELDS = ("title", "description", "location", "participants_json")
CONFLICT_SEALED_FIELDS = ("description",)
REPORT_NOTE_FIELDS = (
    "aa_anmerkungen", "waehrungen_erklaerung", "branchen_analyse",
    "vorgehen_block_optimierungen", "vorgehen_block_zielstrategie",
    "vorgehen_offene_fragen_json", "vorgehen_naechster_termin",
    "vorgehen_todos_json", "vorgehen_dokumente_json",
)
REPORT_NOTE_VERSION_SEAL_FIELDS = (
    "id", "mandate_id", "client_id", "version", *REPORT_NOTE_FIELDS, "edited_by", "edited_at",
)
_ENVELOPE_PREFIX = "pii-sealed:v1:"
_ADVISORY_HASH_FIELDS = (
    "mandate_id", "advisor_id", "entry_type", "entry_datetime", "duration_minutes",
    "communication_channel", "language", "location", "title", "description", "decision",
    "status", "participants_json", "topics_json", "risk_warnings_given_json",
    "cost_disclosure_given", "cost_disclosure_snapshot_json", "conflict_disclosure_ids_json",
    "suitability_check_id", "recommendation_run_id", "client_signed", "client_signed_at", "version",
)


def protocol_text_seal(row_id, mandate_id, values: dict, fields) -> str:
    """Zeilensiegel fuer veraenderbare Zeilen mit versiegeltem Freitext
    (Interessenkonflikte): SHA-256 ueber ID, Mandat und die gespeicherten
    Umschlaege. Bleibt nach Crypto-Shred pruefbar."""
    parts = [str(row_id or ""), str(mandate_id or "")]
    parts += [f"{field}={'' if values.get(field) is None else values.get(field)}" for field in fields]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def report_note_version_hash(row: dict) -> str:
    """Siegel einer Berichtsnotiz-Version ueber die gespeicherten Umschlaege."""
    parts = [f"{key}={'' if row.get(key) is None else row.get(key)}" for key in REPORT_NOTE_VERSION_SEAL_FIELDS]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _is_sealed(value) -> bool:
    return isinstance(value, str) and value.startswith(_ENVELOPE_PREFIX)


def _plain(value) -> bool:
    return value is not None and value != "" and not _is_sealed(value)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class _LegacySealer:
    """Kundenschluessel wie services/pii_vault.py (gleiche Tabelle, gleiches
    Umschlagformat). Vernichteter Schluessel: kein Versiegeln (None)."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.keys: dict = {}

    def _row(self, client_id):
        return self.conn.execute(
            sa_text("SELECT key_id, key_material FROM client_pii_keys WHERE client_id = :c"), {"c": client_id},
        ).first()

    def key(self, client_id):
        if not client_id:
            return None
        if client_id in self.keys:
            return self.keys[client_id]
        row = self._row(client_id)
        if row is None:
            self.conn.execute(
                sa_text("INSERT INTO client_pii_keys (client_id, key_id, key_material, created_at) "
                        "VALUES (:c, :k, :m, :now)"),
                {"c": client_id, "k": str(uuid.uuid4()), "m": Fernet.generate_key().decode("ascii"),
                 "now": _now_utc()},
            )
            row = self._row(client_id)
        self.keys[client_id] = (str(row[0]), str(row[1])) if row is not None and row[1] is not None else None
        return self.keys[client_id]

    def seal(self, client_id, value):
        if value is None or value == "" or _is_sealed(value):
            return value
        key_id, material = self.key(client_id)
        token = Fernet(material.encode("ascii")).encrypt(str(value).encode("utf-8")).decode("ascii")
        return f"{_ENVELOPE_PREFIX}{key_id}:{token}"


def seal_legacy_protocol_texts(conn) -> dict:
    """Versiegelt Altzeilen der Protokoll-Freitexte (idempotent).

    * advisory_log: nur wenn das alte Siegel zum Klartext passt (oder keines
      existiert); dann ``integrity_hash`` neu ueber die Umschlaege. Passt es
      nicht, bleibt die Zeile im Klartext und «verändert» (KN9a sperrt, die
      DSG-Loeschung meldet sie mit UNSEALED_LEGACY_ROWS) -- ein Neu-Siegeln
      wuerde die Manipulation verdecken.
    * conflict_of_interest_disclosures: versiegelt + ``text_seal``.
    * mandate_report_notes: Klartext der Kopfzeile wird Version 1
      (``mandate_report_note_versions``), Kopffelder geleert; die Historie
      vor L2c (``previous_versions_json``) als Ganzes versiegelt.
    * Kunden mit vernichtetem Schluessel (DSG-geloescht) werden
      uebersprungen; Reste meldet die Loeschung.
    """
    tables = set(sa_inspect(conn).get_table_names())
    counts = {"advisory_log_sealed": 0, "advisory_log_skipped_tampered": 0, "conflicts_sealed": 0,
              "report_notes_versioned": 0, "report_history_sealed": 0, "skipped_no_key": 0}
    if "mandates" not in tables or "client_pii_keys" not in tables:
        return counts
    mandates = {str(r[0]): (str(r[1]) if r[1] else None, r[2])
                for r in conn.execute(sa_text("SELECT id, client_id, tenant_id FROM mandates")).all()}
    sealer = _LegacySealer(conn)

    def _client(mandate_id):
        client_id = mandates.get(str(mandate_id), (None, None))[0]
        return client_id if sealer.key(client_id) is not None else None

    if "advisory_log" in tables:
        for row in conn.execute(sa_text("SELECT * FROM advisory_log")).mappings().all():
            if not any(_plain(row.get(f)) for f in ADVISORY_LOG_SEALED_FIELDS):
                continue
            client_id = _client(row["mandate_id"])
            if client_id is None:
                counts["skipped_no_key"] += 1
                continue
            payload = {k: row.get(k) for k in _ADVISORY_HASH_FIELDS}
            stored = row.get("integrity_hash")
            if stored and compute_integrity_hash(payload=payload) != stored:
                counts["advisory_log_skipped_tampered"] += 1
                continue
            sealed = {f: sealer.seal(client_id, row.get(f)) for f in ADVISORY_LOG_SEALED_FIELDS}
            payload.update(sealed)
            conn.execute(
                sa_text("UPDATE advisory_log SET " + ", ".join(f"{f} = :{f}" for f in sealed)
                        + ", integrity_hash = :h WHERE id = :id"),
                {**sealed, "h": compute_integrity_hash(payload=payload) if stored else None, "id": row["id"]},
            )
            counts["advisory_log_sealed"] += 1

    if "conflict_of_interest_disclosures" in tables:
        for row in conn.execute(sa_text("SELECT * FROM conflict_of_interest_disclosures")).mappings().all():
            if row.get("text_seal") or not any(_plain(row.get(f)) for f in CONFLICT_SEALED_FIELDS):
                continue
            client_id = _client(row["mandate_id"])
            if client_id is None:
                counts["skipped_no_key"] += 1
                continue
            sealed = {f: sealer.seal(client_id, row.get(f)) for f in CONFLICT_SEALED_FIELDS}
            conn.execute(
                sa_text("UPDATE conflict_of_interest_disclosures SET description = :description, "
                        "text_seal = :s WHERE id = :id"),
                {**sealed, "s": protocol_text_seal(row["id"], row["mandate_id"], sealed, CONFLICT_SEALED_FIELDS),
                 "id": row["id"]},
            )
            counts["conflicts_sealed"] += 1

    if "mandate_report_notes" in tables and "mandate_report_note_versions" in tables:
        for row in conn.execute(sa_text("SELECT * FROM mandate_report_notes")).mappings().all():
            fields_plain = any(_plain(row.get(f)) for f in REPORT_NOTE_FIELDS)
            history_plain = _plain(row.get("previous_versions_json"))
            if not (fields_plain or history_plain):
                continue
            client_id = _client(row["mandate_id"])
            if client_id is None:
                counts["skipped_no_key"] += 1
                continue
            if fields_plain:
                existing = conn.execute(
                    sa_text("SELECT COUNT(*) FROM mandate_report_note_versions WHERE mandate_id = :m"),
                    {"m": row["mandate_id"]},
                ).scalar()
                if not existing:
                    version = {
                        "id": str(uuid.uuid4()), "mandate_id": str(row["mandate_id"]), "client_id": client_id,
                        "version": 1, **{f: sealer.seal(client_id, row.get(f)) for f in REPORT_NOTE_FIELDS},
                        "edited_by": row["last_edited_by"], "edited_at": row["last_edited_at"],
                    }
                    version["content_hash"] = report_note_version_hash(version)
                    version["tenant_id"] = mandates.get(str(row["mandate_id"]), (None, None))[1]
                    conn.execute(
                        sa_text(f"INSERT INTO mandate_report_note_versions ({', '.join(version)}) "
                                f"VALUES ({', '.join(':' + k for k in version)})"),
                        version,
                    )
                    counts["report_notes_versioned"] += 1
                conn.execute(
                    sa_text("UPDATE mandate_report_notes SET "
                            + ", ".join(f"{f} = NULL" for f in REPORT_NOTE_FIELDS) + " WHERE id = :id"),
                    {"id": row["id"]},
                )
            if history_plain:
                conn.execute(
                    sa_text("UPDATE mandate_report_notes SET previous_versions_json = :h WHERE id = :id"),
                    {"h": sealer.seal(client_id, row["previous_versions_json"]), "id": row["id"]},
                )
                counts["report_history_sealed"] += 1
    return counts


def count_sealed_protocol_rows(conn) -> dict:
    """Downgrade-Sperre: Zeilen, die nur mit Kundenschluessel lesbar sind."""
    tables = set(sa_inspect(conn).get_table_names())
    found: dict = {}
    for table, fields in (
        ("advisory_log", ADVISORY_LOG_SEALED_FIELDS),
        ("conflict_of_interest_disclosures", CONFLICT_SEALED_FIELDS),
        ("mandate_report_notes", (*REPORT_NOTE_FIELDS, "previous_versions_json")),
    ):
        if table not in tables:
            continue
        clause = " OR ".join(f"{f} LIKE :p" for f in fields)
        n = conn.execute(sa_text(f"SELECT COUNT(*) FROM {table} WHERE {clause}"),
                         {"p": _ENVELOPE_PREFIX + "%"}).scalar()
        if n:
            found[table] = int(n)
    if "mandate_report_note_versions" in tables:
        n = conn.execute(sa_text("SELECT COUNT(*) FROM mandate_report_note_versions")).scalar()
        if n:
            found["mandate_report_note_versions"] = int(n)
    return found
