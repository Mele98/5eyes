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
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from database import SQLCIPHER_AVAILABLE, _sqlcipher_enabled, sqlcipher3

logger = logging.getLogger(__name__)


# Dateinamens-Muster: 5eyes-backup-YYYYMMDD-HHMMSS.db
# Strict Format -> Retention / Listing kann zuverlaessig parsen.
_BACKUP_FILENAME_PATTERN = "5eyes-backup-{ts}.db"
_BACKUP_FILENAME_GLOB = "5eyes-backup-*.db"
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# AB-1: Temp-Dateien beim atomaren Schreiben. Werden bei Absturz sichtbar
# als Ruinen liegen gelassen, aber NIE als reguläres Backup gelistet/gepruned.
_PARTIAL_SUFFIX = ".partial"
_PARTIAL_GLOB = "*" + _PARTIAL_SUFFIX


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
    db_key: str | None = None,
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
    db_key
        Optional -- SQLCipher-Key fuer Source (und damit auch Ziel-Kopie).
        Default: `settings.db_key` (identisch zum laufenden Server).
        Nur relevant wenn `settings.db_use_sqlcipher=True`.

    Returns
    -------
    BackupResult mit Pfad, Groesse, Hash, Anzahl behaltene/geprunte.
    """
    src = Path(source_db_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source-DB nicht gefunden: {src}")

    target_dir_path = Path(target_dir).expanduser().resolve()
    target_dir_path.mkdir(parents=True, exist_ok=True)

    # AB-1: Verwaiste Temp-Dateien frueherer, abgebrochener Laeufe entfernen.
    _remove_orphaned_partials(target_dir_path)

    ts = (timestamp or datetime.now(timezone.utc))
    fname = _BACKUP_FILENAME_PATTERN.format(ts=ts.strftime(_TIMESTAMP_FORMAT))
    target = target_dir_path / fname

    # Wirklich atomares Backup: Temp-Datei -> integrity_check -> os.replace.
    # Die Integritaetspruefung passiert VOR dem sichtbaren Rename (in
    # _perform_atomic_copy); erst ein "ok" macht das Backup sichtbar.
    _perform_atomic_copy(src, target, db_key=db_key)

    # Sidecar ERST nach dem Backup-Rename, ebenfalls via Temp+Replace,
    # damit Backup + Sidecar aus Lesersicht atomar erscheinen.
    sha = _sha256_file(target)
    sidecar = target.with_suffix(target.suffix + ".sha256")
    _write_sidecar_atomically(sidecar, f"{sha}  {target.name}\n")

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
    db_key: str | None = None,
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
    db_key
        Optional -- SQLCipher-Key des Backups. Default: `settings.db_key`.
        Nur relevant wenn `settings.db_use_sqlcipher=True`.

    Returns
    -------
    RestoreResult.
    """
    src = Path(backup_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Backup nicht gefunden: {src}")

    hash_verified = False
    if verify_hash:
        # AB-1: Strikte Verifikation. Ein fehlendes ODER mismatchtes Sidecar
        # fuehrt zum Abbruch — NIE stilles Ueberschreiben der Live-DB mit
        # einem unverifizierten (moeglicherweise korrupten) Backup.
        sidecar = src.with_suffix(src.suffix + ".sha256")
        if not sidecar.exists():
            raise ValueError(
                f"Kein SHA256-Sidecar fuer {src.name} — Restore mit "
                f"verify_hash=True abgelehnt (fehlende Integritaetsgarantie)."
            )
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
    # Einspielen in die produktive DB ebenfalls via Temp+os.replace
    # (inkl. integrity_check der Kopie) — abgebrochener Restore hinterlaesst
    # die Live-DB unveraendert.
    _perform_atomic_copy(src, target, db_key=db_key)

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
        _list_backup_files(p),  # *.partial ausgeschlossen
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return files


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _fsync_path(path: Path) -> None:
    """fsync einer Datei (best-effort). Fehler werden geloggt, nicht geworfen."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError as exc:  # pragma: no cover - plattformabhaengig
        logger.debug("fsync: konnte %s nicht oeffnen (%s)", path, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:  # pragma: no cover - plattformabhaengig
        logger.debug("fsync fehlgeschlagen fuer %s (%s)", path, exc)
    finally:
        os.close(fd)


def _fsync_dir(directory: Path) -> None:
    """fsync des Verzeichnisses, damit der Rename durable ist.

    Auf Windows lassen sich Verzeichnisse nicht mit os.open()/os.fsync()
    synchronisieren — dort ist os.replace() bereits atomar und der
    Directory-fsync entfaellt best-effort (kein Fehler).
    """
    if os.name != "posix":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError as exc:  # pragma: no cover - plattformabhaengig
        logger.debug("dir-fsync: konnte %s nicht oeffnen (%s)", directory, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:  # pragma: no cover - plattformabhaengig
        logger.debug("dir-fsync fehlgeschlagen fuer %s (%s)", directory, exc)
    finally:
        os.close(fd)


def _open_connection(path_or_uri: str, *, uri: bool, db_key: str | None) -> sqlite3.Connection:
    """Oeffnet eine SQLite- oder SQLCipher-Connection, je nach Konfiguration.

    Mega-Audit (2026-08-04): Der Modul-Docstring behauptete SQLCipher-
    Kompatibilitaet ("Bytes 1:1"), tatsaechlich importierte die gesamte
    Datei ausschliesslich das stdlib `sqlite3`-Modul -- ein `sqlite3.connect()`
    gegen eine SQLCipher-verschluesselte DB kann die Datei nicht lesen
    (kein PRAGMA key), jeder Backup-/Restore-Versuch waere mit einer
    verschluesselten Produktions-DB fehlgeschlagen.

    Bei aktivem SQLCipher (`settings.db_use_sqlcipher` + Key) wird
    `sqlcipher3` verwendet und Key + Cipher-Pragmas exakt nach dem in
    `database.py` (create_app_engine/attach_sqlite_pragmas,
    bootstrap_sqlite_schema) etablierten Muster gesetzt. Source UND Ziel
    bekommen denselben Key/dieselben Cipher-Parameter, damit
    `Connection.backup()` verschluesselte Seiten 1:1 kopieren kann.
    Ohne SQLCipher: unveraendertes Verhalten (stdlib sqlite3).
    """
    key = db_key if db_key is not None else settings.db_key
    if _sqlcipher_enabled(db_key=key):
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                "DB_USE_SQLCIPHER=true ist gesetzt, aber sqlcipher3 ist nicht "
                "installiert -- Backup/Restore einer verschluesselten Datenbank "
                "ist nicht moeglich. Installiere sqlcipher3-binary oder sqlcipher3."
            )
        conn = sqlcipher3.connect(path_or_uri, uri=uri)
        conn.execute("PRAGMA key = ?", [key or ""])
        conn.execute("PRAGMA cipher_page_size = 4096")
        conn.execute("PRAGMA kdf_iter = 256000")
        conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
        conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
        return conn
    return sqlite3.connect(path_or_uri, uri=uri)


def _integrity_check_ok(db_path: Path, *, db_key: str | None = None) -> bool:
    """Oeffnet die (fertig geschriebene) DB read-only und prueft
    `PRAGMA integrity_check`. True nur bei exakt "ok".
    """
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = _open_connection(uri, uri=True, db_key=db_key)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    return len(rows) == 1 and str(rows[0][0]).lower() == "ok"


def _perform_atomic_copy(source: Path, target: Path, *, db_key: str | None = None) -> None:
    """Wirklich atomares Kopieren einer SQLite-DB (AB-1).

    Ablauf:
      1. Online-Backup via sqlite3.Connection.backup() in eine eindeutige
         Temp-Datei im SELBEN Zielverzeichnis (damit os.replace atomar auf
         demselben Dateisystem laeuft).
      2. Temp-Datei read-only wieder oeffnen und `PRAGMA integrity_check`.
      3. Nur bei "ok": fsync(Datei) -> os.replace(temp, final) -> fsync(dir).
      4. Bei JEDEM Fehler: Temp-Datei entfernen und Exception weiterreichen.

    Auch wenn die Source-DB gerade beschrieben wird, liefert die
    Online-Backup-API einen konsistenten Snapshot. WAL-Journal-Inhalte
    werden mitkopiert. Source wird bewusst URI-mode read-only (`?mode=ro`)
    geoeffnet. Funktioniert mit normalem SQLite und SQLCipher (Bytes 1:1,
    ueber `_open_connection` -- siehe dort).
    """
    target_dir = target.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    # Eindeutige Temp-Datei im Zielverzeichnis (gleiches Dateisystem).
    fd, temp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=_PARTIAL_SUFFIX, dir=str(target_dir)
    )
    os.close(fd)
    temp = Path(temp_name)

    try:
        source_uri = f"file:{source.as_posix()}?mode=ro"
        src_conn = _open_connection(source_uri, uri=True, db_key=db_key)
        try:
            dst_conn = _open_connection(str(temp), uri=False, db_key=db_key)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        # Integritaet der frisch geschriebenen Kopie verifizieren.
        if not _integrity_check_ok(temp, db_key=db_key):
            raise ValueError(
                f"integrity_check fehlgeschlagen fuer Backup-Temp {temp.name}"
            )

        # Durabilitaet: Dateiinhalt auf Platte, dann atomarer Rename.
        _fsync_path(temp)
        os.replace(str(temp), str(target))
        _fsync_dir(target_dir)
    except BaseException:
        # Abbruch zwischen Temp-Schreiben und Rename -> Temp entfernen,
        # damit KEINE gueltig benannte, aber unvollstaendige Datei bleibt.
        try:
            if temp.exists():
                temp.unlink()
        except OSError as exc:  # pragma: no cover
            logger.warning("Konnte Temp-Backup nicht entfernen: %s (%s)", temp, exc)
        raise


def _remove_orphaned_partials(target_dir: Path) -> int:
    """Entfernt verwaiste *.partial-Dateien (Ruinen abgebrochener Laeufe)."""
    if not target_dir.exists():
        return 0
    removed = 0
    for f in target_dir.glob(_PARTIAL_GLOB):
        try:
            f.unlink()
            removed += 1
        except OSError as exc:  # pragma: no cover
            logger.warning("Konnte verwaiste Temp-Datei nicht loeschen: %s (%s)", f, exc)
    return removed


def _write_sidecar_atomically(sidecar: Path, content: str) -> None:
    """Schreibt das .sha256-Sidecar via Temp+os.replace, damit Backup und
    Sidecar atomar (aus Sicht des Lesers) erscheinen.
    """
    target_dir = sidecar.parent
    fd, temp_name = tempfile.mkstemp(
        prefix=sidecar.name + ".", suffix=_PARTIAL_SUFFIX, dir=str(target_dir)
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(temp), str(sidecar))
        _fsync_dir(target_dir)
    except BaseException:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:  # pragma: no cover
            pass
        raise


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


def _list_backup_files(target_dir: Path) -> list[Path]:
    """Alle regulaeren Backup-Dateien — *.partial werden ausgeschlossen."""
    return [
        f
        for f in target_dir.glob(_BACKUP_FILENAME_GLOB)
        if f.suffix != _PARTIAL_SUFFIX and not f.name.endswith(_PARTIAL_SUFFIX)
    ]


def _count_backups(target_dir: Path) -> int:
    return len(_list_backup_files(target_dir))


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
        _list_backup_files(target_dir),  # *.partial ausgeschlossen
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
