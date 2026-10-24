"""Sprint U-62 (Roadmap-Punkt 62, 2026-06-03): Backend-Logging Rotation
Audit-Tests.

Befund Pre-U-62
---------------
Roadmap-Notiz sagte "Backend-Logging ohne Rotation/File". Audit ergab:
core/logging_setup.py implementiert seit U-43 (LOG_DIR-Sprint) bereits
RotatingFileHandler mit maxBytes + backupCount, configure_logging()
wird in main.py @app.on_event('startup') aufgerufen.

U-62 ist also Coverage-Gap, analog zu U-58 (LoginGuard war auch schon
implementiert, nur Tests fehlten).

Diese Suite verifiziert dass die Rotations-Konfiguration tatsaechlich
greift und gegen Drift (z.B. jemand entfernt versehentlich
RotatingFileHandler) geschuetzt ist.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.logging_setup import (  # noqa: E402
    LOG_FILE_NAME,
    configure_logging,
    resolve_log_dir,
    resolve_log_file,
)


def _hard_reset_root_handlers():
    """Entferne ALLE handler am root logger (auch pytest-LogCaptureHandler)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


@pytest.fixture
def fresh_root_logger():
    """Pro Test: root-logger handler entfernen + nach Test restaurieren.

    pytest fuegt einen LogCaptureHandler hinzu der configure_logging()s
    Early-Return triggert ('if root_logger.handlers: return'). Wir
    entfernen den am Test-Start UND geben einen Helper der das
    nochmal direkt vor configure_logging tut (pytest fuegt zwischen
    Fixture-Yield und Test-Body neue Handler hinzu).
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    _hard_reset_root_handlers()
    yield root
    _hard_reset_root_handlers()
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def _configure_with_clean_handlers() -> logging.Logger:
    """Helper: killt alle Handler + ruft configure_logging() neu auf."""
    _hard_reset_root_handlers()
    configure_logging()
    return logging.getLogger()


@pytest.fixture
def tmp_log_dir(tmp_path, monkeypatch):
    """db_path -> tmp_path/db.sqlite -> Logs landen in tmp_path/logs."""
    db_file = tmp_path / "5eyes.db"
    monkeypatch.setattr("config.settings.db_path", str(db_file))
    return tmp_path / "logs"


# ---------------------------------------------------------------------------
# Log-Dir + Log-File-Resolution
# ---------------------------------------------------------------------------

def test_resolve_log_dir_creates_directory(tmp_log_dir):
    log_dir = resolve_log_dir()
    assert log_dir.exists()
    assert log_dir.is_dir()


def test_resolve_log_file_uses_log_file_name(tmp_log_dir):
    log_file = resolve_log_file()
    assert log_file.name == LOG_FILE_NAME
    assert log_file.parent == resolve_log_dir()


def test_log_file_name_is_5eyes_app_log():
    """Drift-Schutz: Dateiname bleibt stabil."""
    assert LOG_FILE_NAME == "5eyes-app.log"


# ---------------------------------------------------------------------------
# configure_logging — Handler-Setup
# ---------------------------------------------------------------------------

def test_configure_logging_adds_stream_and_file_handler(
    fresh_root_logger, tmp_log_dir,
):
    _configure_with_clean_handlers()
    handler_types = {type(h).__name__ for h in fresh_root_logger.handlers}
    assert "StreamHandler" in handler_types, (
        "StreamHandler fehlt — Stdout-Logging waere kaputt."
    )
    assert "RotatingFileHandler" in handler_types, (
        "RotatingFileHandler fehlt — Rotation greift nicht."
    )


def test_rotating_handler_respects_settings(fresh_root_logger, tmp_log_dir):
    _configure_with_clean_handlers()
    rot = next(
        h for h in fresh_root_logger.handlers
        if isinstance(h, RotatingFileHandler)
    )
    from config import settings
    assert rot.maxBytes == settings.log_max_bytes
    assert rot.backupCount == settings.log_backup_count
    assert rot.encoding == "utf-8"


def test_rotating_handler_writes_to_resolved_log_file(
    fresh_root_logger, tmp_log_dir,
):
    _configure_with_clean_handlers()
    rot = next(
        h for h in fresh_root_logger.handlers
        if isinstance(h, RotatingFileHandler)
    )
    assert Path(rot.baseFilename) == resolve_log_file()


# ---------------------------------------------------------------------------
# Idempotenz + Level
# ---------------------------------------------------------------------------

def test_configure_logging_is_idempotent(fresh_root_logger, tmp_log_dir):
    """Zweiter Aufruf adds keine zusaetzlichen Handler."""
    _configure_with_clean_handlers()
    n_handlers_first = len(fresh_root_logger.handlers)
    configure_logging()  # 2. Aufruf OHNE clean
    n_handlers_second = len(fresh_root_logger.handlers)
    assert n_handlers_first == n_handlers_second, (
        f"configure_logging() ist nicht idempotent: "
        f"{n_handlers_first} -> {n_handlers_second} Handler"
    )


def test_configure_logging_updates_level_on_second_call(
    fresh_root_logger, tmp_log_dir, monkeypatch,
):
    """Bei zweitem Aufruf MUSS Level updaten (z.B. fuer Tests)."""
    monkeypatch.setattr("config.settings.log_level", "INFO")
    _configure_with_clean_handlers()
    assert fresh_root_logger.level == logging.INFO

    monkeypatch.setattr("config.settings.log_level", "DEBUG")
    configure_logging()  # 2. Aufruf updated nur Level, kein Reset
    assert fresh_root_logger.level == logging.DEBUG


def test_configure_logging_sets_correct_level(
    fresh_root_logger, tmp_log_dir, monkeypatch,
):
    monkeypatch.setattr("config.settings.log_level", "WARNING")
    _configure_with_clean_handlers()
    assert fresh_root_logger.level == logging.WARNING


# ---------------------------------------------------------------------------
# Smoke: tatsaechliches Schreiben
# ---------------------------------------------------------------------------

def test_log_message_actually_writes_to_file(
    fresh_root_logger, tmp_log_dir,
):
    _configure_with_clean_handlers()
    logger = logging.getLogger("u62-test-logger")
    logger.warning("u62 smoke test message")
    # Force-flush aller Handler
    for h in fresh_root_logger.handlers:
        h.flush()
    log_file = resolve_log_file()
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "u62 smoke test message" in content
    assert "WARNING" in content


def test_formatter_includes_timestamp_level_name_message(
    fresh_root_logger, tmp_log_dir,
):
    """Format-Drift-Schutz: alle 4 Felder erscheinen."""
    _configure_with_clean_handlers()
    logger = logging.getLogger("u62-fmt-test")
    logger.error("formatter check msg")
    for h in fresh_root_logger.handlers:
        h.flush()
    content = resolve_log_file().read_text(encoding="utf-8")
    # asctime (Datum), levelname, name (logger-name), message
    lines = [l for l in content.splitlines() if "formatter check msg" in l]
    assert lines, "Log-Zeile fehlt"
    line = lines[-1]
    assert "|" in line
    assert "ERROR" in line
    assert "u62-fmt-test" in line


# ---------------------------------------------------------------------------
# Settings-Validation: positive numbers
# ---------------------------------------------------------------------------

def test_log_max_bytes_default_is_2mb():
    """Default 2_000_000 = ca. 2MB — vernuenftiges Mittel zwischen
    'eine Rotation pro Tag' und 'Festplatte voll'."""
    from config import settings
    assert settings.log_max_bytes == 2_000_000


def test_log_backup_count_default_is_5():
    """5 Backup-Generationen = ca. 10MB total bei Default-Size."""
    from config import settings
    assert settings.log_backup_count == 5


def test_log_max_bytes_rejects_zero(monkeypatch):
    """validate_positive_numbers verhindert 0."""
    from pydantic import ValidationError
    from config import Settings
    monkeypatch.setenv("LOG_MAX_BYTES", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_log_backup_count_rejects_zero(monkeypatch):
    from pydantic import ValidationError
    from config import Settings
    monkeypatch.setenv("LOG_BACKUP_COUNT", "0")
    with pytest.raises(ValidationError):
        Settings()
