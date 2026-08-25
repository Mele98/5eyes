"""Drift-Test fuer die Roadmap-#68-Migration (ADR-008 Track 2, Cashflow-Editor).

Analog zu Roadmap #63 (Profiling, siehe test_profiling_editor_wiring_contract.py)
ist der Cashflow-Editor eine bereits fertig gebaute React-Seite
(`5eyes-electron/frontend/reporting/src/sections/cashflow/CashflowEditor.tsx`),
die ueber die Route `/clients/:clientId/cashflow-editor` erreichbar ist (siehe
App.tsx: `CashflowEditorRoute` liest `:clientId` und rendert `<CashflowEditor
clientId=.../>`). Anders als beim Profiling-Editor haengt der Cashflow-Editor
am KUNDEN (Client), nicht am Mandat -- die Backend-Endpunkte
(`/clients/{id}/cashflows`, siehe wealth.py) sind client-skopiert.

Fehlender Schritt war (Stand dieses Tests) das **Wiring**: die React-Seite
war/ist unter `/clients/:clientId/cashflow-editor` geroutet, aber im
HTML-Monolithen (`page-cf`, "Einnahmen, Ausgaben und Ziele") nirgends
erreichbar. Dieser Test haelt die Bruecke zwischen beiden Seiten synchron,
analog zu `openProfilingEditor()`:

- Route im React-Router (App.tsx)
- Wiring-Funktion `openCashflowEditor()` im Monolithen (5eyes_v2.html),
  die per `resolveReportingAppUrl()` denselben Token-Handoff nutzt wie
  `openReportingApp()` und `openProfilingEditor()`
- Button `id="btn-cf-cashflow-react-editor"` im Overflow-Menu des
  page-cf-Headers
- Backend-Endpunkte im React-API-Client (api/cashflow.ts) bleiben identisch
  zu denen, die der Inline-Workflow in 5eyes_v2.html bereits verwendet

Wichtige Abgrenzung zu den bestehenden `test_frontend_cashflow_*`-Tests
(z.B. test_frontend_cashflow_goal_workspace_contracts.py, Nachfolger des in
ADR-008 erwaehnten "Cashflow-Review-Editor"-Drift-Tests): jene Tests pruefen
das CSS/DOM-Layout des INLINE-HTML-Workflows auf page-cf (Grid-Spalten,
HUD-Position, Summary-Strip-Reihenfolge etc.), nicht die Bruecke zur
React-Seite. Dieser Test hier prueft ausschliesslich das Wiring (Route <->
Funktion <-> Button <-> Endpunkt-Parity) und dupliziert daher keinen
bestehenden Test.
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
CASHFLOW_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "cashflow.ts"
)
CASHFLOW_PAGE_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "cashflow"
    / "CashflowEditor.tsx"
)

REACT_ROUTE_PATH = "/clients/:clientId/cashflow-editor"
HTML_WIRING_PATH_SEGMENT = "/cashflow-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_router_still_mounts_cashflow_editor_at_expected_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    # Muss auf die CashflowEditorRoute-Wrapper-Komponente gemountet sein, die
    # :clientId aus der URL liest und an <CashflowEditor clientId=.../>
    # weiterreicht (Cashflow haengt am Kunden, nicht am Mandat).
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:200]
    assert "<CashflowEditorRoute" in route_block

    assert "function CashflowEditorRoute()" in app_tsx
    route_fn_body = app_tsx.split("function CashflowEditorRoute()", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "useParams<{ clientId: string }>()" in route_fn_body
    assert "<CashflowEditor clientId={clientId} />" in route_fn_body


def test_html_bridge_opens_exact_same_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openCashflowEditor(){" in html
    bridge_fn = html.split(
        "async function openCashflowEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    # Die Bruecke muss ueber /clients/{id}/... adressieren, exakt wie die
    # React-Route /clients/:clientId/cashflow-editor es erwartet (KEIN
    # Mandats-Pfad wie bei openProfilingEditor()).
    assert "/clients/" in bridge_fn
    assert "getActiveClientId" in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_advisory_report_bridge():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # openReportingApp (Advisory-Report), openProfilingEditor UND
    # openCashflowEditor muessen sich dieselbe Token-/Base-URL-Aufloesung
    # teilen -- keine dritte, evtl. driftende Kopie der Handoff-Logik.
    # 2026-08-02 (Integration): 9 Editor-Bridges teilen sich diese Funktion
    # (openReportingApp, openProfilingEditor, openGoalsEditor,
    # openCashflowEditor, openAllocationEditor, openMandateEditor,
    # openCrmEditor, openCrmEditorForClient, openWealthInflowEditor).
    assert html.count("await resolveReportingAppUrl(path)") == 9


def test_cashflow_editor_entry_point_is_reachable_from_cashflow_section():
    html = _read(HTML_PATH)
    cf_header = html.split('<div id="page-cf" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    assert 'id="btn-cf-cashflow-react-editor"' in cf_header
    assert "openCashflowEditor()" in cf_header
    # Inline-Cashflow-Workflow bleibt in dieser Migrationsphase aktiv
    # (Zwei-Stack-Uebergang gemaess ADR-008) -- keine Fachlogik-Sektion wird
    # entfernt oder ersetzt.
    assert "openNewCashflow('Income')" in cf_header
    assert "openNewCashflow('Expense')" in cf_header


def test_react_cashflow_api_client_calls_same_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    cashflow_api = _read(CASHFLOW_API_PATH)

    # HTML (createCashflow/updateCashflow-Aequivalent ueber API.post/API.put)
    # und React (createCashflow/updateCashflow) muessen exakt denselben
    # Endpunkt-Pfad ansprechen: /clients/{id}/cashflows.
    assert "'/clients/'+cid+'/cashflows'" in html
    assert (
        "/clients/${encodeURIComponent(clientId)}/cashflows`"
        in cashflow_api
    )

    assert "'/clients/'+cid+'/cashflows-derived'" in html
    assert "cashflowsBase(clientId, baseUrl)}-derived" in cashflow_api


def test_react_cashflow_page_does_not_reimplement_derived_cashflow_projection():
    """Reine UI-Migration: die React-Seite darf keine eigene
    Vermoegens-/Cashflow-Projektionslogik fuehren, sondern muss die
    Backend-berechneten derived cashflows (AHV/Pension/etc., siehe
    clients.py:315) unveraendert uebernehmen (fetchDerivedCashflows)."""
    page = _read(CASHFLOW_PAGE_PATH)

    assert "fetchDerivedCashflows" in page
    forbidden_projection_math = re.compile(
        r"(projected|projection)\w*\s*=\s*[^=]*[+\-*/]"
    )
    assert not forbidden_projection_math.search(page)
