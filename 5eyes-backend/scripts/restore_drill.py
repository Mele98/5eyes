"""RESTORE-DRILL-NEVER-PERFORMED-001 (Kontrollrunde 2026-09-27).

docs/deploy/disaster-recovery-plan.md Abschnitt 5 verlangt: "Restore-Drill
(PFLICHT, sonst ist das Backup nur eine Hoffnung)... mindestens
quartalsweise". Die Protokoll-Tabelle dort war seit Erstellung des Plans
(2026-06-15) leer -- kein einziger Drill wurde je durchgefuehrt oder
dokumentiert.

Dieses Script macht aus einer einmaligen manuellen Uebung einen
wiederholbaren Befehl: es fuehrt einen ECHTEN Backup->Verlust->Restore-
Zyklus gegen dieselben Produktionsfunktionen aus (services.backup.
backup_database, services.maintenance.restore_backup -- exakt der Pfad,
den scripts/backup_now.py fuer einen echten Operator nutzt), misst die
tatsaechliche Restore-Dauer und gibt einen fertigen Markdown-Tabellenzeile
fuer das DRP-Protokoll aus.

Umfang / ehrliche Grenzen dieses Drills
----------------------------------------
- Laeuft IMMER in einem frischen, isolierten Sandbox-Verzeichnis
  (tempfile.mkdtemp) -- niemals gegen settings.db_path/settings.backup_dir,
  also niemals gegen echte Kunden-/Mandantendaten. Kein Deploy-Schritt,
  keine Rueckfrage-Gefahr.
- Nutzt eine minimale synthetische Tabelle (keine App-Modelle) mit einer
  Marker-Zeile, um Datenerhalt zu verifizieren. Das ist bewusst: der
  Backup-/Restore-Mechanismus selbst (sqlite3.Connection.backup(),
  SHA256-/HMAC-Sidecar, atomarer Restore) arbeitet auf Datei-/Seiten-
  Ebene und ist schema-agnostisch -- ein synthetisches Schema prueft
  denselben Code-Pfad wie das echte, ohne Risiko und ohne die volle
  App-Initialisierung (Scheduler, Router, Mandanten-Kontext) mitzuschleppen.
  Ein Restore-Drill gegen einen ECHTEN Tier-2/3-Zielhost mit realer
  Infrastruktur bleibt eine SEPARATE, weiterhin ausstehende Uebung (siehe
  Report-Ausgabe unten).
- RPO in diesem Drill ist strukturell ~0 (Backup wird unmittelbar vor dem
  simulierten Verlust erstellt) und NICHT mit dem realen Produktions-RPO
  zu verwechseln (das haengt von der taeglichen Backup-Kadenz ab, siehe
  DRP Abschnitt 1).

Aufruf
------
    python scripts/restore_drill.py
    python scripts/restore_drill.py --keep-workdir   # Sandbox nicht loeschen (Inspektion)
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _create_sandbox_source_db(db_path: Path) -> str:
    """Minimale, synthetische DB mit einer Marker-Zeile. Gibt den Marker
    zurueck, damit der Aufrufer ihn nach dem Restore verifizieren kann."""
    marker = uuid.uuid4().hex
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE restore_drill_marker (id INTEGER PRIMARY KEY, token TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO restore_drill_marker (token) VALUES (?)", (marker,))
        conn.commit()
    finally:
        conn.close()
    return marker


def _read_marker(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT token FROM restore_drill_marker LIMIT 1").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="5eyes Restore-Drill (DRP Abschnitt 5)")
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Sandbox-Verzeichnis nach dem Drill nicht loeschen (zur Inspektion).",
    )
    args = parser.parse_args()

    from services.backup import backup_database
    from services.maintenance import restore_backup

    workdir = Path(tempfile.mkdtemp(prefix="5eyes-restore-drill-"))
    source_db = workdir / "source" / "drill.db"
    backup_dir = workdir / "backups"
    source_db.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    findings: list[str] = []
    exit_code = 0

    try:
        print(f"Sandbox: {workdir}")
        marker = _create_sandbox_source_db(source_db)
        print(f"Synthetische Quell-DB angelegt, Marker={marker}")

        t_backup_start = time.monotonic()
        backup_result = backup_database(
            target_dir=backup_dir,
            source_db_path=source_db,
            retain_days=0,
            keep_minimum=1,
        )
        backup_duration_s = time.monotonic() - t_backup_start
        print(
            f"Backup ok -> {backup_result.path} "
            f"({backup_result.bytes_written} bytes, {backup_duration_s:.3f}s, "
            f"hmac_signed={backup_result.hmac_signed})"
        )

        # Simulierter Totalverlust der Quelle (Host-Ausfall/Fehlbedienung).
        source_db.unlink()
        for sidecar in (source_db.with_suffix(".db-wal"), source_db.with_suffix(".db-shm")):
            sidecar.unlink(missing_ok=True)
        print("Simulierter Verlust: Quell-DB geloescht.")

        t_restore_start = time.monotonic()
        restore_result = restore_backup(
            backup_path=backup_result.path,
            target_db_path=source_db,
        )
        restore_duration_s = time.monotonic() - t_restore_start
        print(
            f"Restore ok -> {restore_result['target_db_path']} "
            f"({restore_duration_s:.3f}s, hash_verified={restore_result['hash_verified']}, "
            f"hmac_verified={restore_result['hmac_verified']})"
        )

        integrity = _integrity_check(source_db)
        if integrity != "ok":
            findings.append(f"PRAGMA integrity_check meldete '{integrity}' statt 'ok'.")

        restored_marker = _read_marker(source_db)
        if restored_marker != marker:
            findings.append(
                f"Marker-Zeile nach Restore nicht identisch (erwartet {marker}, "
                f"erhalten {restored_marker})."
            )

        if not restore_result["hash_verified"]:
            findings.append("SHA256-Integritaet beim Restore NICHT verifiziert.")

        status = "OK -- keine Abweichungen" if not findings else "ABWEICHUNGEN GEFUNDEN"
        befunde = "; ".join(findings) if findings else "keine"

        print("\n" + "=" * 78)
        print("RESTORE-DRILL-BEFUND (DRP Abschnitt 5)")
        print("=" * 78)
        print(f"Status:              {status}")
        print(f"Backup-Dauer:        {backup_duration_s:.3f}s")
        print(f"Restore-Dauer (RTO): {restore_duration_s:.3f}s")
        print("RPO:                 ~0 (Backup unmittelbar vor simuliertem Verlust "
              "erstellt -- NICHT mit dem realen Produktions-RPO verwechseln, "
              "siehe Docstring)")
        print(f"Integritaet:         PRAGMA integrity_check = {integrity}")
        print(f"Datenerhalt:         Marker-Zeile {'intakt' if restored_marker == marker else 'FEHLT/ABWEICHEND'}")
        print(f"Befunde:             {befunde}")
        print(
            "\nOffen (nicht Teil dieses Drills): ein Restore-Drill gegen einen "
            "echten Tier-2/3-Zielhost mit realer Infrastruktur (siehe DRP "
            "Abschnitt 7 -- Postgres+PITR, Off-Site-Ziel-Host)."
        )
        print("\nFertige Tabellenzeile fuer docs/deploy/disaster-recovery-plan.md:")
        print(
            f"| {date.today().isoformat()} | Dev-Sandbox (synthetisch, "
            f"scripts/restore_drill.py) | {restore_duration_s * 1000:.0f} ms "
            f"(synthetische Mini-DB, nicht kapazitaetsrelevant) | ~0 "
            f"(sofortiger Restore nach Backup) | {befunde} |"
        )

        exit_code = 0 if not findings else 1
    finally:
        if args.keep_workdir:
            print(f"\n--keep-workdir gesetzt: Sandbox bleibt erhalten unter {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
