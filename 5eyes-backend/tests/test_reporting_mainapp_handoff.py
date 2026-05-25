"""Sprint U-P22.6 — Token-Handoff von der 5eyes-Hauptapp zur Reporting-Sub-App.

Prüft die zwei Seiten der Übergabe statisch (kein npm nötig):

1. **Reporting-Side** (`src/api/handoff.ts`):
   - Exportiert `consumeHandoffFromUrlFragment()` als Boot-Hook
   - Liest Token aus `window.location.hash` (URL-Fragment, NICHT Query)
   - Schreibt nach `sessionStorage['5eyes_token']` (= Hauptapp-Konvention)
   - Bereinigt die URL via `history.replaceState`
   - Wird in `main.tsx` SOFORT vor React-Render aufgerufen

2. **Hauptapp-Side** (`5eyes_v2.html`):
   - Button `btn-po-advisory-report` im ph-more-Menü neben Depot-Check
   - JS-Funktion `openReportingApp()` die Token holt + window.open ruft
   - Token-Quelle: erst Electron (window.desktop.getAuthToken), dann
     Browser-sessionStorage — gleiche Hierarchie wie der bestehende
     API-Client der Hauptapp
   - URL-Fragment statt Query-String (Token nicht im Server-Log)
"""
from __future__ import annotations

from pathlib import Path

REPORTING_ROOT = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "reporting"
)
MAINAPP_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _read_reporting(rel: str) -> str:
    path = REPORTING_ROOT / rel
    assert path.exists(), f"Datei fehlt: {rel}"
    return path.read_text(encoding="utf-8")


def _read_mainapp() -> str:
    return MAINAPP_HTML.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Reporting-Side — handoff.ts existiert + exportiert Pflicht-API
# ---------------------------------------------------------------------------

def test_handoff_ts_exists_and_exports_consumer():
    content = _read_reporting("src/api/handoff.ts")
    assert "export function consumeHandoffFromUrlFragment" in content
    assert "export interface HandoffResult" in content


def test_handoff_uses_5eyes_token_key_for_sessionstorage():
    """Konvention: Reporting + Hauptapp nutzen denselben Storage-Key
    (`5eyes_token`). Sonst greift der Token-Resolver in client.ts nicht."""
    content = _read_reporting("src/api/handoff.ts")
    assert "5eyes_token" in content
    assert "sessionStorage.setItem" in content


def test_handoff_reads_url_fragment_not_querystring():
    """Token MUSS aus dem URL-Fragment kommen, nicht aus dem Query-String —
    Fragments werden niemals an den Server gesendet (Backend-Log-Hygiene).
    """
    content = _read_reporting("src/api/handoff.ts")
    assert "window.location.hash" in content
    # Wir bereinigen via replaceState, damit der Token weder im History
    # noch im React-Router-Pfad sichtbar bleibt.
    assert "history.replaceState" in content


def test_handoff_is_safe_in_non_browser_environments():
    """Defensive: handoff.ts darf in Node-Test-Umgebungen ohne `window`
    nicht crashen — sonst bricht jeder Vitest-Setup."""
    content = _read_reporting("src/api/handoff.ts")
    assert "typeof window === 'undefined'" in content


# ---------------------------------------------------------------------------
# 2. main.tsx — Handoff wird VOR React-Render aufgerufen
# ---------------------------------------------------------------------------

def test_main_tsx_calls_handoff_before_react_render():
    """consumeHandoffFromUrlFragment() MUSS vor ReactDOM.createRoot stehen,
    damit der Token bereits in sessionStorage liegt, wenn der erste
    fetchAdvisoryReport-Aufruf passiert (sonst 401 beim ersten Load)."""
    content = _read_reporting("src/main.tsx")
    assert "consumeHandoffFromUrlFragment" in content
    # Reihenfolge prüfen: import → call → render
    handoff_pos = content.find("consumeHandoffFromUrlFragment();")
    render_pos = content.find("ReactDOM.createRoot")
    assert handoff_pos > 0
    assert render_pos > 0
    assert handoff_pos < render_pos, (
        "consumeHandoffFromUrlFragment MUSS vor ReactDOM.createRoot aufgerufen werden"
    )


