"""Drift-Test fuer die Roadmap-#67-Migration (ADR-008 Track 2, Modul C).

Analog zur ersten vollstaendigen Slice (Profiling-Fragebogen, siehe
test_profiling_editor_wiring_contract.py) ist der Asset-Allocation-Editor
bereits als React-Route + API-Client + Komponente fertig
(sections/allocation/AllocationEditor.tsx, api/allocation.ts, in App.tsx unter
/mandates/:mandateId/allocation-editor geroutet), aber noch NICHT aus dem
HTML-Monolithen erreichbar (ADR-008-Statustabelle: Asset-Allocation-Edit =
"aktiv" / "(View ✓)" / Drift-Test "✓" -- die vorhandenen Drift-Tests, z.B.
test_frontend_navigation_contracts.py und test_frontend_soll_donut_context.py,
pruefen ausschliesslich die Inline-HTML-Sektion selbst (Navigation, SOLL-Donut-
Kontext-Text) -- keiner von ihnen deckt eine Wiring-Bruecke zum React-Editor
ab, weil diese Bruecke bislang nicht existiert).

Dieser Test haelt -- sobald das Wiring nachgezogen wird -- die Bruecke
zwischen beiden Seiten synchron: bricht die Route im React-Router, die
Backend-Endpunkte im React-API-Client oder die Wiring-Funktion
(openAllocationEditor) im Monolithen auseinander, ohne dass die jeweils
andere Seite mitgezogen wird, schlaegt er fehl (Silent-Drift-Schutz).

Stand dieser PR: das Wiring (openAllocationEditor()-Funktion +
btn-al-react-editor-Button im page-al-Header) ist noch NICHT in
5eyes_v2.html eingebaut (mehrere Agenten arbeiten parallel an dieser Datei --
direkte Edits wuerden kollidieren). Die wiring-bezogenen Tests unten sind
deshalb bewusst rot, bis jemand die Bruecke ergaenzt.
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
ALLOCATION_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "allocation.ts"
)
ALLOCATION_EDITOR_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "allocation"
    / "AllocationEditor.tsx"
)

REACT_ROUTE_PATH = "/mandates/:mandateId/allocation-editor"
HTML_WIRING_PATH_SEGMENT = "/allocation-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_router_still_mounts_allocation_editor_at_expected_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH}"' in app_tsx
    # Muss auf die Editor-Route gemountet sein (AllocationEditorRoute), nicht
    # auf ein ReportShell/Read-Only-Rendering.
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH}"', 1)[1][:200]
    assert "<AllocationEditorRoute" in route_block


def test_allocation_editor_route_component_mounts_editor_not_readonly_view():
    app_tsx = _read(APP_TSX_PATH)

    assert "function AllocationEditorRoute()" in app_tsx
    route_fn_block = app_tsx.split("function AllocationEditorRoute()", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "<AllocationEditor mandateId={mandateId} />" in route_fn_block


def test_html_bridge_opens_exact_same_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openAllocationEditor(){" in html
    bridge_fn = html.split(
        "async function openAllocationEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    # Die Bruecke muss ueber /mandates/{id}/... adressieren, exakt wie die
    # React-Route /mandates/:mandateId/allocation-editor es erwartet.
    assert "/mandates/" in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_other_editor_bridges():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html
    # openReportingApp (Advisory-Report), openProfilingEditor UND
    # openAllocationEditor muessen sich dieselbe Token-/Base-URL-Aufloesung
    # teilen -- keine dritte, evtl. driftende Kopie der Handoff-Logik.
    # 2026-08-02 (Integration): 9 Editor-Bridges teilen sich diese Funktion
    # (openReportingApp, openProfilingEditor, openGoalsEditor,
    # openCashflowEditor, openAllocationEditor, openMandateEditor,
    # openCrmEditor, openCrmEditorForClient, openWealthInflowEditor).
    assert html.count("await resolveReportingAppUrl(path)") == 9


def test_allocation_editor_entry_point_is_reachable_from_asset_allocation_section():
    html = _read(HTML_PATH)
    al_header = html.split('<div id="page-al" class="page">', 1)[1].split(
        '<div id="al-dirty-banner"', 1
    )[0]

    assert 'id="btn-al-react-editor"' in al_header
    assert "openAllocationEditor()" in al_header
    # Inline-Strategie-Berechnung bleibt in dieser Migrationsphase aktiv
    # (Zwei-Stack-Uebergang gemaess ADR-008) -- keine Fachlogik-Sektion wird
    # entfernt.
    assert "calculateInvestmentStrategy()" in al_header


def test_react_allocation_api_client_calls_same_generate_and_sensitivity_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    allocation_api = _read(ALLOCATION_API_PATH)

    # HTML (calculateInvestmentStrategy / openStrategyBacktest-Flow) und React
    # (generateAllocation / runSensitivity) muessen exakt dieselben
    # Endpunkt-Suffixe unter target-allocation ansprechen.
    assert "/target-allocation/generate" in html
    assert "target-allocation" in allocation_api
    assert "/generate" in allocation_api

    assert "/target-allocation/sensitivity" in html
    assert "/sensitivity" in allocation_api


def test_react_allocation_editor_does_not_reimplement_optimizer_math():
    """Reine UI-Migration: der Editor darf den stochastischen Optimizer nicht
    clientseitig nachbauen. expected_return_bps / expected_volatility_bps /
    risky_fraction_total_bps muessen 1:1 aus der Backend-Generate-Response
    (services/portfolio_optimizer) uebernommen werden, keine lokale
    Neuberechnung dieser Kennzahlen."""
    editor = _read(ALLOCATION_EDITOR_PATH)

    forbidden_recompute = re.compile(
        r"(expected_return_bps|expected_volatility_bps|risky_fraction_total_bps)"
        r"\s*=\s*[^,;\n]*[+\-*/]"
    )
    assert not forbidden_recompute.search(editor)
