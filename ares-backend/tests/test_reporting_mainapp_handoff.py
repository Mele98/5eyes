"""Sprint U-P22.6 — Token-Handoff von der Ares-Hauptapp zur Reporting-Sub-App.

Prüft die zwei Seiten der Übergabe statisch (kein npm nötig):

1. **Reporting-Side** (`src/api/handoff.ts`):
   - Exportiert `consumeHandoffFromUrlFragment()` als Boot-Hook
   - Liest Token aus `window.location.hash` (URL-Fragment, NICHT Query)
   - Schreibt nach `sessionStorage[AUTH_TOKEN_STORAGE_KEY]` (Schluessel aus
     `src/api/tokenKey.ts`, identisch mit dem Literal der Hauptapp)
   - Bereinigt die URL via `history.replaceState`
   - Wird in `main.tsx` SOFORT vor React-Render aufgerufen

2. **Hauptapp-Side** (`ares.html`):
   - Button `btn-po-advisory-report` im ph-more-Menü neben Depot-Check
   - JS-Funktion `openReportingApp()` die Token holt + window.open ruft
   - Token-Quelle: erst Electron (window.desktop.getAuthToken), dann
     Browser-sessionStorage — gleiche Hierarchie wie der bestehende
     API-Client der Hauptapp
   - URL-Fragment statt Query-String (Token nicht im Server-Log)
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.brand_digest_support import assert_no_legacy_brand  # noqa: E402

REPORTING_ROOT = (
    Path(__file__).resolve().parents[2]
    / "ares-desktop" / "frontend" / "reporting"
)
MAINAPP_HTML = (
    Path(__file__).resolve().parents[2]
    / "ares-desktop" / "frontend" / "ares.html"
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


def test_handoff_uses_shared_token_key_for_sessionstorage():
    """Konvention: Reporting + Hauptapp nutzen denselben Storage-Key
    (aus `src/api/tokenKey.ts`). Sonst greift der Token-Resolver in
    client.ts nicht."""
    content = _read_reporting("src/api/handoff.ts")
    assert "from './tokenKey'" in content
    assert "sessionStorage.setItem(TOKEN_STORAGE_KEY" in content


_TOKEN_KEY_DECL = re.compile(
    r"^export const AUTH_TOKEN_STORAGE_KEY = '([^']+)';$", re.MULTILINE
)
_MAINAPP_TOKEN_ACCESS = re.compile(
    r"(session|local)Storage\.(?:get|set|remove)Item\('([^']*token[^']*)'"
)
_REPORTING_TOKEN_READERS = (
    "src/api/handoff.ts",
    "src/api/client.ts",
    "src/api/advisoryLog.ts",
    "src/api/reportNotes.ts",
    "src/api/useUserRole.ts",
)


def _reporting_token_key() -> str:
    decls = _TOKEN_KEY_DECL.findall(_read_reporting("src/api/tokenKey.ts"))
    assert len(decls) == 1, decls
    return decls[0]


def test_token_key_is_identical_in_mainapp_and_reporting():
    """W4-a1-Vertrag: Hauptapp und Reporting-Sub-App benutzen exakt denselben
    Access-Token-Schluessel. Reporting hat genau eine Quelle (tokenKey.ts),
    die Hauptapp dasselbe Literal; der Refresh-Token hat einen eigenen Slot."""
    key = _reporting_token_key()
    assert key == "ares.token"
    accesses = _MAINAPP_TOKEN_ACCESS.findall(_read_mainapp())
    assert accesses, "Hauptapp greift auf keinen Token-Schluessel zu"
    keys = {k for _, k in accesses}
    assert keys == {key, "ares.refresh_token"}, keys
    # Nur sessionStorage: kein Token in localStorage, keine Legacy-Uebernahme.
    assert {store for store, _ in accesses} == {"session"}


def test_reporting_token_readers_use_single_key_source_without_local_storage():
    """Jeder Token-Leser/-Schreiber der Sub-App importiert den Schluessel aus
    tokenKey.ts, nennt kein eigenes Literal und liest nicht aus localStorage."""
    key = _reporting_token_key()
    for rel in _REPORTING_TOKEN_READERS:
        content = _read_reporting(rel)
        assert "from './tokenKey'" in content, rel
        assert f"'{key}'" not in content, rel
        assert "localStorage" not in content, rel
    src = REPORTING_ROOT / "src"
    for path in src.rglob("*.ts*"):
        if path.name.endswith((".test.ts", ".test.tsx")) or path.name == "tokenKey.ts":
            continue
        text = path.read_text(encoding="utf-8")
        assert f"'{key}'" not in text, path.relative_to(REPORTING_ROOT)
        assert not re.search(r"localStorage\.\w+\([^)]*token", text, re.IGNORECASE), (
            path.relative_to(REPORTING_ROOT)
        )


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
# 3. Hauptapp-Side — Button + Funktion in ares.html
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
    Konkret: `#token=` muss im URL-Konstruktor auftauchen.

    Roadmap #63 / ADR-008 Track 2 (2026-07-23): der Token-Handoff wurde aus
    openReportingApp() in die geteilte Helper-Funktion
    resolveReportingAppUrl() extrahiert (Wiederverwendung durch
    openProfilingEditor()). openReportingApp() ruft sie auf statt die Logik
    zu duplizieren — die Invariante wird jetzt im Helper geprueft.
    """
    html = _read_mainapp()
    func_start = html.find("async function openReportingApp()")
    func_block = html[func_start:func_start + 2000]
    assert "resolveReportingAppUrl" in func_block, (
        "openReportingApp() muss den geteilten Token-Handoff-Helper nutzen"
    )
    assert "encodeURIComponent(mid)" in func_block

    helper_start = html.find("async function resolveReportingAppUrl(")
    assert helper_start > 0, "resolveReportingAppUrl() fehlt"
    helper_block = html[helper_start:helper_start + 2000]
    assert "#token=" in helper_block, (
        "Token MUSS via URL-Fragment uebergeben werden (Server-Log-Hygiene)"
    )
    assert "encodeURIComponent(token)" in helper_block


