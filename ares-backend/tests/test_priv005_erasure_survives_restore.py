"""PRIV-005 (Codex-Audit): Backup-Restore darf eine DSG-Art.-32-Erasure

nicht rueckgaengig machen.

Hintergrund
-----------
services/client_erasure.py::erase_client_personal_data() anonymisiert
irreversibel die direkt identifizierenden PII-Felder eines Kunden und
markiert dies via ``clients.erased_at``. Ein Backup (services/backup.py)
ist aber ein voller SQLite-Datei-Snapshot -- vor diesem Fix lebte
``erased_at`` NUR in dieser einen Datei. Ein Restore eines Backups, das
VOR der Erasure erstellt wurde, hat die geloeschten Personendaten deshalb
bisher stillschweigend UND spurlos wiederhergestellt: die restaurierte
DB enthielt weder die redigierten Werte noch irgendeinen Hinweis, dass
je eine Erasure stattgefunden hatte (der Loeschvermerk selbst lag ja nur
in der jetzt ueberschriebenen Datei).

Dieser Test-Sweep deckt:
1. RED: Der rohe Restore-Primitive (services.backup.restore_database)
   bleibt bewusst "dumm" (reiner Datei-Restore) und resurrected PII bei
   einem Vor-Erasure-Backup -- dokumentiert das eigentliche Problem und
   schuetzt davor, dass jemand kuenftig annimmt, dieser Layer sei bereits
   sicher.
2. GREEN: services/maintenance.py::restore_backup() (der neue, empfohlene
   Restore-Pfad) konsultiert nach dem Restore automatisch das Erasure-
   Ledger (neben der DB-Datei, siehe services/client_erasure.py) und
   wendet die Erasure erneut an -- die wiederhergestellte DB landet in
   einem konsistenten "Erasure wieder angewendet"-Zustand.
3. REGRESSION: Ein Restore, dem NIE eine Erasure vorausging (Tier-1-
   Normalfall, Holger), verhaelt sich exakt wie vor diesem Fix (leeres
   Ledger -> reines No-Op).
4. Das Ledger-File selbst liegt NICHT in der DB-Datei und wird von einem
   Restore (der nur genau die eine Ziel-Datei ueberschreibt) nicht
   angetastet -- das ist die Kernvoraussetzung, ohne die der ganze Fix
   wirkungslos waere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, ensure_audit_log_triggers  # noqa: E402
from models import (  # noqa: F401,E402
    allocation,
    client_login,
    clients,
    mandates,
    profiling,
    protocol_bausteine,
    refresh_token,
    review,
    snapshots,
    tenant,
    users,
    wealth,
)
from services.backup import backup_database, restore_database  # noqa: E402
from services.client_erasure import (  # noqa: E402
    ERASURE_LEDGER_FILENAME,
    erase_client_personal_data,
)
from services.maintenance import restore_backup  # noqa: E402


NOW = "2026-08-15T10:00:00.000Z"
CLIENT_ID = "client-priv005"


def _build_app_db(db_path: Path) -> None:
    """Legt das volle App-Schema (inkl. audit_log-Immutability-Trigger) in
    einer echten Datei an und schliesst danach jede Verbindung -- Restore
    (os.replace auf genau diese Datei) darf auf Windows nicht durch einen
    noch offenen SQLAlchemy-Connection-Pool blockiert werden.
    """
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    ensure_audit_log_triggers(engine)
    engine.dispose()


def _session_for(db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    return engine, factory


def _seed_client(db_path: Path, *, client_id: str = CLIENT_ID) -> None:
    engine, factory = _session_for(db_path)
    try:
        with factory() as session:
            session.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, password_hash, full_name, role, is_active,
                        totp_enabled, must_change_password, created_at, updated_at
                    )
                    VALUES ('admin-priv005', 'admin-priv005', 'h', 'Admin PRIV005', 'admin',
                            1, 0, 0, :now, :now)
                    """
                ),
                {"now": NOW},
            )
            session.execute(
                text(
                    """
                    INSERT INTO clients (
                        id, client_number, salutation, first_name, last_name, date_of_birth,
                        country_of_residence, canton, civil_status, profession, employer,
                        language, household_type, client_classification,
                        is_professional_opt_out, is_qualified_investor,
                        advisor_id, notes, created_at, updated_at
                    )
                    VALUES (
                        :id, 'P-001', 'Herr', 'Hans', 'Muster', '1970-01-01',
                        'CH', 'ZH', 'verheiratet', 'Ingenieur', 'ACME AG',
                        'DE', 'Paar', 'Privatkunde',
                        0, 0,
                        'admin-priv005', 'wohnt an der Bahnhofstrasse 1', :now, :now
                    )
                    """
                ),
                {"id": client_id, "now": NOW},
            )
            session.commit()
    finally:
        engine.dispose()


