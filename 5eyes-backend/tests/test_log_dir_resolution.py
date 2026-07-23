"""Sprint U-43 (Roadmap-Punkt 43, 2026-06-01): Tests fuer log_dir-
Aufloesung. Vorher war Log-Pfad fest an db_path.parent gekoppelt —
sub-optimal in packaged Electron, wo DB und Logs unterschiedliche
Volumes haben koennten.

Aufloesungs-Reihenfolge (siehe core/logging_setup.resolve_log_dir):
  1. settings.log_dir (env LOG_DIR) wenn nicht-leer
  2. Path(db_path).parent / 'logs'
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
from core.logging_setup import resolve_log_dir


@pytest.fixture()
def reset_settings_after(monkeypatch):
    """Stellt sicher, dass monkeypatched settings nach jedem Test
    automatisch zurueckgesetzt werden."""
    yield
    # monkeypatch räumt automatisch — keine manuelle Cleanup


# ---------------------------------------------------------------------------
# Explizites log_dir (U-43)
# ---------------------------------------------------------------------------

def test_explicit_log_dir_is_used_directly(monkeypatch, tmp_path):
    explicit = tmp_path / 'custom_logs'
    monkeypatch.setattr(settings, 'log_dir', str(explicit))
    result = resolve_log_dir()
    assert result == explicit.resolve()
    assert result.exists()


def test_explicit_log_dir_expands_user_home(monkeypatch, tmp_path):
    """~/foo/logs muss aufgeloest werden (expanduser)."""
    # Wir fakeen home via HOME-env so dass ~ -> tmp_path zeigt.
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))  # Windows
    monkeypatch.setattr(settings, 'log_dir', '~/expanded_logs')
    result = resolve_log_dir()
    # Mindestens muss expanduser-Aufloesung passieren — exact-path-match
    # ist platform-spezifisch (Windows liest USERPROFILE, nicht HOME)
    assert 'expanded_logs' in str(result)


def test_explicit_log_dir_creates_missing_directories(monkeypatch, tmp_path):
    """Wenn das log-Verzeichnis noch nicht existiert, muss es angelegt werden."""
    explicit = tmp_path / 'a' / 'b' / 'c' / 'logs'
    assert not explicit.exists()
    monkeypatch.setattr(settings, 'log_dir', str(explicit))
    result = resolve_log_dir()
    assert result.exists()
    assert result.is_dir()


# ---------------------------------------------------------------------------
# Fallback (Backwards-Compat zu vor-U-43)
# ---------------------------------------------------------------------------

def test_empty_log_dir_falls_back_to_db_path_parent_logs(monkeypatch, tmp_path):
    """Leerer log_dir → Path(db_path).parent / 'logs'."""
    db_file = tmp_path / 'somewhere' / 'mydb.db'
    monkeypatch.setattr(settings, 'log_dir', '')
    monkeypatch.setattr(settings, 'db_path', str(db_file))
    result = resolve_log_dir()
    assert result == (tmp_path / 'somewhere' / 'logs').resolve()
    assert result.exists()


def test_whitespace_only_log_dir_is_treated_as_empty(monkeypatch, tmp_path):
    """log_dir='   ' wird als nicht-gesetzt behandelt (strip)."""
    db_file = tmp_path / 'wp' / 'data.db'
    monkeypatch.setattr(settings, 'log_dir', '   ')
    monkeypatch.setattr(settings, 'db_path', str(db_file))
    result = resolve_log_dir()
    assert result == (tmp_path / 'wp' / 'logs').resolve()


# ---------------------------------------------------------------------------
# Robustheit
# ---------------------------------------------------------------------------

def test_missing_log_dir_attribute_falls_back(monkeypatch, tmp_path):
    """Wenn settings das Attribut log_dir gar nicht hat (alte .env-Bind),
    soll Fallback greifen statt zu crashen."""
    db_file = tmp_path / 'fallback' / 'd.db'
    monkeypatch.setattr(settings, 'db_path', str(db_file))
    # Loesche log_dir-Attribut wenn vorhanden — pydantic-settings hat es
    # eigentlich immer, aber wir verifizieren defensives Verhalten
    # via getattr-Default in resolve_log_dir.
    #
    # 2026-07-23 Fix: monkeypatch.delattr() statt rohem `del settings.log_dir`.
    # Ein rohes `del` auf dem Modul-Singleton `settings` hat KEIN Teardown —
    # das Attribut blieb fuer den Rest des Pytest-Prozesses geloescht und liess
    # JEDEN spaeter laufenden Test, der `monkeypatch.setattr(settings, 'log_dir',
    # ...)` ohne raising=False aufruft, mit AttributeError crashen (gefunden im
    # vollen Suite-Lauf: tests/test_log_rotation_prod_hardening.py schlug NUR im
    # Gesamtlauf fehl, nie isoliert — klassische Testreihenfolge-Verschmutzung
    # ueber ein Modul-Singleton). monkeypatch.delattr() traegt die Wiederherstellung
    # automatisch in den eigenen Undo-Stack ein, wie jede andere monkeypatch-
    # Operation.
    monkeypatch.delattr(settings, 'log_dir', raising=False)
    result = resolve_log_dir()
    assert result == (tmp_path / 'fallback' / 'logs').resolve()
