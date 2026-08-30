"""Sprint U-8 — On-Demand-DB-Backup-CLI.

Aufruf
------
    python scripts/backup_now.py
    python scripts/backup_now.py --target /pfad/zu/backups
    python scripts/backup_now.py --source ~/5eyes/5eyes.db --target /mnt/backup
    python scripts/backup_now.py --restore /pfad/zu/backup.db --target ~/5eyes/5eyes.db

Standardmaessig liest das Script Settings aus `.env` / Umgebungs-
variablen via `config.settings` — selbe Quelle wie der laufende Server.

Sicherheits-Hinweis
-------------------
* Restore ueberschreibt das Ziel ohne Rueckfrage. Server vorher stoppen.
* In Produktion ist der Scheduler in `backup_scheduler.py` der primaere
  Pfad — diese CLI ist fuer Ad-Hoc-Backups (z.B. vor Migration).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="5eyes DB-Backup-CLI")
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Pfad zur SQLite-DB (Default: settings.db_path)",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Backup-Verzeichnis (Default: settings.backup_dir)",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=None,
        help="Retention-Policy in Tagen (Default: settings.backup_retain_days)",
    )
    parser.add_argument(
        "--restore",
        type=str,
        default=None,
        help="Restore-Modus: Pfad zum Backup-File. Schreibt nach --target.",
    )
    parser.add_argument(
        "--no-verify-hash",
        action="store_true",
        help="Restore: SHA256-Sidecar-Verifikation ueberspringen",
    )
    parser.add_argument(
        "--no-verify-hmac",
        action="store_true",
        help=(
            "Restore: HMAC-Sidecar-Verifikation ueberspringen "
            "(SEC-007; wirkungslos wenn kein backup_hmac_key konfiguriert ist)"
        ),
    )
    args = parser.parse_args()

    # Settings lazy laden, damit `--help` ohne .env funktioniert.
    from config import settings  # noqa: WPS433
    from services.backup import backup_database, restore_database

    if args.restore:
        target = args.target or settings.db_path
        result = restore_database(
            backup_path=args.restore,
            target_db_path=target,
            verify_hash=not args.no_verify_hash,
            verify_hmac=not args.no_verify_hmac,
        )
        print(
            f"RESTORE ok -> {result.target_path} "
            f"({result.bytes_restored} bytes, hash_verified={result.hash_verified}, "
            f"hmac_verified={result.hmac_verified})"
        )
        return 0

    source = args.source or settings.db_path
    target = args.target or settings.backup_dir
    retain = (
        args.retain_days
        if args.retain_days is not None
        else settings.backup_retain_days
    )
    result = backup_database(
        target_dir=target,
        source_db_path=source,
        retain_days=retain,
        keep_minimum=settings.backup_keep_minimum,
    )
    print(
        f"BACKUP ok -> {result.path} "
        f"({result.bytes_written} bytes, sha256={result.sha256[:16]}..., "
        f"hmac_signed={result.hmac_signed}, "
        f"retained={result.retained_files}, pruned={result.pruned_files})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