def _client_row(db_path: Path, client_id: str = CLIENT_ID) -> tuple:
    engine, factory = _session_for(db_path)
    try:
        with factory() as session:
            return session.execute(
                text(
                    "SELECT first_name, last_name, notes, erased_at, erasure_reason "
                    "FROM clients WHERE id = :id"
                ),
                {"id": client_id},
            ).one()
    finally:
        engine.dispose()


def _erase_client(db_path: Path, client_id: str = CLIENT_ID, *, reason: str) -> None:
    engine, factory = _session_for(db_path)
    try:
        with factory() as session:
            erase_client_personal_data(session, client_id, reason=reason)
            session.commit()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 1. RED -- der rohe Restore-Primitive bleibt bewusst dumm
# ---------------------------------------------------------------------------

def test_raw_restore_database_alone_resurrects_erased_pii(tmp_path: Path):
    """Dokumentiert das eigentliche PRIV-005-Problem auf der untersten
    Ebene: services.backup.restore_database() ist ein reiner Datei-
    Restore und kennt das Erasure-Ledger nicht -- ein Restore eines
    Vor-Erasure-Backups resurrected die PII. Genau deshalb MUSS die
    Wiederanwendung eine Schicht hoeher (services.maintenance.restore_backup)
    passieren, nicht in restore_database() selbst."""
    db_path = tmp_path / "live.db"
    _build_app_db(db_path)
    _seed_client(db_path)

    backups_dir = tmp_path / "backups"
    pre_erasure_backup = backup_database(target_dir=backups_dir, source_db_path=db_path)

    _erase_client(db_path, reason="Kunde verlangt Loeschung nach DSG Art. 32.")
    erased_row = _client_row(db_path)
    assert erased_row.erased_at is not None
    assert erased_row.first_name != "Hans"

    # Roher Restore des Vor-Erasure-Backups -- OHNE Ledger-Wiederanwendung.
    restore_database(backup_path=pre_erasure_backup.path, target_db_path=db_path)

    resurrected_row = _client_row(db_path)
    assert resurrected_row.first_name == "Hans", (
        "Erwartet: der rohe Restore-Primitive resurrected die PII -- "
        "das ist genau die Luecke, die restore_backup() schliessen muss."
    )
    assert resurrected_row.erased_at is None


# ---------------------------------------------------------------------------
# 2. GREEN -- maintenance.restore_backup() wendet die Erasure erneut an
# ---------------------------------------------------------------------------

def test_restore_backup_reapplies_erasure_after_restoring_pre_erasure_backup(tmp_path: Path):
    db_path = tmp_path / "live.db"
    _build_app_db(db_path)
    _seed_client(db_path)

    backups_dir = tmp_path / "backups"
    pre_erasure_backup = backup_database(target_dir=backups_dir, source_db_path=db_path)

    _erase_client(db_path, reason="Kunde verlangt Loeschung nach DSG Art. 32.")
    erased_row = _client_row(db_path)
    assert erased_row.erased_at is not None

    ledger_path = db_path.parent / ERASURE_LEDGER_FILENAME
    assert ledger_path.exists(), "Erasure haette einen Ledger-Eintrag schreiben muessen."
    ledger_before_restore = ledger_path.read_text(encoding="utf-8")

    result = restore_backup(backup_path=pre_erasure_backup.path, target_db_path=db_path)

    assert result["erasure_reapply"]["reapplied"] == [CLIENT_ID]

    final_row = _client_row(db_path)
    assert final_row.first_name != "Hans", "PII haette nach Restore erneut redigiert sein muessen."
    assert final_row.last_name != "Muster"
    assert final_row.erased_at is not None
    assert "Wiederanwendung nach Restore" in (final_row.erasure_reason or "")

    # Ledger ueberlebt den Restore unangetastet (Restore ueberschreibt nur
    # die eine DB-Datei, nicht das Ledger-File daneben) und waechst um den
    # neuen Wiederanwendungs-Eintrag, den erase_client_personal_data beim
    # Reapply erneut schreibt.
    ledger_after_restore = ledger_path.read_text(encoding="utf-8")
    assert ledger_after_restore.startswith(ledger_before_restore)
    assert ledger_after_restore.count("\n") == ledger_before_restore.count("\n") + 1


