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


def test_react_router_still_mounts_profiling_page_at_expected_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    # Muss unmittelbar auf <ProfilingPage /> gemountet sein (kein ReportShell-Wrapper,
    # das waere ein Read-Only-Report statt des Editor-Workflows).
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:200]
    assert "<ProfilingPage" in route_block


def test_html_bridge_opens_exact_same_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openProfilingEditor(){" in html
    bridge_fn = html.split(
        "async function openProfilingEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    # Die Bruecke muss ueber /mandates/{id}/... adressieren, exakt wie die
    # React-Route /mandates/:mandateId/risikoprofil-editor es erwartet.
    assert "/mandates/" in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_advisory_report_bridge():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # openReportingApp (Advisory-Report) UND openProfilingEditor muessen
    # dieselbe Token-/Base-URL-Aufloesung nutzen -- keine zweite, evtl.
    # driftende Kopie der Handoff-Logik.
    # 2026-08-02 (Integration): mittlerweile teilen sich 9 Editor-Bridges diese
    # Funktion (openReportingApp, openProfilingEditor, openGoalsEditor,
    # openCashflowEditor, openAllocationEditor, openMandateEditor,
    # openCrmEditor, openCrmEditorForClient, openWealthInflowEditor).
    assert html.count("await resolveReportingAppUrl(path)") == 9


def test_profiling_editor_entry_point_is_reachable_from_risikoprofil_section():
    html = _read(HTML_PATH)
    rp_header = html.split('<div id="page-rp" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    assert 'id="btn-rp-react-editor"' in rp_header
    assert "openProfilingEditor()" in rp_header
    # Inline-Fragebogen bleibt in dieser Migrationsphase aktiv (Zwei-Stack-
    # Uebergang gemaess ADR-008) -- keine Fachlogik-Sektion wird entfernt.
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