# ---------------------------------------------------------------------------
# 3. Hauptapp-Side — Button + Funktion in 5eyes_v2.html
# ---------------------------------------------------------------------------

def test_mainapp_has_advisory_report_button_in_portfolio_header():
    """Neuer Button `btn-po-advisory-report` MUSS in der Portfolio-Header-
    Hauptbuttonreihe (`ph-r`) stehen, NICHT versteckt im ⋯-Menü.

    Sprint U-P22.7 (2026-05-25): Button aus ph-more-menu nach ph-r
    verschoben, damit Berater ihn sofort sehen + 1-Klick öffnen können.
    Statisch verifiziert über Adjazenz zum sichtbaren `btn-po-pdf`-Button.
    """
    html = _read_mainapp()
    assert 'id="btn-po-advisory-report"' in html
    assert 'onclick="openReportingApp()' in html
    # Button muss in der sichtbaren Hauptreihe (`ph-r`) sein, NICHT
    # im versteckten `ph-more-menu`. Test: Adjazenz zum sichtbaren
    # PDF-Button (der ebenfalls direkt in ph-r steht).
    pdf_idx = html.find('id="btn-po-pdf"')
    advisory_idx = html.find('id="btn-po-advisory-report"')
    assert pdf_idx > 0 and advisory_idx > 0
    assert abs(advisory_idx - pdf_idx) < 500, (
        "Advisory-Report-Button MUSS in der sichtbaren Header-Reihe (ph-r) stehen, "
        "nicht im versteckten ph-more-menu"
    )


def test_mainapp_open_reporting_app_function_handles_missing_mandate():
    """openReportingApp() MUSS bei fehlendem Mandat sauber abbrechen
    (kein crash, klare Fehler-Meldung)."""
    html = _read_mainapp()
    func_start = html.find("async function openReportingApp()")
    assert func_start > 0
    func_block = html[func_start:func_start + 2000]
    assert "getActiveMandateId" in func_block
    assert "Bitte zuerst ein Mandat" in func_block


def test_mainapp_open_reporting_app_uses_url_fragment_for_token():
    """Token MUSS via URL-Fragment übergeben werden, NICHT via Query.
    Konkret: `#token=` muss im URL-Konstruktor auftauchen."""
    html = _read_mainapp()
    func_start = html.find("async function openReportingApp()")
    func_block = html[func_start:func_start + 2000]
    assert "#token=" in func_block, (
        "Token MUSS via URL-Fragment uebergeben werden (Server-Log-Hygiene)"
    )
    # Plus: encodeURIComponent fuer beide Werte
    assert "encodeURIComponent(mid)" in func_block
    assert "encodeURIComponent(token)" in func_block


def test_mainapp_open_reporting_app_uses_same_token_hierarchy_as_main_api():
    """openReportingApp() MUSS dieselbe Token-Quellen-Hierarchie nutzen
    wie der bestehende API-Client der Hauptapp:
      1. window.desktop.getAuthToken (Electron)
      2. sessionStorage['5eyes_token'] (Browser)
    Sonst kann der Berater die Reporting-App nicht öffnen, obwohl er
    in der Hauptapp eingeloggt ist."""
    html = _read_mainapp()
    func_start = html.find("async function openReportingApp()")
    func_block = html[func_start:func_start + 2000]
    assert "window.desktop" in func_block
    assert "getAuthToken" in func_block
    assert "sessionStorage.getItem('5eyes_token')" in func_block


def test_mainapp_open_reporting_app_uses_window_open_with_noopener():
    """`window.open(..., '_blank', 'noopener')` — kein opener-Referenz
    (Sicherheit: neuer Tab kann window.opener nicht abusen)."""
    html = _read_mainapp()
    func_start = html.find("async function openReportingApp()")
    func_block = html[func_start:func_start + 2000]
    assert "window.open" in func_block
    assert "noopener" in func_block


# ---------------------------------------------------------------------------
# 4. Branding-Compliance bleibt
# ---------------------------------------------------------------------------

def test_handoff_ts_no_third_party_brands():
    content = _read_reporting("src/api/handoff.ts").lower()
    for brand in ("ubs", "pictet", "julius bär", "julius baer",
                  "swiss life", "3eyes", "ppc metrics"):
        assert brand not in content
