"""PII-Vault: Crypto-Shredding fuer Freitexte in append-only Evidence-Tabellen
(DSG-ERASURE-APPEND-ONLY-001, 2026-10-21).

Problem
-------
risk_override_decisions (RiskOverrideDecisionV1) und risk_profile_signoffs
(RiskProfileSignoffV1) verbieten UPDATE/DELETE per Trigger und binden ihren
Inhalt per SHA-256. Ihre Freitexte (Override-Begruendung ``reason``,
Signatur-Notiz ``note``) koennen Personendaten enthalten ("Max Muster hat
... bestaetigt", Familienumstaende, Gesundheit, Erbschaft). Im Klartext
gespeichert -- und als replaybarer Snapshot zusaetzlich im ebenfalls
unveraenderlichen audit_log -- waeren sie nach einem DSG-Art.-32-
Loeschbegehren weder loesch- noch redigierbar, ohne die Unveraenderlichkeit
aufzuweichen.

Loesung (Crypto-Shredding)
--------------------------
* Freitext wird VOR dem Schreiben mit einem zufaelligen Schluessel pro
  Kunde (Tabelle ``client_pii_keys``) per Fernet (AES-128-CBC + HMAC-
  SHA256, authentisiert) versiegelt. In der append-only Zeile und im Audit-
  Snapshot steht nur der Umschlag ``pii-sealed:v1:<key_id>:<token>``.
* Der Record-Hash (decision_hash/signoff_hash) bindet den UMSCHLAG. Er bleibt
  deshalb auch nach der Vernichtung des Schluessels verifizierbar: die
  Zeile ist nachweislich unveraendert; nur ihr Freitext ist nicht mehr
  lesbar. Vor der Vernichtung belegen Fernet-HMAC + Record-Hash zusammen
  die Authentizitaet des Klartexts.
* Die Erasure (services/client_erasure.py) vernichtet den Schluessel
  (``shred_client_keys``): key_material -> NULL, shredded_at gesetzt. Der
  DB-Trigger erlaubt NUR diese Richtung (kein Ersetzen, kein Wiederbeleben,
  kein DELETE) -- der Tombstone belegt die Vernichtung und laesst
  ``seal_for_client`` fuer einen geloeschten Kunden fail-closed scheitern.
* Ein Restore einer aelteren Sicherung bringt den Schluessel zurueck; das
  Erasure-Ledger (PRIV-005, services/erasure_restore.py::
  reapply_erasures_after_restore) fuehrt die Erasure und damit das Shredding
  nach jedem Restore erneut aus.

Bewusste Grenzen (dokumentiert, nicht still)
--------------------------------------------
* Der Schluessel liegt in derselben DB (Schutz at rest: SQLCipher/Host-
  Verschluesselung). Ziel ist Loeschbarkeit, nicht Zugriffsschutz gegen
  DB-Leser -- ein Wrapping mit dem Tenant-KEK (services/tenant_crypto.py)
  waere ein Ops-/Owner-Entscheid (neuer harter Betriebs-Abhaengigkeit).
* Forensische Reste: SQLite-Freelist/WAL bzw. PostgreSQL-Dead-Tuples bis
  VACUUM sowie bereits gezogene Backups/Exporte enthalten den Schluessel
  weiter, bis sie rotieren (gleiche offene Ops-Richtlinie wie fuer alle
  Tier-A-Daten, docs/planning/2026-08-15-dsg-art32-erasure-workflow.md
  Punkt 5). SQLite: die Erasure setzt PRAGMA secure_delete=ON.
* Altbestand: Zeilen, die vor diesem Fix im Klartext geschrieben wurden,
  bleiben unveraendert (Trigger); die Erasure zaehlt und meldet sie
  (``count_unsealed_rows``) -- Owner-/Legal-Entscheid.
"""
from __future__ import annotations

import threading
import weakref
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, inspect as sa_inspect, text
from sqlalchemy.orm import Session

ENVELOPE_PREFIX = "pii-sealed:v1:"

# Append-only Tabellen mit versiegeltem Freitext: (Tabelle, Freitextspalte).
SEALED_APPEND_ONLY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("risk_override_decisions", "reason"),
    ("risk_profile_signoffs", "note"),
    # DSG-ERASURE-NEW-EVIDENCE-001 (Nachzug, 2026-10-23):
    ("goal_revision_decisions", "reason"),
    ("financial_coverage_attestations", "household_persons_json"),
    ("financial_coverage_attestations", "note"),
    # E1 Nachhaltigkeitspraeferenzen: Begruendung eines Kundenverzichts.
    ("investment_preference_decisions", "waiver_reason_sealed"),
    # L2b (H-190): Gruende der Empfehlung (Art. 15 FIDLEG, P-1).
    ("advice_rationales", "client_needs"),
    ("advice_rationales", "recommendation_reasons"),
)


