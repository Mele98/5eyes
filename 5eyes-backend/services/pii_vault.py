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
  Erasure-Ledger (PRIV-005, services/client_erasure.py::
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

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

ENVELOPE_PREFIX = "pii-sealed:v1:"

# Append-only Tabellen mit versiegeltem Freitext: (Tabelle, Freitextspalte).
SEALED_APPEND_ONLY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("risk_override_decisions", "reason"),
    ("risk_profile_signoffs", "note"),
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


def reveal(db: Session, value: Any) -> str | None:
    """Klartext eines Umschlags; None, wenn der Schluessel vernichtet ist.

    Nicht versiegelte Werte (Altbestand vor DSG-ERASURE-APPEND-ONLY-001)
    werden unveraendert zurueckgegeben."""
    if not is_sealed(value):
        return value
    key_id, _, token = value[len(ENVELOPE_PREFIX):].partition(":")
    row = db.execute(
        text("SELECT key_material FROM client_pii_keys WHERE key_id = :key_id"),
        {"key_id": key_id},
    ).first()
    if row is None or row.key_material is None:
        return None
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(row.key_material).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


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
    uebergangen."""
    from services.client_erasure import _in_params, _table_exists

    counts: dict[str, int] = {}
    for table, column in SEALED_APPEND_ONLY_COLUMNS:
        if not _table_exists(db, table):
            continue
        scope = "client_id = :client_id"
        params: dict[str, Any] = {"client_id": client_id, "prefix": ENVELOPE_PREFIX + "%"}
        if mandate_ids:
            clause, id_params = _in_params("m", mandate_ids)
            scope = f"({scope} OR mandate_id IN ({clause}))"
            params.update(id_params)
        n = db.execute(
            text(
                f'SELECT COUNT(*) FROM "{table}" WHERE {scope} '
                f'AND "{column}" IS NOT NULL AND "{column}" <> \'\' '
                f'AND "{column}" NOT LIKE :prefix'
            ),
            params,
        ).scalar()
        if n:
            counts[table] = int(n)
    return counts
