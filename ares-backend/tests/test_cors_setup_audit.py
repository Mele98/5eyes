"""Sprint U-60 (Roadmap-Punkt 60, 2026-06-01): CORS-Setup-Audit + Tests.

Hintergrund
-----------
main.py konfiguriert FastAPI-CORSMiddleware mit:
  allow_origins      = settings.cors_origins
  allow_origin_regex = settings.cors_allow_origin_regex
  allow_credentials  = True
  allow_methods      = ['*']
  allow_headers      = ['*']

Diese Suite verifiziert:
- Default-Origins decken die Electron- und Dev-Browser-Setups ab
- Production-Validator wirft bei Localhost-Origins
- Wildcard '*' in Origins wird IMMER abgelehnt (Browser-Spec-Verletzung
  mit credentials=True)
- 'null' Origin ist da (Electron-Sub-App Cross-Origin)
- Regex erlaubt 'null' als zusaetzliche Variante

Sicherheits-Modell (Stand 2026-06-01)
-------------------------------------
- credentials=True heisst Browser sendet Cookies/Authorization-Header
  bei cross-origin requests
- Mit '*' in allow_origins waere das Spec-Violation — Browser ignoriert
  CORS-Header und blockt
- Daher: explizite Origin-Whitelist Pflicht
- 'null' ist Sonder-Origin fuer file://-Loader (Electron Sub-App Browser-
  Variante) — sichere Verwendung wenn der Backend-Process strikt lokal ist
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import Settings, settings


# ---------------------------------------------------------------------------
# Default-Origins decken bekannte Browser-Setups
# ---------------------------------------------------------------------------

def test_defaults_include_electron_null_origin():
    """Electron Sub-App (file://) sendet Origin: null — Browser-Spec."""
    assert 'null' in settings.cors_origins


def test_defaults_include_electron_app_protocol():
    """Packaged Electron mit electron-builder nutzt app:// — siehe PR #105."""
    assert any('app://' in str(o) for o in settings.cors_origins)


def test_defaults_include_dev_browser_localhost_5173():
    """Vite-Dev-Server der Reporting Sub-App laeuft auf 5173."""
    assert 'http://localhost:5173' in settings.cors_origins


def test_defaults_include_127_0_0_1_variant():
    """Manche Browser senden 127.0.0.1 statt localhost."""
    assert any('127.0.0.1' in str(o) for o in settings.cors_origins)


def test_regex_matches_null_origin():
    """cors_allow_origin_regex muss 'null' matchen (zweite Schiene
    falls Origin-Liste verkuerzt wird)."""
    import re
    pattern = settings.cors_allow_origin_regex
    assert pattern is not None
    assert re.match(pattern, 'null') is not None


# ---------------------------------------------------------------------------
# Production-Safety-Validator (U-60)
# ---------------------------------------------------------------------------

def test_production_rejects_localhost_in_origins(monkeypatch):
    """Production darf KEINE localhost-Origins haben — Berater-Setup
    ist nicht von Localhost zugreifbar."""
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'strong-random-key-1234567890abcdefghij')
    monkeypatch.setenv('DB_USE_SQLCIPHER', 'true')
    monkeypatch.setenv('DB_KEY', 'strong-db-key-abc1234567890')
    # CORS_ORIGINS via env-string (pydantic-settings JSON-parsing)
    monkeypatch.setenv('CORS_ORIGINS', '["http://localhost:5173","app://."]')
    with pytest.raises(ValidationError, match=r'localhost'):
        Settings()


def test_production_rejects_127_0_0_1_in_origins(monkeypatch):
    """127.0.0.1 ist auch verboten in production."""
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'strong-random-key-1234567890abcdefghij')
    monkeypatch.setenv('DB_USE_SQLCIPHER', 'true')
    monkeypatch.setenv('DB_KEY', 'strong-db-key-abc1234567890')
    monkeypatch.setenv('CORS_ORIGINS', '["http://127.0.0.1:5173","app://."]')
    with pytest.raises(ValidationError, match=r'127.0.0.1|localhost'):
        Settings()


def test_production_accepts_app_only_origins(monkeypatch):
    """Production mit nur app:// + null soll problemlos starten."""
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'strong-random-key-1234567890abcdefghij')
    monkeypatch.setenv('DB_USE_SQLCIPHER', 'true')
    monkeypatch.setenv('DB_KEY', 'strong-db-key-abc1234567890')
    monkeypatch.setenv('CORS_ORIGINS', '["app://.","null"]')
    settings_prod = Settings()
    assert 'app://.' in settings_prod.cors_origins
    assert 'null' in settings_prod.cors_origins


# ---------------------------------------------------------------------------
# Wildcard-Safety (kritisch fuer credentials=True)
# ---------------------------------------------------------------------------

def test_wildcard_origin_rejected_even_in_dev(monkeypatch):
    """'*' in allow_origins mit allow_credentials=True ist Browser-Spec-
    Violation. Validator wirft IMMER, auch in development."""
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('CORS_ORIGINS', '["*"]')
    with pytest.raises(ValidationError, match=r'darf nicht "\*"'):
        Settings()


def test_wildcard_with_whitespace_also_rejected(monkeypatch):
    """' * ' (mit Whitespace) wird auch erkannt — strip-Schutz."""
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('CORS_ORIGINS', '["  *  "]')
    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------

def test_origins_list_non_empty():
    """Origins-Liste darf nicht leer sein — sonst kein CORS aktiv."""
    assert len(settings.cors_origins) > 0
