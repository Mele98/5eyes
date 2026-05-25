"""Sprint U-P22.2 + U-P22.3 — Statische Contract-Tests für API-Client + Cover.

Prüft die TypeScript-Module statisch auf Disk (keine npm-Installation
nötig). Validiert dass:
- Schema-v1-Typen alle 15 Sektionen + Sub-Strukturen abdecken
- API-Client robuste Error-Klassen + Defensive Schema-Validierung hat
- React Hook saubere State-Machine implementiert
- Cover-Seite alle Cover-Felder rendert + Branding-konform ist
- App.tsx den Cover-Pfad korrekt einbindet
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPORTING_ROOT = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "reporting"
)
SRC = REPORTING_ROOT / "src"


def _read(relative: str) -> str:
    path = SRC / relative
    assert path.exists(), f"Erwartete Datei fehlt: src/{relative}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Dateistruktur — neue Files vorhanden
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", [
    "api/types.ts",
    "api/client.ts",
    "api/useAdvisoryReport.ts",
    "pages/Cover.tsx",
])
def test_new_files_exist(relative: str):
    assert (SRC / relative).exists(), f"Datei fehlt: src/{relative}"


# ---------------------------------------------------------------------------
# 2. types.ts — alle 15 Sektion-Interfaces deklariert
# ---------------------------------------------------------------------------

def test_types_declares_top_level_advisory_report_interface():
    content = _read("api/types.ts")
    assert "export interface AdvisoryReport" in content
    # Top-Level-Schema-Version 1
    assert "schema_version: 1" in content


@pytest.mark.parametrize("interface", [
    "CoverData",
    "InhaltsverzeichnisData",
    "AusgangslageData",
    "PositionenData",
    "PruefpunkteData",
    "ErkenntnisseData",
    "AssetAllocationData",
    "RisikowaehrungenData",
    "BranchenData",
    "GoalBasedInvestingData",
    "RisikoprofilierungData",
    "BuildingBlocksData",
    "StatementPmData",
    "WeiteresVorgehenData",
    "DisclaimerData",
])
def test_types_declares_section_interface(interface: str):
    """Jede der 15 Sektionen hat ein eigenes Interface (= Sub-Komponenten
    können typsicher gegen ihre eigene Sub-Struktur arbeiten)."""
    content = _read("api/types.ts")
    assert f"export interface {interface}" in content


def test_types_declares_ampel_status_union():
    """Ampel-Status muss alle 4 Werte abdecken (Schema U-P21)."""
    content = _read("api/types.ts")
    assert "AmpelStatus" in content
    for value in ("'gruen'", "'gelb'", "'rot'", "'nicht_beurteilbar'"):
        assert value in content


# ---------------------------------------------------------------------------
# 3. client.ts — Error-Klassen + Schema-Validierung
# ---------------------------------------------------------------------------

def test_client_exports_error_classes():
    content = _read("api/client.ts")
    assert "export class ApiError" in content
    assert "export class SchemaError" in content


def test_client_validates_schema_v1_top_level_keys():
    """Schema-Validierung MUSS prüfen, dass alle 15 Sektion-Keys da sind
    (Defensive vor Render-Crash bei Backend-Drift)."""
    content = _read("api/client.ts")
    # Alle 15 Sektion-Keys + 3 Meta-Keys müssen in validateSchemaV1 sein
    expected = [
        "schema_version", "mandate_id", "generated_at",
        "cover", "inhaltsverzeichnis", "ausgangslage",
        "positionen", "pruefpunkte", "erkenntnisse",
        "asset_allocation", "risikowaehrungen", "branchen",
        "goal_based_investing", "risikoprofilierung",
        "building_blocks", "statement_pm", "weiteres_vorgehen",
        "disclaimer",
    ]
    for key in expected:
        assert f"'{key}'" in content, f"client.ts validiert {key!r} nicht"


def test_client_sends_bearer_token_for_backend_auth():
    """5eyes-Backend erwartet Authorization: Bearer <token> (kein Cookie).
    Token-Quellen-Hierarchie:
      1. Electron: window.desktop.getAuthToken()
      2. Browser-Dev: sessionStorage['5eyes_token'] / localStorage['5eyes_token']
      3. Build-Env: VITE_5EYES_TOKEN (nur DEV)
    credentials:'include' bleibt drin, falls Backend später zusätzlich
    Cookie-Auth unterstützt — kein Regress-Risiko."""
    content = _read("api/client.ts")
    assert "resolveAuthToken" in content
    assert "getAuthToken" in content
    assert "sessionStorage.getItem('5eyes_token')" in content
    assert "Authorization" in content
    assert "Bearer ${token}" in content
    assert "credentials: 'include'" in content


# ---------------------------------------------------------------------------
# 4. useAdvisoryReport — State-Machine + AbortController
# ---------------------------------------------------------------------------

def test_hook_implements_full_state_machine():
    content = _read("api/useAdvisoryReport.ts")
    # 4 States dokumentiert in ReportState
    for state in ("'idle'", "'loading'", "'ready'", "'error'"):
        assert state in content
    # Hook exportiert
    assert "export function useAdvisoryReport" in content
    # AbortController für race-condition-Schutz bei mandateId-Wechsel
    assert "AbortController" in content
    # Reload-API
    assert "reload" in content


# ---------------------------------------------------------------------------
# 5. Cover.tsx — alle Pflicht-Felder gerendert + Branding
# ---------------------------------------------------------------------------

def test_cover_renders_all_required_cover_fields():
    content = _read("pages/Cover.tsx")
    # Alle 6 CoverData-Felder müssen aus data.* gelesen werden
    for field in (
        "data.title",
        "data.subtitle",
        "data.client_name",
        "data.mandate_number",
        "data.report_date",
        "data.advisor_name",
    ):
        assert field in content, f"Cover rendert {field!r} nicht"


def test_cover_uses_swiss_date_format():
    """Schweizer Datums-Format DD.MM.YYYY für report_date."""
    content = _read("pages/Cover.tsx")
    assert "formatReportDate" in content
    # Test-helper: regex-Pattern für ISO-Validierung muss da sein
    assert r"^\d{4}-\d{2}-\d{2}$" in content or r"\\d{4}-\\d{2}-\\d{2}" in content


def test_cover_has_data_testids_for_e2e_hooks():
    """data-testid auf den 4 Kern-Feldern, damit E2E-Tests + visuelle
    Regression diese gezielt ansteuern können."""
    content = _read("pages/Cover.tsx")
    for testid in (
        '"report-page-cover"',
        '"cover-title"',
        '"cover-client-name"',
        '"cover-advisor-name"',
        '"cover-report-date"',
    ):
        assert f"data-testid={testid}" in content


# ---------------------------------------------------------------------------
# 6. App.tsx — Cover wird via Hook eingebunden
# ---------------------------------------------------------------------------

def test_app_wires_cover_via_hook():
    content = _read("App.tsx")
    assert "useAdvisoryReport" in content
    assert "<Cover" in content
    # Loading- und Error-States gerendert (Defensive)
    for testid in ('"report-loading"', '"report-error"'):
        assert f"data-testid={testid}" in content


# ---------------------------------------------------------------------------
# 7. Branding-Compliance bleibt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", [
    "api/types.ts",
    "api/client.ts",
    "api/useAdvisoryReport.ts",
    "pages/Cover.tsx",
    "App.tsx",
])
def test_no_third_party_brands_in_new_files(relative: str):
    content = _read(relative).lower()
    forbidden = (
        "ubs", "pictet", "julius bär", "julius baer",
        "swiss life", "3eyes", "ppc metrics",
    )
    for brand in forbidden:
        assert brand not in content, f"Verbotene Marke '{brand}' in {relative}"


# ---------------------------------------------------------------------------
# 8. Schema-Sync: types.ts spiegelt Backend-Schema (Sub-Set-Check)
# ---------------------------------------------------------------------------

def test_types_schema_matches_backend_keys():
    """Wenn das Backend-Modul `compute_advisory_report` einen Top-Level-Key
    hat, MUSS er auch im TypeScript-Schema sein. Drift wird hier verhindert."""
    backend_file = (
        Path(__file__).resolve().parent.parent
        / "services" / "advisory_report.py"
    )
    backend = backend_file.read_text(encoding="utf-8")
    # Extrahiere alle Sektion-Keys aus dem Return-Dict des Entry-Points
    matches = re.findall(r'"([a-z_]+)":\s*_build_', backend)
    types_content = _read("api/types.ts")
    for backend_key in matches:
        assert backend_key in types_content, (
            f"Backend-Sektion '{backend_key}' fehlt im TypeScript-Schema"
        )
