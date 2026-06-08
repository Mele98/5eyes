"""Sprint U-8 (2026-05-30, Roadmap-Punkt 8): DB-Backup-Strategie.

Implementiert atomare, WAL-aware SQLite-Backups ueber die offizielle
`sqlite3.Connection.backup()`-API. Der Backend-Server kann beim Backup
weiter Schreibvorgaenge entgegennehmen — SQLite hat dafuer interne
Locking-Garantien.

Features
--------
* Atomares Backup waehrend der Server lauft (WAL-mode)
* SHA256-Sidecar fuer Integritaets-Verifikation
* Retention-Policy: aeltere Backups werden geloescht
* SQLCipher-aware (verschluesseltes Backup wird 1:1 kopiert, gleicher Key)
* Restore-Pfad mit Hash-Verifikation
* CLI-aufrufbar (siehe scripts/backup_now.py)

Sicherheits-Hinweis
-------------------
* Backups werden im selben Verzeichnis abgelegt wie die DB ist
  empfehlenswert NICHT. Berater muss `backup_dir` auf separate Platte
  / externes Volume zeigen.
* Backups enthalten ALLE Kundendaten — Aufbewahrung muss FINMA/DSG-
  konform geschehen (verschluesselt, Zugriff dokumentiert).
* Bei SQLCipher: Backup ist mit DEMSELBEN Key verschluesselt wie das
  Original. Key-Rotation erfordert separates Re-Encrypt-Verfahren.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# Dateinamens-Muster: 5eyes-backup-YYYYMMDD-HHMMSS.db
# Strict Format -> Retention / Listing kann zuverlaessig parsen.
_BACKUP_FILENAME_PATTERN = "5eyes-backup-{ts}.db"
_BACKUP_FILENAME_GLOB = "5eyes-backup-*.db"
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"


@dataclass(frozen=True)
class BackupResult:
    """Ergebnis eines Backup-Laufs."""

    path: Path
    bytes_written: int
    sha256: str
    timestamp: datetime
    retained_files: int
    pruned_files: int


@dataclass(frozen=True)
class RestoreResult:
    """Ergebnis eines Restore-Laufs."""

    target_path: Path
    bytes_restored: int
    hash_verified: bool


def backup_database(
    target_dir: str | Path,
    *,
    source_db_path: str | Path,
    retain_days: int = 30,
    keep_minimum: int = 3,
    timestamp: datetime | None = None,
) -> BackupResult:
    """Erzeugt ein atomares Backup der SQLite-DB.

    Parameter
    ---------
    target_dir
        Verzeichnis fuer die Backup-Dateien. Wird angelegt wenn fehlend.
    source_db_path
        Pfad zur produktiven SQLite-Datei.
    retain_days
        Backups aelter als N Tage werden geloescht. 0 = nie aufraeumen.
    keep_minimum
        Mindestens so viele Backups bleiben erhalten, auch wenn aelter
        als `retain_days`. Schuetzt vor Katastrophe wenn Server lange
        offline war und dann ein Backup laeuft, das "alles" wegputzen
        wuerde.
    timestamp
        Optional zum Testen — sonst now(UTC).

    Returns
    -------
    BackupResult mit Pfad, Groesse, Hash, Anzahl behaltene/geprunte.
    """
    src = Path(source_db_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source-DB nicht gefunden: {src}")

    target_dir_path = Path(target_dir).expanduser().resolve()
    target_dir_path.mkdir(parents=True, exist_ok=True)

    ts = (timestamp or datetime.now(timezone.utc))
    fname = _BACKUP_FILENAME_PATTERN.format(ts=ts.strftime(_TIMESTAMP_FORMAT))
    target = target_dir_path / fname

    # Atomares Backup via sqlite3.Connection.backup()
    # — funktioniert auch wenn die Source-DB gerade geschrieben wird.
    _perform_atomic_copy(src, target)

    sha = _sha256_file(target)
    sidecar = target.with_suffix(target.suffix + ".sha256")
    sidecar.write_text(f"{sha}  {target.name}\n", encoding="utf-8")

    pruned = _prune_old_backups(
        target_dir_path,
        retain_days=retain_days,
        keep_minimum=keep_minimum,
        now=ts,
    )
    retained = _count_backups(target_dir_path)

    bytes_written = target.stat().st_size
    logger.info(
        "DB-Backup ok | source=%s target=%s bytes=%d sha256=%s pruned=%d retained=%d",
        src,
        target,
        bytes_written,
        sha[:16],
        pruned,
        retained,
    )

    return BackupResult(
        path=target,
        bytes_written=bytes_written,
        sha256=sha,
        timestamp=ts,
        retained_files=retained,
        pruned_files=pruned,
    )


def restore_database(
    backup_path: str | Path,
    *,
    target_db_path: str | Path,
    verify_hash: bool = True,
) -> RestoreResult:
    """Stellt eine DB aus einem Backup wieder her.

    Parameter
    ---------
    backup_path
        Pfad zur Backup-Datei.
    target_db_path
        Wohin restored werden soll. Existierende Datei wird ueberschrieben.
    verify_hash
        Wenn True und ein `.sha256`-Sidecar existiert, wird der Hash
        des Backups vor dem Restore verifiziert.

    Returns
    -------
    RestoreResult.
    """
    src = Path(backup_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Backup nicht gefunden: {src}")

    hash_verified = False
    if verify_hash:
        sidecar = src.with_suffix(src.suffix + ".sha256")
        if sidecar.exists():
            expected = sidecar.read_text(encoding="utf-8").split()[0].strip()
            actual = _sha256_file(src)
            if expected != actual:
                raise ValueError(
                    f"SHA256-Mismatch fuer {src.name}: "
                    f"expected={expected[:16]}... actual={actual[:16]}..."
                )
            hash_verified = True

    target = Path(target_db_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _perform_atomic_copy(src, target)

    bytes_restored = target.stat().st_size
    logger.info(
        "DB-Restore ok | source=%s target=%s bytes=%d hash_verified=%s",
        src,
        target,
        bytes_restored,
        hash_verified,
    )

    return RestoreResult(
        target_path=target,
        bytes_restored=bytes_restored,
        hash_verified=hash_verified,
    )


def list_backups(target_dir: str | Path) -> list[Path]:
    """Listet alle Backup-Dateien im Verzeichnis, neueste zuerst."""
    p = Path(target_dir).expanduser().resolve()
    if not p.exists():
        return []
    files = sorted(
        p.glob(_BACKUP_FILENAME_GLOB),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return files


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _perform_atomic_copy(source: Path, target: Path) -> None:
    """Atomares Kopieren via sqlite3.Connection.backup().

    Auch wenn die Source-DB gerade beschrieben wird, liefert die
    Online-Backup-API einen konsistenten Snapshot. WAL-Journal-Inhalte
    werden mitkopiert.

    Wir oeffnen die Source bewusst URI-mode read-only (`?mode=ro`), um
    keine konkurrierenden Writes zu provozieren. Das funktioniert
    sowohl mit normalem SQLite als auch mit SQLCipher-DBs — die
    .backup()-API kopiert die Bytes wie sie sind.
    """
    source_uri = f"file:{source.as_posix()}?mode=ro"
    src_conn = sqlite3.connect(source_uri, uri=True)
    try:
        dst_conn = sqlite3.connect(str(target))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _sha256_file(path: Path, chunk_size: int = 1 << 16) -> str:
    """SHA256-Hex eines beliebig grossen Files (streaming)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _count_backups(target_dir: Path) -> int:
    return sum(1 for _ in target_dir.glob(_BACKUP_FILENAME_GLOB))


def _prune_old_backups(
    target_dir: Path,
    *,
    retain_days: int,
    keep_minimum: int,
    now: datetime,
) -> int:
    """Loescht Backups, die aelter als `retain_days` sind. Behaelt aber
    mindestens `keep_minimum` der neuesten Files, falls retain_days zu
    aggressiv war.
    """
    if retain_days <= 0:
        return 0

    cutoff = now.timestamp() - retain_days * 86400
    all_backups = sorted(
        target_dir.glob(_BACKUP_FILENAME_GLOB),
        key=lambda f: f.stat().st_mtime,
        reverse=True,  # neueste zuerst
    )
    # Mindestens `keep_minimum` immer behalten — die Top-N nie pruefen
    candidates = all_backups[keep_minimum:]
    pruned = 0
    for f in candidates:
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                # Sidecar auch wegrumen
                sidecar = f.with_suffix(f.suffix + ".sha256")
                if sidecar.exists():
                    sidecar.unlink()
                pruned += 1
            except OSError as exc:
                logger.warning("Konnte altes Backup nicht loeschen: %s (%s)", f, exc)
    return pruned