def test_restore_backup_skips_already_erased_client_without_error(tmp_path: Path):
    """Restore eines Backups, das die Erasure BEREITS enthaelt (Normalfall
    -- Backup ist neuer als die Loeschung): kein erneuter Erasure-Aufruf,
    keine 409-Kollision, reines No-Op fuer diesen Client."""
    db_path = tmp_path / "live.db"
    _build_app_db(db_path)
    _seed_client(db_path)
    _erase_client(db_path, reason="Kunde verlangt Loeschung nach DSG Art. 32.")

    backups_dir = tmp_path / "backups"
    post_erasure_backup = backup_database(target_dir=backups_dir, source_db_path=db_path)

    result = restore_backup(backup_path=post_erasure_backup.path, target_db_path=db_path)

    assert result["erasure_reapply"]["reapplied"] == []
    assert result["erasure_reapply"]["already_erased"] == [CLIENT_ID]
    final_row = _client_row(db_path)
    assert final_row.erased_at is not None


# ---------------------------------------------------------------------------
# 3. REGRESSION -- Tier-1-Normalfall (nie eine Erasure) bleibt unveraendert
# ---------------------------------------------------------------------------

def test_restore_backup_is_pure_noop_when_no_erasure_ever_happened(tmp_path: Path):
    db_path = tmp_path / "live.db"
    _build_app_db(db_path)
    _seed_client(db_path)

    backups_dir = tmp_path / "backups"
    backup = backup_database(target_dir=backups_dir, source_db_path=db_path)

    # Kein Ledger-File vorhanden -- der klassische Holger-Normalfall.
    ledger_path = db_path.parent / ERASURE_LEDGER_FILENAME
    assert not ledger_path.exists()

    result = restore_backup(backup_path=backup.path, target_db_path=db_path)

    assert result["hash_verified"] is True
    assert result["erasure_reapply"]["entries_seen"] == 0
    assert result["erasure_reapply"]["reapplied"] == []

    row = _client_row(db_path)
    assert row.first_name == "Hans"
    assert row.erased_at is None
    assert not ledger_path.exists(), "No-Op darf kein Ledger-File aus dem Nichts erzeugen."


def test_restore_backup_matches_raw_restore_database_bytes_when_ledger_empty(tmp_path: Path):
    """Zusaetzliche Absicherung: restore_backup() darf im Normalfall exakt
    dasselbe Restore-Ergebnis liefern wie der rohe Primitive (gleiche
    Bytes/Hash) -- der Wrapper aendert das Restore-Verhalten selbst nicht,
    er ergaenzt nur den Erasure-Reapply-Schritt danach."""
    db_path_a = tmp_path / "live_a.db"
    db_path_b = tmp_path / "live_b.db"
    _build_app_db(db_path_a)
    _seed_client(db_path_a)
    _build_app_db(db_path_b)
    _seed_client(db_path_b)

    backups_dir = tmp_path / "backups"
    backup = backup_database(target_dir=backups_dir, source_db_path=db_path_a)

    raw_result = restore_database(backup_path=backup.path, target_db_path=db_path_a)
    wrapped_result = restore_backup(backup_path=backup.path, target_db_path=db_path_b)

    assert raw_result.bytes_restored == wrapped_result["bytes_restored"]
    assert raw_result.hash_verified == wrapped_result["hash_verified"]


# ---------------------------------------------------------------------------
# 4. Ledger-Datei ueberlebt strukturell einen Datei-Replace des DB-Files
# ---------------------------------------------------------------------------

def test_ledger_file_is_untouched_by_restores_atomic_copy(tmp_path: Path):
    """Kernvoraussetzung des ganzen Fixes: _perform_atomic_copy() (der
    Restore-Mechanismus in services/backup.py) ueberschreibt NUR die eine
    Zieldatei (os.replace(temp, target)) -- eine Sibling-Datei im selben
    Verzeichnis bleibt davon vollstaendig unberuehrt."""
    db_path = tmp_path / "live.db"
    _build_app_db(db_path)
    _seed_client(db_path)

    backups_dir = tmp_path / "backups"
    backup = backup_database(target_dir=backups_dir, source_db_path=db_path)

    ledger_path = db_path.parent / ERASURE_LEDGER_FILENAME
    ledger_path.write_text('{"client_id": "sentinel", "reason": "x", "erased_at": "y"}\n', encoding="utf-8")
    sentinel_mtime = ledger_path.stat().st_mtime
    sentinel_content = ledger_path.read_text(encoding="utf-8")

    restore_database(backup_path=backup.path, target_db_path=db_path)

    assert ledger_path.exists()
    assert ledger_path.read_text(encoding="utf-8") == sentinel_content
    assert ledger_path.stat().st_mtime == sentinel_mtime
