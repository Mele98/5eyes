"""PRIV-005 / PRIVACY-001: Erasure-Ledger nach einem DB-Restore wieder anwenden.

Aus ``services/client_erasure.py`` ausgelagert (Architektur-Ratsche, Zyklus
client_erasure <-> privacy_erasure): Die Restore-Orchestrierung braucht beide
Seiten -- die Kunden-Erasure (``client_erasure``) und die Wiederherstellung von
Loeschvorgaengen/Sperrvermerken (``privacy_erasure``). Liegt sie in einem
eigenen Modul ueber beiden, haengt ``client_erasure`` nicht mehr von
``privacy_erasure`` ab; ``privacy_erasure`` nutzt ``client_erasure`` weiterhin
in einer Richtung. Verhalten unveraendert (Funktion wortgleich verschoben).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from database import create_app_engine
from services.client_erasure import (
    ERASURE_LEDGER_FILENAME,
    _read_ledger_entries,
    erase_client_personal_data,
)
from services.privacy_erasure import reapply_ledger_entries


def reapply_erasures_after_restore(
    target_db_path: str | Path, *, db_key: str | None = None
) -> dict[str, Any]:
    """PRIV-005: Nach einem DB-Restore (services/backup.py::restore_database)
    aufzurufen. Liest das Erasure-Ledger neben ``target_db_path`` und wendet
    jede dort protokollierte Erasure erneut an, deren Kunde in der frisch
    wiederhergestellten DB noch NICHT als erased markiert ist (``erased_at``
    IS NULL) -- das ist genau der Fall, wenn das restaurierte Backup aelter
    als die urspruengliche Loeschung war.

    Kunden, die in der wiederhergestellten DB bereits ``erased_at`` gesetzt
    haben (Normalfall: Backup ist neuer als jede Erasure) oder gar nicht
    mehr existieren, werden uebersprungen -- reines No-Op fuer den
    Tier-1-Normalfall (kein Ledger vorhanden bzw. Backup ohnehin aktuell).
    """
    target = Path(target_db_path).expanduser().resolve()
    ledger_path = target.parent / ERASURE_LEDGER_FILENAME
    entries = _read_ledger_entries(ledger_path)

    summary: dict[str, Any] = {
        "ledger_file": str(ledger_path),
        "entries_seen": len(entries),
        "reapplied": [],
        "already_erased": [],
        "skipped_not_found": [],
    }
    if not entries:
        return summary

    engine = create_app_engine(db_path=target, db_key=db_key)
    session_factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    seen_client_ids: set[str] = set()
    try:
        with session_factory() as db:
            for entry in entries:
                if entry.get("kind"):
                    # PRIVACY-001: Vorgangs- und Entsorgungseintraege wendet
                    # services/privacy_erasure.py weiter unten an.
                    continue
                client_id = entry.get("client_id")
                if not client_id or client_id in seen_client_ids:
                    continue
                seen_client_ids.add(client_id)

                row = db.execute(
                    text("SELECT erased_at FROM clients WHERE id = :id"),
                    {"id": client_id},
                ).first()
                if row is None:
                    summary["skipped_not_found"].append(client_id)
                    continue
                if row[0]:
                    summary["already_erased"].append(client_id)
                    continue

                original_reason = entry.get("reason", "")
                reapply_reason = (
                    "Automatische Wiederanwendung nach Restore eines Backups, "
                    "das aelter als die urspruengliche DSG-Art.-32-Loeschung "
                    f"ist (urspruenglicher Grund: {original_reason})"
                )
                erase_client_personal_data(
                    db, client_id, reason=reapply_reason,
                    # PRIVACY-001: gesperrt aufzubewahrende versiegelte
                    # Freitexte duerfen auch nach dem Restore nicht vernichtet
                    # werden. Alt-Eintraege ohne Feld: wie bisher vernichten.
                    shred_pii_keys=bool(entry.get("pii_keys_shredded", True)),
                )
                db.commit()
                summary["reapplied"].append(client_id)

            # PRIVACY-001: Loeschvorgaenge, Sperrvermerke und spaetere
            # Schluesselvernichtungen vor der operativen Freigabe herstellen.
            summary["privacy"] = reapply_ledger_entries(db, entries)
            db.commit()
    finally:
        engine.dispose()

    return summary
