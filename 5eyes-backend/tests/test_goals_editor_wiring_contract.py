"""Drift-Test fuer die ADR-008-Track-2-Migration des Goal-Wizards (Ziele).

Der Goal-Editor ist die naechste Sektion nach dem Profiling-Fragebogen, die
durch das ADR-008-Muster (Schema-First -> React-Page -> Tests -> Wiring ->
Drift-Test) laeuft:

- Schema + React-Seite + Tests bereits vorhanden (Track #64):
  5eyes-electron/frontend/reporting/src/sections/goals/GoalsEditor.tsx
  API-Client: 5eyes-electron/frontend/reporting/src/api/goals.ts
- Wiring: openGoalsEditor() im HTML-Monolithen soll die React-Seite in
  einem neuen Tab oeffnen (analog zu openProfilingEditor()), der Inline-
  Ziele-Workflow (Ziel erfassen ueber "m-nz"-Modal auf page-cf) bleibt als
  Uebergangsloesung aktiv (Zwei-Stack-Betrieb gemaess ADR-008).

Dieser Test haelt die Bruecke zwischen beiden Seiten synchron: bricht die
Route im React-Router, die Backend-Endpunkte im React-API-Client oder die
Wiring-Funktion im Monolithen auseinander, ohne dass die jeweils andere
Seite mitgezogen wird, schlaegt er fehl (Silent-Drift-Schutz).

Stand bei Testerstellung: das Wiring in 5eyes_v2.html ist noch NICHT
eingebaut (siehe ADR-008-Update 2026-07-23, offene Luecke fuer den
Goal-Wizard) -- die wiring-bezogenen Assertions in diesem File sind daher
erwartungsgemaess rot, bis openGoalsEditor() + der Button
btn-cf-goals-react-editor in page-cf ergaenzt werden.
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
GOALS_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "goals.ts"
)
GOALS_EDITOR_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "goals"
    / "GoalsEditor.tsx"
)

REACT_ROUTE_PATH = "/mandates/:mandateId/goals-editor"
HTML_WIRING_PATH_SEGMENT = "/goals-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_router_still_mounts_goals_editor_page_at_expected_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    # Muss (ueber GoalsEditorRoute) unmittelbar auf <GoalsEditor /> gemountet
    # sein (kein ReportShell-Wrapper, das waere ein Read-Only-Report statt
    # des Editor-Workflows).
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:400]
    assert "GoalsEditorRoute" in route_block

    # GoalsEditorRoute selbst muss <GoalsEditor mandateId=...} rendern.
    route_fn = app_tsx.split("function GoalsEditorRoute()", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "<GoalsEditor" in route_fn


def test_html_bridge_opens_exact_same_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openGoalsEditor(){" in html
    bridge_fn = html.split(
        "async function openGoalsEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    # Die Bruecke muss ueber /mandates/{id}/... adressieren, exakt wie die
    # React-Route /mandates/:mandateId/goals-editor es erwartet.
    assert "/mandates/" in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_advisory_report_bridge():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # openReportingApp (Advisory-Report), openProfilingEditor UND
    # openGoalsEditor muessen dieselbe Token-/Base-URL-Aufloesung nutzen --
    # keine weitere, evtl. driftende Kopie der Handoff-Logik.
    # 2026-08-02 (Integration): 9 Editor-Bridges teilen sich diese Funktion
    # (openReportingApp, openProfilingEditor, openGoalsEditor,
    # openCashflowEditor, openAllocationEditor, openMandateEditor,
    # openCrmEditor, openCrmEditorForClient, openWealthInflowEditor).
    assert html.count("await resolveReportingAppUrl(path)") == 9


def test_goals_editor_entry_point_is_reachable_from_cashflow_ziele_section():
    html = _read(HTML_PATH)
    cf_header = html.split('<div id="page-cf" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    assert 'id="btn-cf-goals-react-editor"' in cf_header
    assert "openGoalsEditor()" in cf_header
    # Inline-Ziele-Erfassung (Modal "m-nz") bleibt in dieser Migrationsphase
    # aktiv (Zwei-Stack-Uebergang gemaess ADR-008) -- keine Fachlogik-
    # Sektion wird entfernt.
    assert "om('m-nz')" in cf_header


def test_react_goals_api_client_calls_same_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    goals_api = _read(GOALS_API_PATH)

    # HTML-Monolith und React-Client muessen denselben Endpunkt-Suffix
    # ansprechen (Backend-Vertrag: routers/wealth.py, .../goals).
    assert "/goals" in html
    assert "/goals`" in goals_api or "'/goals'" in goals_api or '"/goals"' in goals_api


def test_react_goals_editor_does_not_reimplement_scoring_or_ranking_logic():
    """Reine UI-Migration: die React-Seite darf keine eigene Scoring- oder
    Priorisierungs-Arithmetik fuehren, sondern muss rank/hardness/target-
    Werte unveraendert vom Backend uebernehmen und anzeigen (siehe
    GoalRecord in api/types.ts). Anders als beim Risikoprofil gibt es fuer
    Ziele keine Score-Formel im engeren Sinn -- der Test bewacht trotzdem
    gegen eine zukuenftige Drift, falls doch einmal Berechnungslogik in
    die Praesentationsschicht rutscht."""
    page = _read(GOALS_EDITOR_PATH)

    forbidden_score_math = re.compile(r"(score|rank)\s*=\s*[^=]*[+\-*/]")
    assert not forbidden_score_math.search(page)
