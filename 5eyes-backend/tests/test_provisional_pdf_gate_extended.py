"""WP-B (2026-08-01): Provisorik-Gate-Erweiterung auf 5 weitere PDF-Typen.

Deckt die Verallgemeinerung von WP4 (services.pdf.provisional_notice) ab:
- Anlagestrategie (services.pdf.documents.anlagestrategie)
- Asset Allocation (services.pdf.documents.asset_allocation)
- Portfolio (services.pdf.documents.portfolio)
- Ex-ante Kostenausweis (services.pdf.documents.cost_disclosure)
- Strategie-Backtest (services.pdf.documents.backtest)

Aufbau (Vorbild tests/test_provisional_pdf_gate.py):
  1) Shared-Resolver (`services.pdf.provisional_notice.
     resolve_pdf_provisional_notice`): CH-Kurzschluss (kein DB-Zugriff) +
     echtes DE-Mandat mit data_derived-CMA (Banner) + committee_approved-CMA
     (kein Banner).
  2) Router-Wiring (`routers.pdf_reports._attach_provisional_notice`):
     dieselbe Funktion, die alle 5 betroffenen Endpoints aufrufen.
  3) Pro Dokumenttyp: DE-Mandat mit data_derived-CMA -> Banner im
     PDF-Text der ersten Seite; CH-Mandat (kein provisional_notice, siehe
     1) -> kein Banner, unveraendertes Verhalten.
"""
from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.mandates import Mandate
from routers.pdf_reports import _attach_provisional_notice
from services.pdf.base import (
    AnlagestrategieData,
    BacktestData,
    CostDisclosurePDFData,
    PDFContext,
    PortfolioData,
)
from services.pdf.provisional_notice import resolve_pdf_provisional_notice
from services.pdf.reportlab_renderer import ReportLabRenderer
from services.portfolio_engine import generate_recommendation_run

# Wiederverwendete DE-Seed-Fixtures aus WP2 (Engine-Wiring) -- identisch zum
# Vorbild tests/test_provisional_pdf_gate.py.
from test_engine_de_jurisdiction_wiring import (  # noqa: F401 (session_factory ist eine Fixture)
    _seed_de_mandate,
    session_factory,
)


def _de_notice(session_factory, *, suffix: str, cma_status: str = "data_derived") -> dict | None:
    """Seedet ein echtes DE-Mandat + RecommendationRun und liefert das per
    `resolve_pdf_provisional_notice` daraus resolvte Notice-Dict (oder None
    bei committee_approved)."""
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix=suffix, cma_status=cma_status,
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        return resolve_pdf_provisional_notice(s, mandate)


# ---------------------------------------------------------------------------
# 1) Shared-Resolver -- services.pdf.provisional_notice.
#    resolve_pdf_provisional_notice
# ---------------------------------------------------------------------------

def test_shared_resolver_none_for_ch_jurisdiction_null():
    fake_mandate = SimpleNamespace(jurisdiction=None, id="does-not-matter", tenant_id=None)
    assert resolve_pdf_provisional_notice(None, fake_mandate) is None


def test_shared_resolver_none_for_ch_jurisdiction_explicit():
    fake_mandate = SimpleNamespace(jurisdiction="CH", id="does-not-matter", tenant_id=None)
    assert resolve_pdf_provisional_notice(None, fake_mandate) is None


def test_shared_resolver_set_for_de_data_derived(session_factory):
    notice = _de_notice(session_factory, suffix="shared-provisional")
    assert notice is not None
    assert notice["jurisdiction"] == "DE"
    assert notice["cma_status"] == "data_derived"
    assert "PROVISORISCH" in notice["message"] or "Investment Committee" in notice["message"]


def test_shared_resolver_none_for_de_committee_approved(session_factory):
    notice = _de_notice(session_factory, suffix="shared-approved", cma_status="committee_approved")
    assert notice is None


# ---------------------------------------------------------------------------
# 2) Router-Wiring -- routers.pdf_reports._attach_provisional_notice
#    (identische Funktion, die alle 5 betroffenen Endpoints aufrufen)
# ---------------------------------------------------------------------------

