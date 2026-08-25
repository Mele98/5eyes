"""Drift-Test fuer die Roadmap-#65-Migration (ADR-008 Track 2, Mandate-Edit).

Analog zu test_profiling_editor_wiring_contract.py (Roadmap #63): der React-
Mandate-Editor existiert bereits vollstaendig (Schema/Page/Tests unter
5eyes-electron/frontend/reporting/src/sections/mandate/MandateEditor.tsx,
API-Client unter .../src/api/mandate.ts, Route in App.tsx), aber die
Wiring-Bruecke im HTML-Monolithen fehlt noch (ADR-008, Abschnitt "Update
2026-07-23"): openMandateEditor() gibt es im Monolithen noch nicht, ebenso
wenig den Button "Editor (Beta)" im Stammdaten-Seitenkopf.

Dieser Test haelt -- sobald das Wiring nachgezogen wird -- die Bruecke
zwischen React-Router, Backend-Endpunkten (api/mandate.ts) und der
Wiring-Funktion im Monolithen synchron (Silent-Drift-Schutz). Bis dahin
schlagen die wiring-spezifischen Tests bewusst rot fehl (fehlende
Funktion/Button), waehrend die bereits erfuellten Vertraege (React-Route,
Endpunkt-Parität, keine Fachlogik-Reimplementierung) gruen bleiben.
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
MANDATE_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "mandate.ts"
)
MANDATE_EDITOR_PAGE_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "mandate"
    / "MandateEditor.tsx"
)

REACT_ROUTE_PATH = "/mandates/:mandateId/mandate-editor"
HTML_WIRING_PATH_SEGMENT = "/mandate-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_router_still_mounts_mandate_editor_route_at_expected_path():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    # Muss auf <MandateEditorRoute /> gemountet sein (der Params-Guard-Wrapper),
    # nicht auf ein ReportShell-Wrapper -- das waere ein Read-Only-Report statt
    # des Editor-Workflows.
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:200]
    assert "<MandateEditorRoute" in route_block


def test_react_route_wrapper_renders_mandate_editor_component_directly():
    app_tsx = _read(APP_TSX_PATH)

    assert "function MandateEditorRoute()" in app_tsx
    wrapper_block = app_tsx.split("function MandateEditorRoute()", 1)[1][:600]
    # MandateEditorRoute muss <MandateEditor mandateId=...> unmittelbar
    # mounten (kein zusaetzlicher Report-Wrapper).
    assert "<MandateEditor mandateId=" in wrapper_block


def test_html_bridge_opens_exact_same_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openMandateEditor(){" in html
    bridge_fn = html.split(
        "async function openMandateEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    # Die Bruecke muss ueber /mandates/{id}/... adressieren, exakt wie die
    # React-Route /mandates/:mandateId/mandate-editor es erwartet.
    assert "/mandates/" in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_other_editor_bridges():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # openReportingApp (Advisory-Report), openProfilingEditor (Risikoprofil)
    # UND openMandateEditor muessen dieselbe Token-/Base-URL-Aufloesung
    # nutzen -- keine dritte, evtl. driftende Kopie der Handoff-Logik.
    # 2026-08-02 (Integration): 9 Editor-Bridges teilen sich diese Funktion
    # (openReportingApp, openProfilingEditor, openGoalsEditor,
    # openCashflowEditor, openAllocationEditor, openMandateEditor,
    # openCrmEditor, openCrmEditorForClient, openWealthInflowEditor).
    assert html.count("await resolveReportingAppUrl(path)") == 9


def test_mandate_editor_entry_point_is_reachable_from_stammdaten_section():
    html = _read(HTML_PATH)
    sd_header = html.split('<div id="page-sd" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    assert 'id="btn-sd-mandate-react-editor"' in sd_header
    assert "openMandateEditor()" in sd_header
    # Das Inline-Mandate-Settings-Modal bleibt in dieser Migrationsphase aktiv
    # (Zwei-Stack-Uebergang gemaess ADR-008) -- keine Fachlogik-Sektion wird
    # entfernt.
    assert "openStammdatenModal()" in sd_header


def test_react_mandate_api_client_calls_same_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    mandate_api = _read(MANDATE_API_PATH)

    # HTML (openMandateSettingsModal/saveMandateSettings) und React
    # (fetchMandate/updateMandate) muessen exakt denselben Endpunkt
    # ansprechen: GET/PUT /mandates/{id}.
    assert "API.get('/mandates/'+encodeURIComponent(mid))" in html
    assert "API.put('/mandates/'+encodeURIComponent(mid)" in html

    assert "`${baseUrl}/mandates/${encodeURIComponent(mandateId)}`" in mandate_api
    assert "method: 'GET'" in mandate_api
    assert "method: 'PUT'" in mandate_api


def test_react_mandate_page_does_not_reimplement_validation_logic():
    """Reine UI-Migration: die React-Seite darf keine eigene Validierungs-
    oder Payload-Logik fuehren, sondern muss validateMandate()/
    buildMandateUpdatePayload() aus lib/mandateForm.ts uebernehmen (analog zur
    Scoring-Delegation bei ProfilingPage.tsx / Roadmap #63)."""
    page = _read(MANDATE_EDITOR_PAGE_PATH)

    assert "validateMandate(form)" in page
    assert "buildMandateUpdatePayload(form)" in page

    forbidden_inline_reimplementation = re.compile(r"function\s+validateMandate|function\s+buildMandateUpdatePayload")
    assert not forbidden_inline_reimplementation.search(page)
