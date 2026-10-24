"""Drift-Test fuer die Roadmap-#63-Migration (ADR-008 Track 2, Modul C).

Der Profiling-Fragebogen ist die erste Sektion, die vollstaendig durch das
ADR-008-Muster (Schema-First -> React-Page -> Tests -> Wiring -> Drift-Test)
gelaufen ist:

- Schema + React-Seite + Tests: PR #306
  (5eyes-electron/frontend/reporting/src/sections/profiling/ProfilingPage.tsx)
- Wiring: openProfilingEditor() im HTML-Monolithen oeffnet die React-Seite
  in einem neuen Tab (analog zu openReportingApp()), der Inline-Fragebogen
  bleibt als Uebergangsloesung aktiv (Zwei-Stack-Betrieb gemaess ADR-008).

Dieser Test haelt die Bruecke zwischen beiden Seiten synchron: bricht die
Route im React-Router, die Backend-Endpunkte im React-API-Client oder die
Wiring-Funktion im Monolithen auseinander, ohne dass die jeweils andere
Seite mitgezogen wird, schlaegt er fehl (Silent-Drift-Schutz).

O-1 (CIO-Entscheid): Der Editor ist gesperrt. Er wich vom Standard-Fragebogen
ab (Texte, Fragen 6/7, pauschale Antworten). Die Route zeigt nur noch einen
Sperrhinweis, der Knopf im Monolithen ist ausgeblendet und deaktiviert, die
Bruecke oeffnet keinen Tab mehr. Der Inline-Standard-Fragebogen bleibt.
"""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"
APP_TSX_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "App.tsx"
)
PROFILING_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "profiling.ts"
)
PROFILING_PAGE_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "profiling"
    / "ProfilingPage.tsx"
)

REACT_ROUTE_PATH = "/mandates/:mandateId/risikoprofil-editor"
HTML_WIRING_PATH_SEGMENT = "/risikoprofil-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_route_shows_lock_notice_instead_of_editor():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:200]
    assert "<ProfilingEditorLocked" in route_block
    assert "<ProfilingPage" not in app_tsx
    assert "sections/profiling/ProfilingPage'" not in app_tsx


def test_html_bridge_no_longer_opens_the_editor():
    html = _read(HTML_PATH)

    assert "async function openProfilingEditor(){" in html
    bridge_fn = html.split(
        "async function openProfilingEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT not in bridge_fn
    assert "window.open" not in bridge_fn
    assert "resolveReportingAppUrl" not in bridge_fn
    assert "gesperrt" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_advisory_report_bridge():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # Die verbleibenden Editor-Bridges teilen sich dieselbe Token-/Base-URL-
    # Aufloesung (openReportingApp, openGoalsEditor, openCashflowEditor,
    # openMandateEditor, openCrmEditor, openCrmEditorForClient,
    # openWealthInflowEditor). Der Risikoprofil-Editor ist gesperrt (O-1).
    assert html.count("await resolveReportingAppUrl(path)") == 7


def test_profiling_editor_button_is_hidden_and_disabled():
    html = _read(HTML_PATH)
    rp_header = html.split('<div id="page-rp" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    button = rp_header.split('id="btn-rp-react-editor"', 1)[1].split(">", 1)[0]
    assert " hidden" in button
    assert " disabled" in button
    assert 'style="display:none"' in button
    # Inline-Standard-Fragebogen bleibt der einzige Erfassungsweg.
    assert "saveRiskProfile()" in rp_header


def test_react_profiling_api_client_calls_same_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    profiling_api = _read(PROFILING_API_PATH)

    # HTML (saveRiskProfile) und React (createRiskAssessment) muessen exakt
    # denselben Endpunkt-Suffix ansprechen.
    assert "'/risk-assessments'" in html or '"/risk-assessments"' in html
    assert "'/risk-assessments'" in profiling_api

    assert "/risk-assessments/current" in html
    assert "/risk-assessments/current" in profiling_api


def test_react_profiling_page_does_not_reimplement_scoring_formulas():
    """Reine UI-Migration: die React-Seite darf keine eigene Scoring-Logik
    fuehren, sondern muss risk_capacity_score_x10 / final_profile etc. vom
    Backend uebernehmen (siehe RiskSummary.tsx / api/types.ts)."""
    page = _read(PROFILING_PAGE_PATH)

    forbidden_score_math = re.compile(r"score\s*=\s*[^=]*[+\-*/]")
    assert not forbidden_score_math.search(page)
