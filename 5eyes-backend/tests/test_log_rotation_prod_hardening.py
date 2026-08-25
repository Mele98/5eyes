"""Roadmap #89 (Log-Rotation + LOG_DIR-Prod).

Audit-Befund vor #89
---------------------
LOG_DIR ist bereits konfigurierbar (U-43) und Rotation via
RotatingFileHandler ist bereits verdrahtet + auditiert (U-62,
test_logging_rotation_audit.py). Die verbleibende Luecke fuer echten
Produktivbetrieb: configure_logging() wird in main.py's FastAPI-Lifespan
aufgerufen (@asynccontextmanager async def lifespan). Wenn LOG_DIR (oder
dessen Fallback Path(db_path).parent/'logs') zur Laufzeit nicht schreibbar
ist -- z.B. falsch konfiguriertes Volume, fehlende Berechtigung in einem
Container/Service-User-Setup -- wirft RotatingFileHandler(...) bzw. das
zugrunde liegende mkdir() eine OSError, die VOR #89 unbehandelt durch
configure_logging() nach main.py durchschlug und den App-Start crashte.

Diese Suite deckt ab:
  (a) Rotation-Handler wird in production/staging korrekt aus den
      Settings konfiguriert (max_bytes/backup_count) -- Regressionsschutz,
      dass die Konfiguration envs-unabhaengig bleibt.
  (b) In development bleibt das Verhalten unveraendert (weiterhin
      Stream- + RotatingFileHandler, wie vor #89) -- #89 haertet nur
      Fehlerpfade, es gibt keine Env-Gate-Umstellung, um bestehendes,
      funktionierendes Verhalten nicht zu duplizieren/zu brechen.
  (c) LOG_DIR-Erstellung/Handler-Oeffnung ist crash-sicher: ein
      Schreibfehler (z.B. PermissionError) darf configure_logging()
      NICHT crashen lassen -- Fallback ist Konsolen-Logging + Warnung.
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

from config import settings  # noqa: E402
from core.logging_setup import configure_logging, resolve_log_file  # noqa: E402


def _hard_reset_root_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


@pytest.fixture
def fresh_root_logger():
    """Root-Logger isolieren: Handler vor/nach Test sichern+restaurieren."""
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
    _hard_reset_root_handlers()
    configure_logging()
    return logging.getLogger()


@pytest.fixture
def tmp_log_dir(tmp_path, monkeypatch):
    """db_path -> tmp_path/db.sqlite -> Logs landen in tmp_path/logs."""
    db_file = tmp_path / "5eyes.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    # raising=False: robuster gegen Testreihenfolge-Verschmutzung (siehe
    # 2026-07-23-Fix in test_log_dir_resolution.py -- ein anderer Test hatte
    # das Attribut per rohem `del` ohne Teardown vom Settings-Singleton
    # entfernt; monkeypatch.setattr() mit dem strikten Default (raising=True)
    # verlangt, dass das Attribut bereits existiert).
    monkeypatch.setattr(settings, "log_dir", "", raising=False)
    return tmp_path / "logs"


# ---------------------------------------------------------------------------
# (a) Rotation korrekt in production/staging
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env", ["production", "staging"])
def test_rotation_handler_configured_from_settings_in_prod_like_envs(
    fresh_root_logger, tmp_log_dir, monkeypatch, env,
):
    monkeypatch.setattr(settings, "app_env", env)
    monkeypatch.setattr(settings, "log_max_bytes", 1_234_567)
    monkeypatch.setattr(settings, "log_backup_count", 7)
    _configure_with_clean_handlers()

    rot = next(
        h for h in fresh_root_logger.handlers
        if isinstance(h, RotatingFileHandler)
    )
    assert rot.maxBytes == 1_234_567
    assert rot.backupCount == 7
    assert Path(rot.baseFilename) == resolve_log_file()


# ---------------------------------------------------------------------------
# (b) development bleibt unveraendert
# ---------------------------------------------------------------------------

def test_development_env_keeps_stream_and_file_handler_unchanged(
    fresh_root_logger, tmp_log_dir, monkeypatch,
):
    """#89 aendert das Env-Gating NICHT (kein Rotation-Handler existierte
    schon vorher fuer alle Envs inkl. development) -- dev-Verhalten bleibt
    identisch zu vor #89."""
    monkeypatch.setattr(settings, "app_env", "development")
    _configure_with_clean_handlers()

    handler_types = {type(h).__name__ for h in fresh_root_logger.handlers}
    assert handler_types == {"StreamHandler", "RotatingFileHandler"}