def test_attach_provisional_notice_leaves_ctx_unchanged_for_ch_mandate():
    ctx = PDFContext(
        mandate_name="CH Mandant", advisor_name="Berater", report_date=date.today(),
    )
    fake_mandate = SimpleNamespace(jurisdiction="CH", id="does-not-matter", tenant_id=None)
    result = _attach_provisional_notice(ctx, None, fake_mandate)
    assert result is ctx
    assert result.provisional_notice is None


def test_attach_provisional_notice_sets_notice_for_de_data_derived(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="attach-provisional", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ctx = PDFContext(
            mandate_name="DE Mandant", advisor_name="Berater", report_date=date.today(),
            base_currency="EUR",
        )
        result = _attach_provisional_notice(ctx, s, mandate)
    assert result is not ctx
    assert result.provisional_notice is not None
    assert result.provisional_notice["jurisdiction"] == "DE"


# ---------------------------------------------------------------------------
# 3) Pro Dokumenttyp: Banner-Sichtbarkeit auf der ersten (Cover-)Seite
# ---------------------------------------------------------------------------

def _ctx(*, provisional_notice: dict | None = None) -> PDFContext:
    return PDFContext(
        mandate_name="DE Test Mandant", advisor_name="Test Berater",
        advisor_org="WealthArchitekten Test", report_date=date.today(),
        base_currency="EUR", provisional_notice=provisional_notice,
    )


def _first_page_text(pdf_bytes: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return reader.pages[0].extract_text() or ""


def _minimal_saa_data() -> AnlagestrategieData:
    return AnlagestrategieData(
        target_allocation_bps={"equities": 5000, "bonds": 5000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        mandate_number="M-WPB",
    )


def _minimal_portfolio_data() -> PortfolioData:
    return PortfolioData(
        mandate_number="M-WPB",
        advisory_wealth_rappen=100_000_00,
        positions=[{
            "name": "Test Fonds", "isin": "DE0000000001",
            "asset_class": "equities", "sub_asset_class": "Aktien Welt",
            "target_weight_bps": 10000, "target_amount_rappen": 100_000_00,
        }],
    )


def _minimal_cost_disclosure_data() -> CostDisclosurePDFData:
    return CostDisclosurePDFData(
        mandate_number="M-WPB",
        advisory_wealth_rappen=0,
        payload={
            "data_pending": True,
            "currency": "EUR",
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
        },
    )


@pytest.mark.parametrize(
    "render_method, build_data",
    [
        ("render_anlagestrategie", _minimal_saa_data),
        ("render_asset_allocation", _minimal_saa_data),
        ("render_portfolio", _minimal_portfolio_data),
        ("render_cost_disclosure", _minimal_cost_disclosure_data),
        ("render_backtest", BacktestData),
    ],
)
def test_document_shows_banner_for_de_data_derived(session_factory, render_method, build_data):
    notice = _de_notice(session_factory, suffix=f"doc-{render_method}")
    assert notice is not None, "Vorbedingung: DE data_derived muss ein Notice-Dict liefern"

    ctx = _ctx(provisional_notice=notice)
    renderer = ReportLabRenderer()
    pdf = getattr(renderer, render_method)(ctx, build_data())
    text = _first_page_text(pdf)

    assert "PROVISORISCH" in text, (
        f"{render_method}: Provisorik-Banner fehlt auf Seite 1. Text: {text[:300]}"
    )
    assert "NICHT IC-FREIGEGEBEN" in text


@pytest.mark.parametrize(
    "render_method, build_data",
    [
        ("render_anlagestrategie", _minimal_saa_data),
        ("render_asset_allocation", _minimal_saa_data),
        ("render_portfolio", _minimal_portfolio_data),
        ("render_cost_disclosure", _minimal_cost_disclosure_data),
        ("render_backtest", BacktestData),
    ],
)
def test_document_shows_no_banner_for_ch_mandate(render_method, build_data):
    """CH-Mandat: PDFContext.provisional_notice ist per Default None (siehe
    resolve_pdf_provisional_notice-Kurzschluss fuer CH) -> unveraendertes
    Verhalten, kein Banner."""
    ctx = _ctx(provisional_notice=None)
    renderer = ReportLabRenderer()
    pdf = getattr(renderer, render_method)(ctx, build_data())
    text = _first_page_text(pdf)

    assert "PROVISORISCH" not in text
    assert "NICHT IC-FREIGEGEBEN" not in text
    assert pdf[:4] == b"%PDF"
