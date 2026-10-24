"""PROVISORIK-WARNBANNER-JSON-001 (Kontrollrunde 2026-09-27).

`services.jurisdiction.provisional_gate.assert_jurisdiction_ready()` existiert
seit WP2, hatte aber ausser Tests keine echten Aufrufstellen -- die
Provisorik-Warnung ("PROVISORISCH -- NICHT IC-FREIGEGEBEN") erreichte NUR den
PDF-Export (services/pdf/provisional_notice.py, ueber die 6 Dokumenttypen).
Weder der JSON-Aggregator (services/advisory_report.py, konsumiert von der
React-Reporting-App und der API) noch das Kundenportal
(routers/client_portal.py::client_portal_mandate_report, das denselben
Aggregator-Payload 1:1 weiterreicht) zeigten diese Warnung -- ein Kunde mit
einem Nicht-CH-Mandat und noch nicht IC-freigegebenen Kapitalmarktannahmen
sah in seinem EIGENEN Portal WENIGER Warnung als der Berater im PDF.

Dieser Test deckt:
1. compute_advisory_report() liefert das neue Top-Level-Feld
   "provisional_data_warning" (None fuer CH, dict fuer Nicht-CH ohne
   IC-Freigabe) -- sowohl mit als auch ohne existierenden RecommendationRun.
2. Das Feld ist in PROTECTED_REPORT_SECTIONS -- laesst sich NICHT per
   mandate.hidden_report_sections wegkonfigurieren.
3. Der tatsaechliche Kundenportal-Endpoint (GET /client-portal/mandates/
   {id}/report) liefert dasselbe Feld -- End-to-End-Beweis, dass die
   Warnung den Kunden wirklich erreicht, nicht nur den JSON-Aggregator
   isoliert betrachtet.

Wiederverwendet die DE-Seed-Helper aus tests/test_engine_de_jurisdiction_
wiring.py (WP2) und den Provisorik-Test-Aufbau aus
tests/test_provisional_pdf_gate.py, um Fixture-Duplikation zu vermeiden.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.client_login import ClientLogin
from models.mandates import Mandate
from models.users import User
from services.advisory_report import PROTECTED_REPORT_SECTIONS, compute_advisory_report
from services.portfolio_engine import generate_recommendation_run

# Wiederverwendete DE-Seed-Fixtures aus WP2 (Engine-Wiring).
from test_engine_de_jurisdiction_wiring import (  # noqa: F401 (session_factory ist eine Fixture)
    _seed_de_mandate,
    session_factory,
)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 1) JSON-Aggregator: Feld ist gesetzt/None je nach Jurisdiktion+CMA-Status
# ---------------------------------------------------------------------------

def test_provisional_data_warning_none_for_de_committee_approved_with_run(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="jsonagg-approved-run", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        report = compute_advisory_report(s, mandate)
    assert report["provisional_data_warning"] is None


def test_provisional_data_warning_set_for_de_data_derived_with_run(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="jsonagg-provisional-run", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        report = compute_advisory_report(s, mandate)
    warning = report["provisional_data_warning"]
    assert warning is not None
    assert warning["jurisdiction"] == "DE"
    assert warning["cma_status"] == "data_derived"
    assert "PROVISORISCH" in warning["message"]


def test_provisional_data_warning_set_for_de_data_derived_without_run(session_factory):
    """Kein RecommendationRun existiert noch -- Live-Pruefung der aktuellen
    CMA-Referenzzeile muss trotzdem die Warnung ausloesen."""
    _advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="jsonagg-provisional-norun", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        report = compute_advisory_report(s, mandate)
    warning = report["provisional_data_warning"]
    assert warning is not None
    assert warning["jurisdiction"] == "DE"


def test_provisional_data_warning_none_for_ch_mandate(session_factory):
    """CH-Mandat (jurisdiction None/"CH") -- IMMER None, unabhaengig vom
    CMA-Status irgendeiner Jurisdiktion."""
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="jsonagg-ch-control", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        mandate.jurisdiction = None
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        report = compute_advisory_report(s, mandate)
    assert report["provisional_data_warning"] is None


# ---------------------------------------------------------------------------
# 2) Kann nicht per hidden_report_sections versteckt werden
# ---------------------------------------------------------------------------

def test_provisional_data_warning_is_protected_from_hiding(session_factory):
    import json as _json

    assert "provisional_data_warning" in PROTECTED_REPORT_SECTIONS

    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="jsonagg-hide-attempt", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        mandate.hidden_report_sections = _json.dumps(["provisional_data_warning"])
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        report = compute_advisory_report(s, mandate)
    assert report["provisional_data_warning"] is not None


# ---------------------------------------------------------------------------
# 3) End-to-End: der echte Kundenportal-Endpoint liefert dieselbe Warnung
# ---------------------------------------------------------------------------

def test_client_portal_report_endpoint_surfaces_provisional_warning(session_factory):
    """GET /client-portal/mandates/{id}/report -- derselbe Kunde, der sein
    eigenes Nicht-CH-Mandat einsieht, MUSS die Provisorik-Warnung sehen,
    nicht nur der Berater im PDF."""
    from fastapi.testclient import TestClient

    from database import get_db
    from main import app
    from services.auth import get_current_user

    advisor_id, mid, tenant_id = _seed_de_mandate(
        session_factory, suffix="portal-e2e", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        cid = mandate.client_id
        now = _now()
        client_user = User(
            id="portal-e2e-user", username="portal-e2e-user", password_hash="h",
            full_name="DE Test Client", role="client", is_active=1,
            tenant_id=tenant_id, created_at=now, updated_at=now,
        )
        s.add(client_user)
        s.add(ClientLogin(
            id="portal-e2e-link", user_id="portal-e2e-user", client_id=cid,
            is_active=1, created_by=advisor_id, created_at=now,
        ))
        s.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    from types import SimpleNamespace
    current = SimpleNamespace(
        id="portal-e2e-user", full_name="DE Test Client",
        email="c@test.local", role="client",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    try:
        with TestClient(app) as client:
            response = client.get(f"/client-portal/mandates/{mid}/report")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    warning = data["provisional_data_warning"]
    assert warning is not None
    assert warning["jurisdiction"] == "DE"
    assert "PROVISORISCH" in warning["message"]


def test_client_portal_report_endpoint_no_warning_for_ch_control(session_factory):
    """Gegenprobe: derselbe Endpoint zeigt fuer ein bereits IC-freigegebenes
    Mandat KEIN Banner -- kein falsch-positiver Alarm."""
    from fastapi.testclient import TestClient

    from database import get_db
    from main import app
    from services.auth import get_current_user

    advisor_id, mid, tenant_id = _seed_de_mandate(
        session_factory, suffix="portal-e2e-approved", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        cid = mandate.client_id
        now = _now()
        client_user = User(
            id="portal-e2e-user-2", username="portal-e2e-user-2", password_hash="h",
            full_name="DE Test Client 2", role="client", is_active=1,
            tenant_id=tenant_id, created_at=now, updated_at=now,
        )
        s.add(client_user)
        s.add(ClientLogin(
            id="portal-e2e-link-2", user_id="portal-e2e-user-2", client_id=cid,
            is_active=1, created_by=advisor_id, created_at=now,
        ))
        s.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    from types import SimpleNamespace
    current = SimpleNamespace(
        id="portal-e2e-user-2", full_name="DE Test Client 2",
        email="c2@test.local", role="client",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    try:
        with TestClient(app) as client:
            response = client.get(f"/client-portal/mandates/{mid}/report")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provisional_data_warning"] is None
