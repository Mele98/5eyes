"""FIDLEG Art. 8/9 Ex-ante Kostenausweis — Standalone-PDF.

Pendant zu PR 1 (JSON-Endpoint). Diese PR liefert das eigenstaendige
PDF-Dokument, das vor Auftragsausfuehrung dem Kunden ausgehaendigt
werden kann.

Backend-Cost-Logik ist in tests/pdf/test_kostenausweis.py separat
gedeckt; hier:
- Document-Composer baut Cover + Content (synthetisch)
- Renderer liefert valides PDF (sanity-check Magic-Bytes)
- Endpoint registriert + 404/200-Flow
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from services.auth import get_current_user
from services.pdf.base import CostDisclosurePDFData, PDFContext


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cost_disclosure_pdf.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-pdf-cd",
        username="advisor-pdf-cd",
        password_hash="h",
        full_name="Test Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _seed_minimal_mandate(session_factory, advisor_user, mandate_id: str = "mdt-pdf-cd") -> str:
    with session_factory() as db:
        db.add(advisor_user)
        db.add(Client(
            id="cli-pdf-cd", client_number="C-PDF-CD", first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id="cli-pdf-cd", mandate_number="M-PDF-CD",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id


# ---------------------------------------------------------------------------
# Endpoint-Verhalten
# ---------------------------------------------------------------------------


def test_endpoint_unknown_mandate_404(auth_client):
    resp = auth_client.get("/mandates/does-not-exist/reports/cost-disclosure.pdf")
    assert resp.status_code == 404


def test_endpoint_pending_liefert_valides_pdf(auth_client, advisor_user, session_factory):
    """Auch ohne Empfehlung muss das PDF rendern (pending-State -> Hinweis)."""
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/cost-disclosure.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    # PDF-Magic
    assert resp.content[:4] == b"%PDF"
    # Filename folgt dem Mandate-Number-Pattern (vermindert Pollution in
    # Download-Ordnern).
    assert "kostenausweis-M_PDF_CD" in resp.headers["content-disposition"]


def test_endpoint_in_route_table():
    paths = {getattr(r, "path", None) for r in app.routes if hasattr(r, "methods")}
    assert "/mandates/{mandate_id}/reports/cost-disclosure.pdf" in paths


# ---------------------------------------------------------------------------
# Document-Composer (synthetisch, ohne DB)
# ---------------------------------------------------------------------------


def _ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=datetime.date(2026, 6, 8), base_currency="CHF",
    )


def _full_payload() -> dict:
    return {
        "data_pending": False,
        "currency": "CHF",
        "as_of": "2026-06-08T00:00:00Z",
        "source_run_id": "run-1",
        "fidleg_basis": "Art. 8/9 FIDLEG; Art. 8/14 FIDLEV",
        "advisory_wealth_rappen": 1_000_000_00,
        "invested_amount_rappen": 1_000_000_00,
        "product_cost_coverage_bps": 10000,
        "cost_items": [
            {
                "key": "default_advisory_fee_bps",
                "label": "Beratungs-/Verwaltungsgebuehr",
                "category": "Dienstleistungskosten",
                "frequency": "jaehrlich",
                "rate_bps": 25,
                "amount_rappen": 2_500_00,
                "basis_rappen": 1_000_000_00,
                "basis_label": "Beratungsvermoegen",
                "source": "Gebuehrenmodell der Empfehlung",
                "is_estimate": False,
                "included_in_total": True,
            },
            {
                "key": "product_ter",
                "label": "Produktkosten (gewichtete TER)",
                "category": "Produktkosten",
                "frequency": "jaehrlich",
                "rate_bps": 50,
                "amount_rappen": 5_000_00,
                "basis_rappen": 1_000_000_00,
                "basis_label": "Empfohlenes Produktvolumen",
                "source": "TER der empfohlenen Produkte",
                "is_estimate": False,
                "included_in_total": True,
            },
        ],
        "totals": {
            "one_time_rappen": 0,
            "one_time_bps": 0,
            "annual_rappen": 7_500_00,
            "annual_bps": 75,
            "first_year_rappen": 7_500_00,
            "first_year_bps": 75,
        },
        "is_complete": True,
        "has_estimates": False,
        "warnings": [],
    }


def _pending_payload() -> dict:
    return {
        "data_pending": True,
        "currency": "CHF",
        "as_of": None,
        "source_run_id": None,
        "fidleg_basis": "Art. 8/9 FIDLEG; Art. 8/14 FIDLEV",
        "advisory_wealth_rappen": 0,
        "invested_amount_rappen": 0,
        "product_cost_coverage_bps": 0,
        "cost_items": [],
        "totals": {
            "one_time_rappen": 0, "one_time_bps": None,
            "annual_rappen": 0, "annual_bps": None,
            "first_year_rappen": 0, "first_year_bps": None,
        },
        "is_complete": False,
        "has_estimates": False,
        "warnings": ["Noch keine Portfolioempfehlung vorhanden."],
    }


def test_document_compose_pending_keine_exception():
    """Pending-State darf kein None-Render-Crash provozieren."""
    from services.pdf.documents.cost_disclosure import build_cost_disclosure_flowables
    data = CostDisclosurePDFData(
        mandate_number="M-1",
        advisory_wealth_rappen=0,
        payload=_pending_payload(),
    )
    flow = build_cost_disclosure_flowables(_ctx(), data)
    assert flow  # Cover + Header + Block — mindestens ein Element


def test_document_compose_voll_befuellt_render_pdf_bytes():
    """End-to-End: ReportLabRenderer liefert valides PDF aus voller Payload."""
    from services.pdf.reportlab_renderer import ReportLabRenderer
    data = CostDisclosurePDFData(
        mandate_number="M-1",
        advisory_wealth_rappen=1_000_000_00,
        payload=_full_payload(),
    )
    pdf_bytes = ReportLabRenderer().render_cost_disclosure(_ctx(), data)
    assert pdf_bytes[:4] == b"%PDF"
    # Sanity: > 5kB sind realistisch fuer ein 2-Seiten-Dokument
    assert len(pdf_bytes) > 5000


def test_standalone_full_cost_disclosure_stays_on_two_pages():
    """Cover + disclosure must not orphan the total row on a third page."""
    from io import BytesIO

    from services.pdf.reportlab_renderer import ReportLabRenderer

    payload = _full_payload()
    payload["cost_items"].append({
        "key": "transaction_costs",
        "label": "Geschaetzs- und Transaktionskosten",
        "category": "Transaktionskosten",
        "frequency": "einmalig",
        "rate_bps": 15,
        "amount_rappen": 1_500_00,
        "basis_rappen": 1_000_000_00,
        "basis_label": "Empfohlenes Produktvolumen",
        "source": "Konservative Schaetzung",
        "is_estimate": True,
        "included_in_total": True,
    })
    payload["warnings"] = [
        "Transaktionskosten sind mangels produktspezifischer Angaben geschaetzt."
    ]
    payload["has_estimates"] = True
    payload["totals"].update({
        "one_time_rappen": 1_500_00,
        "one_time_bps": 15,
        "first_year_rappen": 9_000_00,
        "first_year_bps": 90,
    })

    data = CostDisclosurePDFData(
        mandate_number="M-1",
        advisory_wealth_rappen=1_000_000_00,
        payload=payload,
    )
    pdf_bytes = ReportLabRenderer().render_cost_disclosure(_ctx(), data)

    assert len(PdfReader(BytesIO(pdf_bytes)).pages) == 2


def test_renderer_method_existiert():
    from services.pdf.reportlab_renderer import ReportLabRenderer
    assert hasattr(ReportLabRenderer(), "render_cost_disclosure")
