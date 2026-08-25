"""WP4 (2026-07-31): Provisional-Gate im Advisory-Report-PDF-Pfad.

Testet `services.pdf.documents.advisory_report._resolve_advisory_report_
provisional_notice` sowie die tatsaechliche Sichtbarkeit des
"PROVISORISCH -- NICHT IC-FREIGEGEBEN"-Banners auf der Cover-Seite des
gerenderten PDFs.

Szenarien (siehe Auftrag):
  - CH (jurisdiction None oder "CH"): IMMER kein Banner, unveraendertes
    Verhalten -- ueberprueft ohne DB-Zugriff (der Resolver kehrt vor jeder
    Query zurueck) UND stichprobenartig via Payload-Render.
  - DE-Mandat mit CMA-status="data_derived" (nicht IC-freigegeben): Banner
    erscheint, sowohl wenn ein RecommendationRun existiert (WP2-Feld
    `provisional_data_warning`) als auch wenn (noch) keiner existiert
    (Live-Pruefung der aktuellen CMA-Zeile).
  - DE-Mandat mit CMA-status="committee_approved": KEIN Banner, in beiden
    Fallgruppen (mit/ohne RecommendationRun).

Wiederverwendet die DE-Seed-Helper aus tests/test_engine_de_jurisdiction_
wiring.py (WP2), um Duplikation von Fixture-Code zu vermeiden.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.mandates import Mandate
from services.pdf.documents.advisory_report import (
    _resolve_advisory_report_provisional_notice,
    render_advisory_report_pdf,
    render_advisory_report_pdf_from_payload,
)
from services.portfolio_engine import generate_recommendation_run

# Wiederverwendete DE-Seed-Fixtures aus WP2 (Engine-Wiring).
from test_engine_de_jurisdiction_wiring import (  # noqa: F401 (session_factory ist eine Fixture)
    _seed_de_mandate,
    session_factory,
)


# ---------------------------------------------------------------------------
# 1) CH-Kurzschluss -- kein DB-Zugriff notwendig, resolver kehrt sofort zurueck
# ---------------------------------------------------------------------------

def test_resolve_notice_none_for_ch_jurisdiction_null():
    """mandate.jurisdiction is None -> CH-Fallback -> IMMER None, kein DB-Zugriff."""
    fake_mandate = SimpleNamespace(jurisdiction=None, id="does-not-matter", tenant_id=None)
    assert _resolve_advisory_report_provisional_notice(None, fake_mandate) is None


def test_resolve_notice_none_for_ch_jurisdiction_explicit():
    """mandate.jurisdiction == 'CH' -> IMMER None, kein DB-Zugriff."""
    fake_mandate = SimpleNamespace(jurisdiction="CH", id="does-not-matter", tenant_id=None)
    assert _resolve_advisory_report_provisional_notice(None, fake_mandate) is None


# ---------------------------------------------------------------------------
# 2) DE-Mandat MIT RecommendationRun (Primaerquelle: provisional_data_warning)
# ---------------------------------------------------------------------------

def test_resolve_notice_none_for_de_committee_approved_with_run(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="notice-approved-run", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        notice = _resolve_advisory_report_provisional_notice(s, mandate)
    assert notice is None, (
        "committee_approved-CMA (via RecommendationRun.provisional_data_warning) "
        "darf KEIN Provisorik-Banner ausloesen"
    )


def test_resolve_notice_set_for_de_data_derived_with_run(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="notice-provisional-run", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        notice = _resolve_advisory_report_provisional_notice(s, mandate)
    assert notice is not None
    assert notice["jurisdiction"] == "DE"
    assert notice["cma_status"] == "data_derived"
    assert "PROVISORISCH" in notice["message"]


# ---------------------------------------------------------------------------
# 3) DE-Mandat OHNE RecommendationRun (Fallback: Live-Pruefung der CMA-Zeile)
# ---------------------------------------------------------------------------

def test_resolve_notice_none_for_de_committee_approved_without_run(session_factory):
    _advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="notice-approved-norun", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        notice = _resolve_advisory_report_provisional_notice(s, mandate)
    assert notice is None


def test_resolve_notice_set_for_de_data_derived_without_run(session_factory):
    _advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="notice-provisional-norun", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        notice = _resolve_advisory_report_provisional_notice(s, mandate)
    assert notice is not None
    assert notice["jurisdiction"] == "DE"
    assert notice["cma_status"] == "data_derived"
    assert "PROVISORISCH" in notice["message"]


# ---------------------------------------------------------------------------
# 4) Payload-Render: Cover-Banner nur wenn "provisional_notice"-Key gesetzt
# ---------------------------------------------------------------------------

def _minimal_cover_payload(*, with_notice: bool) -> dict:
    payload = {
        "schema_version": 2,
        "mandate_id": "test-mandate-id",
        "generated_at": "2026-07-31T10:00:00.000Z",
        "cover": {
            "title": "Strategische Portfolioanalyse",
            "subtitle": "Persoenlicher Advisory-Report",
            "client_name": "Test Mandant",
            "mandate_number": "MX-DE-01",
            "report_date": "2026-07-31",
            "advisor_name": "Test Berater",
        },
        "disclaimer": {"hinweise": ["Test-Hinweis."]},
    }
    if with_notice:
        payload["provisional_notice"] = {
            "jurisdiction": "DE",
            "cma_status": "data_derived",
            "message": (
                "Kapitalmarktannahmen fuer Jurisdiktion 'DE' sind noch nicht "
                "vom Investment Committee freigegeben."
            ),
        }
    return payload


def test_cover_shows_banner_when_provisional_notice_present():
    pypdf = pytest.importorskip("pypdf")
    payload = _minimal_cover_payload(with_notice=True)
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert "PROVISORISCH" in cover_text
    assert "NICHT IC-FREIGEGEBEN" in cover_text


def test_cover_has_no_banner_when_provisional_notice_absent():
    pypdf = pytest.importorskip("pypdf")
    payload = _minimal_cover_payload(with_notice=False)
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert "PROVISORISCH" not in cover_text


# ---------------------------------------------------------------------------
# 5) End-to-end: render_advisory_report_pdf() gegen echtes DE-Mandat
# ---------------------------------------------------------------------------

def test_render_advisory_report_pdf_shows_banner_for_de_data_derived(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="e2e-provisional", cma_status="data_derived",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()

    pypdf = pytest.importorskip("pypdf")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        pdf = render_advisory_report_pdf(s, mandate, advisor=None)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert "PROVISORISCH" in cover_text, (
        f"Erwartetes Provisorik-Banner fehlt im Cover. Cover-Text: {cover_text[:400]}"
    )


def test_render_advisory_report_pdf_no_banner_for_de_committee_approved(session_factory):
    advisor_id, mid, _tenant_id = _seed_de_mandate(
        session_factory, suffix="e2e-approved", cma_status="committee_approved",
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()

    pypdf = pytest.importorskip("pypdf")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        pdf = render_advisory_report_pdf(s, mandate, advisor=None)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert "PROVISORISCH" not in cover_text