# L2c (H-192): veraenderbare bzw. versionierte Tabellen mit versiegeltem
# Freitext (Protokoll-Freitexte). Zusammen mit SEALED_APPEND_ONLY_COLUMNS die
# Grundlage von ``count_unsealed_rows`` (Altbestand im Klartext).
SEALED_PROTOCOL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("advisory_log", "title"),
    ("advisory_log", "description"),
    ("advisory_log", "location"),
    ("advisory_log", "participants_json"),
    ("conflict_of_interest_disclosures", "description"),
    *(("mandate_report_notes", c) for c in (
        "aa_anmerkungen", "waehrungen_erklaerung", "branchen_analyse",
        "vorgehen_block_optimierungen", "vorgehen_block_zielstrategie",
        "vorgehen_offene_fragen_json", "vorgehen_naechster_termin", "vorgehen_todos_json",
        "vorgehen_dokumente_json", "previous_versions_json",
    )),
    *(("mandate_report_note_versions", c) for c in (
        "aa_anmerkungen", "waehrungen_erklaerung", "branchen_analyse",
        "vorgehen_block_optimierungen", "vorgehen_block_zielstrategie",
        "vorgehen_offene_fragen_json", "vorgehen_naechster_termin", "vorgehen_todos_json",
        "vorgehen_dokumente_json",
    )),
)


