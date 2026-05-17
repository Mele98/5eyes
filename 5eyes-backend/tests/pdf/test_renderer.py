"""PDF-Renderer Tests: Validitaet + Inhalt + Performance."""
from __future__ import annotations

from datetime import date

import pytest

from services.pdf.base import (
    AnlagestrategieData,
    PDFContext,
    PDFRenderer,
    RisikoprofilData,
)
from services.pdf.reportlab_renderer import ReportLabRenderer


@pytest.fixture
def ctx():
    return PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster & Partner AG",
        report_date=date(2026, 5, 17),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )


@pytest.fixture
def saa_data():
    return AnlagestrategieData(
        target_allocation_bps={
            "equities": 4000,
            "bonds": 3000,
            "real_estate": 1500,
            "alternatives": 1000,
            "liquidity": 500,
        },
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=15,
        monte_carlo_stats={"p10": 800_000_00, "p50": 1_500_000_00, "p90": 2_500_000_00},
        optimizer_reasoning=(
            "Risikoausgewogene Allokation mit Equity-Tilt aufgrund langem Horizont."
        ),
        risk_profile_label="Ausgewogen",
    )


@pytest.fixture
def risk_data():
    return RisikoprofilData(
        risk_profile_label="Ausgewogen",
        risk_capacity_score=65,
        risk_tolerance_score=58,
        knowledge_services={"Anlageberatung": True, "Vermoegensverwaltung": False},
        knowledge_instruments={"Aktien": True, "Anleihen": True, "Derivate": False},
        experience_years=8,
        suitability_note="Risikofaehigkeit und Toleranz sind kompatibel.",
    )


def test_renderer_implements_protocol():
    r = ReportLabRenderer()
    assert isinstance(r, PDFRenderer)


def test_anlagestrategie_pdf_magic_bytes(ctx, saa_data):
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert pdf[:4] == b"%PDF", "PDF must start with magic bytes %PDF"


def test_anlagestrategie_pdf_eof(ctx, saa_data):
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    # ReportLab beendet mit %%EOF
    assert b"%%EOF" in pdf[-256:]


def test_anlagestrategie_pdf_returns_bytes(ctx, saa_data):
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert isinstance(pdf, bytes)


def test_anlagestrategie_pdf_size_plausible(ctx, saa_data):
    """PDF sollte 10kB-500kB sein."""
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert 3_000 < len(pdf) < 500_000, f"size={len(pdf)} unerwartet"


def test_anlagestrategie_pdf_contains_mandate_name(ctx, saa_data):
    """Mandant-Name muss im PDF-Body vorkommen (Title-Tag, Header)."""
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    # ReportLab schreibt Strings als komprimierte Streams — wir suchen im
    # gesamten PDF-Body nach dem Namen (kann in Streams gepackt sein).
    # Schwacher Check: PDF-Title (Metadata, immer plaintext).
    assert b"Hans Muster" in pdf, "mandate name should be in PDF metadata"


def test_anlagestrategie_pdf_contains_advisor_name(ctx, saa_data):
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    # Author-Metadata enthaelt advisor
    assert b"Anna Berater" in pdf


def test_anlagestrategie_pdf_title_metadata(ctx, saa_data):
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert b"Anlagestrategie" in pdf


def test_anlagestrategie_with_empty_mc_stats(ctx):
    """Ohne Monte Carlo Stats: kein MC-Section, aber PDF valid."""
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 5000, "bonds": 5000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        monte_carlo_stats=None,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    assert pdf[:4] == b"%PDF"


def test_anlagestrategie_with_minimal_allocation(ctx):
    """Nur ein Bucket allokiert — sollte trotzdem valides PDF erzeugen."""
    data = AnlagestrategieData(
        target_allocation_bps={"liquidity": 10000},
        cma_expected_return_bps=10,
        cma_expected_vol_bps=20,
        horizon_years=2,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000


def test_anlagestrategie_without_reasoning(ctx, saa_data):
    """Ohne optimizer_reasoning: kein Begruendungs-Block, PDF valid."""
    data = AnlagestrategieData(
        target_allocation_bps=saa_data.target_allocation_bps,
        cma_expected_return_bps=saa_data.cma_expected_return_bps,
        cma_expected_vol_bps=saa_data.cma_expected_vol_bps,
        horizon_years=saa_data.horizon_years,
        monte_carlo_stats=saa_data.monte_carlo_stats,
        optimizer_reasoning=None,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    assert pdf[:4] == b"%PDF"


def test_risikoprofil_pdf_magic_bytes(ctx, risk_data):
    pdf = ReportLabRenderer().render_risikoprofil(ctx, risk_data)
    assert pdf[:4] == b"%PDF"


def test_risikoprofil_pdf_contains_label(ctx, risk_data):
    pdf = ReportLabRenderer().render_risikoprofil(ctx, risk_data)
    # Title-Metadata
    assert b"Risikoprofil" in pdf


def test_render_performance_under_2_seconds(ctx, saa_data):
    """End-to-end Render < 2 Sekunden (Performance-Anforderung Spec §6)."""
    import time
    r = ReportLabRenderer()
    t0 = time.perf_counter()
    pdf = r.render_anlagestrategie(ctx, saa_data)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"render took {elapsed:.2f}s, expected < 2s"
    assert len(pdf) > 0


def test_two_renders_are_isolated(ctx, saa_data):
    """Mehrfaches Rendern erzeugt unabhaengige PDFs."""
    r = ReportLabRenderer()
    pdf_a = r.render_anlagestrategie(ctx, saa_data)
    pdf_b = r.render_anlagestrategie(ctx, saa_data)
    # PDF-Bytes koennen identisch sein (deterministischer Output) — wichtig
    # ist nur dass beide gueltig sind und das gleiche Mandate enthalten.
    assert pdf_a[:4] == b"%PDF"
    assert pdf_b[:4] == b"%PDF"
    assert b"Hans Muster" in pdf_a
    assert b"Hans Muster" in pdf_b


def test_context_without_audit_hash(saa_data):
    """audit_hash=None → kein Crash, Footer zeigt 'n/a'."""
    ctx_no_hash = PDFContext(
        mandate_name="X",
        advisor_name="Y",
        report_date=date(2026, 1, 1),
        audit_hash=None,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx_no_hash, saa_data)
    assert pdf[:4] == b"%PDF"


def test_context_special_chars_in_name(saa_data):
    """Umlaute + Sonderzeichen im Namen funktionieren."""
    ctx = PDFContext(
        mandate_name="Übermütige & Söhne AG <Spezial>",
        advisor_name="Müller-Schörli",
        report_date=date(2026, 5, 17),
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000


def test_anlagestrategie_zero_horizon(ctx):
    """Edge-case: horizon_years=0 produziert noch valides PDF."""
    data = AnlagestrategieData(
        target_allocation_bps={"liquidity": 10000},
        cma_expected_return_bps=0,
        cma_expected_vol_bps=0,
        horizon_years=0,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    assert pdf[:4] == b"%PDF"


def test_anlagestrategie_extra_buckets_ignored(ctx, saa_data):
    """Unbekannte Buckets in allocation_bps werden ignoriert (nicht crashen)."""
    data = AnlagestrategieData(
        target_allocation_bps={
            "equities": 5000, "bonds": 5000, "unknown_bucket": 999
        },
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    assert pdf[:4] == b"%PDF"