def test_mainapp_open_reporting_app_uses_same_token_hierarchy_as_main_api():
    """openReportingApp() MUSS (via resolveReportingAppUrl()) dieselbe
    Token-Quellen-Hierarchie nutzen wie der bestehende API-Client der
    Hauptapp:
      1. window.desktop.getAuthToken (Electron)
      2. sessionStorage['ares.token'] (Browser)
    Sonst kann der Berater die Reporting-App nicht öffnen, obwohl er
    in der Hauptapp eingeloggt ist."""
    html = _read_mainapp()
    helper_start = html.find("async function resolveReportingAppUrl(")
    assert helper_start > 0, "resolveReportingAppUrl() fehlt"
    helper_block = html[helper_start:helper_start + 2000]
    assert "window.desktop" in helper_block
    assert "getAuthToken" in helper_block
    assert "sessionStorage.getItem('ares.token')" in helper_block


def test_mainapp_open_reporting_app_uses_window_open_with_noopener():
    """`window.open(..., '_blank', 'noopener')` — kein opener-Referenz
    (Sicherheit: neuer Tab kann window.opener nicht abusen)."""
    html = _read_mainapp()
    func_start = html.find("async function openReportingApp()")
    func_block = html[func_start:func_start + 2000]
    assert "window.open" in func_block
    assert "noopener" in func_block


def test_resolve_reporting_app_url_does_not_reference_window_api():
    """Bugfix A3-Pilot (2026-08-17): `API` ist ein top-level `const API = {...}`
    (siehe ares.html, ca. Zeile 5000) — NICHT an `window` gehaengt. Ein
    `window.API`-Check ist daher immer `undefined` und der Zweig greift nie,
    wodurch resolveReportingAppUrl() IMMER auf den hartcodierten
    127.0.0.1:8000-Fallback zurueckfiel, selbst wenn das Backend auf einem
    anderen Host/Port lief. Betroffen: Advisory-Report- und
    Risikoprofil-Editor-Buttons.

    Regressionstest: helper MUSS die bare `API`-Bindung referenzieren (wie
    an den anderen Call-Sites im File, z.B. `await API.baseUrl()` bei
    openProfilingEditor), NICHT `window.API`.
    """
    html = _read_mainapp()
    helper_start = html.find("async function resolveReportingAppUrl(")
    assert helper_start > 0, "resolveReportingAppUrl() fehlt"
    helper_end = html.find("\n}\n", helper_start)
    helper_block = html[helper_start:helper_end]

    assert "window.API" not in helper_block, (
        "window.API ist immer undefined (API ist ein top-level const, nicht "
        "an window gehaengt) -- der Backend-URL-Fallback wuerde sonst "
        "silently IMMER greifen"
    )
    assert "API.baseUrl" in helper_block, (
        "resolveReportingAppUrl() muss die echte Backend-URL ueber die "
        "bare API-Bindung (API.baseUrl()) aufloesen"
    )


# ---------------------------------------------------------------------------
# 4. Branding-Compliance bleibt
# ---------------------------------------------------------------------------

def test_handoff_ts_no_third_party_brands():
    content = _read_reporting("src/api/handoff.ts").lower()
    for brand in ("ubs", "pictet", "julius bär", "julius baer",
                  "swiss life", "ppc metrics"):
        assert brand not in content
    assert_no_legacy_brand(content, "src/api/handoff.ts")