class PiiVaultError(RuntimeError):
    """Versiegeln nicht moeglich (kein Kunde, Schluessel vernichtet)."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _fernet(key_material: str):
    from cryptography.fernet import Fernet

    return Fernet(key_material.encode("ascii"))


def is_sealed(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(ENVELOPE_PREFIX)


def _key_row(db: Session, client_id: str):
    return db.execute(
        text(
            "SELECT key_id, key_material, shredded_at FROM client_pii_keys "
            "WHERE client_id = :client_id"
        ),
        {"client_id": client_id},
    ).first()


def _ensure_key(db: Session, client_id: str):
    row = _key_row(db, client_id)
    if row is not None:
        return row
    from cryptography.fernet import Fernet

    from database import new_uuid

    # ON CONFLICT DO NOTHING (SQLite >= 3.24 und PostgreSQL): zwei parallele
    # erste Versiegelungen fuer denselben Kunden erzeugen genau einen Schluessel.
    db.execute(
        text(
            "INSERT INTO client_pii_keys (client_id, key_id, key_material, created_at) "
            "VALUES (:client_id, :key_id, :key_material, :now) "
            "ON CONFLICT (client_id) DO NOTHING"
        ),
        {
            "client_id": client_id,
            "key_id": new_uuid(),
            "key_material": Fernet.generate_key().decode("ascii"),
            "now": _now(),
        },
    )
    return _key_row(db, client_id)


def seal_for_client(db: Session, client_id: str | None, plaintext: Any) -> str | None:
    """Versiegelt ``plaintext`` mit dem Schluessel des Kunden.

    None/leer bleibt None/leer (nichts zu schuetzen). Bereits versiegelte
    Werte werden unveraendert zurueckgegeben. Fail-closed: ohne Kunde oder
    mit vernichtetem Schluessel (DSG-geloeschter Kunde) -> PiiVaultError,
    es wird NIE stillschweigend Klartext geschrieben."""
    if plaintext is None:
        return None
    value = str(plaintext)
    if value == "" or is_sealed(value):
        return value
    if not client_id:
        raise PiiVaultError("Freitext kann ohne Kunden-ID nicht versiegelt werden.")
    row = _ensure_key(db, client_id)
    if row is None or row.key_material is None:
        raise PiiVaultError(
            "Die Personendaten dieses Kunden wurden nach DSG Art. 32 geloescht "
            "(Schluessel vernichtet) -- neuer Freitext wird nicht gespeichert."
        )
    token = _fernet(row.key_material).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{ENVELOPE_PREFIX}{row.key_id}:{token}"


# C-L2D-01 (Codex-Abnahme 26.11.2026): Alle lebenden Leser des Prozesses. Eine
# committete Schluesselvernichtung leert ihre Caches (``_invalidate_all_readers``),
# auch in anderen Sessions desselben Prozesses.
_LIVE_READERS: "weakref.WeakSet[KeyReader]" = weakref.WeakSet()
_LIVE_READERS_LOCK = threading.Lock()
_SESSION_HOOK_FLAG = "pii_vault_key_reader_hooks"
_SHRED_HOOK_FLAG = "pii_vault_shred_commit_hook"


def _readers(session: Session | None = None) -> list["KeyReader"]:
    with _LIVE_READERS_LOCK:
        readers = list(_LIVE_READERS)
    return [r for r in readers if session is None or r.db is session]


def _invalidate_readers_of(session: Session) -> None:
    for reader in _readers(session):
        reader._invalidate()


def _invalidate_all_readers() -> None:
    for reader in _readers():
        reader._invalidate()


def _install_session_hooks(db: Session) -> None:
    """Der Cache eines Lesers gilt hoechstens bis zum Ende der Transaktion, in
    der er gefuellt wurde (auf PostgreSQL: so lange, wie die FOR-SHARE-Sperre
    der Schluesselzeile gehalten wird). Danach liest er neu aus der DB."""
    info = getattr(db, "info", None)
    if info is None or info.get(_SESSION_HOOK_FLAG):
        return
    info[_SESSION_HOOK_FLAG] = True
    for name in ("after_commit", "after_rollback", "after_soft_rollback"):
        event.listen(db, name, lambda session, *_args: _invalidate_readers_of(session))


def _key_lock_clause(db: Session) -> str:
    """PostgreSQL: FOR SHARE haelt die Schluesselzeile bis zum Transaktionsende;
    ``shred_client_keys`` (UPDATE) wartet, bis aeltere Leser beendet sind.
    SQLite serialisiert Schreiber dateiweit; dort sichern die Prozess-Registry
    und die Transaktionsgrenze denselben Vertrag."""
    try:
        return " FOR SHARE" if db.get_bind().dialect.name == "postgresql" else ""
    except Exception:  # pragma: no cover - ungebundene Session
        return ""


class KeyReader:
    """N-938-02: Lesekontext EINES Aufrufs (Liste, Bericht, PDF). Kundenschluessel,
    Mandat -> Kunde und der Loeschbeleg werden je einmal gelesen statt je
    versiegeltem Wert.

    C-L2D-01 (Vertrag): Nach Commit einer Schluesselvernichtung kann kein neuer
    oder bereits aktiver Ares-Leser den Schluessel erneut zur Entschluesselung
    verwenden. Umsetzung:
    * Der Cache gilt nur innerhalb der laufenden Transaktion (Commit/Rollback
      der Session leert ihn); auf PostgreSQL liest ``key`` mit FOR SHARE, die
      Vernichtung wartet also auf aeltere Leser.
    * ``shred_client_keys`` leert sofort alle Leser derselben Session und nach
      seinem Commit alle Leser des Prozesses.
    * ``close``/Context-Manager: leert den Cache; danach verweigert der Leser.
    Keine Aussage ueber forensische Nullung unveraenderlicher Python-Bytes."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._keys: dict[str, Any] = {}
        self._erased: dict[str, bool] = {}
        self._clients: dict[str, str | None] = {}
        self._closed = False
        _install_session_hooks(db)
        with _LIVE_READERS_LOCK:
            _LIVE_READERS.add(self)

    def __enter__(self) -> "KeyReader":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _invalidate(self) -> None:
        self._keys.clear()
        self._erased.clear()
        self._clients.clear()

    def close(self) -> None:
        self._invalidate()
        self._closed = True
        with _LIVE_READERS_LOCK:
            _LIVE_READERS.discard(self)

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise PiiVaultError("Lesekontext ist geschlossen; fuer einen neuen Aufruf neu oeffnen.")

    def key(self, key_id: str):
        self._check_open()
        if key_id not in self._keys:
            self._keys[key_id] = self.db.execute(
                text(
                    "SELECT client_id, key_material, shredded_at FROM client_pii_keys "
                    "WHERE key_id = :key_id" + _key_lock_clause(self.db)
                ),
                {"key_id": key_id},
            ).first()
        return self._keys[key_id]

    def erased(self, client_id: str | None) -> bool:
        self._check_open()
        cache_key = str(client_id or "")
        if cache_key not in self._erased:
            self._erased[cache_key] = erasure_executed_for_client(self.db, client_id)
        return self._erased[cache_key]

    def client_of_mandate(self, mandate_id: Any) -> str | None:
        self._check_open()
        if not mandate_id:
            return None
        key = str(mandate_id)
        if key not in self._clients:
            value = self.db.execute(
                text("SELECT client_id FROM mandates WHERE id = :id"), {"id": key},
            ).scalar()
            self._clients[key] = str(value) if value else None
        return self._clients[key]


