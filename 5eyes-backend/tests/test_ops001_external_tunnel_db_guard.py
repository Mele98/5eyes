"""Regression-Lock fuer OPS-001 (Codex-Audit 2026-08-25, docs/audits/
2026-08-25-auth-execution-operations-followup-audit.md).

docs/deploy/start-external.ps1 startet das Backend und oeffnet einen
oeffentlichen Cloudflare-Quick-Tunnel darauf. Vor dem Fix zeigte das Skript
ohne explizites DB_PATH implizit auf dieselbe Datei wie die normale
Electron-Desktop-App (~\\5eyes\\5eyes.db) -- ALLOW_REAL_CLIENT_DATA=false
blockt dabei nur neue, selbst-klassifizierte "real"-Schreibzugriffe
(services/data_classification.py::enforce_data_classification), NICHT
Lesezugriffe auf bereits vorhandene echte Mandantendaten. Ein Fehlgriff
(Skript ohne Nachdenken gestartet, waehrend die Desktop-DB bereits echte
Kundendaten enthaelt) haette diese Daten oeffentlich erreichbar gemacht.

Fix: ohne explizites DB_PATH zeigt das Skript auf eine separate Staging-
Datei; zeigt DB_PATH explizit auf die produktive Desktop-DB, verlangt das
Skript eine getippte Bestaetigung vor dem Start.

Dies ist ein reiner PowerShell-Text-Scan (kein pwsh-Runner in der CI-
Pipeline verfuegbar) -- analog zu bestehenden Raw-Text-Scan-Tests fuer
Frontend-/Skript-Dateien in dieser Suite. Ein Syntax-Parse-Check erfolgte
separat manuell (Parser]::ParseFile, keine Fehler).
"""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_ROOT.parent / "docs" / "deploy" / "start-external.ps1"


def _script_text() -> str:
    assert SCRIPT_PATH.exists(), f"{SCRIPT_PATH} fehlt -- OPS-001-Skript verschoben/umbenannt?"
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_defaults_to_a_separate_db_path_when_none_is_set():
    text = _script_text()
    assert "if (-not $env:DB_PATH)" in text, (
        "Kein Guard fuer fehlendes DB_PATH gefunden -- OPS-001-Fix entfernt?"
    )
    assert "external-demo.db" in text, (
        "Default-DB_PATH zeigt nicht mehr erkennbar auf eine separate Staging-Datei."
    )


def test_script_requires_typed_confirmation_before_exposing_the_real_db():
    text = _script_text()
    assert "$realDbPath" in text
    assert "ich verstehe das risiko" in text, (
        "Getippte Bestaetigung fuer den Fall DB_PATH==echte Desktop-DB fehlt."
    )
    assert "exit 1" in text


def test_script_still_documents_that_allow_real_client_data_only_gates_writes():
    """Die (weiterhin korrekte) Doku-Aussage darf nicht wieder verschwinden --
    sonst faellt jemand erneut auf die falsche Annahme herein, der Flag
    wuerde auch Lesezugriffe blocken."""
    text = _script_text()
    assert "blockt nur" in text
    assert "Lesezugriffe" in text
