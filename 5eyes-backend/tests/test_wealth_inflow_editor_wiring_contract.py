"""Drift-Test fuer die Roadmap-#54-Migration (ADR-008 Track 2, Modul C).

Der Vermoegenszufluesse-Editor (WealthInflowEditor) ist gemaess ADR-008
"Update 2026-07-23" eine der Sektionen, deren React-Route (App.tsx) bereits
existiert, ohne dass sie im HTML-Monolithen erreichbar ist ("Gleiche
Wiring-Luecke besteht noch fuer ... WealthInflowEditor in App.tsx").

Analog zum Profiling-Wiring (openProfilingEditor(), siehe
test_profiling_editor_wiring_contract.py) muss eine openWealthInflowEditor()
-Bruecke in 5eyes_v2.html die React-Seite per Token-Handoff in einem neuen
Tab oeffnen -- diesmal ueber die Client-ID (nicht Mandats-ID), weil die
React-Route /clients/:clientId/wealth-inflows-editor lautet.

Dieser Test haelt die Bruecke zwischen beiden Seiten synchron: bricht die
Route im React-Router, die Backend-Endpunkte im React-API-Client oder die
Wiring-Funktion im Monolithen auseinander, ohne dass die jeweils andere
Seite mitgezogen wird, schlaegt er fehl (Silent-Drift-Schutz).

Stand bei Erstellung dieses Tests: das Wiring in 5eyes_v2.html ist NOCH
NICHT eingebaut (nur die React-Seite existiert bereits) -- die
wiring-bezogenen Assertions (Funktion/Button/Handoff-Zaehler) schlagen
deshalb erwartungsgemaess fehl (rot), bis die Bruecke ergaenzt wird.
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
WEALTH_INFLOW_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "wealthInflow.ts"
)
WEALTH_INFLOW_PAGE_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "wealthInflow"
    / "WealthInflowEditor.tsx"
)
WEALTH_INFLOW_FORM_LIB_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "lib"
    / "wealthInflowForm.ts"
)

REACT_ROUTE_PATH = "/clients/:clientId/wealth-inflows-editor"
HTML_WIRING_PATH_SEGMENT = "/wealth-inflows-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_router_still_mounts_wealth_inflow_editor_at_expected_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    # Muss unmittelbar auf die Route-Wrapper-Komponente gemountet sein (kein
    # ReportShell-Wrapper, das waere ein Read-Only-Report statt des
    # Editor-Workflows). Die Wrapper-Komponente validiert :clientId und
    # reicht ihn an <WealthInflowEditor clientId={clientId} /> durch.
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:200]
    assert "<WealthInflowEditorRoute" in route_block


def test_html_bridge_opens_exact_same_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openWealthInflowEditor(){" in html
    bridge_fn = html.split(
        "async function openWealthInflowEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    # Die Bruecke muss ueber /clients/{id}/... adressieren (Client-ID, NICHT
    # Mandats-ID), exakt wie die React-Route
    # /clients/:clientId/wealth-inflows-editor es erwartet.
    assert "/clients/" in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_advisory_report_bridge():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # openReportingApp (Advisory-Report), openProfilingEditor UND
    # openWealthInflowEditor muessen dieselbe Token-/Base-URL-Aufloesung
    # nutzen -- keine dritte, evtl. driftende Kopie der Handoff-Logik.
    # 2026-08-02 (Integration): 9 Editor-Bridges teilen sich diese Funktion
    # (openReportingApp, openProfilingEditor, openGoalsEditor,
    # openCashflowEditor, openAllocationEditor, openMandateEditor,
    # openCrmEditor, openCrmEditorForClient, openWealthInflowEditor).
    assert html.count("await resolveReportingAppUrl(path)") == 9


def test_wealth_inflow_editor_entry_point_is_reachable_from_vermoegen_section():
    html = _read(HTML_PATH)
    vg_header = html.split('<div id="page-vg" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    assert 'id="btn-vg-wealthinflow-react-editor"' in vg_header
    assert "openWealthInflowEditor()" in vg_header
    # Inline-Erfassung ("+ Position", oeffnet Modal m-aw) bleibt in dieser
    # Migrationsphase aktiv (Zwei-Stack-Uebergang gemaess ADR-008) -- keine
    # Fachlogik-Sektion wird entfernt.
    assert "om('m-aw')" in vg_header


def test_react_wealth_inflow_api_client_calls_same_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    api = _read(WEALTH_INFLOW_API_PATH)

    # Collection-Endpoint (GET Liste / POST Neuanlage) laeuft unter
    # /clients/{id}/wealth-inflows -- HTML (Inline-CRUD, routers/wealth.py)
    # und React-API-Client muessen denselben Pfad ansprechen.
    assert "/clients/'+cid+'/wealth-inflows'" in html
    assert "/clients/${encodeURIComponent(clientId)}/wealth-inflows" in api

    # Item-Endpoint (PUT/DELETE) laeuft NICHT unter /clients (Inflow-ID ist
    # global eindeutig), siehe Doc-Kommentar in api/wealthInflow.ts.
    assert "/wealth-inflows/'+currentInflowEditId" in html
    assert "/wealth-inflows/'+inflowId" in html
    assert "/wealth-inflows/${encodeURIComponent(inflowId)}" in api


def test_react_wealth_inflow_editor_does_not_reimplement_projection_math():
    """Reine UI-Migration: der Editor darf keine eigene Hochrechnung fuehren
    (z.B. kumulierter Betrag ueber Frequenz * Laufzeit) -- das gehoert in die
    Planungs-Engine (services/portfolio_engine.py), nicht in die
    Praesentationsschicht. Der Editor reicht amount_rappen/duration_years/
    frequency unveraendert an das Backend durch (siehe buildWealthInflowPayload
    in lib/wealthInflowForm.ts)."""
    page = _read(WEALTH_INFLOW_PAGE_PATH)
    form_lib = _read(WEALTH_INFLOW_FORM_LIB_PATH)

    forbidden_projection_math = re.compile(
        r"(amount|duration)[A-Za-z_]*\s*\*\s*(duration|amount|frequency)",
        re.IGNORECASE,
    )
    assert not forbidden_projection_math.search(page)
    assert not forbidden_projection_math.search(form_lib)
