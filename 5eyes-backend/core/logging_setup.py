import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings


LOG_FILE_NAME = '5eyes-app.log'


def resolve_log_dir() -> Path:
    """Liefert das Log-Verzeichnis fuer den 5eyes-Backend.

    U-43 (Roadmap-Punkt 43, 2026-06-01): Aufloesungs-Reihenfolge:
      1. settings.log_dir (env LOG_DIR) — explizit gesetzt -> direkt nutzen
      2. Path(settings.db_path).parent / 'logs' — Backwards-Compat
         (vor U-43 die einzige Quelle)

    In packaged Electron sollte log_dir explizit auf
    app.getPath('userData')/logs zeigen, damit DB-Path und Log-Path
    unabhaengig konfigurierbar sind (z.B. DB auf Backup-Volume,
    Logs lokal).
    """
    explicit = str(getattr(settings, 'log_dir', '') or '').strip()
    if explicit:
        log_dir = Path(explicit).expanduser().resolve()
    else:
        base_dir = Path(settings.db_path).expanduser().resolve().parent
        log_dir = base_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def resolve_log_file() -> Path:
    return resolve_log_dir() / LOG_FILE_NAME


def configure_logging() -> None:
    root_logger = logging.getLogger()
    desired_level = getattr(logging, settings.log_level, logging.INFO)

    if root_logger.handlers:
        root_logger.setLevel(desired_level)
        return

    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(desired_level)
    root_logger.addHandler(stream_handler)

    # Roadmap #89 (Log-Rotation + LOG_DIR-Prod): LOG_DIR/Rotation koennen in
    # echten Produktivumgebungen an Berechtigungs- oder Volume-Problemen
    # scheitern (z.B. LOG_DIR zeigt auf ein read-only oder noch nicht
    # gemountetes Verzeichnis). Ein Schreibfehler hier darf den App-Start
    # NICHT zum Absturz bringen — Fallback ist Konsolen-Logging (bereits
    # oben registriert) + eine Warnung, statt die FastAPI-Lifespan mit einer
    # unbehandelten Exception abzubrechen.
    try:
        file_handler = RotatingFileHandler(
            resolve_log_file(),
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError as exc:
        root_logger.warning(
            'Log-Datei-Handler konnte nicht initialisiert werden (LOG_DIR=%r): %s '
            '- Logging faellt auf Konsole zurueck.',
            getattr(settings, 'log_dir', '') or settings.db_path,
            exc,
        )
