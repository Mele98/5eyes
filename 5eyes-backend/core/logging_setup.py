import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings


LOG_FILE_NAME = '5eyes-app.log'


def resolve_log_dir() -> Path:
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

    file_handler = RotatingFileHandler(
        resolve_log_file(),
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding='utf-8',
    )
    file_handler.setFormatter(formatter)

    root_logger.setLevel(desired_level)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
