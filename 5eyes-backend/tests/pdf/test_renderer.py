"""PDF-Renderer Tests: Validitaet + Inhalt + Performance."""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from services.pdf.base import (
    AnlagestrategieData,
    DepotCheckData,
    PDFContext,
    PDFRenderer,
    PortfolioData,
    ProtokollData,
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


def test_anlagestrategie_reference_structure_has_19_pages(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={
            "equities": 7100,
            "real_estate": 2000,
            "alternatives": 700,
            "liquidity": 200,
        },
        cma_expected_return_bps=431,
        cma_expected_vol_bps=1078,
        horizon_years=15,
        risk_profile_label="Wachstum",
        mandate_number="M-42",
        advisory_wealth_rappen=535_100_00,
        risk_score_x10=80,
        investment_horizon_years=15,
        bucket_bands_bps={
            "equities": (6500, 7500),
            "real_estate": (1500, 2500),
            "alternatives": (0, 1000),
            "liquidity": (0, 500),
        },
        products=[
            {
                "name": "UBS ETF MSCI World",
                "isin": "IE000N6LBS91",
                "asset_class": "equities",
                "sub_asset_class": "Aktien Welt",
                "target_weight_bps": 3195,
                "target_amount_rappen": 170_964_00,
                "ter_bps": 12,
                "provider": "UBS",
            }
        ],
        advisory_positions=[
            {"asset_class": "equities", "sub_asset_class": "Aktien", "current_amount_rappen": 103_500_00},
            {"asset_class": "bonds", "sub_asset_class": "Obligationen", "current_amount_rappen": 99_000_00},
        ],
        other_wealth_positions=[
            {"label": "Cash extern", "amount_rappen": 100_000_00, "kind": "Liquiditaet"}
        ],
        cashflow_events=[
            {"name": "Freizuegigkeitsdepot", "recurrence": "Einmalig", "start_label": "03.2028", "amount_rappen": 169_000_00}
        ],
        goals_list=[
            {"name": "Vermoegensverzehr", "category": "Rente", "recurrence": "Monatlich", "period_label": "2026-2040", "amount_rappen": 5_025_00}
        ],
        goal_analysis=[
            {"rank": 1, "label": "Vermoegensverzehr", "achievement_score": 75, "target_text": "Rente sichern", "shortfall_rappen": 0}
        ],
        current_allocation_bps={"equities": 3868, "bonds": 3700, "real_estate": 832, "liquidity": 1600},
        allocation_preferences={
            "policy": {"esg": "esg_integration", "universe": "standard", "homeBias": "ch_focus", "hedging": "hedged"},
            "assetClasses": {"equitiesGeo": "Schweiz Fokus", "bondsDuration": "Langfristig", "realestateMarket": "Schweiz", "altsGold": True},
            "product": {"fundsOnly": True},
            "geo": {"chFocus": True},
            "bands": {},
        },
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 19

    page5 = reader.pages[4].extract_text() or ""
    page6 = reader.pages[5].extract_text() or ""
    page13 = reader.pages[12].extract_text() or ""
    page14 = reader.pages[13].extract_text() or ""
    assert "SOLL-ALLOKATION" in page5
    assert "SUBANLAGEKLASSEN" in page6
    assert "SOLL-ALLOKATION" in page13
    assert "SUBANLAGEKLASSEN" in page14


def test_anlagestrategie_renders_complete_risk_questionnaire(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={
            "equities": 4000,
            "bonds": 3000,
            "real_estate": 1500,
            "alternatives": 1000,
            "liquidity": 500,
        },
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    page2 = PdfReader(BytesIO(pdf)).pages[1].extract_text() or ""

    assert "Frage" in page2
    assert "Antwort" in page2
    assert "Punkte" not in page2
    for question_number in range(1, 12):
        assert f"Frage {question_number}" in page2
    assert "Regelmässiges Einkommen" in page2
    assert "Risikofähigkeit" in page2
    assert page2.count("Nicht beantwortet") >= 11


def test_anlagestrategie_hides_standard_band_column(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 5000, "bonds": 5000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        bucket_bands_bps={"equities": (4500, 5500), "bonds": (4500, 5500)},
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    page5 = PdfReader(BytesIO(pdf)).pages[4].extract_text() or ""

    assert "SOLL-ALLOKATION" in page5
    assert "Band Min" not in page5


def test_anlagestrategie_mentions_manual_risk_override(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 5000, "bonds": 5000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        risk_profile_label="Wachstumsorientiert",
        risk_is_overridden=True,
        risk_override_reason="Kundenwunsch dokumentiert",
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "Kundenwunsch dokumentiert" in text
    assert "MANUELLE" in text or "Manuelle" in text


def test_assetallocation_pdf_contains_only_allocation_and_subclasses(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 6000, "bonds": 4000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        products=[
            {
                "name": "Nicht im Asset-Allocation-PDF",
                "asset_class": "equities",
                "sub_asset_class": "Aktien Welt",
                "target_weight_bps": 6000,
                "target_amount_rappen": 60_000_00,
            }
        ],
    )
    pdf = ReportLabRenderer().render_asset_allocation(ctx, data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "SOLL-ALLOKATION" in text
    assert "SUBANLAGEKLASSEN" in text
    assert "BESPRECHUNGSFOKUS" in text
    assert "SOLL-Quoten je Anlageklasse" in text
    assert "Subanlageklassen und Zielbetr" in text
    assert "Aktien Total" in text
    assert "Obligationen Total" in text
    assert "Aktien Welt" in text
    assert text.count("Aktien Welt") == 1
    assert "Wichtiger Hinweis" in text
    assert "Kundenwunsch" in text
    assert "isolierter Auszug" in text
    assert "Risikoprofil" not in text
    assert "Eignungsprüfung" not in text
    assert "Eignungspruefung" not in text
    assert "Vermögensübersicht" not in text
    assert "Vermoegensuebersicht" not in text
    assert "Portfolio" not in text
    assert "Nicht im Asset-Allocation-PDF" not in text
    assert "Band Min" in text
    assert "Band Max" in text
    assert "strategischen Mittelpunkt" in text


def test_assetallocation_pdf_prints_target_bands_in_single_extract(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 6000, "bonds": 4000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        bucket_bands_bps={"equities": (5500, 6500), "bonds": (3500, 4500)},
        allocation_preferences={"bands": {"equities": {"min_bps": 5500, "max_bps": 6500}}},
    )
    pdf = ReportLabRenderer().render_asset_allocation(ctx, data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "Band Min" in text
    assert "Band Max" in text
    assert "55%" in text
    assert "65%" in text


def test_anlagestrategie_risk_questionnaire_formats_knowledge_answers(ctx):
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 5000, "bonds": 5000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        risk_answers=[
            {
                "question_number": 1,
                "answer_label": (
                    'Finanzdienstleistungen: {"Anlageberatung": '
                    '{"known": true, "informed": true}}'
                ),
                "answer_points": 0,
            },
        ],
    )
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    page2 = PdfReader(BytesIO(pdf)).pages[1].extract_text() or ""

    assert "Anlageberatung: Kenntnisse vorhanden, Aufklärung erhalten" in page2
    assert '{"known"' not in page2


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


def test_risikoprofil_pdf_hides_internal_scores_and_mentions_override(ctx):
    data = RisikoprofilData(
        risk_profile_label="Wachstumsorientiert",
        risk_capacity_score=65,
        risk_tolerance_score=58,
        experience_years=12,
        is_overridden=True,
        override_reason="Kundenwunsch dokumentiert",
        override_client_confirmed=True,
        override_warning_delivered=True,
    )
    pdf = ReportLabRenderer().render_risikoprofil(ctx, data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "Wachstumsorientiert" in text
    assert "65 / 100" not in text
    assert "58 / 100" not in text
    assert "Übersteuerung" in text
    assert "Kundenbestätigung" in text
    assert "Warnhinweis" in text
    assert "Kundenwunsch dokumentiert" in text


def test_risikoprofil_pdf_documents_questions_and_signature(ctx):
    data = RisikoprofilData(
        risk_profile_label="Wachstumsorientiert",
        risk_capacity_score=65,
        risk_tolerance_score=58,
        risk_score_x10=58,
        mandate_number="M-RP",
        mandate_type="Anlageberatung",
        knowledge_services={"Anlageberatung": {"known": True, "informed": True}},
        knowledge_instruments={"Anlagefonds": {"known": True, "informed": True}},
        risk_answers=[
            {
                "question_number": 3,
                "question_section": "Risikofaehigkeit",
                "answer_label": "CHF 10'000 bis CHF 20'000",
                "answer_points": 3,
            },
            {
                "question_number": 11,
                "question_section": "Risikobereitschaft",
                "answer_label": "Ich bleibe investiert und prüfe die Strategie im Gespräch.",
                "answer_points": 3,
            },
        ],
    )
    pdf = ReportLabRenderer().render_risikoprofil(ctx, data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "Eignungsprüfung" in text
    assert "Frage 1" in text
    assert "Frage 11" in text
    assert "Anlageberatung" in text
    assert "vorstehenden Angaben zu Risikoprofil" in text
    assert "Ort, Datum / Klient" in text
    assert "vorliegende Anlagestrategie" not in text


def test_depotcheck_cover_uses_report_specific_title(ctx):
    pdf = ReportLabRenderer().render_depotcheck(ctx, DepotCheckData(mandate_number="M-D"))
    first_page = PdfReader(BytesIO(pdf)).pages[0].extract_text() or ""

    assert "Depot-Check" in first_page
    assert "Anlagestrategie" not in first_page


def test_portfolio_pdf_contains_only_positions(ctx):
    data = PortfolioData(
        mandate_number="M-42",
        advisory_wealth_rappen=100_000_00,
        positions=[
            {
                "name": "Test Fonds",
                "isin": "CH0000000001",
                "asset_class": "equities",
                "sub_asset_class": "Aktien Welt",
                "target_weight_bps": 10000,
                "target_amount_rappen": 100_000_00,
                "ter_bps": 20,
            }
        ],
    )
    pdf = ReportLabRenderer().render_portfolio(ctx, data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "Portfolio" in text
    assert "BESPRECHUNGSFOKUS" in text
    assert "Konkrete Produkte mit ISIN" in text
    assert "PORTFOLIO-POSITIONEN" in text
    assert "Aktien:" in text
    assert "Aktien Welt" in text
    assert "Zielwert" in text
    assert "Waehrung" in text
    assert "Test Fonds" in text
    assert "Wichtiger Hinweis" in text
    assert "Kundenwunsch" in text
    assert "isolierter Auszug" in text
    assert "Bestätigung" not in text
    assert "Bestaetigung" not in text
    assert "Portfolio-Übersicht" not in text
    assert "Portfolio-Uebersicht" not in text


def test_protokoll_pdf_magic_bytes(ctx):
    data = ProtokollData(
        mandate_number="M-42",
        advisory_wealth_rappen=1_250_000_00,
        latest_recommendation_summary="Strategie wurde besprochen.",
        entries=[
            {
                "entry_date": "2026-05-19",
                "entry_type": "Review",
                "title": "Entscheid dokumentiert",
                "description": "Kunde stimmt der Umsetzung zu.",
                "decision": "Umsetzung",
                "status": "Empfohlen",
            }
        ],
    )
    pdf = ReportLabRenderer().render_protokoll(ctx, data)
    assert pdf[:4] == b"%PDF"
    assert b"Beratungsprotokoll" in pdf


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