def reveal(db: Session, value: Any, *, reader: KeyReader | None = None) -> str | None:
    """Klartext eines Umschlags; None, wenn der Schluessel vernichtet ist.

    Nicht versiegelte Werte (Altbestand vor DSG-ERASURE-APPEND-ONLY-001)
    werden unveraendert zurueckgegeben."""
    if not is_sealed(value):
        return value
    key_id, _, token = value[len(ENVELOPE_PREFIX):].partition(":")
    row = (reader or KeyReader(db)).key(key_id)
    if row is None or row.key_material is None:
        return None
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(row.key_material).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # L2c: ein beschaedigter Umschlag (z. B. angehaengter Text mit
        # Nicht-ASCII-Zeichen) ist unlesbar, kein Serverfehler.
        return None


# L2b (H-190): Lesestatus eines gespeicherten Freitexts. "Geloescht" heisst
# nur: der Kundenschluessel ist nachweislich vernichtet (Tombstone mit
# shredded_at). Ein Umschlag, der sich mit vorhandenem Schluessel nicht
# oeffnen laesst, ist dagegen "unlesbar" (kein DSG-Fall, Fehler sichtbar).
REVEAL_PLAIN = "klartext"          # Altbestand, nicht versiegelt
REVEAL_OPEN = "geoeffnet"          # versiegelt, Schluessel vorhanden
REVEAL_SHREDDED = "geloescht"      # versiegelt, Schluessel vernichtet (DSG)
REVEAL_UNREADABLE = "unlesbar"     # versiegelt, Schluessel fehlt/passt nicht


def _table_columns(db: Session, table: str) -> set[str]:
    """Spalten einer Tabelle (leer, wenn sie fehlt); SQLite und PostgreSQL."""
    inspector = sa_inspect(db.connection())
    if not inspector.has_table(table):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table)}


def erasure_executed_for_client(db: Session, client_id: str | None) -> bool:
    """L2c / N-936-04: Ist fuer diesen Kunden eine ausgefuehrte Loeschung
    belegt? Nur dann gilt ein vernichteter Schluessel als DSG-Loeschung.

    Beleg ist (a) ein PRIVACY-001-Loeschvorgang mit Status EXECUTED oder
    PARTIALLY_EXECUTED, in dem eine Crypto-Shred-Zeile angewendet bzw.
    entsorgt wurde, oder (b) der Alt-Pfad ``erase_client_personal_data``
    (``clients.erased_at`` gesetzt). Ein direkt in der Datenbank gesetzter
    Tombstone ohne diesen Beleg ist keine Loeschung, sondern eine Veraenderung.
    """
    if not client_id:
        return False
    if _table_columns(db, "privacy_erasure_cases") and _table_columns(db, "privacy_erasure_dispositions"):
        hit = db.execute(
            text(
                "SELECT 1 FROM privacy_erasure_cases c "
                "JOIN privacy_erasure_dispositions d ON d.case_id = c.id "
                "WHERE c.client_id = :client_id AND d.client_id = :client_id "
                "AND c.status IN ('EXECUTED', 'PARTIALLY_EXECUTED') "
                "AND d.method = 'CRYPTO_SHRED' "
                "AND ((d.decision_status = 'APPLIED' "
                "AND d.disposition IN ('DELETE', 'ANONYMIZE', 'PARTIAL_DELETE_MINIMIZE')) "
                "OR d.decision_status = 'DISPOSED') LIMIT 1"
            ),
            {"client_id": client_id},
        ).first()
        if hit is not None:
            return True
    if "erased_at" in _table_columns(db, "clients"):
        erased = db.execute(
            text("SELECT erased_at FROM clients WHERE id = :client_id"), {"client_id": client_id},
        ).scalar()
        if erased:
            return True
    return False