# ---------------------------------------------------------------------------
# (c) Crash-Sicherheit bei Schreibfehler
# ---------------------------------------------------------------------------

def test_permission_error_on_file_handler_does_not_crash_startup(
    fresh_root_logger, tmp_log_dir, monkeypatch,
):
    """Simuliert einen Produktions-Fall (z.B. LOG_DIR nicht schreibbar):
    RotatingFileHandler-Konstruktion wirft PermissionError. configure_logging()
    darf das NICHT nach main.py's Lifespan durchreichen -- App-Start haengt
    daran (asynccontextmanager lifespan)."""
    monkeypatch.setattr(settings, "app_env", "production")
    _hard_reset_root_handlers()

    with patch(
        "core.logging_setup.RotatingFileHandler",
        side_effect=PermissionError("Zugriff verweigert (simuliert)"),
    ):
        configure_logging()  # darf NICHT raisen

    root = logging.getLogger()
    handler_types = {type(h).__name__ for h in root.handlers}
    assert "StreamHandler" in handler_types, (
        "Konsolen-Fallback fehlt -- ganz ohne Logging waere Diagnose in "
        "Prod unmoeglich."
    )
    assert "RotatingFileHandler" not in handler_types


def test_log_dir_mkdir_failure_does_not_crash_startup(
    fresh_root_logger, tmp_log_dir, monkeypatch,
):
    """Der Fehler kann auch aus resolve_log_dir()'s mkdir() selbst kommen
    (z.B. Elternverzeichnis read-only) statt aus dem Handler-Konstruktor."""
    monkeypatch.setattr(settings, "app_env", "production")
    _hard_reset_root_handlers()

    with patch(
        "core.logging_setup.Path.mkdir",
        side_effect=PermissionError("mkdir verweigert (simuliert)"),
    ):
        configure_logging()  # darf NICHT raisen

    root = logging.getLogger()
    handler_types = {type(h).__name__ for h in root.handlers}
    assert "StreamHandler" in handler_types
    assert "RotatingFileHandler" not in handler_types


def test_warning_is_emitted_on_fallback(fresh_root_logger, tmp_log_dir, monkeypatch, capsys):
    """Der Fallback muss sichtbar sein (nicht silent) -- sonst merkt Ops
    in Prod nie, dass Datei-Logging fehlt. configure_logging() fuegt den
    StreamHandler VOR dem riskanten Datei-Handler-Setup hinzu, daher landet
    die Warnung auf stdout (dort verifiziert statt via caplog, weil
    caplog's eigener Root-Handler durch den harten Reset entfernt wuerde
    und configure_logging() sonst -- wegen 'if root_logger.handlers: return'
    -- gar nicht bis zum Datei-Handler-Setup kaeme)."""
    monkeypatch.setattr(settings, "app_env", "production")
    _hard_reset_root_handlers()

    with patch(
        "core.logging_setup.RotatingFileHandler",
        side_effect=OSError("Disk voll (simuliert)"),
    ):
        configure_logging()

    captured = capsys.readouterr()
    assert "Log-Datei-Handler konnte nicht initialisiert werden" in captured.out


def test_configure_logging_still_idempotent_after_fallback(
    fresh_root_logger, tmp_log_dir, monkeypatch,
):
    """Nach einem Fallback (nur StreamHandler) darf ein zweiter Aufruf
    keine weiteren Handler anhaeufen -- bestehende Idempotenz-Garantie
    (U-62) muss auch im Fehlerpfad gelten."""
    monkeypatch.setattr(settings, "app_env", "production")
    _hard_reset_root_handlers()

    with patch(
        "core.logging_setup.RotatingFileHandler",
        side_effect=PermissionError("simuliert"),
    ):
        configure_logging()

    root = logging.getLogger()
    n_after_fallback = len(root.handlers)
    configure_logging()  # 2. Aufruf, kein neuer Versuch (handlers bereits gesetzt)
    assert len(root.handlers) == n_after_fallback
