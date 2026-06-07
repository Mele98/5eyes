"""Bug-#6 (2026-06-07): Advisory-Report im Portfolio kaputt.

User-Report: 'Hmmm...diese Seite ist leider nicht erreichbar
localhost haben die Verbindung verweigert. ERR_CONNECTION_REFUSED'

Root-Cause: openReportingApp() im Hauptfrontend oeffnete hartcodierten
Vite-Dev-Server (http://localhost:5173). Der laeuft in der Demo/Production
nicht — Berater sah leere Seite mit Verbindungsfehler.

Fix:
- vite.config.ts: base='/reporting/'
- main.tsx: BrowserRouter basename='/reporting'
- Backend main.py: mount StaticFiles auf /reporting + SPA-Fallback
- 5eyes_v2.html: openReportingApp() nutzt Backend-URL (gleicher Origin
  wie die API), kein separater Dev-Server mehr noetig.

Tests:
- /reporting liefert index.html
- /reporting/mandates/<id>/report liefert index.html (SPA-Fallback)
- /reporting/assets/<file> 404 wenn File nicht existiert, statisch sonst
- Frontend-Source-Parse: Marker + Backend-URL-Pattern
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Modelle muessen vor dem main-Import registriert sein.
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

REPORTING_DIST = (
    BACKEND_ROOT.parent
    / "5eyes-electron" / "frontend" / "reporting" / "dist"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.skipif(
    not (REPORTING_DIST / "index.html").is_file(),
    reason="Reporting-Dist nicht gebaut — npm run build im reporting/-Ordner",
)
def test_reporting_root_liefert_spa_index(client):
    """GET /reporting → SPA-index.html."""
    resp = client.get("/reporting")
    assert resp.status_code == 200
    body = resp.text
    assert "<div id=\"root\">" in body
    assert "/reporting/assets/" in body  # Vite base-Prefix korrekt


@pytest.mark.skipif(
    not (REPORTING_DIST / "index.html").is_file(),
    reason="Reporting-Dist nicht gebaut",
)
def test_reporting_spa_fallback_fuer_react_router_pfad(client):
    """GET /reporting/mandates/<id>/report → liefert auch index.html.

    react-router uebernimmt clientseitig die Aufloesung; Backend muss
    fuer alle Tiefenpfade die index.html zurueckgeben (SPA-Pattern).
    """
    resp = client.get("/reporting/mandates/m-test-123/report")
    assert resp.status_code == 200
    assert "<div id=\"root\">" in resp.text


@pytest.mark.skipif(
    not (REPORTING_DIST / "index.html").is_file(),
    reason="Reporting-Dist nicht gebaut",
)
def test_reporting_assets_404_fuer_unbekannte_datei(client):
    """Asset-Pfad-Praefix darf NICHT vom SPA-Fallback abgefangen werden,
    sonst bekaeme der Browser HTML statt 404 und scheitert beim JS-Parse."""
    resp = client.get("/reporting/assets/nicht-vorhanden-xyz.js")
    assert resp.status_code == 404


def test_reporting_dist_index_html_hat_korrekten_base_prefix():
    """vite.config.ts base='/reporting/' muss sich in den gebauten
    Asset-URLs niederschlagen. Sonst landen <script src=...> auf der
    falschen Origin (Wurzel statt /reporting/)."""
    if not (REPORTING_DIST / "index.html").is_file():
        pytest.skip("Reporting-Dist nicht gebaut")
    index = (REPORTING_DIST / "index.html").read_text(encoding="utf-8")
    # Kein nackter /assets/-Pfad, sondern /reporting/assets/.
    assert "src=\"/reporting/assets/" in index
    assert "href=\"/reporting/assets/" in index
    # Negativ: kein nackter /assets/ (Build-Drift-Wache)
    assert "src=\"/assets/" not in index


# ===========================================================================
# Frontend-Source-Parse
# ===========================================================================


def test_frontend_open_reporting_app_nutzt_backend_url():
    """5eyes_v2.html: openReportingApp() darf NICHT mehr localhost:5173
    hartcodieren, sondern muss Backend-Base + /reporting/ benutzen."""
    html_path = (
        BACKEND_ROOT.parent
        / "5eyes-electron" / "frontend" / "5eyes_v2.html"
    )
    text = html_path.read_text(encoding="utf-8")

    bug6_start = text.find("Bug-#6 (2026-06-07)")
    assert bug6_start > 0, "Bug-#6-Marker fehlt in 5eyes_v2.html"

    # Im openReportingApp-Block: Backend-Mount-Pfad und keine 5173-Konstante.
    fn_start = text.find("async function openReportingApp", bug6_start)
    fn_end = text.find("\n}\n", fn_start)
    assert fn_start > 0 and fn_end > fn_start
    fn_body = text[fn_start:fn_end]
    assert "'/reporting'" in fn_body or "\"/reporting\"" in fn_body
    assert "localhost:5173" not in fn_body, (
        "Vite-Dev-Server-URL ist noch im Code — Fix unvollstaendig"
    )


def test_vite_config_hat_base_reporting():
    """Vite muss mit base='/reporting/' bauen, sonst stimmen die
    Asset-URLs im gebauten index.html nicht."""
    vite_config = (
        BACKEND_ROOT.parent
        / "5eyes-electron" / "frontend" / "reporting" / "vite.config.ts"
    )
    text = vite_config.read_text(encoding="utf-8")
    assert "base: '/reporting/'" in text


def test_main_tsx_browser_router_basename():
    """BrowserRouter braucht basename='/reporting', damit react-router-
    Pfade unter /reporting/* aufgeloest werden."""
    main_tsx = (
        BACKEND_ROOT.parent
        / "5eyes-electron" / "frontend" / "reporting" / "src" / "main.tsx"
    )
    text = main_tsx.read_text(encoding="utf-8")
    assert "basename=\"/reporting\"" in text
