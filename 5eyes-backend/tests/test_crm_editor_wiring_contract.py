"""Drift-Test fuer die Roadmap-#66-Migration (ADR-008 Track 2, Kunden-CRM).

Kunden-CRM ist die naechste Sektion nach dem Profiling-Fragebogen, die dem
ADR-008-Muster (Schema-First -> React-Page -> Tests -> Wiring -> Drift-Test)
folgt:

- React-Komponente + API-Client + Tests bereits vorhanden (Track #66):
  5eyes-electron/frontend/reporting/src/sections/crm/CrmEditor.tsx
  5eyes-electron/frontend/reporting/src/api/crm.ts
- Zwei React-Router-Routen existieren bereits in App.tsx:
    /crm-editor                     -> <CrmEditor />            (Suche/Liste,
                                        kein Kunde vorselektiert)
    /clients/:clientId/crm-editor   -> <CrmEditorRoute />        (Deep-Link,
                                        laedt Stammdaten des Kunden vor)
- Fehlender Schritt (dieser PR/dieses Ticket) ist das **Wiring**: beide
  Routen waren im HTML-Monolithen nirgends erreichbar.

Gewaehlte Integrationspunkte (siehe finaler Report des Wiring-Auftrags):
1. Sidebar-Kundenregister (".sb-hd", neben "Alle anzeigen") -> clientloser
   Einstieg ueber openCrmEditor() -> /crm-editor. Das ist der natuerliche Ort
   fuer "Kunden suchen/verwalten" ohne bereits ausgewaehltes Mandat.
2. Stammdaten-Seite (#page-sd) -> Einstieg fuer den aktuell aktiven Kunden
   ueber openCrmEditorForClient() -> /clients/{id}/crm-editor, analog zum
   Muster von getActiveMandateId()/openProfilingEditor().

Dieser Test haelt die Bruecke zwischen React-Routen, HTML-Wiring-Funktionen
und Backend-Endpunkten synchron: bricht eine Seite auseinander ohne dass die
jeweils andere mitgezogen wird, schlaegt er fehl (Silent-Drift-Schutz).

Da das Wiring in 5eyes_v2.html zum Zeitpunkt dieses Commits noch NICHT
angewendet wurde (siehe Wiring-Auftrag: Datei wird von mehreren Agenten
parallel bearbeitet, daher nur Report statt Direkt-Edit), MUESSEN die
wiring-bezogenen Assertions hier zunaechst fehlschlagen (rot), bis jemand
die im Report beschriebenen Snippets tatsaechlich eintraegt.
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
CRM_API_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "api"
    / "crm.ts"
)
CRM_EDITOR_PATH = (
    REPO_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "crm"
    / "CrmEditor.tsx"
)

REACT_ROUTE_PATH_LIST = "/crm-editor"
REACT_ROUTE_PATH_CLIENT = "/clients/:clientId/crm-editor"
HTML_WIRING_PATH_SEGMENT = "/crm-editor"


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def test_react_router_still_mounts_crm_editor_at_clientless_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH_LIST}"' in app_tsx
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH_LIST}"', 1)[1][:80]
    # Muss unmittelbar auf <CrmEditor /> gemountet sein (kein Report-Shell-
    # Wrapper, das waere Read-Only statt Editor-Workflow).
    assert "<CrmEditor" in route_block


def test_react_router_still_mounts_crm_editor_at_per_client_route():
    app_tsx = _read(APP_TSX_PATH)

    assert f'path="{REACT_ROUTE_PATH_CLIENT}"' in app_tsx
    route_block = app_tsx.split(f'path="{REACT_ROUTE_PATH_CLIENT}"', 1)[1][:120]
    assert "<CrmEditorRoute" in route_block

    # CrmEditorRoute muss den clientId-Parameter tatsaechlich als
    # initialClientId an CrmEditor durchreichen (Deep-Link-Vertrag).
    route_fn_block = app_tsx.split("function CrmEditorRoute()", 1)[1][:300]
    assert "useParams" in route_fn_block
    assert "clientId" in route_fn_block
    assert "<CrmEditor initialClientId={clientId} />" in route_fn_block


def test_html_bridge_opens_exact_clientless_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openCrmEditor(){" in html
    bridge_fn = html.split(
        "async function openCrmEditor(){", 1
    )[1].split("\n}\n", 1)[0]

    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn
    # Der clientlose Einstieg braucht keinen Mandats-/Kunden-Guard -- die
    # Route nimmt keine ID entgegen.
    assert "getActiveClientId" not in bridge_fn
    assert "getActiveMandateId" not in bridge_fn


def test_html_bridge_opens_exact_per_client_route_the_react_router_exposes():
    html = _read(HTML_PATH)

    assert "async function openCrmEditorForClient(){" in html
    bridge_fn = html.split(
        "async function openCrmEditorForClient(){", 1
    )[1].split("\n}\n", 1)[0]

    assert "/clients/" in bridge_fn
    assert HTML_WIRING_PATH_SEGMENT in bridge_fn
    assert "resolveReportingAppUrl(path)" in bridge_fn
    # Muss denselben Guard-Stil wie openProfilingEditor() nutzen (kein
    # eigenes, driftendes Fehlerverhalten).
    assert "getActiveClientId" in bridge_fn
    assert "showAppError" in bridge_fn or "alert(" in bridge_fn


def test_html_bridge_reuses_same_token_handoff_as_other_react_bridges():
    html = _read(HTML_PATH)

    assert "async function resolveReportingAppUrl(path){" in html

    for fn_name in ("openCrmEditor", "openCrmEditorForClient"):
        bridge_fn = html.split(f"async function {fn_name}(){{", 1)[1].split(
            "\n}\n", 1
        )[0]
        assert "await resolveReportingAppUrl(path)" in bridge_fn, (
            f"{fn_name} muss dieselbe Token-/Base-URL-Aufloesung nutzen wie "
            "openReportingApp()/openProfilingEditor() -- keine zweite, "
            "evtl. driftende Kopie der Handoff-Logik."
        )


def test_crm_editor_clientless_entry_point_is_reachable_from_sidebar_register():
    html = _read(HTML_PATH)
    sidebar_hd = html.split('<div class="sb-hd">', 1)[1].split("</div>", 1)[0]

    assert 'id="btn-crm-react-editor"' in sidebar_hd
    assert "openCrmEditor()" in sidebar_hd
    # Sidebar-Suche/-Register bleibt aktiv (Zwei-Stack-Uebergang gemaess
    # ADR-008) -- keine Fachlogik-Sektion wird entfernt.
    assert "Alle anzeigen" in sidebar_hd


def test_crm_editor_per_client_entry_point_is_reachable_from_stammdaten_page():
    html = _read(HTML_PATH)
    sd_header = html.split('<div id="page-sd" class="page">', 1)[1].split(
        '<div class="pad">', 1
    )[0]

    assert 'id="btn-sd-crm-react-editor"' in sd_header
    assert "openCrmEditorForClient()" in sd_header
    # Inline-Stammdaten-Modal bleibt in dieser Migrationsphase aktiv
    # (Zwei-Stack-Uebergang gemaess ADR-008) -- keine Fachlogik-Sektion wird
    # entfernt.
    assert "openStammdatenModal()" in sd_header


def test_react_crm_api_client_calls_same_endpoints_as_html_monolith():
    html = _read(HTML_PATH)
    crm_api = _read(CRM_API_PATH)

    # HTML (Stammdaten-Liste/-Speichern) und React (listClients/updateClient)
    # muessen denselben Endpunkt-Stamm ansprechen.
    assert "'/clients'" in html or '"/clients"' in html
    assert "/clients${" in crm_api or "/clients?" in crm_api or "`${baseUrl}/clients" in crm_api

    assert "/clients/'+cid" in html or "/clients/'+clientId" in html or "/clients/'+currentClientId" in html
    assert "/clients/${encodeURIComponent(clientId)}" in crm_api


def test_react_crm_editor_does_not_bypass_api_client_with_raw_fetch():
    """Reine UI-Migration: CrmEditor.tsx darf keine eigenen fetch()-Aufrufe
    fuehren, sondern muss ausschliesslich ueber api/crm.ts (listClients/
    fetchClient/updateClient) mit dem Backend sprechen. Das ist das CRM-
    Analogon zu 'keine eigene Scoring-Logik' beim Profiling-Editor: es
    verhindert eine zweite, potenziell driftende Kopie der Backend-
    Anbindung direkt in der Komponente."""
    page = _read(CRM_EDITOR_PATH)

    assert "fetch(" not in page
    assert "listClients" in page
    assert "fetchClient" in page
    assert "updateClient" in page