def reveal_state(
    db: Session, value: Any, *, client_id: str | None = None, reader: KeyReader | None = None,
) -> tuple[str | None, str]:
    """(Klartext oder None, Status) eines gespeicherten Freitexts.

    L2c: Mit ``client_id`` (Kunde der Zeile) gilt zusaetzlich
    * N-936-05: Gehoert der Schluessel des Umschlags einem anderen Kunden,
      ist der Wert ``unlesbar`` (verändert), auch wenn er sich oeffnen laesst.
    * N-936-04: Ein vernichteter Schluessel gilt nur als ``geloescht``, wenn
      fuer den Kunden eine ausgefuehrte Loeschung belegt ist
      (``erasure_executed_for_client``); sonst ``unlesbar``.
    Ohne ``client_id`` (Altaufrufer) bleibt das bisherige Verhalten.
    """
    if not is_sealed(value):
        return value, REVEAL_PLAIN
    key_id = value[len(ENVELOPE_PREFIX):].partition(":")[0]
    reader = reader or KeyReader(db)
    row = reader.key(key_id)
    if client_id is not None and (row is None or str(row.client_id) != str(client_id)):
        return None, REVEAL_UNREADABLE
    if row is not None and row.key_material is None and row.shredded_at:
        if client_id is not None and not reader.erased(client_id):
            return None, REVEAL_UNREADABLE
        return None, REVEAL_SHREDDED
    plain = reveal(db, value, reader=reader)
    return plain, (REVEAL_OPEN if plain is not None else REVEAL_UNREADABLE)


def shred_client_keys(db: Session, client_id: str) -> int:
    """Vernichtet den Schluessel des Kunden (Crypto-Shredding).

    Existiert noch kein Schluessel, wird ein Tombstone angelegt, damit spaeter
    nichts mehr fuer diesen Kunden versiegelt werden kann. Rueckgabe: Anzahl
    vernichteter Schluessel (0 = es gab keinen aktiven)."""
    now = _now()
    if db.get_bind().dialect.name == "sqlite":
        # Freigegebene Seiteninhalte mit Nullen ueberschreiben (wirkt auf die
        # nachfolgenden Schreibvorgaenge dieser Verbindung).
        db.execute(text("PRAGMA secure_delete = ON"))
    result = db.execute(
        text(
            "UPDATE client_pii_keys SET key_material = NULL, shredded_at = :now "
            "WHERE client_id = :client_id AND key_material IS NOT NULL"
        ),
        {"now": now, "client_id": client_id},
    )
    shredded = int(result.rowcount or 0)
    # C-L2D-01: Leser derselben Session sofort leeren; nach dem Commit dieser
    # Vernichtung alle Leser des Prozesses (andere Sessions).
    _invalidate_readers_of(db)
    info = getattr(db, "info", None)
    if info is not None and not info.get(_SHRED_HOOK_FLAG):
        info[_SHRED_HOOK_FLAG] = True
        event.listen(db, "after_commit", lambda _session: _invalidate_all_readers())
    if _key_row(db, client_id) is None:
        from database import new_uuid

        db.execute(
            text(
                "INSERT INTO client_pii_keys (client_id, key_id, key_material, created_at, shredded_at) "
                "VALUES (:client_id, :key_id, NULL, :now, :now)"
            ),
            {"client_id": client_id, "key_id": new_uuid(), "now": now},
        )
    return shredded


def count_unsealed_rows(db: Session, client_id: str, mandate_ids: list[str]) -> dict[str, int]:
    """Altbestand: append-only Zeilen dieses Kunden mit Klartext-Freitext.

    Diese Zeilen koennen ohne Aufweichung der Trigger nicht redigiert werden
    und werden deshalb gemeldet (Owner-/Legal-Entscheid), nie still
    uebergangen. Pro Tabelle EINE Abfrage ueber alle Freitextspalten: eine
    Zeile mit mehreren Klartextspalten zaehlt einmal."""
    from services.client_erasure import _in_params

    by_table: dict[str, list[str]] = {}
    for table, column in SEALED_APPEND_ONLY_COLUMNS + SEALED_PROTOCOL_COLUMNS:
        by_table.setdefault(table, []).append(column)
    counts: dict[str, int] = {}
    for table, columns in by_table.items():
        present = _table_columns(db, table)
        columns = [column for column in columns if column in present]
        if not columns:
            continue
        params: dict[str, Any] = {"client_id": client_id, "prefix": ENVELOPE_PREFIX + "%"}
        scopes = ["client_id = :client_id"] if "client_id" in present else []
        if mandate_ids and "mandate_id" in present:
            clause, id_params = _in_params("m", mandate_ids)
            scopes.append(f"mandate_id IN ({clause})")
            params.update(id_params)
        if not scopes:
            continue
        scope = "(" + " OR ".join(scopes) + ")"
        unsealed = " OR ".join(
            f"(\"{column}\" IS NOT NULL AND \"{column}\" <> '' AND \"{column}\" NOT LIKE :prefix)"
            for column in columns
        )
        n = db.execute(
            text(f'SELECT COUNT(*) FROM "{table}" WHERE {scope} AND ({unsealed})'),
            params,
        ).scalar()
        if n:
            counts[table] = int(n)
    return counts
